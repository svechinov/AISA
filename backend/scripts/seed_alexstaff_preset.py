"""Sync the AlexStaff Agency canon (prompt/critic/signature/ICP) onto a live run's RunSetup.

This script does NOT create or look up projects/runs by name — it never invents a target.
The run to sync is given explicitly via --run-id (no default). If that run does not exist,
the script prints an error and exits with code 1. Historical runs are never touched
implicitly; always name the run id you mean.

Action: upsert the run_setups row for --run-id with the canon below (prompt_setup_text,
critic_canon_text, language, osint_discovery_mode, sender_signature_html, icp_min_employees,
icp_max_employees, icp_criteria_json). Creates the RunSetup row if it doesn't exist yet.

--dry-run is mandatory to run before any write against a live campaign: it writes nothing
and prints a unified diff (difflib) of the DB's current value vs canon for every text field,
plus a before/after line for every scalar field. Read the diff before dropping --dry-run.

Offer catalog (OFFERS / TrainingProgram) is global — training_programs has no project_id or
run_id column, so it is not scoped to any project/run — seeding it is opt-in via
--seed-offers (off by default) so this script stays focused on the RunSetup sync it exists
for. It remains idempotent by name when used.

Usage (local):
    cd backend && ./venv/bin/python scripts/seed_alexstaff_preset.py --run-id 3 --dry-run
    cd backend && ./venv/bin/python scripts/seed_alexstaff_preset.py --run-id 3

Usage (prod — per CLAUDE.md "Грабли", scripts/ is not baked into the image, so run it via
the infra/data bind mount and remove it afterwards):
    scp backend/scripts/seed_alexstaff_preset.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_alexstaff_preset.py --run-id 3 --dry-run'
    # review the diff; only if it looks right:
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_alexstaff_preset.py --run-id 3'
    ssh bizos 'rm ~/ai-biz-os/infra/data/seed_alexstaff_preset.py'

Source of truth for the persona/proof points: context/recruiting/utp/game-dev-recruiting-utp.md
(condensed to English here).
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.models.sending_policy import SendingPolicy  # noqa: E402
from app.models.training_program import TrainingProgram  # noqa: E402
from app.services.critic_canon import DEFAULT_CRITIC_CANON  # noqa: E402
from app.services.persona_service import (  # noqa: E402
    ALEXEY_SLUG,
    ANASTASIA_SLUG,
    STEPAN_SLUG,
    alexey_persona_kwargs,
    anastasia_persona_kwargs,
    stepan_persona_kwargs,
)

PROMPT_SETUP_TEXT = """About us (AlexStaff Agency, alexstaff.agency): an IT-recruiting agency that has recruited for game studios and publishers since 2006 - combining the reach and process of a specialised IT-recruiting agency with ~20 years lived inside gamedev. Voice: "we" - the agency team. Sender: Alexey, the agency's co-founder, based in Paphos, Cyprus; often in Limassol. Meeting-offer geography is NOT improvised per email: the closing paragraph is resolved by a geo-segment cascade (recipient's own location -> company office city -> company country; Cyprus with no city -> segment 4; not Cyprus or unclear -> segment 5) and appended to your body in code, not written by you (see HARD RULE 11). Meeting options always live inside one sentence - never as a menu of separate questions (see HARD RULE 7). The agency also has a US office - worth mentioning to English-speaking recipients (distributed organization, calls across time zones are fine).

Proof anchors (all can be named openly):
- Alawar (since 2006): hired ~70 people - a third of the company at its 2008 peak (~200).
- Alawar (2003-2008, use for casual-game studios): we hired about a third of the company during its golden era - the years that produced Farm Frenzy and Treasures of Montezuma.
- Helio Games (Limassol, Cyprus): around 20 hires since 2021 - a significant part of their current team, with the studio coming back to us year after year.
- Social Quantum: opened their Novosibirsk office from scratch and grew it from 2-3 to 120+ people.
- Broken Sun MMORPG (OIJO GAMES / REDNECK STUDIO): grew the team from 30 to about 260 people through open beta - hundreds of hires along the way - while raising the seniority bar, not diluting it; relocated up to 35 people per month under hard logistics.
- Georgia presence: two of our own team live in Georgia, one of them right in Tbilisi - use when the company hires in Georgia / the Caucasus ("we know that market from the inside").

