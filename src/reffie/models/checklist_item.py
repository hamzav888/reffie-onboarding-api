from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reffie.db.base import Base

if TYPE_CHECKING:
    from reffie.models.account import Account


class ChecklistItem(Base):
    """
    Onboarding checklist state entry for an account.

    Maps to the ``checklist_state`` table. Each row records whether a
    specific step in the onboarding workflow has been completed for a given
    :class:`~reffie.models.account.Account`.

    The combination of ``account_id`` and ``step_id`` is unique — one row
    per step per account.

    :cvar id: Primary key (UUID v4).
    :cvar account_id: Foreign key to the owning :class:`~reffie.models.account.Account`.
    :cvar step_id: Deterministic step identifier (e.g. ``"pre-kick-off__confirm"``).
    :cvar done: Whether the step has been marked complete.
    :cvar note: Optional free-text note left on the step.
    :cvar first_touched_at: Timestamp of first interaction with this step (UTC).
    :cvar completed_at: Timestamp when the step was marked done (UTC).
    :cvar account: Back-reference to the parent account.
    """

    __tablename__ = "checklist_state"
    __table_args__ = (
        sa.UniqueConstraint("account_id", "step_id", name="uq_checklist_account_step"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(sa.String, nullable=False)
    done: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    note: Mapped[str] = mapped_column(sa.String, server_default=sa.text("''"), nullable=False)
    first_touched_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    account: Mapped[Account] = relationship(back_populates="checklist_items")
