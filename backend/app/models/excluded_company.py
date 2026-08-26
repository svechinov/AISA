from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Why a company is out of the segment, forever, across runs.
EXCLUDE_REASON_COMPETITOR = "competitor"        # a recruiting agency — a peer, not a buyer
EXCLUDE_REASON_JOB_BOARD = "job_board"          # job board / aggregator / referral platform
EXCLUDE_REASON_MEDIA = "media"                  # gaming media, events, education projects
EXCLUDE_REASON_NOT_A_BUYER = "not_a_buyer"      # cannot buy (PSL-locked subsidiary, gov, individual)
EXCLUDE_REASON_OFF_SEGMENT = "off_segment"      # off-ICP for reasons not covered above
EXCLUDE_REASON_MANUAL = "manual"


class ExcludedCompany(Base):
    """Cross-run do-not-collect registry for COMPANIES (B-264).

    ``suppression_list`` is the same idea for people: it keys on an email address and cannot hold a
    company. A "not our segment" verdict used to live only inside one run
    (``run_companies.ai_fit_status='incorrect'``), so the next Apollo sweep with the same filters
    collected the same competitor / job board / Microsoft subsidiary again and paid for research on
    it a second time (US wave 1: 10 of 24 companies).

    Matching is by ``domain`` first (stable) and by ``name_key`` second (a lowercased,
    punctuation-free company name) for rows collected without a usable website.
    """

    __tablename__ = "excluded_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # At least one of domain / name_key is always set (enforced by the repository, not the schema —
    # a company with neither has no identity to match on).
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False, default=EXCLUDE_REASON_MANUAL)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