Offer: once commercial terms are agreed, sourcing starts within hours and we present the first candidate within 24-72 hours. Roles: Unity/C#, Unreal, art, animation, game design, narrative, QA, backend (Node/TS, .NET). We source worldwide - remote and relocation, many countries and languages, not limited to one market.

Differentiator: instead of forwarding CV piles, we get candidates genuinely excited about the studio and what it is building, so they come already wanting to work there specifically, not just weighing another offer.

Second differentiator (use when depth of partnership matters more than speed): studios don't hire us for one-off vacancy closings - they trust us to grow their team for years (Alawar: ~70 hires since 2006, a third of the company at its 2008 peak; Helio Games: around 20 hires since 2021, a significant part of their current team).

Art-role differentiator (use whenever the confirmed roles include art): for art roles we bring in external experts who assess portfolio style fit before candidates reach the studio - the studio only meets artists who match its visual direction.

Email goal: a short intro 15-minute call (or an in-person meeting for Cyprus-based studios).

Tone: expert, concise, like a personal 1-on-1 note; no sales clichés, no buzzwords.

HARD RULES (always follow):
1. The first candidate comes within 24-72 hours AFTER commercial terms are agreed - never tie the 24-72h window to just a call or a brief. Prefer phrasing like "once we've agreed the terms, sourcing starts within hours - and in 24-72 hours you meet a first candidate who fits the role and wants to join <Company>": the promise must name speed AND fit AND motivation, never speed alone. Open the help paragraph directly with what we do (e.g. "We can help - not by forwarding CV piles, but by bringing you candidates genuinely excited about what you're building...") rather than circling back to the previous paragraph's problem first (see HARD RULE 14).
2. Do NOT quote internal program/offer names (no "Tempo hiring", "Scale-up hiring", etc.) - describe the approach in plain words, no capitalised branded method names.
3. Position us as an IT-recruiting agency that has recruited for game studios and publishers since 2006 - not as "just gamedev people" or "not an HR agency". Do not invent a separate "gaming division" name.
4. Length: the whole email body YOU write is about 120-140 words in 3 short paragraphs - a cold email, not an essay (the closing paragraph is a 4th paragraph appended in code afterward, see HARD RULE 11; do not write it and do not count it here). The who-we-are block ("We're AlexStaff - ...") is at most 2 sentences: one of positioning, one with the proof points. The salutation uses the FULL form of the recipient's first name (Dmitry, Alexander) - never a diminutive (Dima, Sasha), even if the contact data spells it that way.
5. Talk about the recipient's TASK and the facts - never speculate about their feelings or state of mind. BANNED: "you're probably feeling the pressure", "this must be stressful", "I imagine you're overwhelmed" and any similar guesses about emotions. Interpret what the facts mean for the work, not for the person's mood. When interpreting, name the PROCESS, not the people: "finding reliable engineers is the bottleneck", never "your engineers are the bottleneck" (reads as blaming their team). Never assert their internal limits either ("it's outpacing your capacity") - describe the load itself, not what they supposedly cannot handle.
6. The subject line MUST include the recipient company's name - it pulls harder in the inbox than a city or a generic phrase (e.g. "Sunday Games" beats "(Limassol)").
7. One ask per email: a single low-friction closing question. Do not offer a menu of options ("a call or a meeting or...").
8. NEVER name specific open roles or vacancies unless they are literally present in the evidence (personalization.vacancy_signals or the dossier). If personalization.vacancy_signals is empty or missing, that means the live vacancy radar found ZERO confirmed open roles - do not fall back on training memory or invent roles from the company's general profile; build the email on the no-vacancy template (see NO-VACANCY OPENING instructions injected below) instead of a roles hook. Name a confirmed role plainly (e.g. "an artist", "a Unity developer") - do not recite the posting's attributes (remote/hybrid, seniority grade, location) back at the recipient: they know their own vacancy. Mention an attribute later in the body only when it carries our offer (e.g. remote or multi-country roles -> the worldwide-sourcing sentence).
9. NEVER add a sign-off, valediction, or sender name at the end of the body (no "Best,", no "Alexey", no company name) - the system appends the sender's signature block automatically. End the body with the closing CTA question.
10. Sources rule: say WHAT is open (the roles), never WHERE we found it. The company's own careers page is fine to reference implicitly ("your careers page shows..."), but NEVER name a third-party job board or aggregator (hh.ru, ingamejob, BuiltIn, Glassdoor, LinkedIn Jobs, etc.) - listing where we looked reads as surveillance, not research.
11. The closing paragraph is fixed per the recipient's geo segment (Paphos / Limassol / Larnaca-Nicosia / Cyprus-no-city / not-Cyprus) and is appended to your body in code after you write it (B-158) - do NOT write your own meeting offer, sign-off, or closing paragraph; end the body right after the offer/solution content (see HARD RULE 4).
12. Hook facts must be verified: attribute a product, feature, or partnership to the company only when it comes from the company's own sources (site, careers page, official announcements). If personalization/evidence marks a fact as unconfirmed, leave it out of the email entirely - never soften an unconfirmed fact into a hedge, just drop it.
13. Do NOT recap the recipient's own product back to them with a genre/category definition (e.g. "the open-economy sci-fi MMORPG") - they already know what they built. Naming the product and one recent, concrete event about it is fine; show you understand the company through what it means for THEIR hiring, not by restating what the product is.
14. Each paragraph must stand on its own. Never open a paragraph by referring back to the paragraph before the one directly above it (no "That's exactly the load..." style callbacks to content two paragraphs back) - a reader who skipped straight to that paragraph must still follow it.
15. Rhythm: one thought per sentence, minimum commas. Sentences should be short - split up anything longer than about 15 words. Do NOT use an em dash (—) anywhere in the email body - use a hyphen or split into two sentences instead; an em dash reads as AI-written text (rule carried over from the TG-outreach canon, B-110). Exception: verbatim blocks (finales) are inserted as-is and may contain any punctuation, including em dashes - this rule governs what YOU write, not the fixed closing paragraph appended after your body. BANNED rhetorical pattern: the inversion "this isn't about X - it's about Y" (and any "not X, but Y" pileup) - state directly what matters and why.
16. Turn claims into actions, not adjectives: "happy to share references" is checkable and reads as real; "we have good references" is a self-assessment nobody can verify. Prefer the concrete offer over the adjective.
17. A role named in the hook is valid ONLY if evidence supports at least one of: (a) it is listed on the company's own live careers page; (b) it is a posting no older than 30 days with a working Apply link; (c) it is a fresh post in an industry Telegram channel. An aggregator's cached copy of a role, and any role marked "no longer accepting applications", are BANNED regardless of how recently they were seen (tightens HARD RULE 8: being present in the evidence is necessary but not sufficient).
18. A vacancy named in the hook must sit inside the recipient's own zone of responsibility (their office, team, or geography) - do not reach for any open role at the company if it belongs to a different office or a function the recipient doesn't own.
19. Self-introduction lives ONLY in the closing paragraph appended in code - it always introduces the sender (co-founder, based in Cyprus). The body must contain NO self-introduction at all: no "I co-founded", no "where I live myself", no sender title or residence. One self-intro per email, and it is always the finale. (Exception: the verbatim no-vacancy opener "One co-founder to another" is a fixed block and stays as written.)
20. Helio Games proof point: use ONLY "around 20 hires since 2021 - a significant part of their current team." Never state or imply a percentage (not "70%", not "20%") for Helio Games or any other studio unless that exact number is present in the evidence for THIS recipient.
We are a recruiting partner - do NOT pitch software, outsourcing, or consulting.

