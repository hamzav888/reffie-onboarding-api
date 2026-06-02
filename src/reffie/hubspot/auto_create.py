"""
Automatic account creation triggered by HubSpot Closed Won webhooks.

This module is designed to run as a FastAPI background task.  It opens its
own database session (same pattern as writeback.py) because it executes after
the HTTP response is sent and the request-scoped session is already closed.
"""

import logging
from typing import Any

from sqlalchemy import select

import reffie.db.session as db_session_module
import reffie.hubspot.client as hubspot_client
import reffie.hubspot.sync as sync_module
import reffie.hubspot.writeback as writeback_module
import reffie.onboarding_flows as onboarding_flows_module
from reffie.config import Settings
from reffie.models import Account

logger = logging.getLogger(__name__)


async def process_closed_won(deal_id: str, settings: Settings) -> None:
    """
    Verify Closed Won + matching product, then create an onboarding account.

    Idempotent: if an account with ``hubspot_deal_id == deal_id`` already
    exists the function logs and returns immediately (HubSpot may fire the
    webhook more than once).

    Opens its own database session.  All HubSpot and database errors are
    caught, logged, and swallowed — background tasks must not crash the worker.

    :param deal_id: HubSpot deal object ID from the webhook event.
    :param settings: Application settings providing HubSpot credentials.
    """
    async with db_session_module.AsyncSessionLocal() as session:
        # Idempotency guard — webhook may fire multiple times.
        result = await session.execute(select(Account).where(Account.hubspot_deal_id == deal_id))
        if result.scalar_one_or_none() is not None:
            logger.info("Account for deal %s already exists, skipping", deal_id)
            return

        # Re-verify the stage at processing time — the webhook can be delayed.
        try:
            stage = await hubspot_client.get_deal_stage(deal_id, settings)
        except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
            logger.exception("Failed to fetch stage for deal %s", deal_id)
            return

        if stage is None or stage not in settings.hubspot_closed_won_stage_ids:
            logger.info("Deal %s is no longer Closed Won (stage=%s), skipping", deal_id, stage)
            return

        # Fetch quotes attached to this deal.
        try:
            quote_ids = await hubspot_client.get_deal_quote_ids(deal_id, settings)
        except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
            logger.exception("Failed to fetch quotes for deal %s", deal_id)
            return

        if quote_ids == []:
            logger.info("Deal %s has no quotes, skipping account creation", deal_id)
            return

        # Collect all line items from all quotes.
        all_items: list[dict[str, Any]] = []
        for quote_id in quote_ids:
            try:
                items = await hubspot_client.get_quote_line_items(quote_id, settings)
            except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
                logger.exception("Failed to fetch line items for quote %s", quote_id)
                continue
            all_items.extend(items)

        # Deterministic ordering: sort by line-item id before scanning for a flow.
        all_items.sort(key=lambda item: item.get("id", ""))

        flow = None
        for item in all_items:
            candidate = onboarding_flows_module.flow_for_sku(item.get("sku"))
            if candidate is not None:
                flow = candidate
                break

        if flow is None:
            logger.info("Deal %s: no matching product SKU, skipping account creation", deal_id)
            return

        # Create the account by re-using the existing sync pipeline.
        try:
            account = await sync_module.pull_deal(deal_id, session, settings)
        except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
            logger.exception("Failed to pull deal %s from HubSpot", deal_id)
            return

        # Apply the flow's initial stage (pull_deal sets PLATFORM_STAGES[0] for new
        # accounts; this override handles future flows with different starting stages).
        account.onboarding_stage = flow.initial_stage
        await session.commit()

    # sync_stage_to_hubspot opens its own session — call outside our session block.
    await writeback_module.sync_stage_to_hubspot(account.id, settings)
    logger.info(
        "Created account %s from HubSpot deal %s (product=%s)",
        account.id,
        deal_id,
        flow.product_name,
    )
