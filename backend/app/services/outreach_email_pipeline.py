"""Two-step outbound email generation: reasoning JSON → subject/body + validation + style (stage 2–3)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.repositories.email_draft_repo import list_outbound_draft_bodies_for_run_excluding_contact
from app.services.email_finale_templates import (
    effective_segment_for_malindi,
    finale_instruction_block,
    get_finale_text,
    get_finale_variants,
    pick_finale_variant_index,
)
from app.services.email_style_service import resolve_effective_email_style, style_prompt_fragment
from app.services.email_validation_service import (
    EMAIL_KIND_NO_VACANCY,
    email_kind_for,
    validate_outbound_email,
)
from app.services.geo_segment_service import resolve_geo_segment
from app.services.llm_gateway import generate_json
from app.services.persona_service import get_run_persona
from app.services.personalization_service import sync_contact_personalization_row
from app.utils.contact_personalization_io import get_personalization_dict
from app.utils.contact_source_payload import effective_contact_source_json
from app.services.prompt_builder import build_prompt_split
from app.services.rules_service import get_effective_rules_from_run
from app.services.run_context_service import (
    build_master_prompt_text,
    get_critic_canon_text,
    get_effective_context,
    get_max_authored_words,
)

logger = logging.getLogger(__name__)

# Email skeleton = 5 evidence-backed slots (decision 09.06). Names reuse the legacy keys where they
# map (hook=Зацепка/trigger, angle=Мэтчинг, cta_type=Призыв) and add explicit problem/solution.
# key_point is kept (mirrors solution) for backward compat with meta/UI readers.
REASONING_SCHEMA = {
    "hook": "string",       # Зацепка: конкретный инфоповод о компании/ЛПР (заземлён на факт)
    "angle": "string",      # Мэтчинг: через проблему/ценности/подход/корп-событие
    "problem": "string",    # Проблема, которую решаем (подтверждена фактом)
    "solution": "string",   # Решение/Quick Win под этот кейс (оффер из prompt_setup_text; при матче — программа из каталога, см. _apply_program_match)
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


def _sanitize_vacancy_signals_for_prompt(signals: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip provenance (source URLs AND the summary line) from vacancy_signals before it enters
    any LLM prompt (decision 7, B-063): the letter must say WHAT is open, never WHERE we found
    it. `summary` follows vacancy_radar.EXTRACTION_SCHEMA, which names the source by design (e.g.
    "Hiring: senior Unity dev, 2D artist (careers page, LinkedIn)") — leaving it in the prompt
    re-leaks exactly the surveillance framing this sanitizer exists to remove (code review
    finding #2: incident Brickworks, 15.07). role/location/country on each role is all the
    generator needs. The full signals (summary + sources) stay in run_company_extra for anyone
    that needs provenance outside the prompt."""
    if not isinstance(signals, dict):
        return signals
    roles = signals.get("open_roles")
    clean_roles: list[dict[str, Any]] = []
    if isinstance(roles, list):
        for r in roles:
            if isinstance(r, dict):
                clean_roles.append({k: v for k, v in r.items() if k != "evidence_url"})
    return {
        "is_hiring": signals.get("is_hiring"),
        "open_roles": clean_roles,
    }