GOLD-STANDARD EXAMPLE (approved by Alexey manually on 2026-07-20, replacing the earlier Scorewarrior example - the founder's reference for tone, structure, length and level of concreteness):
Subject: Staffing Supernova Shards at Sunday Games
Body:
Hi Serge,

You're taking Supernova Shards from prototypes and licensed IP into a full-scale live-service MMORPG. Now with the Immutable partnership on top. That means standing up engineering, economy/game design and live-ops in parallel. It's a heavy load and the roadmap runs on relentlessly.

We're AlexStaff - an IT-recruiting agency recruiting for game studios and publishers since 2006. We've grown a team from 30 to about 260 people - hundreds of hires along the way - while raising the seniority bar, not diluting it. On Cyprus we've made around 20 hires for Helio Games since 2021 - a significant part of their current team.

We can help! And not by mindlessly forwarding CV piles, but by bringing you candidates genuinely excited about what you're building. We start right after we agree the terms. Within 24-72 hours you meet the first candidates who fit the role and want to join Sunday Games specifically. Studios keep us for years, not one-off closings. And we're happy to share references.

Would you have 15 minutes for a call? Or, if you happen to be in Limassol or Paphos, a coffee, or Malindi on a Wednesday.

How to use the example: everything recipient-specific (subject, hook, the interpretation of what it means for hiring, the closing candidate line) must be rebuilt from THIS recipient's data - never reuse Sunday Games' facts and never copy those sentences for another recipient. The standing blocks (who-we-are, the CV-piles differentiator, the once-terms-agreed promise) may stay close to the example. The example's final paragraph (the meeting offer) is illustrative only - it is not written by you at all; the real one is appended in code separately (HARD RULE 11); do not reuse Sunday Games' version of it and do not write your own."""

SIGNATURE_HTML = (
    "<p>Alexey<br>"
    "AlexStaff Agency - recruiting for game studios and publishers since 2006<br>"
    '<a href="mailto:alex@alexstaff.agency">alex@alexstaff.agency</a> · '
    '<a href="https://alexstaff.agency">alexstaff.agency</a><br>'
    "Based in Cyprus</p>"
)

# US-run overlay (B-128 Phase 3, --profile us): appended to PROMPT_SETUP_TEXT verbatim through a
# blank line, never edited into the shared core. Source of truth: docs/us-email-canon-2026-07-20.md
# section 2 - copy byte-for-byte, do not paraphrase or "fix" hyphens/quotes.
US_PROFILE_OVERLAY = """=== US RUN OVERRIDES (this run only) ===
Everything above still applies, except where a rule below overrides it.

Sender on this run: Stepan, the agency's COO, based in the United States (Eastern time). The About-us description of the sender as Alexey, a co-founder based in Paphos and often in Limassol, does NOT apply here. There is no Cyprus geo-segment cascade on this run.

21. NEVER frame the offer around price, savings, rates, or cost comparison, and never use the words "offshore", "outsourcing", "low-cost", "cheap", or any "half the price" framing anywhere in the email. In this market a cheap agency reads as a low-quality signal. Commercial terms are a conversation, not a cold email.
22. NEVER introduce the sender in the body: no "I co-founded", no job title, no location, no "where I live myself". The body speaks as "we", the agency team. The sender's self-introduction lives inside the appended closing paragraph (B-158: added in code, not written by you) and appears exactly once per email. This overrides the "body OR finale" choice in HARD RULE 19: on this run it is always the finale.
23. The closing paragraph is appended to your body in code (B-158) - never write your own meeting offer or closing paragraph. Ignore the Cyprus geo-segment list in HARD RULE 11; it does not apply here.
24. Email goal on this run: a short intro 15-minute call. Never offer an in-person meeting, a coffee, or any Cyprus-based option.
25. Using the GOLD-STANDARD EXAMPLE above: its tone, structure, length and level of concreteness remain the reference. Three parts of it are specific to Alexey and must NEVER be reused here: (a) "an IT-recruiting agency I co-founded" - on this run write "an IT-recruiting agency" with no self-introduction; (b) "On Cyprus, where I live myself" - drop it, and state the Helio Games proof without any personal-residence framing; (c) the entire final paragraph offering a call, a coffee in Limassol or Paphos, or Malindi on a Wednesday - do not write a final paragraph at all, the real closing is appended in code.
26. Proof anchors on this run: use "Social Quantum: opened a new office from scratch and grew it from 2-3 to 120+ people" - never name the city or the country of that office. All other proof anchors are unchanged, including the Helio Games wording fixed by HARD RULE 20.
27. Lead the help paragraph with the retention point: we do not forward CV piles, we bring candidates genuinely excited about what the studio is building, so the person who accepts the offer chose THIS studio specifically and is still there a year later. The 24-72 hour promise (HARD RULE 1) stays, as the supporting point right after it."""

# Offer catalog: UTP segments A-D as matcher entries (name/pains/bullets feed the
# email `solution` slot verbatim through program_matcher.solution_text).
OFFERS: list[dict] = [
    {
        "name": "Fast single-role search",
        "description": (
            "Contingency search for one key role at a small studio (10-30 people): the founder "
            "or lead briefs us and, once commercial terms are agreed, the search starts within "
            "hours and the first candidate lands in 24-72 hours. We pitch the studio's product "
            "and culture to candidates ourselves, so they arrive at the tech interview motivated, not cold."
        ),
        "target_pains": [
            "one wrong hire can stall the whole product",
            "no in-house recruiting, founder does the hiring",
            "a key role has been open for months",
            "candidates ghost or arrive unmotivated",
        ],
        "audience": "founders / leads of 10-30-person studios",
        "format": "contingency search, first candidate in 24-72 hours",
        "bullets": [
            "once terms are agreed, sourcing starts within hours",
            "first candidate in 24-72 hours after terms are agreed",
            "we sell your product and culture to candidates - they come in motivated",
            "Unity/C#, Unreal, art, game design, backend (Node/TS, .NET)",
        ],
    },
    {
        "name": "Sustained parallel hiring for content & live-ops teams",
        "description": (
            "Sustained-pace hiring for content production: art, animation, game design, QA. "
            "When the content pipeline is the revenue engine, an unfilled seat is lost income - "
            "we keep the hiring pace up without dropping the quality bar."
        ),
        "target_pains": [
            "content pipeline stalls because seats are empty",
            "hiring speed vs quality tradeoff",
            "scaling art / animation / QA teams",
            "live-ops cadence at risk",
        ],
        "audience": "producers / studio heads of content-driven and live-ops studios",
        "format": "ongoing pipeline hiring at production tempo",
        "bullets": [
            "specialised in continuous, parallel hiring for content production",
            "art, animation, game design, QA",
            "team grows with the product without losing quality",
        ],
    },
    {
        "name": "Cyprus hiring and relocation to Cyprus",
        "description": (
            "Hiring for Cyprus-based studios: we know the local candidate market from inside "
            "(a significant part of Helio Games (Limassol) hired by us since 2021 - around 20 "
            "roles) and we know how to sell relocation or remote-to-Cyprus setups to candidates "
            "worldwide."
        ),
        "target_pains": [
            "thin local candidate market in Cyprus",
            "selling relocation to candidates",
            "mixing local, remote and relocated hires",
        ],
        "audience": "CEOs / HRDs of Cyprus-based studios",
        "format": "local hiring + global sourcing with relocation support",
        "bullets": [
            "a significant part of Helio Games (Limassol) hired by us since 2021 - around 20 roles",
            "global sourcing: remote and relocation, many countries and languages",
            "relocated up to 35 people per month under hard logistics",
            "in-person kickoff possible - we are based in Cyprus",
        ],
    },
    {
        "name": "Fast team scale-up for production pushes",
        "description": (
            "Team scale-up for a production push: our reference case is Broken Sun MMORPG "
            "(OIJO GAMES / REDNECK STUDIO) - 30 -> 260 people, hundreds of hires along the way, "
            "through open beta, while raising the seniority bar instead of diluting it."
        ),
        "target_pains": [
            "team must grow several-fold for production",
            "hundreds of hires class of problem",
            "keeping the seniority bar while scaling fast",
            "new office / new location staffing",
        ],
        "audience": "COOs / production directors of scaling studios",
        "format": "dedicated scale-up hiring engagement",
        "bullets": [
            "Broken Sun MMORPG: 30 -> 260 people, hundreds of hires along the way, through open beta",
            "Social Quantum office opened from scratch: 2-3 -> 120+",
            "scale and raise expertise at the same time",
        ],
    },
]


# Canon values synced onto RunSetup — the text blocks above (PROMPT_SETUP_TEXT etc.) plus
# the scalar/ICP fields that travel with them.
CANON_ICP_CRITERIA_JSON = {
    "industry_keywords": [
        "game studio", "game development", "gamedev", "mobile games",
        "video games", "game publisher",
    ],
    "regions": ["Cyprus"],
}

# Text fields diffed with difflib.unified_diff in --dry-run.
CANON_TEXT_FIELDS = {
    "prompt_setup_text": PROMPT_SETUP_TEXT,
    "critic_canon_text": DEFAULT_CRITIC_CANON,
    "sender_signature_html": SIGNATURE_HTML,
}

# Scalar fields printed as before/after in --dry-run.
CANON_SCALAR_FIELDS = {
    "language": "English",
    "osint_discovery_mode": "api_only",
    "icp_min_employees": 10,
    "icp_max_employees": 500,
    "icp_criteria_json": CANON_ICP_CRITERIA_JSON,
}


def _canon_fields_for_profile(profile: str = "cyprus") -> tuple[dict, dict]:
    """Build (text_fields, scalar_fields) for --profile. "cyprus" (the default) returns the
    module canon dicts unchanged, byte-for-byte - existing behavior. "us" (B-128 Phase 3) overlays
    the sender and ICP for Stepan's run without touching the shared core (PROMPT_SETUP_TEXT,
    DEFAULT_CRITIC_CANON, HARD RULES 1-20, the Sunday Games example, finales): see
    docs/us-email-canon-2026-07-20.md. Called from both the --dry-run diff path and the write
    path so they never see different values for the same profile."""
    if profile == "cyprus":
        return CANON_TEXT_FIELDS, CANON_SCALAR_FIELDS

    if profile == "anastasia":
        # B-533, wave 2: same shared core (prompt/critic/ICP) as cyprus, only the signature
        # differs. The live wave-1 run (id=5) is NOT synced through this profile — its canon was
        # hand-set in prod and only its signature is touched, via --fields sender_signature_html.
        text_fields = {
            **CANON_TEXT_FIELDS,
            "sender_signature_html": anastasia_persona_kwargs()["signature_html"],
        }
        return text_fields, CANON_SCALAR_FIELDS

    text_fields = {
        **CANON_TEXT_FIELDS,
        "prompt_setup_text": PROMPT_SETUP_TEXT + "\n\n" + US_PROFILE_OVERLAY,
        "sender_signature_html": stepan_persona_kwargs()["signature_html"],
    }
    scalar_fields = {
        **CANON_SCALAR_FIELDS,
        "icp_min_employees": 30,
        "icp_max_employees": 200,
        "icp_criteria_json": {**CANON_ICP_CRITERIA_JSON, "regions": ["United States"]},
    }
    return text_fields, scalar_fields


def _seed_persona_alexey(db) -> Persona:
    """Upsert the "alexey" Persona row (idempotent by slug) — B-071 decision 8/9: the byte-identical
    migration of the old FINALE_TEMPLATES/SEGMENT_NAMES (email_finale_templates.py) and Cyprus
    keyword tables (geo_segment_service.py) out of code and into persona data. Canonical data lives
    in app.services.persona_service (not here — scripts/ is not baked into the prod image, see
    AI-Biz-OS/CLAUDE.md "Грабли"); this function only performs the upsert."""
    persona = db.query(Persona).filter(Persona.slug == ALEXEY_SLUG).first()
    if not persona:
        persona = Persona(slug=ALEXEY_SLUG)
        db.add(persona)
    for field, value in alexey_persona_kwargs().items():
        if field == "slug":
            continue
        setattr(persona, field, value)
    db.flush()
    return persona


STEPAN_MAILBOX_EMAIL = "stepan@alexstaff.agency"

# Warm-up not started yet: effective_daily_cap()/warmup_daily_cap() (sending_gates.py) fall back to
# the FULL daily_cap (25) when started_on is missing/unparseable, not to the ramp's conservative
# `start` (5) — confirmed by reading that code (see B-071 final-stage report). A far-future sentinel
# date keeps weeks_elapsed clamped to 0, so the effective cap stays at start(5) until Алексей flips
# started_on to the real kickoff date to begin the ramp.
STEPAN_WARMUP_NOT_STARTED_SENTINEL = "2099-01-01"


def _seed_persona_stepan(db) -> Persona:
    """Upsert the "stepan" Persona row (idempotent by slug) — B-071 final stage: US COO persona,
    verbatim finale/signature approved by Алексей 18.07 (see multitenancy-personas-handoff-
    2026-07-18.md decision 15а). Canonical data lives in app.services.persona_service (not here —
    scripts/ is not baked into the prod image, see AI-Biz-OS/CLAUDE.md "Грабли"); this function only
    performs the upsert."""
    persona = db.query(Persona).filter(Persona.slug == STEPAN_SLUG).first()
    if not persona:
        persona = Persona(slug=STEPAN_SLUG)
        db.add(persona)
    for field, value in stepan_persona_kwargs().items():
        if field == "slug":
            continue
        setattr(persona, field, value)
    db.flush()
    return persona


def _seed_persona_anastasia(db) -> Persona:
    """Upsert the "anastasia" Persona row (idempotent by slug) — B-533: account manager persona,
    not present in code before this (the live prod row was hand-created). Canonical data lives in
    app.services.persona_service (not here — scripts/ is not baked into the prod image, see
    AI-Biz-OS/CLAUDE.md "Грабли"); this function only performs the upsert."""
    persona = db.query(Persona).filter(Persona.slug == ANASTASIA_SLUG).first()
    if not persona:
        persona = Persona(slug=ANASTASIA_SLUG)
        db.add(persona)
    for field, value in anastasia_persona_kwargs().items():
        if field == "slug":
            continue
        setattr(persona, field, value)
    db.flush()
    return persona


def _seed_sending_policy_stepan(db) -> SendingPolicy:
    """Upsert the sending_policies row for stepan@alexstaff.agency (idempotent by mailbox_email) —
    B-071 final stage, decision 13: mirrors Alexey's live policy, with a wider window/timezone for
    the US market and a warm-up ramp that has NOT started yet (see STEPAN_WARMUP_NOT_STARTED_SENTINEL
    above) — Алексей flips started_on to kick off the ramp explicitly."""
    policy = db.query(SendingPolicy).filter(SendingPolicy.mailbox_email == STEPAN_MAILBOX_EMAIL).first()
    if not policy:
        policy = SendingPolicy(mailbox_email=STEPAN_MAILBOX_EMAIL)
        db.add(policy)
    policy.daily_cap = 25
    policy.hourly_cap = 3
    policy.min_gap_minutes = 20
    policy.gap_jitter_minutes = 45
    policy.send_days_first_touch = "tue,wed,thu"
    policy.send_days_follow_up = "mon,tue,wed,thu"
    policy.window_start = "09:00"
    policy.window_end = "15:00"
    policy.timezone = "America/New_York"
    policy.warmup_ramp_json = {
        "start": 5,
        "step_per_week": 5,
        "cap": 25,
        "started_on": STEPAN_WARMUP_NOT_STARTED_SENTINEL,
    }
    policy.follow_up_after_business_days = 4
    policy.max_touches = 2
    policy.enabled = True
    db.flush()
    return policy


def _seed_offers(db) -> None:
    """Upsert the OFFERS catalog (idempotent by name). Global — not scoped to any project/run."""
    for offer in OFFERS:
        row = db.query(TrainingProgram).filter(TrainingProgram.name == offer["name"]).first()
        if not row:
            row = TrainingProgram(name=offer["name"], status="active")
            db.add(row)
        row.description = offer["description"]
        row.target_pains = offer["target_pains"]
        row.audience = offer["audience"]
        row.format = offer["format"]
        row.bullets = offer["bullets"]
        row.status = "active"
    db.flush()
    print(f"Seeded {len(OFFERS)} offers.")


def _print_text_diff(field: str, old: str | None, new: str) -> None:
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = (new or "").splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(old_lines, new_lines, fromfile=f"db:{field}", tofile=f"canon:{field}", lineterm="")
    )
    if diff:
        print(f"--- {field} DIFFERS ---")
        for line in diff:
            print(line)
    else:
        print(f"{field}: identical")


def _print_scalar_diff(field: str, old, new) -> None:
    if old != new:
        print(f"{field}: DB={old!r} -> canon={new!r}")
    else:
        print(f"{field}: identical ({old!r})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Sync the AlexStaff canon (prompt/critic/signature/ICP) onto a run's RunSetup."
    )
    ap.add_argument("--run-id", type=int, required=True, help="Target run id (no default).")
    ap.add_argument(
        "--profile",
        choices=["cyprus", "us", "anastasia"],
        default="cyprus",
        help=(
            "Canon profile to sync (default: cyprus - existing behavior, byte-for-byte). "
            "'us' overlays sender (Stepan) and ICP for the US run without touching the shared "
            "core (B-128 Phase 3, see docs/us-email-canon-2026-07-20.md). 'anastasia' (B-533) "
            "overlays only sender_signature_html for future wave-2 runs."
        ),
    )
    ap.add_argument(
        "--fields",
        type=str,
        default=None,
        help=(
            "Comma-separated RunSetup field names to restrict this sync to, e.g. "
            "'sender_signature_html'. When set, both --dry-run's diff and the write only touch "
            "these fields - everything else on the run's canon is left untouched. Off by default "
            "(syncs the full canon). B-533: use this to update a live run's signature without "
            "rewriting its per-run prompt_setup_text/critic_canon_text/ICP."
        ),
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Print unified diff of DB vs canon; write nothing."
    )
    ap.add_argument(
        "--seed-offers",
        action="store_true",
        help="Also upsert the OFFERS catalog (TrainingProgram rows). Off by default.",
    )
    ap.add_argument(
        "--seed-persona-alexey",
        action="store_true",
        help="Also upsert the 'alexey' Persona row (finales/geo-map/signature, B-071). Off by default.",
    )
    ap.add_argument(
        "--seed-persona-stepan",
        action="store_true",
        help="Also upsert the 'stepan' Persona row (US COO, B-071 final stage). Off by default.",
    )
    ap.add_argument(
        "--seed-persona-anastasia",
        action="store_true",
        help="Also upsert the 'anastasia' Persona row (account manager, B-533). Off by default.",
    )
    ap.add_argument(
        "--seed-sending-policy-stepan",
        action="store_true",
        help=(
            "Also upsert the sending_policies row for stepan@alexstaff.agency (B-071 final stage). "
            "Off by default."
        ),
    )
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if not run:
            print(f"Run id={args.run_id} not found.", file=sys.stderr)
            sys.exit(1)

        setup = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
        text_fields, scalar_fields = _canon_fields_for_profile(args.profile)

        allowed_fields: set[str] | None = None
        if args.fields:
            allowed_fields = {f.strip() for f in args.fields.split(",") if f.strip()}
            text_fields = {k: v for k, v in text_fields.items() if k in allowed_fields}
            scalar_fields = {k: v for k, v in scalar_fields.items() if k in allowed_fields}

        if args.dry_run:
            print(
                f"DRY RUN: run_id={run.id} ({run.name!r}); profile={args.profile!r}; "
                f"fields={sorted(allowed_fields) if allowed_fields else 'ALL'}; "
                f"RunSetup {'exists' if setup else 'MISSING (would be created)'}"
            )
            for field, canon_value in text_fields.items():
                old = getattr(setup, field, None) if setup else None
                _print_text_diff(field, old, canon_value)
            for field, canon_value in scalar_fields.items():
                old = getattr(setup, field, None) if setup else None
                _print_scalar_diff(field, old, canon_value)
            if args.seed_persona_alexey:
                existing = db.query(Persona).filter(Persona.slug == ALEXEY_SLUG).first()
                print(
                    f"persona '{ALEXEY_SLUG}': "
                    + ("exists, would be updated" if existing else "MISSING (would be created)")
                )
            if args.seed_persona_stepan:
                existing = db.query(Persona).filter(Persona.slug == STEPAN_SLUG).first()
                print(
                    f"persona '{STEPAN_SLUG}': "
                    + ("exists, would be updated" if existing else "MISSING (would be created)")
                )
            if args.seed_persona_anastasia:
                existing = db.query(Persona).filter(Persona.slug == ANASTASIA_SLUG).first()
                print(
                    f"persona '{ANASTASIA_SLUG}': "
                    + ("exists, would be updated" if existing else "MISSING (would be created)")
                )
            if args.seed_sending_policy_stepan:
                existing = (
                    db.query(SendingPolicy)
                    .filter(SendingPolicy.mailbox_email == STEPAN_MAILBOX_EMAIL)
                    .first()
                )
                print(
                    f"sending_policy '{STEPAN_MAILBOX_EMAIL}': "
                    + ("exists, would be updated" if existing else "MISSING (would be created)")
                )
            print("Dry run; no changes.")
            return

        if args.seed_offers:
            _seed_offers(db)

        if args.seed_persona_alexey:
            _seed_persona_alexey(db)
            db.commit()
            print(f"Seeded persona '{ALEXEY_SLUG}'.")

        if args.seed_persona_stepan:
            _seed_persona_stepan(db)
            db.commit()
            print(f"Seeded persona '{STEPAN_SLUG}'.")

        if args.seed_persona_anastasia:
            _seed_persona_anastasia(db)
            db.commit()
            print(f"Seeded persona '{ANASTASIA_SLUG}'.")

        if args.seed_sending_policy_stepan:
            _seed_sending_policy_stepan(db)
            db.commit()
            print(f"Seeded sending policy for '{STEPAN_MAILBOX_EMAIL}'.")

        if not setup:
            setup = RunSetup(run_id=run.id)
            db.add(setup)
        for field, canon_value in text_fields.items():
            setattr(setup, field, canon_value)
        for field, canon_value in scalar_fields.items():
            setattr(setup, field, canon_value)

        db.commit()
        print(f"Synced RunSetup for run_id={run.id} ({run.name!r}).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
