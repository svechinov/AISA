"""Canon of judgement (B-077 etap 2): the LLM critic's taste rubric as an editable artifact.

Symmetry with the letters canon (`PROMPT_SETUP_TEXT` seed <-> `RunSetup.prompt_setup_text` live
value): DEFAULT_CRITIC_CANON is the code-default seed, `RunSetup.critic_canon_text` is the per-run
live value that can be edited without a deploy. This canon judges VACANCY emails only — no_vacancy
emails skip the LLM taste rubric entirely (mechanical §2.3 conformance instead, see
email_validation_service._check_no_vacancy_conformance).

Static text only — no interpolation. The Subject/Body/evidence data block and the
"Return strict JSON" schema are a fixed skeleton assembled around this canon in
email_validation_service.validate_outbound_email, not part of the canon itself.
"""

from __future__ import annotations

DEFAULT_CRITIC_CANON = """You are an elite B2B SDR Critic. Score this cold email on a strict rubric (each 1-5).

Criteria (1=poor, 5=excellent):
1. relevance_score: fit to THIS company based on the evidence (1=generic, 5=highly tailored).
2. specificity_score: uses concrete facts/names from the evidence, not fluff (1=no facts, 5=hard evidence used).
3. non_spam_score: human 1-to-1 tone, no marketing jargon (1=spammy blast, 5=natural).
4. cta_score: one clear closing ask; multiple meeting-format options inside a single closing sentence are acceptable campaign style, do not penalize (1=weak/none/vague, 5=crisp single closing ask).
5. clarity_score: clear, concise, well-structured, appropriate length (1=rambling, 5=tight).

Also judge:
hook_grounded (true/false): does the OPENING reference a concrete fact/trigger from the evidence
(prefer person_osint when present, else company evidence or a confirmed vacancy signal)? false if the opener is generic.

Scoring note: the sender's track-record proof points (client cases with numbers) are mandated by the
campaign — do not penalize their presence. Penalize only if they CROWD OUT recipient-specific content."""
