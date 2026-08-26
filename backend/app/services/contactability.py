"""The 'is this address safe to email?' predicate — permanent, non-negotiable checks shared by
the queue worker (sending_gates.evaluate_gates), the manual send chokepoint
(email_sender.validate_outbound_draft_sendable), and the follow-up cadence
(followup_cadence_service). One rule everywhere, so a suppressed/dead contact can't leak out
through whichever path forgot to check it.

Deliberately narrow: only the cross-run suppression list and a *confirmed* dead mailbox/address
block. Catch-all and unknown verification verdicts do NOT block — a provider that can't confirm
an individual mailbox on an otherwise-live domain is not a reason to withhold a real lead (decision
2026-07-08, see docs/AI-Biz-OS-backlog.md). Temporal gates (caps, send window, one-dialog-per-company)
are a separate, worker-only concern in sending_gates.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.suppression_repo import is_suppressed


@dataclass
class ContactabilityResult:
    ok: bool
    reason: str | None = None


def is_contactable(db: Session, to_email: str | None, contact=None) -> ContactabilityResult:
    if is_suppressed(db, to_email):
        return ContactabilityResult(False, "recipient is on the suppression list")
    if contact is not None:
        if (getattr(contact, "email_health", "") or "") == "dead_mailbox":
            return ContactabilityResult(False, "contact email_health = dead_mailbox")
        if (getattr(contact, "email_verification_status", "") or "") == "dead":
            return ContactabilityResult(False, "address verification = dead")
    return ContactabilityResult(True)
