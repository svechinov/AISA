"""Per-run, per-outbound-draft: whether the Events tab chain is collapsed in Human UI."""

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RunEventChainCollapse(Base):
    __tablename__ = "run_event_chain_collapse"
    __table_args__ = (UniqueConstraint("run_id", "email_draft_id", name="uq_run_event_chain_run_draft"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    email_draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collapsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