def _serialize_personalization(db: Session, contact: Contact) -> dict[str, Any]:
    from app.models.run_company import RunCompany
    pj = get_personalization_dict(db, contact.id, contact.personalization_json)

    osint_dossier = ""
    vacancy_signals = None
    if contact.company:
        rc = db.query(RunCompany).filter(RunCompany.run_id == contact.run_id, RunCompany.name == contact.company).first()
        if rc:
            from app.utils.run_company_extra import effective_run_company_extra
            kv = effective_run_company_extra(db, rc)
            osint_dossier = kv.get("osint_dossier", "")
            vacancy_signals = kv.get("vacancy_signals") or None

    return {
        "company_facts": pj.get("company_facts") or [],
        "role_angle": (pj.get("role_angle") or "").strip(),
        "why_this_company": (pj.get("why_this_company") or "").strip(),
        "offer_fit": (pj.get("offer_fit") or "").strip(),
        "risks_or_constraints": (pj.get("risks_or_constraints") or "").strip(),
        "osint_dossier": osint_dossier,
        "person_osint": pj.get("person_osint"),
        "vacancy_signals": _sanitize_vacancy_signals_for_prompt(vacancy_signals),
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
    pers: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Internal planning JSON — not the email itself."""
    role = _contact_role_for_prompt(db, contact)
    brief = _run_brief_blocks(run)
    if pers is None:
        pers = _serialize_personalization(db, contact)  # standalone callers; compose passes it in
    rules = _rules(db, run.id)
    style_block = style_prompt_fragment(style_mode)
    
    rs = getattr(run, "run_setup", None)
    lang = getattr(rs, "language", "English") or "English"

    variant_note = ""
    if master_variant:
        variant_note = (
            "A master variant exists for this run — it is a TONE/STRUCTURE reference for this campaign only, "
            "not text to reuse verbatim in the reasoning step.\n"
            f"Reference subject (do not copy): {master_variant.get('subject', '')[:200]}\n"
        )

    task = rs.reasoning_prompt if rs and rs.reasoning_prompt else (
        f"{style_block}\n\n"
        "You are a senior SDR at the sender company described in Campaign / prompt setup above. "
        "Plan one outbound email as a 5-slot skeleton based on this recipient's evidence (OSINT). "
        "Return a short internal plan (not the email).\n\n"
        f"{variant_note}"
        "Fill these slots (each grounded in INPUT DATA, never invented):\n"
        "- hook: ONE concrete trigger / newsworthy fact about this company or person. Priority: "
        "personalization.vacancy_signals (they are hiring RIGHT NOW — name the specific open roles) "
        "> personalization.person_osint > personalization.osint_dossier / company_facts.\n"
        "- angle: how we connect to them — through their problem, values, approach, or a recent company event.\n"
        "- problem: the specific pain we address, supported by a fact from the evidence "
        "(e.g. team scaling, hiring pressure, restructuring, production/timeline risk).\n"
        "- solution: ONE fast, concrete first step for THIS case. Draw the offer/who-we-are from the "
        "Campaign / prompt setup (persona) above; pick the angle that fits their problem.\n"
        "- cta_type: what we ask for (e.g. a short 15-minute call).\n\n"
        "Grounding rules: do not invent companies, metrics, people, or awards not present in INPUT DATA. "
        "If personalization.person_osint is present, PRIORITIZE facts about the person (quotes, articles, "
        "career) over the general company dossier.\n"
        # The `solution` slot may be overwritten after reasoning by a concrete catalog program
        # (_apply_program_match) — it stays the single offer slot either way.
    )

    # Language enforcement
    task = f"ALWAYS WRITE THE RESPONSE (hook, angle, problem, solution, cta_type) IN {lang}.\n\n{task}"

    # B-371: prompt_setup_text (HARD RULES + gold-standard, per run — byte-constant within a run) is
    # a cacheable prefix rather than glued straight into task, so Anthropic can cache it across calls.
    cacheable_prefix = ""
    if (prompt_setup_text or "").strip():
        cacheable_prefix = f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n"
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

    prefix, rest = build_prompt_split(
        task=task,
        data=data,
        rules=rules,
        output_schema=REASONING_SCHEMA,
        cacheable_prefix=cacheable_prefix,
    )
    out = generate_json(rest, task_kind="outreach_reasoning", cache_prefix=prefix)
    solution = (out.get("solution") or out.get("key_point") or "").strip()
    return {
        "hook": (out.get("hook") or "").strip(),
        "angle": (out.get("angle") or "").strip(),
        "problem": (out.get("problem") or "").strip(),
        "solution": solution,
        "cta_type": (out.get("cta_type") or "").strip(),
        "key_point": solution,  # backward-compat mirror for meta/UI readers
    }


# No-vacancy body (ru-email-canon.md §2.3, decision 5): when the radar confirmed zero open roles,
# a "we saw you're hiring X" hook is forbidden — use the "reaching out early" approach instead.
# The closing paragraph is still injected separately by geo (finale_instruction_block), so these
# templates cover only the opening + who-we-are paragraphs.
NO_VACANCY_OPENERS: dict[str, dict[str, str]] = {
    "en": {
        "founder": (
            "One co-founder to another — this isn't about a specific vacancy. I'm reaching out "
            "early, before there's a role to fill, because the studios we work best with usually "
            "get to know us before the hiring crunch hits, not during it."
        ),
        "other": (
            "This isn't about a specific vacancy — I'm reaching out early, before there's a role "
            "to fill, because the studios we work best with usually get to know us before the "
            "hiring crunch hits, not during it."
        ),
    },
    "ru": {
        "founder": (
            "Пишу как кофаундер кофаундеру — и это не про конкретную вакансию. Обращаюсь "
            "заранее, до того как появится роль под закрытие: студии, с которыми у нас "
            "складывается лучше всего, обычно знакомятся с нами до горячки найма, а не в её "
            "разгар."
        ),
        "other": (
            "Это письмо не про конкретную вакансию. Пишу заранее, до того как появится роль под "
            "закрытие: студии, с которыми у нас складывается лучше всего, обычно знакомятся с "
            "нами до горячки найма, а не в её разгар."
        ),
    },
}

NO_VACANCY_MIDDLE: dict[str, str] = {
    "en": (
        "We're AlexStaff — an IT-recruiting agency, recruiting for game studios and publishers "
        "since 2006. We grew the Broken Sun team from 30 to about 260 people through open beta, "
        "and here on Cyprus we've been growing Helio Games' team since 2021 — around 20 hires, "
        "a significant part of the studio, with the studio coming back to us year after year.\n\n"
        "When you do open a seat — engineer, artist, designer — the slow part is finding someone "
        "who actually wants to build your game, not just field another offer. This is what we do "
        "best: we start working as soon as the financial terms are agreed, and within 24-72 "
        "hours you meet a first candidate who fits the role and genuinely wants to build your "
        "project."
    ),
    "ru": (
        "Мы — AlexStaff, IT-рекрутинговое агентство; подбираем для игровых студий и издателей с "
        "2006 года. Команду Broken Sun вырастили с 30 до примерно 260 человек за время открытой "
        "беты, а здесь, на Кипре, с 2021 года растим команду Helio Games — около 20 наймов, "
        "значительная часть студии.\n\n"
        "Когда позиция откроется — инженер, художник, дизайнер — самое долгое будет найти "
        "человека, которому действительно хочется делать вашу игру, а не просто рассматривать "
        "ещё один оффер. Это ровно то, что мы умеем лучше всего: начинаем работать сразу после "
        "согласования финансовых условий, и уже через 24–72 часа вы встречаете первого "
        "кандидата, который подходит и которому по-настоящему хочется работать над вашим "
        "проектом."
    ),
}


def _is_founder_role(role: str) -> bool:
    return "founder" in (role or "").lower()


def _sender_is_founder(persona) -> bool:
    """Does the SENDING persona speak as a co-founder? The "One co-founder to another" opener
    asserts it about the sender, not only about the recipient — Stepan (US COO, B-128) must never
    use it, or the body contradicts the "I'm the agency's COO" self-intro in his own finale."""
    from app.services.persona_service import ALEXEY_SLUG

    return (getattr(persona, "slug", "") or "").strip().lower() == ALEXEY_SLUG


def _no_vacancy_block(lang: str, role: str, persona=None) -> str:
    lang_key = "ru" if (lang or "").strip().lower() == "russian" else "en"
    peer_to_peer = _is_founder_role(role) and (persona is None or _sender_is_founder(persona))
    variant = "founder" if peer_to_peer else "other"
    opener = NO_VACANCY_OPENERS[lang_key][variant]
    middle = NO_VACANCY_MIDDLE[lang_key]
    return (
        "NO-VACANCY OPENING (ru-email-canon.md §2.3) — the vacancy radar confirmed ZERO open "
        "roles for this company. It is FORBIDDEN to name any specific job title/role anywhere in "
        "this email. Use this opening + who-we-are content closely (adapt the name/company, do "
        "not invent open roles); the closing paragraph is injected separately below, do not "
        "duplicate it here:\n"
        f"{opener}\n\n{middle}"
    )


def _worldwide_note(vacancy_signals: dict[str, Any]) -> str | None:
    """Worldwide-hiring block (ru-email-canon.md §2.1, decision 6): confirmed roles outside
    Cyprus, or spread across several countries, is framed as OUR advantage in the body — never a
    reason to soften the pitch. Does not affect the closing-paragraph geo segment (always the
    recipient's own location)."""
    roles = vacancy_signals.get("open_roles") or []
    if not isinstance(roles, list) or not roles:
        return None
    countries: set[str] = set()
    non_cyprus = False
    for r in roles:
        if not isinstance(r, dict):
            continue
        country = (r.get("country") or "").strip()
        location = (r.get("location") or "").strip()
        combo = f"{country} {location}".lower()
        if country:
            countries.add(country.lower())
        if combo.strip() and "cyprus" not in combo and "кипр" not in combo:
            non_cyprus = True
    if not non_cyprus and len(countries) <= 1:
        return None
    n_roles = len(roles)
    n_countries = max(len(countries), 1)
    return (
        "WORLDWIDE HIRING (ru-email-canon.md §2.1) — this company's confirmed open roles are "
        "outside Cyprus or spread across several countries. Do NOT soften the pitch; add ONE "
        "sentence in the body framing this as our advantage, in this spirit: "
        f'"{n_roles} roles across {n_countries} countries means {n_countries} candidate markets '
        'at once — and we\'re well set up to search in all of them." Also weave in the '
        'worldwide-sourcing formula: "we find the right candidates anywhere in the world — '
        'working locally, relocating, or fully remote". This does NOT change the closing-'
        "paragraph geo segment below, which is always based on the RECIPIENT's own location, "
        "not the company's hiring geography."
    )


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
    pers: dict[str, Any] | None = None,
    finale_variant_index: int | None = None,
) -> tuple[str, str]:
    """Final subject + body; must reflect personalization and reasoning.

    finale_variant_index (B-147): which closing-paragraph variant to use, pre-chosen by the caller
    (compose_outreach_subject_body) so every retry of the same generation attempt agrees with the
    one that gets persisted to email_drafts.finale_variant. None picks at random (e.g. direct/test
    callers that don't need to persist the choice).
    """
    role = _contact_role_for_prompt(db, contact)
    if pers is None:
        pers = _serialize_personalization(db, contact)
    rules = _rules(db, run.id)
    brief = _run_brief_blocks(run)
    style_block = style_prompt_fragment(style_mode)
    
    rs = getattr(run, "run_setup", None)
    lang = getattr(rs, "language", "English") or "English"

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

    custom_draft_prompt = bool(rs and rs.draft_prompt)
    task = rs.draft_prompt if rs and rs.draft_prompt else (
        f"{style_block}\n\n"
        + fix_block
        + "You are a senior SDR writing on behalf of the sender company described in "
        "Campaign / prompt setup above — take the persona, offer, and proof points from there. "
        "FOCUS: offer one fast, concrete first step that gives the recipient immediate value "
        "and opens the door to a long-term engagement.\n\n"
        "Write one outbound B2B cold email (subject + body) for this recipient.\n\n"
        + master_block
        + "Follow the planned 5-slot skeleton from Internal reasoning, in order: "
        "open with `hook` (the concrete trigger) → connect via `angle` → name the `problem` → "
        "offer the `solution` (one concrete first step) → close with `cta_type`. Weave them into "
        "natural prose (do NOT print slot labels).\n"
        + "Hard requirements:\n"
        "- If personalization.vacancy_signals is non-empty, the hook MUST reference the concrete "
        "open role(s) they are hiring for right now and tie the offer to filling them fast.\n"
        "- Otherwise, if personalization.person_osint is non-empty, you MUST start the email with a hook referencing their personal background, article, or quote.\n"
        "- If personalization.osint_dossier is non-empty (and neither of the above applies), use a concrete fact from it as the opening hook.\n"
        "- After listing concrete facts (e.g. open roles), add ONE sentence interpreting what they mean "
        "for this recipient's role (e.g. 'that's simultaneous scaling across art and engineering — "
        "which lands on your desk as a coordination problem'). Facts without interpretation read like a bot.\n"
        "- Include 1-2 proof points WITH CONCRETE NUMBERS from the campaign setup (clients, team-growth "
        "figures, percentages). A letter without numbers is a weak letter.\n"
        "- Address the specific pain from the reasoning `problem` slot (scaling, hiring, production pressure, etc.) as evidenced by the dossier.\n"
        "- Offer ONE specific, fast first step drawn from the campaign setup or the matched offer.\n"
        "- If the `solution` slot names a concrete offer/program, convey its essence in plain words "
        "(the key points/benefits) IN THE BODY (the concise solution digest) — do NOT use the "
        "internal program/offer name itself (HARD RULE 2 always wins). Do NOT attach or "
        "promise an attachment — instead, OFFER to send detailed materials if they're interested. "
        "Materials follow only after a reply.\n"
        "- Do NOT write a closing paragraph, meeting offer, sign-off, or CTA question of your own "
        "(B-158) — the system appends the geo-specific closing paragraph (which already contains "
        "the meeting offer and the CTA question) programmatically right after your body. End the "
        "body immediately after the concrete offer/solution content: no farewell line, no "
        "invitation to meet, no goodbye.\n"
        "- Write like one human to another: plain words, no buzzwords or marketing jargon.\n"
        "- Avoid generic openers: jump straight into the fact or trigger.\n"
        "- Body: include a brief salutation (e.g. Hi FirstName,) then 4-8 sentences total (the "
        "closing paragraph is appended separately, not counted here).\n"
        "- Subject: specific, not generic, intriguing; sentence case, grounded in the recipient's facts "
        "(their roles, their numbers). NEVER salesy Title Case like 'Quick Solutions for Your Hiring Needs'.\n"
        "- Return ONLY valid JSON matching the schema. No markdown wrapping the JSON.\n\n"
        "Internal reasoning (use, do not quote verbatim):\n"
        f"{json.dumps(reasoning, ensure_ascii=False)}\n"
    )

    # B-063: geo-segment closing paragraph is mandatory regardless of which base task was used
    # above (default or a per-run rs.draft_prompt override) — the fixed finale is a business
    # rule, not campaign-specific copy.
    # B-071: identity (geo-map + verbatim finales) comes from the run's persona, not a hardcoded
    # sender — empty run.persona_id resolves to the "alexey" persona (decision 8).
    # B-158: the model is NOT asked to write the closing paragraph (see the "Hard requirements"
    # bullet above) — its verbatim text is appended in code after generation instead (below),
    # so byte-exactness is guaranteed by construction rather than by LLM compliance.
    persona = get_run_persona(db, run)
    geo = resolve_geo_segment(db, contact, persona, pers)
    effective_segment = effective_segment_for_malindi(persona, geo["segment"], geo["malindi"])
    finale_text = get_finale_text(
        persona, effective_segment, lang, geo["ex_cis"], geo["malindi"],
        variant_index=finale_variant_index,
    )
    # B-158: запрет писать закрывающий абзац дописывается всегда, но формулировка зависит от того,
    # откуда приехал task. Дефолтный блок выше содержит буллеты «Hard requirements», на которые
    # можно сослаться; кампания со своим draft_prompt (Фаза 2, FG) заменяет их целиком — там
    # ссылка указывала бы в никуда, а вместе с буллетами пропадает и явный запрет на прощание.
    # Текст ветки else сохранён ДОСЛОВНО: кампании без своего draft_prompt (AlexStaff, NODA12 —
    # ни одна из них draft_prompt не задаёт) не меняются ни на байт.
    if custom_draft_prompt:
        task += (
            "\n\nDo NOT write a closing paragraph yourself: no farewell line, no invitation to "
            "meet, no goodbye, no sign-off. The closing paragraph (self-intro + meeting offer + "
            "one closing CTA question) is fixed by business rule and is appended to your body "
            "automatically after you write it."
        )
    else:
        task += (
            "\n\nDo NOT write a closing paragraph yourself — see the 'Hard requirements' bullet above. "
            "The closing paragraph (self-intro + meeting offer + one closing CTA question) is fixed by "
            "business rule and is appended to your body automatically after you write it."
        )

    # Kept in lockstep with the critic's decision below (compose_outreach_subject_body) via the
    # same shared email_kind_for — two independent derivations of "no signal" previously risked
    # drifting apart (generator's has_open_roles vs email_kind_for's vacancy_signals check).
    vacancy_signals = pers.get("vacancy_signals")
    if email_kind_for(pers, persona) == EMAIL_KIND_NO_VACANCY:
        # No confirmed open roles anywhere (radar + dossier), and this persona has no other
        # fallback — the no-vacancy template replaces the roles hook; naming a role here would be
        # an invented one (decision 5/9, B-063).
        task += "\n\n" + _no_vacancy_block(lang, role, persona)
        task += (
            "\n\nHARD RULE: personalization.vacancy_signals is empty — do NOT name any specific "
            "open role/title anywhere in the email; build the hook from the no-vacancy opening "
            "above, not from invented positions."
        )
    else:
        worldwide = _worldwide_note(vacancy_signals or {})
        if worldwide:
            task += "\n\n" + worldwide

    # Language enforcement
    task = f"ALWAYS WRITE THE RESPONSE (subject, body) IN {lang}.\n\n{task}"

    # B-371: same cacheable-prefix treatment as the reasoning step above.
    cacheable_prefix = ""
    if (prompt_setup_text or "").strip():
        cacheable_prefix = f"Campaign / prompt setup (primary):\n{(prompt_setup_text or '').strip()}\n\n"
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

    prefix, rest = build_prompt_split(
        task=task,
        data=data,
        rules=rules,
        output_schema=DRAFT_SCHEMA,
        cacheable_prefix=cacheable_prefix,
    )
    out = generate_json(rest, task_kind="outreach_draft", cache_prefix=prefix)
    subject = (out.get("subject") or "").strip()
    body = (out.get("body") or "").strip()
    if not subject or not body:
        raise ValueError("Model returned empty subject or body")
    if len(body) < 120:
        raise ValueError("Email body too short")
    if len(body) > 12000:
        raise ValueError("Email body too long")

    # B-158: the closing paragraph is appended here, in code, never written by the model — this is
    # what guarantees byte-exactness (the model's own attempts to reproduce it "verbatim" were not
    # reliable; see the module docstring in email_finale_templates.py).
    if finale_text:
        body = f"{body}\n\n{finale_text}"
    return subject, body


def _apply_program_match(
    db: Session, run: Any, reasoning: dict, pers: dict[str, Any]
) -> dict[str, Any] | None:
    """Feature 1: replace the generic `solution` slot with a concrete catalog program when one fits.

    Mutates reasoning's solution/key_point with the program-grounded text (the program name and
    bullets live in that text — that is all the draft model needs) and returns the match record
    for generation meta (meta["matched_program"]: ids/fit/rationale stay OUT of the LLM prompt).
    The PDF is NOT attached to the cold email — matched_program is recorded so the program PDF can
    be sent as a follow-up after a positive reply (decision 12.06).
    Returns None (generic offer kept) when the catalog is empty, nothing fits, or the matcher fails.
    """
    problem = (reasoning.get("problem") or "").strip()
    if not problem:
        return None
    try:
        from app.services.program_matcher import match_program

        rs = getattr(run, "run_setup", None)
        # Фаза 2, Task 3: пресет может выключить матчер целиком (рамка-«веер» перечисляет
        # программы сама и матчер подменил бы её слотом ОДНОЙ программы). Проверяем СРАЗУ после
        # rs и ДО резолва персоны/вызова матчера — выключенный матчер не стоит ни обращения к БД
        # за персоной, ни LLM-вызова. Только явный False; NULL = включён (импорт match_program
        # выше по коду бесплатный, гейт его не экономит и не должен).
        if rs is not None and getattr(rs, "program_match_enabled", None) is False:
            return None
        # Фаза 2, Task 2: матчер видит каталог персоны рана + глобальные строки (persona_id IS
        # NULL). Персона резолвится почти всегда — ран без persona_id падает на строку alexey, —
        # так что фильтр обычно ВКЛЮЧЁН, и неизменность поведения держится не на его отсутствии, а
        # на семантике NULL: пока каталог не размечен по персонам (инстанс партнёра), выборка
        # возвращает ровно те же строки. id=None бывает лишь у in-memory-фоллбэка alexey — когда
        # строки персоны нет в БД вовсе (юнит-вызовы без сидера).
        persona = get_run_persona(db, run)
        match = match_program(
            db,
            problem=problem,
            dossier=pers.get("osint_dossier") or "",
            person_osint=pers.get("person_osint"),
            vacancy_signals=pers.get("vacancy_signals"),
            language=getattr(rs, "language", "English"),
            persona_id=getattr(persona, "id", None),
        )
    except Exception as exc:
        logger.warning("Program matcher failed (generic offer kept): %s", exc, exc_info=False)
        return None
    if not match:
        return None
    reasoning["solution"] = match["solution_text"]
    reasoning["key_point"] = match["solution_text"]
    return {
        "program_id": match["program_id"],
        "name": match["name"],
        "asset_id": match["asset_id"],
        "format": match["format"],
        "bullets": match["bullets"],
        "fit_score": match["fit_score"],
        "rationale": match["rationale"],
    }


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
    pers: dict[str, Any] | None = None,
    finale_variant_index: int | None = None,
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
        pers=pers,
        finale_variant_index=finale_variant_index,
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
        "critic_taste_pass": val.get("critic_taste_pass"),
        "critic_scores": val.get("critic_scores"),
        "critic_hook_grounded": val.get("critic_hook_grounded"),
        "critic_canon_used": val.get("critic_canon_used"),
        "critic_evidence": val.get("critic_evidence"),
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
    # B-071: the critic's fixed-block exclusion (decision 4, B-063) reads the run's persona.
    persona = get_run_persona(db, run)

    # B-147: pick the closing-paragraph variant ONCE per compose call, so every retry below (and
    # the meta persisted to email_drafts.finale_variant) agrees on the same rotated choice.
    rs = getattr(run, "run_setup", None)
    lang = getattr(rs, "language", "English") or "English"
    geo = resolve_geo_segment(db, contact, persona, pers)
    finale_variant_index = pick_finale_variant_index(
        persona, geo["segment"], lang, geo["ex_cis"], geo["malindi"]
    )
    # B-158: the exact set of verbatim closing-paragraph options valid for this recipient's
    # resolved segment — the critic's hard byte-gate below checks the body ends with one of these.
    effective_segment = effective_segment_for_malindi(persona, geo["segment"], geo["malindi"])
    expected_finale_variants = get_finale_variants(
        persona, effective_segment, lang, geo["ex_cis"], geo["malindi"]
    )

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
    matched_program: dict[str, Any] | None = None

    try:
        reasoning = generate_email_reasoning(
            db,
            run,
            contact,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
            regenerate_hint=reg_hint,
            pers=pers,
        )
        matched_program = _apply_program_match(db, run, reasoning, pers)
        subject, body = generate_email_draft(
            db,
            run,
            contact,
            reasoning,
            prompt_setup_text=prompt_setup_text,
            master_variant=master_variant,
            style_mode=style_mode,
            regenerate_hint=reg_hint,
            pers=pers,
            finale_variant_index=finale_variant_index,
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
            pers=pers,
            finale_variant_index=finale_variant_index,
        )

    # B-077: the critic judges against the generation contract (vacancy vs no_vacancy), the same
    # decision generate_email_draft made above via the shared email_kind_for(pers, persona).
    email_kind = email_kind_for(pers, persona)
    # B-077 etap 2: per-run canon of judgement, editable without a deploy (falls back to
    # DEFAULT_CRITIC_CANON inside validate_outbound_email when unset).
    critic_canon = get_critic_canon_text(run)
    max_authored_words = get_max_authored_words(run)
    val = validate_outbound_email(
        subject, body, pers, peer_bodies, email_kind=email_kind, critic_canon=critic_canon,
        persona=persona, expected_finale_variants=expected_finale_variants,
        company_name=(contact.company or "").strip() or None,
        max_authored_words=max_authored_words,
    )
    retries = 0

    # B-077 decision 3: feedback the generator cannot act on without breaking the contract must not
    # drive a retry. For no_vacancy the LLM taste-rubric is skipped, so its codes should never
    # appear — but if they ever do they are contract-conflicting (regeneration would be N× Opus with
    # a predetermined failure, the Horns Up loop) and are filtered out of the retry feedback here.
    _CONTRACT_CONFLICTING_CODES = ("hook_not_grounded", "llm_critic_rejected")

    def _issue_lines(v: dict[str, Any]) -> list[str]:
        skip = set(_CONTRACT_CONFLICTING_CODES) if email_kind == EMAIL_KIND_NO_VACANCY else set()
        out: list[str] = []
        for issue in v.get("issues") or []:
            if not isinstance(issue, dict) or issue.get("code") in skip:
                continue
            if (issue.get("detail") or "").strip():
                out.append(str(issue["detail"]).strip())
        return out

    while retries < MAX_VALIDATION_RETRIES and not val.get("is_valid"):
        prior = _issue_lines(val)
        if not prior:
            if email_kind == EMAIL_KIND_NO_VACANCY:
                # No contract-safe, actionable feedback left — don't burn Opus on a retry whose
                # outcome is predetermined (B-077 decision 3). The verbatim §2.3 draft stands.
                break
            prior = ["Improve specificity and remove generic phrasing."]
        retries += 1
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
                    pers=pers,
                    finale_variant_index=finale_variant_index,
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
                    pers=pers,
                    finale_variant_index=finale_variant_index,
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
        val = validate_outbound_email(
            subject, body, pers, peer_bodies, email_kind=email_kind, critic_canon=critic_canon,
            persona=persona, company_name=(contact.company or "").strip() or None,
            max_authored_words=max_authored_words,
        )

    meta = _build_generation_meta(
        reasoning=reasoning,
        style_mode=style_mode,
        val=val,
        validation_retries=retries,
        pipeline_source="llm",
    )
    meta["matched_program"] = matched_program  # Feature 1: persistence attaches the PDF from here
    meta["finale_variant"] = finale_variant_index  # B-147: which rotated closing variant was used
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
    persona = get_run_persona(db, run)
    val = validate_outbound_email(
        subject, body, pers, peer_bodies,
        email_kind=email_kind_for(pers, persona), critic_canon=get_critic_canon_text(run),
        persona=persona, company_name=(contact.company or "").strip() or None,
        max_authored_words=get_max_authored_words(run),
    )
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
        "critic_taste_pass": val.get("critic_taste_pass"),
        "critic_scores": val.get("critic_scores"),
        "critic_hook_grounded": val.get("critic_hook_grounded"),
        "critic_canon_used": val.get("critic_canon_used"),
        "critic_evidence": val.get("critic_evidence"),
    }
