import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import reffie.hubspot.client as hubspot_client
import reffie.hubspot.tech_stack as tech_stack_module
from reffie.config import Settings
from reffie.constants import PLATFORM_STAGES
from reffie.models import Account, Poc

logger = logging.getLogger(__name__)

_DEAL_PROPERTIES: list[str] = [
    "dealname",
    "hs_object_id",
    "onboarding_cs_rep",
    "kickoff_call_date",
    "amount",
    "contract_length",
    "success_metrics",
    "property_type",
    "city",
    "state",
]

_CONTACT_PROPERTIES: list[str] = [
    "firstname",
    "lastname",
    "email",
    "phone",
    "jobtitle",
]

# A line item whose name contains this token forces contract_length, overriding
# whatever the deal-level contract_length field says.
_MONEY_BACK_NAME_TOKEN = "money-back"  # noqa: S105 — product-name substring, not a secret
_MONEY_BACK_CONTRACT_LENGTH = "6 months"


def has_money_back_guarantee(line_items: list[dict[str, Any]]) -> bool:
    """Return ``True`` if any line item is the money-back-guarantee product.

    :param line_items: Normalised line-item dicts (each with a ``name`` key).
    :returns: ``True`` if any line item name contains the money-back token.
    """
    return any(_MONEY_BACK_NAME_TOKEN in str(i.get("name", "")).lower() for i in line_items)


def _str(props: dict[str, Any], key: str) -> str:
    """Return a stripped string value from a HubSpot properties dict, or ``""``."""
    val = props.get(key)
    return str(val).strip() if val is not None else ""


def _str_or_none(props: dict[str, Any], key: str) -> str | None:
    """Return a non-empty stripped string, or ``None`` if absent or blank."""
    val = _str(props, key)
    return val if val != "" else None


def _parse_decimal(props: dict[str, Any], key: str) -> Decimal | None:
    """
    Parse a HubSpot numeric property as a :class:`~decimal.Decimal`.

    :param props: HubSpot ``properties`` dict.
    :param key: Property name to parse.
    :returns: Parsed value, or ``None`` if absent, blank, or non-numeric.
    """
    raw = _str(props, key)
    if raw == "":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _parse_date(props: dict[str, Any], key: str) -> date | None:
    """
    Parse a HubSpot DATE property (``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM:SSZ``).

    :param props: HubSpot ``properties`` dict.
    :param key: Property name to parse.
    :returns: Parsed date, or ``None`` if absent, blank, or unparseable.
    """
    raw = _str(props, key)
    if raw == "":
        return None
    # Slice to 10 chars to handle both plain dates and ISO datetimes.
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _apply_deal_fields_to_account(account: Account, props: dict[str, Any], deal_id: str) -> None:
    """
    Write mapped HubSpot deal properties onto an Account instance in place.

    Handles both the initial-create and re-sync-update paths to avoid
    duplicating the mapping logic.

    :param account: The Account instance to mutate.
    :param props: The ``properties`` dict from a HubSpot deal response.
    :param deal_id: Fallback value used for ``hubspot_deal_id`` if ``hs_object_id``
        is absent from the response.
    """
    city = _str(props, "city")
    state = _str(props, "state")
    account.hubspot_deal_id = _str(props, "hs_object_id") or deal_id
    account.company_name = _str(props, "dealname") or "Unknown"
    account.location = ", ".join(filter(None, [city, state])) or "Unknown"
    # property_type is a HubSpot multi-checkbox: its API value is a
    # semicolon-separated string (e.g. "SFR;Condo"). Normalise to a
    # comma-space-joined string; empty stays empty.
    raw_property_type = _str(props, "property_type")
    if raw_property_type:
        parts = [p.strip() for p in raw_property_type.split(";") if p.strip()]
        account.property_type = ", ".join(parts)
    else:
        account.property_type = ""
    account.cs_rep = _str(props, "onboarding_cs_rep") or "Unassigned"
    # onboarding_stage is intentionally NOT set here — the platform owns it.
    # New accounts receive PLATFORM_STAGES[0] at creation time; existing accounts
    # keep whatever stage they are at.
    account.arr = _parse_decimal(props, "amount")
    account.contract_length = _str_or_none(props, "contract_length")
    account.success_metrics = _str_or_none(props, "success_metrics")
    # kickoff_call_date is read-only from HubSpot — never written back.
    account.kickoff_call_date = _parse_date(props, "kickoff_call_date")


