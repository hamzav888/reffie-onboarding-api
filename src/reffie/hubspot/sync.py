import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import reffie.hubspot.client as hubspot_client
from reffie.constants import PLATFORM_STAGES
from reffie.models import Account, Poc

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
    account.property_type = _str(props, "property_type") or "Unknown"
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


async def pull_deal(deal_id: str, db_session: AsyncSession) -> Account:
    """
    Fetch a HubSpot deal and its contacts, then upsert them into the local database.

    Behaviour:
    - If an account with ``hubspot_deal_id == deal_id`` already exists, its fields
      are updated in place.
    - If no such account exists, a new one is created.
    - All existing POCs for the account are replaced with the current HubSpot contacts.
    - ``kickoff_call_date`` is populated from HubSpot but never written back.

    :param deal_id: HubSpot deal object ID to sync.
    :param db_session: Active database session.
    :returns: The upserted :class:`~reffie.models.account.Account` with POCs and
        checklist items eagerly loaded.
    :raises HubSpotNotFoundError: If the deal does not exist in HubSpot.
    :raises HubSpotAPIError: For other HubSpot API errors.
    """
    deal_data = await hubspot_client.get_deal_properties(deal_id, _DEAL_PROPERTIES)
    props: dict[str, Any] = deal_data.get("properties", {})

    contact_ids = await hubspot_client.get_deal_contact_ids(deal_id)
    contacts_data = [
        await hubspot_client.get_contact_properties(cid, _CONTACT_PROPERTIES) for cid in contact_ids
    ]

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
