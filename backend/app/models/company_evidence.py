"""Evidence Store (Phase 2): structured, queryable copy of the company dossier.

The Tavily dossier (`osint_dossier` in run_company extra KV) is a JSON string with
`evidence:[{fact, source_url, confidence_score}]` + `hypotheses[]` + `triggers[]`.
These rows are synced from it on enrich (and via backfill), so facts become SQL-queryable
(coverage metrics, ICP gates later) and the UI can render them with sources. The KV dossier
stays the raw source of truth; this table is a derived index — safe to rebuild any time.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CompanyEvidence(Base):
    __tablename__ = "company_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    run_company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("run_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized for per-run queries (coverage, gates) without a join.
    run_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # "evidence" | "hypothesis" | "trigger" — hypotheses/triggers carry no source/confidence.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="evidence", index=True)

    fact: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
