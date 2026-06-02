import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import reffie.hubspot.writeback as writeback
from reffie.auth import CurrentUser, get_current_user
from reffie.config import Settings, get_settings
from reffie.db.session import get_db_session
from reffie.models import Account
from reffie.schemas.account import AccountCreate, AccountDetail, AccountSummary, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


async def _load_account_detail(account_id: uuid.UUID, db_session: AsyncSession) -> Account:
    """
    Fetch a single account with POCs and checklist items eagerly loaded.

    :param account_id: UUID of the account to load.
    :param db_session: Active database session.
    :returns: The matching :class:`~reffie.models.account.Account`.
    :raises HTTPException: 404 if no account with ``account_id`` exists.
    """
    result = await db_session.execute(
        select(Account)
        .options(selectinload(Account.pocs), selectinload(Account.checklist_items))
        .where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("", response_model=list[AccountSummary])
async def list_accounts(
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> list[AccountSummary]:
    """
    Return a summary list of all accounts ordered by company name.

    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :returns: List of :class:`~reffie.schemas.account.AccountSummary`.
    """
    result = await db_session.execute(select(Account).order_by(Account.company_name))
    accounts = result.scalars().all()
    return [AccountSummary.model_validate(a) for a in accounts]


@router.get("/{account_id}", response_model=AccountDetail)
async def get_account(
    account_id: uuid.UUID,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> AccountDetail:
    """
    Return full detail for a single account including POCs and checklist state.

    :param account_id: UUID path parameter.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :returns: :class:`~reffie.schemas.account.AccountDetail`.
    :raises HTTPException: 404 if the account does not exist.
    """
    account = await _load_account_detail(account_id, db_session)
    return AccountDetail.model_validate(account)


@router.post("", response_model=AccountDetail, status_code=201)
async def create_account(
    body: AccountCreate,
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AccountDetail:
    """
    Create a new account and return its full detail.

    Triggers a background task to sync the initial stage to HubSpot if the
    account has a ``hubspot_deal_id``.

    :param body: Account creation payload.
    :param background_tasks: FastAPI background task queue.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :param settings: Application settings (passed to the background task).
    :returns: :class:`~reffie.schemas.account.AccountDetail` for the new account.
    """
    account = Account(**body.model_dump())
    db_session.add(account)
    await db_session.flush()
    await db_session.commit()
    account = await _load_account_detail(account.id, db_session)
    background_tasks.add_task(writeback.sync_stage_to_hubspot, account.id, settings)
    return AccountDetail.model_validate(account)


@router.patch("/{account_id}", response_model=AccountDetail)
async def patch_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    background_tasks: BackgroundTasks,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AccountDetail:
    """
    Partially update an account — only fields present in the request body are changed.

    Triggers a background task to sync the updated stage to HubSpot.

    :param account_id: UUID of the account to update.
    :param body: Fields to update; absent fields are ignored.
    :param background_tasks: FastAPI background task queue.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :param settings: Application settings (passed to the background task).
    :returns: Updated :class:`~reffie.schemas.account.AccountDetail`.
    :raises HTTPException: 404 if the account does not exist.
    """
    account = await _load_account_detail(account_id, db_session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    await db_session.flush()
    await db_session.commit()
    background_tasks.add_task(writeback.sync_stage_to_hubspot, account.id, settings)
    return AccountDetail.model_validate(account)


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> None:
    """
    Delete an account and all its associated data.

    :param account_id: UUID of the account to delete.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :raises HTTPException: 404 if the account does not exist.
    """
    result = await db_session.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await db_session.delete(account)
    await db_session.flush()
    await db_session.commit()
