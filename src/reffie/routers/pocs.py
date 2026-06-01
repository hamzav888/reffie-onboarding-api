import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.db.session import get_db_session
from reffie.models import Account, Poc
from reffie.schemas.poc import PocIn, PocOut

router = APIRouter(tags=["pocs"])


@router.put("/accounts/{account_id}/pocs", response_model=list[PocOut])
async def replace_pocs(
    account_id: uuid.UUID,
    body: list[PocIn],
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
) -> list[PocOut]:
    """
    Replace all points of contact for an account with the supplied list.

    Deletes every existing POC for the account, then inserts the new ones.
    Passing an empty list removes all POCs.

    :param account_id: UUID of the owning account.
    :param body: New list of POCs to associate with the account.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :returns: The newly created list of :class:`~reffie.schemas.poc.PocOut`.
    :raises HTTPException: 404 if the account does not exist.
    """
    account_result = await db_session.execute(select(Account).where(Account.id == account_id))
    if account_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Account not found")

    await db_session.execute(delete(Poc).where(Poc.account_id == account_id))

    new_pocs = [
        Poc(
            id=uuid.uuid4(),
            account_id=account_id,
            name=poc.name,
            email=poc.email,
            phone=poc.phone,
            role=poc.role,
        )
        for poc in body
    ]
    db_session.add_all(new_pocs)
    await db_session.flush()
    await db_session.commit()
    return [PocOut.model_validate(p) for p in new_pocs]