def _map_contact_to_poc(contact_data: dict[str, Any], account_id: uuid.UUID) -> Poc:
    """
    Map a raw HubSpot contact response to a transient :class:`~reffie.models.poc.Poc`.

    :param contact_data: Full HubSpot contact object (``id`` + ``properties`` keys).
    :param account_id: UUID of the owning account.
    :returns: Transient Poc instance ready to be added to the session.
    """
    props: dict[str, Any] = contact_data.get("properties", {})
    first = _str(props, "firstname")
    last = _str(props, "lastname")
    name = f"{first} {last}".strip() or "Unknown"
    return Poc(
        id=uuid.uuid4(),
        account_id=account_id,
        name=name,
        email=_str(props, "email"),
        phone=_str_or_none(props, "phone"),
        role=_str_or_none(props, "jobtitle"),
    )


async def pull_deal(deal_id: str, db_session: AsyncSession, settings: Settings) -> Account:
    """
    Fetch a HubSpot deal, its contacts, and its associated company, then upsert
    them into the local database.

    Behaviour:
    - If an account with ``hubspot_deal_id == deal_id`` already exists, its fields
      are updated in place.
    - If no such account exists, a new one is created.
    - All existing POCs for the account are replaced with the current HubSpot contacts.
    - ``kickoff_call_date`` is populated from HubSpot but never written back.
    - If a company is associated with the deal, ``tech_stack`` is populated from
      the company's tech stack properties and ``hubspot_company_id`` is stored.
    - If no company is associated, ``tech_stack`` and ``hubspot_company_id`` are
      left untouched on existing accounts; new accounts receive empty defaults.

    :param deal_id: HubSpot deal object ID to sync.
    :param db_session: Active database session.
    :param settings: Application settings providing HubSpot credentials.
    :returns: The upserted :class:`~reffie.models.account.Account` with POCs and
        checklist items eagerly loaded.
    :raises HubSpotNotFoundError: If the deal does not exist in HubSpot.
    :raises HubSpotAPIError: For other HubSpot API errors.
    """
    deal_data = await hubspot_client.get_deal_properties(deal_id, _DEAL_PROPERTIES)
    props: dict[str, Any] = deal_data.get("properties", {})

    contact_ids = await hubspot_client.get_deal_contact_ids(deal_id)
    contacts_data: list[dict[str, Any]] = []
    for cid in contact_ids:
        try:
            contact = await hubspot_client.get_contact_properties(cid, _CONTACT_PROPERTIES)
            contacts_data.append(contact)
        except hubspot_client.HubSpotNotFoundError:
            logger.warning(
                "Skipping deleted contact %s for deal %s — contact no longer exists in HubSpot",
                cid,
                deal_id,
            )
            continue

    company_id = await hubspot_client.get_deal_company_id(deal_id, settings)
    company_props: dict[str, str | None] | None = None
    if company_id is not None:
        company_props = await hubspot_client.get_company_properties(
            company_id, hubspot_client.TECH_STACK_PROPERTIES, settings
        )

    existing_result = await db_session.execute(
        select(Account).where(Account.hubspot_deal_id == deal_id)
    )
    account = existing_result.scalar_one_or_none()

    if account is None:
        account = Account(
            id=uuid.uuid4(),
            company_name="",
            location="",
            property_type="",
            cs_rep="",
            # Platform owns onboarding_stage; new accounts start at the first stage.
            onboarding_stage=PLATFORM_STAGES[0],
        )
        db_session.add(account)

    _apply_deal_fields_to_account(account, props, deal_id)

    if company_props is not None and company_id is not None:
        account.hubspot_company_id = company_id
        account.tech_stack = tech_stack_module.hubspot_to_ts(company_props)

    # Best-effort: a money-back-guarantee line item forces contract_length,
    # overriding the deal-level field. A HubSpot hiccup here must not fail the sync.
    try:
        line_items = await hubspot_client.get_deal_line_items(deal_id, settings)
    except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
        logger.exception(
            "Failed to fetch line items for deal %s — skipping contract override", deal_id
        )
        line_items = []
    if has_money_back_guarantee(line_items):
        account.contract_length = _MONEY_BACK_CONTRACT_LENGTH

    await db_session.flush()

    await db_session.execute(delete(Poc).where(Poc.account_id == account.id))
    new_pocs = [_map_contact_to_poc(c, account.id) for c in contacts_data]
    db_session.add_all(new_pocs)
    await db_session.flush()
    await db_session.commit()

    final_result = await db_session.execute(
        select(Account)
        .options(selectinload(Account.pocs), selectinload(Account.checklist_items))
        .where(Account.id == account.id)
    )
    return final_result.scalar_one()
