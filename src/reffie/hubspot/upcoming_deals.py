"""
Cache-in-DB service for HubSpot deals in upcoming pipeline stages.

Provides background-task functions to upsert, remove, and bulk-refresh the
``upcoming_deals`` table. No HubSpot API call is made synchronously — all
network and DB work happens inside background tasks that open their own session.
"""

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

import reffie.db.session as db_session_module
import reffie.hubspot.client as client_module
import reffie.hubspot.tech_stack as tech_stack_module
from reffie.config import Settings
from reffie.hubspot.client import (
    TECH_STACK_PROPERTIES,
    HubSpotAPIError,
    HubSpotNotFoundError,
)
from reffie.models import UpcomingDeal

logger = logging.getLogger(__name__)

# Deal properties fetched from HubSpot for each upcoming deal.
_DEAL_PROPERTIES = ["dealname", "dealstage", "amount", "closedate", "hubspot_owner_id"]


def _parse_decimal(raw: object) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return Decimal(str(raw).strip())
    except InvalidOperation:
        return None


def _parse_date(raw: object) -> date | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


async def _fetch_deal_data(deal_id: str, settings: Settings) -> dict[str, object] | None:
    """
    Fetch all data needed to populate an :class:`~reffie.models.UpcomingDeal` row.

    Fetches deal properties, associated company tech stack, and owner name.
    Returns ``None`` if the deal itself is not found in HubSpot. Missing
    company or owner data is handled gracefully (defaults to empty / ``None``).

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing HubSpot credentials.
    :returns: Dict with keys matching ``UpcomingDeal`` fields, or ``None``.
    """
    try:
        deal = await client_module.get_deal_properties(deal_id, _DEAL_PROPERTIES)
    except HubSpotNotFoundError:
        logger.warning("_fetch_deal_data: deal %s not found in HubSpot", deal_id)
        return None

    props: dict[str, object] = deal.get("properties") or {}
    company_name: str = (str(props.get("dealname") or "")).strip() or "Unknown"
    deal_stage: str = str(props.get("dealstage") or "").strip()
    arr = _parse_decimal(props.get("amount"))
    close_date = _parse_date(props.get("closedate"))
    owner_id = str(props.get("hubspot_owner_id") or "").strip()

    # Tech stack from associated company.
    tech_stack: dict[str, object] = {}
    try:
        company_id = await client_module.get_deal_company_id(deal_id, settings)
        if company_id is not None:
            company_props = await client_module.get_company_properties(
                company_id, TECH_STACK_PROPERTIES, settings
            )
            tech_stack = tech_stack_module.hubspot_to_ts(company_props)
    except (HubSpotAPIError, HubSpotNotFoundError):
        logger.warning("_fetch_deal_data: could not fetch company for deal %s", deal_id)

    # Owner name from the Owners API.
    sales_rep_name: str | None = None
    if owner_id != "":
        try:
            owner = await client_module.get_owner(owner_id, settings)
            first = str(owner.get("firstName") or "").strip()
            last = str(owner.get("lastName") or "").strip()
            full = f"{first} {last}".strip()
            sales_rep_name = full if full != "" else None
        except (HubSpotAPIError, HubSpotNotFoundError):
            logger.warning(
                "_fetch_deal_data: could not fetch owner %s for deal %s", owner_id, deal_id
            )

    return {
        "company_name": company_name,
        "deal_stage": deal_stage,
        "tech_stack": tech_stack,
        "sales_rep_name": sales_rep_name,
        "arr": arr,
        "close_date": close_date,
    }


def _apply_data_to_row(row: UpcomingDeal, data: dict[str, object]) -> None:
    """Mutate ``row`` in place with all fields from ``data``."""
    row.company_name = str(data["company_name"])
    row.deal_stage = str(data["deal_stage"])
    row.tech_stack = data["tech_stack"]  # type: ignore[assignment]
    row.sales_rep_name = data["sales_rep_name"]  # type: ignore[assignment]
    row.arr = data["arr"]  # type: ignore[assignment]
    row.close_date = data["close_date"]  # type: ignore[assignment]
    row.last_synced_at = datetime.now(UTC)


