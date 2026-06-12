"""
Router for the Upcoming Deals tab.

Exposes the ``upcoming_deals`` cache as a read endpoint and provides a
``POST /refresh`` endpoint that triggers a full rebuild from HubSpot.
All endpoints require authentication.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

import reffie.hubspot.upcoming_deals as upcoming_deals_module
from reffie.auth import CurrentUser, get_current_user
from reffie.config import Settings, get_settings
from reffie.db.session import get_db_session
from reffie.models import UpcomingDeal
from reffie.schemas.upcoming_deal import UpcomingDealOut

router = APIRouter(prefix="/upcoming-deals", tags=["upcoming-deals"])


@router.post("/refresh")
async def trigger_refresh(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    _: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    """
    Trigger a full rebuild of the upcoming-deals cache from HubSpot.

    Returns immediately; the rebuild runs as a background task. The frontend
    can poll ``GET /upcoming-deals`` after a short delay to see updated results.

    :param background_tasks: FastAPI background task queue.
    :param settings: Application settings.
    :returns: ``{"status": "ok"}``
    """
    background_tasks.add_task(upcoming_deals_module.refresh_all, settings)
    return {"status": "ok"}


@router.get("", response_model=list[UpcomingDealOut])
async def list_upcoming_deals(
    db_session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(get_current_user),
) -> list[UpcomingDeal]:
    """
    Return all cached upcoming deals, ordered by close date ascending (nulls last).

    :param db_session: Database session.
    :returns: List of upcoming deals.
    """
    result = await db_session.execute(
        select(UpcomingDeal).order_by(nullslast(UpcomingDeal.close_date.asc()))
    )
    return list(result.scalars().all())


@router.get("/{deal_id}", response_model=UpcomingDealOut)
async def get_upcoming_deal(
    deal_id: uuid.UUID,
    db_session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(get_current_user),
) -> UpcomingDeal:
    """
    Return a single upcoming deal by primary key.

    :param deal_id: UUID primary key of the upcoming deal row.
    :param db_session: Database session.
    :returns: The matching upcoming deal.
    :raises HTTPException: 404 if not found.
    """
    result = await db_session.execute(
        select(UpcomingDeal).where(UpcomingDeal.id == deal_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Upcoming deal not found")
    return row
