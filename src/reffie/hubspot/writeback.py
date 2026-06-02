"""
HubSpot write-back: translates the platform's onboarding state into the
HubSpot deal stage and writes it back via the CRM API.

This module is designed to run as a FastAPI background task. It opens its own
database session (rather than accepting the request's session) because background
tasks execute after the HTTP response is sent and the request-scoped session is
already closed.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

import reffie.db.session as db_session_module
import reffie.hubspot.client as hubspot_client
from reffie.config import Settings
from reffie.constants import PLATFORM_STAGES
from reffie.models import Account

logger = logging.getLogger(__name__)


async def sync_stage_to_hubspot(account_id: uuid.UUID, settings: Settings) -> None:
    """
    Compute the HubSpot deal stage from platform state and write it to HubSpot.

    Opens its own database session to avoid depending on the request-scoped
    session, which will already be closed by the time a background task runs.

    Failures from HubSpot are logged but never re-raised — the background task
    must not crash the worker on a downstream API error.

    :param account_id: UUID of the account whose stage should be synced.
    :param settings: Application settings providing HubSpot credentials.
    """
    async with db_session_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(Account)
            .options(selectinload(Account.checklist_items))
            .where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()

    if account is None:
        return

    if account.hubspot_deal_id is None:
        return

    steps_done = {item.step_id: item.done for item in account.checklist_items}

    stage = account.onboarding_stage
    stage_idx = PLATFORM_STAGES.index(stage) if stage in PLATFORM_STAGES else 0

    sixty_day_items = [
        i for i in account.checklist_items if i.step_id.startswith("60-day-check-in__")
    ]
    sixty_day_complete = (
        stage == "60-day check-in"
        and len(sixty_day_items) > 0
        and all(i.done for i in sixty_day_items)
    )

    properties: dict[str, str]

    if sixty_day_complete:
        properties = {
            "onboarding_stage": "Onboarding Complete",
            "onboarding_complete_date": datetime.now(UTC).date().isoformat(),
        }
    elif steps_done.get("training-call__schedule-checkin") is True:
        properties = {"onboarding_stage": "Check-In Scheduled"}
    elif stage_idx > PLATFORM_STAGES.index("Training call"):
        properties = {"onboarding_stage": "Check-in Pending"}
    elif (
        steps_done.get("validation-call__schedule-training") is True
        or steps_done.get("kick-off-call__schedule-training") is True
    ):
        properties = {"onboarding_stage": "Training Scheduled"}
    elif stage_idx > PLATFORM_STAGES.index("Kick-off call"):
        properties = {"onboarding_stage": "Training Pending"}
    elif steps_done.get("pre-kick-off__schedule-kickoff") is True:
        properties = {"onboarding_stage": "Kick-Off Scheduled"}
    else:
        properties = {"onboarding_stage": "Kick-Off Pending"}

    try:
        await hubspot_client.update_deal_properties(account.hubspot_deal_id, properties, settings)
    except (hubspot_client.HubSpotAPIError, hubspot_client.HubSpotNotFoundError):
        logger.exception(
            "HubSpot write-back failed for account %s / deal %s",
            account_id,
            account.hubspot_deal_id,
        )
