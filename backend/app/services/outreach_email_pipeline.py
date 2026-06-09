"""Two-step outbound email generation: reasoning JSON → subject/body + validation + style (stage 2–3)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.repositories.email_draft_repo import list_outbound_draft_bodies_for_run_excluding_contact
from app.services.email_style_service import resolve_effective_email_style, style_prompt_fragment
from app.services.email_validation_service import validate_outbound_email
from app.services.llm_gateway import generate_json
from app.services.personalization_service import sync_contact_personalization_row
from app.utils.contact_personalization_io import get_personalization_dict
from app.utils.contact_source_payload import effective_contact_source_json
from app.services.prompt_builder import build_prompt
from app.services.rules_service import get_effective_rules_from_run
from app.services.run_context_service import build_master_prompt_text, get_effective_context

logger = logging.getLogger(__name__)

# Email skeleton = 5 evidence-backed slots (decision 09.06). Names reuse the legacy keys where they
# map (hook=Зацепка/trigger, angle=Мэтчинг, cta_type=Призыв) and add explicit problem/solution.
# key_point is kept (mirrors solution) for backward compat with meta/UI readers.
REASONING_SCHEMA = {
    "hook": "string",       # Зацепка: конкретный инфоповод о компании/ЛПР (заземлён на факт)
    "angle": "string",      # Мэтчинг: через проблему/ценности/подход/корп-событие
    "problem": "string",    # Проблема, которую решаем (подтверждена фактом)
    "solution": "string",   # Решение/Quick Win под этот кейс (оффер из prompt_setup_text; позже — программа из каталога)
    "cta_type": "string",   # Призыв к действию
}

DRAFT_SCHEMA = {"subject": "string", "body": "string"}

MAX_VALIDATION_RETRIES = 2


def _contact_role_for_prompt(db: Session, contact: Contact) -> str:
    r = (contact.role or "").strip()
    if r:
        return r
    sj = effective_contact_source_json(db, contact)
    if isinstance(sj, dict):
        for k in ("role", "title", "job_title", "position"):
            v = sj.get(k)
            if v:
                return str(v).strip()
    return ""


def _needs_personalization_sync(db: Session, contact: Contact) -> bool:
    pj = get_personalization_dict(db, contact.id, contact.personalization_json)
    if pj is None or not isinstance(pj, dict):
        return True
    if len(pj) == 0:
        return True
    if "role_angle" not in pj:
        return True
    return False


def ensure_contact_personalization(db: Session, contact: Contact) -> None:
    if _needs_personalization_sync(db, contact):
        sync_contact_personalization_row(db, contact)
        db.add(contact)
        db.flush()


def _rules(db: Session, run_id: int) -> list[str]:
    try:
        return get_effective_rules_from_run(db, run_id, "generate_emails")
    except ValueError:
        return []


def _serialize_personalization(db: Session, contact: Contact) -> dict[str, Any]:
    from app.models.run_company import RunCompany
    pj = get_personalization_dict(db, contact.id, contact.personalization_json)
    
    osint_dossier = ""
    if contact.company:
        rc = db.query(RunCompany).filter(RunCompany.run_id == contact.run_id, RunCompany.name == contact.company).first()
        if rc:
            from app.utils.run_company_extra import effective_run_company_extra
            kv = effective_run_company_extra(db, rc)
            osint_dossier = kv.get("osint_dossier", "")

    return {
        "company_facts": pj.get("company_facts") or [],
        "role_angle": (pj.get("role_angle") or "").strip(),
        "why_this_company": (pj.get("why_this_company") or "").strip(),
        "offer_fit": (pj.get("offer_fit") or "").strip(),
        "risks_or_constraints": (pj.get("risks_or_constraints") or "").strip(),
        "osint_dossier": osint_dossier,
        "person_osint": pj.get("person_osint"),
    }


def _run_brief_blocks(run: Any) -> dict[str, str]:
    ctx = get_effective_context(run)
    mp = (getattr(run, "master_prompt", None) or "").strip()
    return {
        "effective_context": ctx,
        "master_prompt": mp,
        "labeled_master_prompt": build_master_prompt_text(ctx) if run else "",
    }


def generate_email_reasoning(
    db: Session,
    run: Any,
    contact: Contact,
    *,
    prompt_setup_text: str | None,
    master_variant: dict[str, str] | None,
    style_mode: str,
    regenerate_hint: str = "",
) -> dict[str, str]:
    """Internal planning JSON — not the email itself."""
    role = _contact_role_for_prompt(db, contact)
    brief = _run_brief_blocks(run)
    pers = _serialize_personalization(db, contact)
    rules = _rules(db, run.id)
    style_block = style_prompt_fragment(style_mode)
    
    rs = getattr(run, "run_setup", None)
    lang = getattr(rs, "language", "Russian")

    variant_note = ""
    if master_variant:
        variant_note = (
            "A master variant exists for this run — it is a TONE/STRUCTURE reference for this campaign only, "
            "not text to reuse verbatim in the reasoning step.\n"
            f"Reference subject (do not copy): {master_variant.get('subject', '')[:200]}\n"
        )

    task = rs.reasoning_prompt if rs and rs.reasoning_prompt else (
        f"{style_block}\n\n"
        "You are a Senior SDR at FG Consulting. Plan one outbound email as a 5-slot skeleton "
        "based on this recipient's evidence (OSINT). Return a short internal plan (not the email).\n\n"
        f"{variant_note}"
        "Fill these slots (each grounded in INPUT DATA, never invented):\n"
        "- hook (Зацепка): ONE concrete trigger / inforpovod about this company or person, taken from "
        "personalization.person_osint (preferred) or personalization.osint_dossier / company_facts.\n"
        "- angle (Мэтчинг): how we connect to them — through their problem, values, approach, or a corporate event.\n"
        "- problem (Проблема): the specific pain we address, supported by a fact from the evidence "
        "(management hunger, scaling/restructuring, weak sales ops, etc.).\n"
        "- solution (Решение): ONE fast Quick Win for THIS case. Draw the offer/who-we-are from the "
        "Campaign / prompt setup (persona) above; pick the angle that fits their problem.\n"
        "- cta_type (Призыв): what we ask for (e.g. a short 15-minute call).\n\n"
        "Grounding rules: do not invent companies, metrics, people, or awards not present in INPUT DATA. "
        "If personalization.person_osint is present, PRIORITIZE facts about the person (quotes, articles, "
        "career) over the general company dossier.\n"
        # NOTE (near-term): the `solution` slot will also accept a concrete program matched from the
        # training-programs catalog (text/bullets/PDF). Keep it as the single offer slot.
    )

    # Language enforcement
    task = f"ALWAYS WRITE THE RESPONSE (hook, angle, problem, solution, cta_type) IN {lang}.\n\n{task}"

    if (prompt_setup_text or "").strip():
        task = (
            f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n" + task
        )
    if regenerate_hint:
        task += regenerate_hint

    data: dict[str, Any] = {
        "recipient": {
            "company": contact.company,
            "name": contact.name,
            "role": role,
            "email": contact.email,
            "website": contact.website,
        },
        "personalization": pers,
        "run_brief": brief,
    }

    prompt = build_prompt(
        task=task,
        data=data,
        rules=rules,
        output_schema=REASONING_SCHEMA,
    )
    out = generate_json(prompt, task_kind="outreach_reasoning")
    solution = (out.get("solution") or out.get("key_point") or "").strip()
    return {
        "hook": (out.get("hook") or "").strip(),
        "angle": (out.get("angle") or "").strip(),
        "problem": (out.get("problem") or "").strip(),
        "solution": solution,
        "cta_type": (out.get("cta_type") or "").strip(),
        "key_point": solution,  # backward-compat mirror for meta/UI readers
    }


def generate_email_draft(
    db: Session,
    run: Any,
    contact: Contact,
    reasoning: dict[str, str],
    *,
    prompt_setup_text: str | None,
    master_variant: dict[str, str] | None,
    style_mode: str,
    prior_issues: list[str] | None = None,
    regenerate_hint: str = "",
) -> tuple[str, str]:
    """Final subject + body; must reflect personalization and reasoning."""
    role = _contact_role_for_prompt(db, contact)
    pers = _serialize_personalization(db, contact)
    rules = _rules(db, run.id)
    brief = _run_brief_blocks(run)
    style_block = style_prompt_fragment(style_mode)
    
    rs = getattr(run, "run_setup", None)
    lang = getattr(rs, "language", "Russian")

    master_block = ""
    if master_variant:
        master_block = (
            "Master variant (REFERENCE ONLY — strategy, tone, level of directness). "
            "Write a NEW email for this recipient; do NOT paste or lightly edit this text.\n"
            f"Reference subject: {master_variant.get('subject', '')}\n"
            f"Reference body (no salutation in master; you add Hi Name, in output):\n{master_variant.get('body', '')}\n"
        )

    fix_block = ""
    if prior_issues:
        fix_block = (
            "Fix these validation problems from the previous draft (rewrite fully):\n"
            + "\n".join(f"- {p}" for p in prior_issues)
            + "\n\n"
        )

    task = rs.draft_prompt if rs and rs.draft_prompt else (
        f"{style_block}\n\n"
        + fix_block
        + "You are a Senior SDR and Business Strategist at 'FG Consulting'. "
        "We specialize in implementing systemic changes in corporate governance and training (sales and leadership). "
        "OUR CURRENT FOCUS: Selling fast, targeted solutions (Quick Wins) that give the client immediate value, 'unblock' bottlenecks, and open doors for long-term contracts.\n\n"
        "Write one outbound B2B cold email (subject + body) for this recipient.\n\n"
        + master_block
        + "Follow the planned 5-slot skeleton from Internal reasoning, in order: "
        "open with `hook` (the concrete trigger) → connect via `angle` → name the `problem` → "
        "offer the `solution` (one Quick Win) → close with `cta_type`. Weave them into natural prose "
        "(do NOT print slot labels).\n"
        + "Hard requirements:\n"
        "- If personalization.person_osint is non-empty, you MUST start the email with a hook referencing their personal background, article, or quote.\n"
        "- If personalization.osint_dossier is non-empty (and no person_osint), use a concrete fact from it to create a powerful 'Product Hook'.\n"
        "- Address their management hunger (lack of strong leaders, mergers, scaling issues) or sales problems if apparent from the dossier.\n"
        "- Offer ONE specific, fast Quick Win step (e.g., training, facilitation session, workshop, express audit).\n"
        "- The CTA (Call to Action) must be a short 15-minute call.\n"
        "- DO NOT use IT jargon. Use words like 'external partner', 'development of managerial competencies'.\n"
        "- Avoid generic openers: jump straight into the fact or trigger.\n"
        "- Body: include a brief salutation (e.g. Hi FirstName,) then 5–10 sentences total.\n"
        "- Subject: specific, not generic, intriguing.\n"
        "- Return ONLY valid JSON matching the schema. No markdown wrapping the JSON.\n\n"
        "Internal reasoning (use, do not quote verbatim):\n"
        f"{json.dumps(reasoning, ensure_ascii=False)}\n"
    )
    
    # Language enforcement
    task = f"ALWAYS WRITE THE RESPONSE (subject, body) IN {lang}.\n\n{task}"

    if (prompt_setup_text or "").strip():
        task = f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n" + task
    if regenerate_hint:
        task += regenerate_hint

    data = {
        "recipient": {
            "company": contact.company,
            "name": contact.name,
            "role": role,
            "email": contact.email,
            "website": contact.website,
        },
        "personalization": pers,
        "run_brief": brief,
    }

    prompt = build_prompt(
        task=task,
        data=data,
        rules=rules,
        output_schema=DRAFT_SCHEMA,
    )
    out = generate_json(prompt, task_kind="outreach_draft")
    subject = (out.get("subject") or "").strip()
    body = (out.get("body") or "").strip()
    if not subject or not body:
        raise ValueError("Model returned empty subject or body")
    if len(body) < 120:
        raise ValueError("Email body too short")
    if len(body) > 12000:
        raise ValueError("Email body too long")
    return subject, body


def _draft_without_reasoning(
    db: Session,
    run: Any,
    contact: Contact,
    *,
    prompt_setup_text: str | None,
    master_variant: dict[str, str] | None,
    style_mode: str,
    prior_issues: list[str] | None = None,
    regenerate_hint: str = "",
) -> tuple[str, str]:
    """Single-shot draft if reasoning step fails."""
    return generate_email_draft(
        db,
        run,
        contact,
        {
            "hook": "",
            "angle": "",
            "problem": "",
            "solution": "",
            "cta_type": "",
            "key_point": "",
        },
        prompt_setup_text=prompt_setup_text,
        master_variant=master_variant,
        style_mode=style_mode,
        prior_issues=prior_issues,
        regenerate_hint=regenerate_hint,
    )


def _build_generation_meta(
    *,
    reasoning: dict[str, str],
    style_mode: str,
    val: dict[str, Any],
    validation_retries: int,
    pipeline_source: str,
) -> dict[str, Any]:
    return {
        "reasoning": reasoning,
        "style_mode": style_mode,
        "validation_score": val.get("score"),
        "validation_issues": val.get("issues", []),
        "is_valid": val.get("is_valid"),
        "peer_similarity_max": val.get("peer_similarity_max"),
        "validation_retries": validation_retries,
        "pipeline_source": pipeline_source,
    }


def compose_outreach_subject_body(
    db: Session,
    run: Any,
    contact: Contact,
    *,
    prompt_setup_text: str | None,
    master_variant: dict[str, str] | None,
    regenerate_from_subject: str | None = None,
    regenerate_from_body: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """
    Unified entry: personalization → reasoning → draft → validate with retries.
    Returns (subject, body, generation_meta_json).
    """
    ensure_contact_personalization(db, contact)
    style_mode = resolve_effective_email_style(db, run, contact)
    peer_bodies = list_outbound_draft_bodies_for_run_excluding_contact(db, run.id, contact.id)
    pers = _serialize_personalization(db, contact)

    reg_hint = ""
    if (regenerate_from_body or "").strip() or (regenerate_from_subject or "").strip():
        reg_hint = (
            "\n\nREGENERATE: The user clicked Regenerate. "
            "Produce a meaningfully different subject and body than the prior draft below "
            "(do not reuse sentences or overall structure; keep the same campaign goal).\n"
            f"Prior subject: {(regenerate_from_subject or '')[:500]}\n"
            f"Prior body (avoid repeating):\n{(regenerate_from_body or '')[:8000]}\n"
        )

    reasoning: dict[str, str] = {
        "hook": "",
        "angle": "",
        "problem": "",
        "solution": "",
        "cta_type": "",
        "key_point": "",
    }

    try:
        reasoning = generate_email_reasoning(
            db,
            run,
            contact,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
            regenerate_hint=reg_hint,
        )
        subject, body = generate_email_draft(
            db,
            run,
            contact,
            reasoning,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
            regenerate_hint=reg_hint,
        )
    except Exception as exc:
        logger.warning(
            "Outreach two-step LLM failed run_id=%s contact_id=%s: %s — trying draft-only",
            getattr(run, "id", None),
            contact.id,
            exc,
            exc_info=False,
        )
        subject, body = _draft_without_reasoning(
            db,
            run,
            contact,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
            regenerate_hint=reg_hint,
        )

    val = validate_outbound_email(subject, body, pers, peer_bodies)
    retries = 0

    def _issue_lines(v: dict[str, Any]) -> list[str]:
        out: list[str] = []
        for issue in v.get("issues") or []:
            if isinstance(issue, dict) and (issue.get("detail") or "").strip():
                out.append(str(issue["detail"]).strip())
        return out

    while retries < MAX_VALIDATION_RETRIES and not val.get("is_valid"):
        retries += 1
        prior = _issue_lines(val)
        if not prior:
            prior = ["Improve specificity and remove generic phrasing."]
        has_reasoning = any(
            (reasoning or {}).get(k) for k in ("hook", "angle", "problem", "solution", "cta_type")
        )
        try:
            if has_reasoning:
                subject, body = generate_email_draft(
                    db,
                    run,
                    contact,
                    reasoning,
                    prompt_setup_text=prompt_setup_text,
                    master_variant=master_variant,
                    style_mode=style_mode,
                    prior_issues=prior,
                    regenerate_hint=reg_hint,
                )
            else:
                subject, body = _draft_without_reasoning(
                    db,
                    run,
                    contact,
                    prompt_setup_text=prompt_setup_text,
                    master_variant=master_variant,
                    style_mode=style_mode,
                    prior_issues=prior,
                    regenerate_hint=reg_hint,
                )
        except Exception as exc:
            logger.warning(
                "Validation retry draft failed run_id=%s contact_id=%s: %s",
                getattr(run, "id", None),
                contact.id,
                exc,
                exc_info=False,
            )
            break
        val = validate_outbound_email(subject, body, pers, peer_bodies)

    meta = _build_generation_meta(
        reasoning=reasoning,
        style_mode=style_mode,
        val=val,
        validation_retries=retries,
        pipeline_source="llm",
    )
    pt = (prompt_setup_text or "").strip()
    meta["prompt_setup_text_used"] = pt if pt else None
    return subject, body, meta


def build_template_fallback_meta(
    db: Session,
    run: Any,
    contact: Contact,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """After personalize_outbound: still record style + validation snapshot."""
    style_mode = resolve_effective_email_style(db, run, contact)
    pers = _serialize_personalization(db, contact)
    peer_bodies = list_outbound_draft_bodies_for_run_excluding_contact(db, run.id, contact.id)
    val = validate_outbound_email(subject, body, pers, peer_bodies)
    return {
        "reasoning": {},
        "style_mode": style_mode,
        "validation_score": val.get("score"),
        "validation_issues": val.get("issues", []),
        "is_valid": val.get("is_valid"),
        "peer_similarity_max": val.get("peer_similarity_max"),
        "validation_retries": 0,
        "pipeline_source": "template_fallback",
        "prompt_setup_text_used": None,
    }
