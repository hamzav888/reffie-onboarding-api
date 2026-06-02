from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import reffie.hubspot.client as hubspot_client
import reffie.hubspot.sync as hubspot_sync
from reffie.auth import CurrentUser, get_current_user
from reffie.config import Settings, get_settings
from reffie.db.session import get_db_session
from reffie.schemas.account import AccountDetail

router = APIRouter(prefix="/hubspot", tags=["hubspot"])


@router.post("/sync/{deal_id}", response_model=AccountDetail, status_code=200)
async def sync_deal(
    deal_id: str,
    db_session: AsyncSession = Depends(get_db_session),
    _current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> AccountDetail:
    """
    Pull a HubSpot deal, its contacts, and its associated company, upsert into
    the local database, and return the resulting account.

    :param deal_id: HubSpot deal object ID to sync.
    :param db_session: Injected database session.
    :param _current_user: Authenticated user (required, not used directly).
    :param settings: Application settings providing HubSpot credentials.
    :returns: Updated or newly created :class:`~reffie.schemas.account.AccountDetail`.
    :raises HTTPException: 404 if the deal does not exist in HubSpot.
    :raises HTTPException: 502 if HubSpot returns another API error.
    """
    try:
        account = await hubspot_sync.pull_deal(deal_id, db_session, settings)
    except hubspot_client.HubSpotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except hubspot_client.HubSpotAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AccountDetail.model_validate(account)
