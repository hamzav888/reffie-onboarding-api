import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.config import Settings, get_settings
from reffie.db.session import get_db_session
from reffie.hubspot import writeback
from reffie.models import Account, ChecklistItem
from reffie.schemas.checklist import ChecklistItemOut, ChecklistItemUpdate

router = APIRouter(tags=["checklist"])


@router.patch("/accounts/{account_id}/checklist/{step_id}", response_model=ChecklistItemOut)
async def upsert_checklist_item(
    account_id: uuid.UUID,
    step_id: str,
    body: ChecklistItemUpdate,
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ChecklistItemOut:
    """
    Update a checklist step for an account, creating the row if it does not yet exist.

    Triggers a background task to sync the updated stage to HubSpot.

    :param account_id: UUID of the owning account.
    :param step_id: Deterministic step identifier (e.g. ``"pre-kick-off__confirm"``).
    :param body: Fields to update; absent fields are left unchanged.
    :param background_tasks: FastAPI background task queue.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :param settings: Application settings (passed to the background task).
    :returns: Updated or newly created :class:`~reffie.schemas.checklist.ChecklistItemOut`.
    :raises HTTPException: 404 if the account does not exist.
    """
    account_result = await db_session.execute(select(Account).where(Account.id == account_id))
    if account_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Account not found")

    item_result = await db_session.execute(
        select(ChecklistItem).where(
            ChecklistItem.account_id == account_id,
            ChecklistItem.step_id == step_id,
        )
    )
    item = item_result.scalar_one_or_none()

    if item is None:
        # Set Python-side defaults explicitly; server_default values are only
        # applied by the DB during INSERT and won't be present until a refresh.
        item = ChecklistItem(
            id=uuid.uuid4(),
            account_id=account_id,
            step_id=step_id,
            done=False,
            note="",
        )
        db_session.add(item)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    await db_session.flush()
    await db_session.commit()
    # Re-query so the response reflects any DB-side values set during the write.
    refreshed = await db_session.execute(
        select(ChecklistItem).where(
            ChecklistItem.account_id == account_id,
            ChecklistItem.step_id == step_id,
        )
    )
    item = refreshed.scalar_one()
    background_tasks.add_task(writeback.sync_stage_to_hubspot, account_id, settings)
    return ChecklistItemOut.model_validate(item)
