from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from reffie.db.base import Base

if TYPE_CHECKING:
    from reffie.models.checklist_item import ChecklistItem
    from reffie.models.poc import Poc


class Account(Base):
    """
    Customer account in the Reffie onboarding platform.

    Maps to the ``accounts`` table. An account is the top-level entity
    grouping points of contact and onboarding checklist state.

    :cvar id: Primary key (UUID v4).
    :cvar hubspot_deal_id: Linked HubSpot deal, if synced.
    :cvar hubspot_company_id: Linked HubSpot company, if synced.
    :cvar company_name: Display name of the company.
    :cvar location: Geographic location of the property.
    :cvar property_type: Category of property (e.g. multifamily, commercial).
    :cvar arr: Annual recurring revenue in USD.
    :cvar contract_length: Duration of the contract (e.g. "12 months").
    :cvar success_metrics: Free-text description of agreed success criteria.
    :cvar cs_rep: Name of the assigned customer success representative.
    :cvar onboarding_stage: Current stage slug in the onboarding workflow.
    :cvar kickoff_call_date: Date the kickoff call was or will be held.
    :cvar tech_stack: JSON object describing the customer's current technology stack.
    :cvar skipped_stages: Stage slugs intentionally skipped for this account.
    :cvar created_at: Timestamp of record creation (UTC).
    :cvar updated_at: Timestamp of last update (UTC).
    :cvar pocs: Points of contact belonging to this account.
    :cvar checklist_items: Checklist state entries for this account.
    """

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hubspot_deal_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    hubspot_company_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    company_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    location: Mapped[str] = mapped_column(sa.String, nullable=False)
    property_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    arr: Mapped[Decimal | None] = mapped_column(sa.Numeric(precision=12, scale=2), nullable=True)
    contract_length: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    success_metrics: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    cs_rep: Mapped[str] = mapped_column(sa.String, nullable=False)
    onboarding_stage: Mapped[str] = mapped_column(sa.String, nullable=False)
    kickoff_call_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    tech_stack: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    skipped_stages: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String),
        server_default=sa.text("'{}'::varchar[]"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.func.now(),
        nullable=False,
    )

    pocs: Mapped[list[Poc]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
    checklist_items: Mapped[list[ChecklistItem]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )
