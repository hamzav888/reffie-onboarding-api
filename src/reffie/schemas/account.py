import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reffie.schemas.checklist import ChecklistItemOut
from reffie.schemas.poc import PocOut


class AccountCreate(BaseModel):
    """Input schema for creating a new account."""

    hubspot_deal_id: str | None = None
    hubspot_company_id: str | None = None
    company_name: str
    location: str
    property_type: str
    arr: Decimal | None = None
    contract_length: str | None = None
    success_metrics: str | None = None
    cs_rep: str
    onboarding_stage: str
    kickoff_call_date: date | None = None
    skipped_stages: list[str] = []
    tech_stack: dict[str, Any] = Field(default_factory=dict)


class AccountUpdate(BaseModel):
    """Partial update payload — only provided fields are applied."""

    hubspot_deal_id: str | None = None
    hubspot_company_id: str | None = None
    company_name: str | None = None
    location: str | None = None
    property_type: str | None = None
    arr: Decimal | None = None
    contract_length: str | None = None
    success_metrics: str | None = None
    cs_rep: str | None = None
    onboarding_stage: str | None = None
    kickoff_call_date: date | None = None
    skipped_stages: list[str] | None = None
    tech_stack: dict[str, Any] | None = None


class AccountSummary(BaseModel):
    """Lightweight account representation used in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hubspot_company_id: str | None = None
    company_name: str
    cs_rep: str
    onboarding_stage: str
    skipped_stages: list[str]
    tech_stack: dict[str, Any] = Field(default_factory=dict)


class AccountDetail(BaseModel):
    """Full account representation including related POCs and checklist state."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hubspot_deal_id: str | None
    hubspot_company_id: str | None
    company_name: str
    location: str
    property_type: str
    arr: Decimal | None
    contract_length: str | None
    success_metrics: str | None
    cs_rep: str
    onboarding_stage: str
    kickoff_call_date: date | None
    skipped_stages: list[str]
    tech_stack: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    pocs: list[PocOut]
    checklist_items: list[ChecklistItemOut]