async def fetch_and_upsert_deal(deal_id: str, settings: Settings) -> None:
    """
    Fetch a HubSpot deal and upsert it into the ``upcoming_deals`` table.

    Intended to run as a FastAPI background task. Opens its own DB session.
    If the deal is not found in HubSpot, returns without writing anything.

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing HubSpot credentials.
    """
    try:
        data = await _fetch_deal_data(deal_id, settings)
        if data is None:
            return

        async with db_session_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(UpcomingDeal).where(UpcomingDeal.hubspot_deal_id == deal_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UpcomingDeal(id=uuid.uuid4(), hubspot_deal_id=deal_id)
                session.add(row)
            _apply_data_to_row(row, data)
            await session.commit()

        logger.info("fetch_and_upsert_deal: upserted deal_id=%s", deal_id)
    except (SQLAlchemyError, HubSpotAPIError, HubSpotNotFoundError):
        logger.exception("fetch_and_upsert_deal failed deal_id=%s", deal_id)


async def remove_deal(deal_id: str) -> None:
    """
    Remove a deal from the ``upcoming_deals`` cache.

    Idempotent — no-op if the deal is not present. Intended to run as a
    FastAPI background task when a deal moves out of an upcoming stage.
    Opens its own DB session.

    :param deal_id: HubSpot deal object ID.
    """
    try:
        async with db_session_module.AsyncSessionLocal() as session:
            await session.execute(
                delete(UpcomingDeal).where(UpcomingDeal.hubspot_deal_id == deal_id)
            )
            await session.commit()
        logger.info("remove_deal: removed deal_id=%s (if present)", deal_id)
    except SQLAlchemyError:
        logger.exception("remove_deal failed deal_id=%s", deal_id)


async def refresh_all(settings: Settings) -> None:
    """
    Rebuild the ``upcoming_deals`` cache from HubSpot.

    Fetches all deals in the configured upcoming stages, upserts each one,
    then deletes any stale rows whose deal IDs were not returned by HubSpot.
    Intended to run as a FastAPI background task. Opens its own DB session.

    :param settings: Application settings providing HubSpot credentials.
    """
    if settings.hubspot_upcoming_stage_ids == []:
        logger.warning("refresh_all: no upcoming stage IDs configured — skipping")
        return

    try:
        all_deals = await client_module.search_deals_by_stage_all(
            settings.hubspot_upcoming_stage_ids, settings
        )
        logger.info("refresh_all: found %d deals in upcoming stages", len(all_deals))

        fetched_ids: list[str] = []

        async with db_session_module.AsyncSessionLocal() as session:
            for deal in all_deals:
                deal_id = str(deal.get("id") or "").strip()
                if deal_id == "":
                    continue

                data = await _fetch_deal_data(deal_id, settings)
                if data is None:
                    continue

                fetched_ids.append(deal_id)

                result = await session.execute(
                    select(UpcomingDeal).where(UpcomingDeal.hubspot_deal_id == deal_id)
                )
                row = result.scalar_one_or_none()
                if row is None:
                    row = UpcomingDeal(id=uuid.uuid4(), hubspot_deal_id=deal_id)
                    session.add(row)
                _apply_data_to_row(row, data)

            # Delete rows for deals no longer in the upcoming stages.
            if fetched_ids != []:
                await session.execute(
                    delete(UpcomingDeal).where(
                        UpcomingDeal.hubspot_deal_id.not_in(fetched_ids)
                    )
                )

            await session.commit()

        logger.info("refresh_all: upserted %d deals, stale rows pruned", len(fetched_ids))
    except (SQLAlchemyError, HubSpotAPIError):
        logger.exception("refresh_all failed")
