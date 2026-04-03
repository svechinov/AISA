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
from app.services.prompt_builder import build_prompt
from app.services.rules_service import get_effective_rules_from_run
from app.services.run_context_service import build_master_prompt_text, get_effective_context

logger = logging.getLogger(__name__)

REASONING_SCHEMA = {
    "hook": "string",
    "angle": "string",
    "cta_type": "string",
    "key_point": "string",
}

DRAFT_SCHEMA = {"subject": "string", "body": "string"}

MAX_VALIDATION_RETRIES = 2


def _contact_role_for_prompt(contact: Contact) -> str:
    r = (contact.role or "").strip()
    if r:
        return r
    sj = contact.source_json or {}
    if isinstance(sj, dict):
        for k in ("role", "title", "job_title", "position"):
            v = sj.get(k)
            if v:
                return str(v).strip()
    return ""


def _needs_personalization_sync(contact: Contact) -> bool:
    pj = contact.personalization_json
    if pj is None or not isinstance(pj, dict):
        return True
    if len(pj) == 0:
        return True
    if "role_angle" not in pj:
        return True
    return False


def ensure_contact_personalization(db: Session, contact: Contact) -> None:
    if _needs_personalization_sync(contact):
        sync_contact_personalization_row(db, contact)
        db.add(contact)
        db.flush()


def _rules(db: Session, run_id: int) -> list[str]:
    try:
        return get_effective_rules_from_run(db, run_id, "generate_emails")
    except ValueError:
        return []


def _serialize_personalization(contact: Contact) -> dict[str, Any]:
    pj = contact.personalization_json if isinstance(contact.personalization_json, dict) else {}
    return {
        "company_facts": pj.get("company_facts") or [],
        "role_angle": (pj.get("role_angle") or "").strip(),
        "why_this_company": (pj.get("why_this_company") or "").strip(),
        "offer_fit": (pj.get("offer_fit") or "").strip(),
        "risks_or_constraints": (pj.get("risks_or_constraints") or "").strip(),
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
) -> dict[str, str]:
    """Internal planning JSON — not the email itself."""
    role = _contact_role_for_prompt(contact)
    brief = _run_brief_blocks(run)
    pers = _serialize_personalization(contact)
    rules = _rules(db, run.id)
    style_block = style_prompt_fragment(style_mode)

    variant_note = ""
    if master_variant:
        variant_note = (
            "A master variant exists for this run — it is a TONE/STRUCTURE reference for this campaign only, "
            "not text to reuse verbatim in the reasoning step.\n"
            f"Reference subject (do not copy): {master_variant.get('subject', '')[:200]}\n"
        )

    task = (
        f"{style_block}\n\n"
        "Plan one outbound email for this recipient.\n\n"
        f"{variant_note}"
        "Return a short internal plan (not the email).\n"
        "Requirements:\n"
        "- hook: one concrete reason this message fits this company/person (no generic praise)\n"
        "- angle: how we frame the ask (one line)\n"
        "- cta_type: what we ask for (e.g. reply, call, read)\n"
        "- key_point: the single idea to land\n\n"
        "Ground the hook in personalization.company_facts and role_angle when present; "
        "do not invent companies, metrics, or awards not present in INPUT DATA.\n"
    )
    if (prompt_setup_text or "").strip():
        task = (
            f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n" + task
        )

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
    return {
        "hook": (out.get("hook") or "").strip(),
        "angle": (out.get("angle") or "").strip(),
        "cta_type": (out.get("cta_type") or "").strip(),
        "key_point": (out.get("key_point") or "").strip(),
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
) -> tuple[str, str]:
    """Final subject + body; must reflect personalization and reasoning."""
    role = _contact_role_for_prompt(contact)
    pers = _serialize_personalization(contact)
    rules = _rules(db, run.id)
    brief = _run_brief_blocks(run)
    style_block = style_prompt_fragment(style_mode)

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

    task = (
        f"{style_block}\n\n"
        + fix_block
        + "Write one outbound email (subject + body) for this recipient.\n\n"
        + master_block
        + "Hard requirements:\n"
        "- If personalization.company_facts is non-empty, use at least one concrete detail in the body "
        "(paraphrase allowed). If it is empty, anchor the email in recipient company/name/role only.\n"
        "- Reflect personalization.role_angle when non-empty; otherwise stay specific to recipient fields.\n"
        "- Explain briefly why this recipient/company (why_this_company or key_point from reasoning).\n"
        "- Avoid generic openers: do not start with 'I hope this finds you well', 'I wanted to reach out', "
        "'I came across', 'We help companies like yours', or similar filler.\n"
        "- Body: include a brief salutation (e.g. Hi FirstName,) then paragraphs; 5–12 sentences total.\n"
        "- Subject: specific, not generic.\n"
        "- No markdown unless necessary.\n\n"
        "Internal reasoning (use, do not quote verbatim):\n"
        f"{json.dumps(reasoning, ensure_ascii=False)}\n"
    )
    if (prompt_setup_text or "").strip():
        task = f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n" + task

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
) -> tuple[str, str]:
    """Single-shot draft if reasoning step fails."""
    return generate_email_draft(
        db,
        run,
        contact,
        {
            "hook": "",
            "angle": "",
            "cta_type": "",
            "key_point": "",
        },
        prompt_setup_text=prompt_setup_text,
        master_variant=master_variant,
        style_mode=style_mode,
        prior_issues=prior_issues,
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
) -> tuple[str, str, dict[str, Any]]:
    """
    Unified entry: personalization → reasoning → draft → validate with retries.
    Returns (subject, body, generation_meta_json).
    """
    ensure_contact_personalization(db, contact)
    style_mode = resolve_effective_email_style(run, contact)
    peer_bodies = list_outbound_draft_bodies_for_run_excluding_contact(db, run.id, contact.id)
    pers = _serialize_personalization(contact)

    reasoning: dict[str, str] = {
        "hook": "",
        "angle": "",
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
        )
        subject, body = generate_email_draft(
            db,
            run,
            contact,
            reasoning,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
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
            (reasoning or {}).get(k) for k in ("hook", "angle", "key_point", "cta_type")
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
    return subject, body, meta


def build_template_fallback_meta(
    db: Session,
    run: Any,
    contact: Contact,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """After personalize_outbound: still record style + validation snapshot."""
    style_mode = resolve_effective_email_style(run, contact)
    pers = _serialize_personalization(contact)
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
    }
