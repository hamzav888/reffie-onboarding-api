import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class UpcomingDealOut(BaseModel):
    """
    Serialised representation of an upcoming-pipeline deal.

    :param id: Primary key.
    :param hubspot_deal_id: HubSpot deal object ID.
    :param company_name: Company name from the deal.
    :param deal_stage: HubSpot internal stage ID.
    :param tech_stack: Tech stack properties from the associated company.
    :param sales_rep_name: Full name of the assigned sales rep (None if unset).
    :param arr: Annual recurring revenue (None if not set on the deal).
    :param close_date: Projected close date (None if not set).
    :param last_synced_at: When this row was last fetched from HubSpot.
    :param created_at: Row creation timestamp.
    :param updated_at: Row last-update timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hubspot_deal_id: str
    company_name: str
    deal_stage: str
    tech_stack: dict[str, Any]
    sales_rep_name: str | None
    arr: Decimal | None
    close_date: date | None
    last_synced_at: datetime
    created_at: datetime
    updated_at: datetime
