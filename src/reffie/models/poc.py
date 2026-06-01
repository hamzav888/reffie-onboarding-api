from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reffie.db.base import Base

if TYPE_CHECKING:
    from reffie.models.account import Account


class Poc(Base):
    """
    Point of contact for a customer account.

    Maps to the ``pocs`` table. Each :class:`~reffie.models.account.Account`
    may have one or more points of contact involved in the onboarding process.

    :cvar id: Primary key (UUID v4).
    :cvar account_id: Foreign key to the owning :class:`~reffie.models.account.Account`.
    :cvar name: Full name of the contact.
    :cvar email: Email address of the contact.
    :cvar phone: Optional phone number.
    :cvar role: Optional job title or role at the company.
    :cvar account: Back-reference to the parent account.
    """

    __tablename__ = "pocs"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    email: Mapped[str] = mapped_column(sa.String, nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    role: Mapped[str | None] = mapped_column(sa.String, nullable=True)

    account: Mapped[Account] = relationship(back_populates="pocs")
