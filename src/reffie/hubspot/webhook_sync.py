"""
Apply individual HubSpot property changes (delivered via webhook) to the
matching account.

Unlike a full ``pull_deal`` sync, this handles a single ``deal.propertyChange``
or ``company.propertyChange`` event by writing one mapped field. The value is
taken directly from the webhook payload — no HubSpot API call is made. Runs as
a FastAPI background task and opens its own DB session.
"""

import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import reffie.db.session as db_session_module
from reffie.models import Account

logger = logging.getLogger(__name__)


def _cs_rep_value(raw: str | None) -> str:
    """Map a HubSpot ``onboarding_cs_rep`` value to ``cs_rep`` (stripped).

    Blank values never reach here — they are skipped before any write so an
    existing rep is not clobbered (see :func:`sync_deal_property`).
    """
    return raw.strip() if raw else ""


# HubSpot deal property name → (Account attribute, value transform).
# Only onboarding_cs_rep is active; the rest mirror _apply_deal_fields_to_account
# in sync.py and can be enabled once Connie subscribes the property in HubSpot.
WEBHOOK_FIELD_MAP: dict[str, tuple[str, Callable[[str | None], object]]] = {
    "onboarding_cs_rep": ("cs_rep", _cs_rep_value),
    # "dealname": ("company_name", lambda v: (v.strip() if v else "") or "Unknown"),
    # "amount": ("arr", _parse_decimal_value),         # Decimal | None
    # "contract_length": ("contract_length", _str_or_none_value),
    # "success_metrics": ("success_metrics", _str_or_none_value),
}

# HubSpot company property name → (Account attribute, value transform).
COMPANY_WEBHOOK_FIELD_MAP: dict[str, tuple[str, Callable[[str | None], object]]] = {
    "onboarding_cs_rep": ("cs_rep", _cs_rep_value),
}


async def sync_deal_property(deal_id: str, property_name: str, property_value: str | None) -> None:
    """
    Apply a single HubSpot deal property change to the matching account.

    Finds the account by ``hubspot_deal_id``; if none exists, returns silently.
    A blank or ``None`` ``property_value`` is skipped entirely so an existing
    value is preserved rather than overwritten with a blank. The value is taken
    from the webhook payload directly (not re-fetched from HubSpot).

    :param deal_id: HubSpot deal object ID (``str(event.object_id)``).
    :param property_name: HubSpot property that changed.
    :param property_value: New value from the webhook payload (may be ``None``).
    """
    mapping = WEBHOOK_FIELD_MAP.get(property_name)
    if mapping is None:
        return
    if property_value is None or property_value.strip() == "":
        logger.warning(
            "sync_deal_property: blank value for deal_id=%s property=%s — preserving existing",
            deal_id,
            property_name,
        )
        return
    attr_name, transform = mapping
    try:
        async with db_session_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Account).where(Account.hubspot_deal_id == deal_id)
            )
            account = result.scalar_one_or_none()
            if account is None:
                logger.warning(
                    "sync_deal_property: no account for deal_id=%s property=%s — skipping",
                    deal_id,
                    property_name,
                )
                return
            setattr(account, attr_name, transform(property_value))
            await session.commit()
    except SQLAlchemyError:
        logger.exception("sync_deal_property failed deal_id=%s property=%s", deal_id, property_name)


async def sync_company_property(
    company_id: str, property_name: str, property_value: str | None
) -> None:
    """
    Apply a single HubSpot company property change to the matching account.

    Finds the account by ``hubspot_company_id``; if none exists, returns silently.
    A blank or ``None`` ``property_value`` is skipped entirely so an existing
    value is preserved rather than overwritten with a blank.

    :param company_id: HubSpot company object ID (``str(event.object_id)``).
    :param property_name: HubSpot property that changed.
    :param property_value: New value from the webhook payload (may be ``None``).
    """
    mapping = COMPANY_WEBHOOK_FIELD_MAP.get(property_name)
    if mapping is None:
        return
    if property_value is None or property_value.strip() == "":
        logger.warning(
            "sync_company_property: blank value for company_id=%s property=%s — preserving",
            company_id,
            property_name,
        )
        return
    attr_name, transform = mapping
    try:
        async with db_session_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Account).where(Account.hubspot_company_id == company_id)
            )
            account = result.scalar_one_or_none()
            if account is None:
                logger.warning(
                    "sync_company_property: no account for company_id=%s property=%s — skipping",
                    company_id,
                    property_name,
                )
                return
            setattr(account, attr_name, transform(property_value))
            await session.commit()
    except SQLAlchemyError:
        logger.exception(
            "sync_company_property failed company_id=%s property=%s", company_id, property_name
        )
