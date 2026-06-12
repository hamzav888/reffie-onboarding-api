from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reffie.db.base import Base


class UpcomingDeal(Base):
    """
    Cache of HubSpot deals currently in an upcoming pipeline stage.

    Populated via webhook events and the ``POST /upcoming-deals/refresh``
    endpoint. Rows are removed when a deal moves out of the watched stages.

    :cvar id: Primary key (UUID v4).
    :cvar hubspot_deal_id: HubSpot deal object ID (unique — one row per deal).
    :cvar company_name: Associated company name from the deal.
    :cvar deal_stage: HubSpot internal stage ID at time of last sync.
    :cvar tech_stack: Tech stack properties from the associated company.
    :cvar sales_rep_name: Full name of the HubSpot deal owner.
    :cvar arr: Deal amount (annual recurring revenue).
    :cvar close_date: Projected close date from the deal.
    :cvar last_synced_at: When this row was last fetched from HubSpot.
    :cvar created_at: Timestamp of row creation (UTC).
    :cvar updated_at: Timestamp of last row update (UTC).
    """

    __tablename__ = "upcoming_deals"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hubspot_deal_id: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    company_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    deal_stage: Mapped[str] = mapped_column(sa.String, nullable=False)
    tech_stack: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    sales_rep_name: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    arr: Mapped[Decimal | None] = mapped_column(sa.Numeric(precision=12, scale=2), nullable=True)
    close_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
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
