"""
Unit tests for the upcoming-deals HubSpot service module.

All HubSpot API calls and DB sessions are mocked. No network or DB required.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import SQLAlchemyError

from reffie.config import settings as _settings
from reffie.hubspot.client import HubSpotAPIError, HubSpotNotFoundError
from reffie.hubspot.upcoming_deals import (
    _fetch_deal_data,  # pyright: ignore[reportPrivateUsage]
    fetch_and_upsert_deal,
    refresh_all,
    remove_deal,
)
from reffie.models import UpcomingDeal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEAL_ID = "deal-7001"

_DEAL_DATA: dict[str, object] = {
    "company_name": "Gamma Inc",
    "deal_stage": "1713761016",
    "tech_stack": {"pms": "Yardi"},
    "sales_rep_name": "Alice Sales",
    "arr": Decimal("75000.00"),
    "close_date": date(2026, 10, 1),
}


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_upcoming_deal(deal_id: str = _DEAL_ID) -> UpcomingDeal:
    row = UpcomingDeal(
        id=uuid.uuid4(),
        hubspot_deal_id=deal_id,
        company_name="Old Name",
        deal_stage="stage_0",
        tech_stack={},
        sales_rep_name=None,
        arr=None,
        close_date=None,
        last_synced_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return row


# ---------------------------------------------------------------------------
# fetch_and_upsert_deal — new deal
# ---------------------------------------------------------------------------


async def test_fetch_and_upsert_deal_creates_new_row() -> None:
    session = _make_mock_session()
    # DB returns None → new row to be created.
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result

    with (
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=_DEAL_DATA),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await fetch_and_upsert_deal(_DEAL_ID, _settings)

    session.add.assert_called_once()
    session.commit.assert_called_once()
    added_row: UpcomingDeal = session.add.call_args[0][0]
    assert added_row.hubspot_deal_id == _DEAL_ID
    assert added_row.company_name == "Gamma Inc"
    assert added_row.arr == Decimal("75000.00")


async def test_fetch_and_upsert_deal_updates_existing_row() -> None:
    session = _make_mock_session()
    existing = _make_upcoming_deal()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = existing
    session.execute.return_value = execute_result

    with (
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=_DEAL_DATA),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await fetch_and_upsert_deal(_DEAL_ID, _settings)

    # No new row added — the existing row was mutated.
    session.add.assert_not_called()
    session.commit.assert_called_once()
    assert existing.company_name == "Gamma Inc"
    assert existing.deal_stage == "1713761016"
    assert existing.sales_rep_name == "Alice Sales"


async def test_fetch_and_upsert_deal_skips_when_deal_not_found() -> None:
    session = _make_mock_session()

    with (
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=None),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await fetch_and_upsert_deal(_DEAL_ID, _settings)

    session.add.assert_not_called()
    session.commit.assert_not_called()


async def test_fetch_and_upsert_deal_swallows_db_error() -> None:
    session = _make_mock_session()
    session.execute.side_effect = SQLAlchemyError("DB down")

    with (
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=_DEAL_DATA),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        # Must not raise.
        await fetch_and_upsert_deal(_DEAL_ID, _settings)


# ---------------------------------------------------------------------------
# remove_deal
# ---------------------------------------------------------------------------


async def test_remove_deal_executes_delete() -> None:
    session = _make_mock_session()
    session.execute.return_value = MagicMock()

    with mock.patch(
        "reffie.db.session.AsyncSessionLocal",
        MagicMock(return_value=session),
    ):
        await remove_deal(_DEAL_ID)

    session.execute.assert_called_once()
    session.commit.assert_called_once()


async def test_remove_deal_swallows_db_error() -> None:
    session = _make_mock_session()
    session.execute.side_effect = SQLAlchemyError("DB error")

    with mock.patch(
        "reffie.db.session.AsyncSessionLocal",
        MagicMock(return_value=session),
    ):
        await remove_deal(_DEAL_ID)
    # Reaching here confirms the error was swallowed.


# ---------------------------------------------------------------------------
# refresh_all
# ---------------------------------------------------------------------------


async def test_refresh_all_upserts_and_prunes_stale() -> None:
    session = _make_mock_session()
    # First execute: SELECT for deal-1 returns None (new row).
    # Second execute: DELETE stale rows.
    new_row_result = MagicMock()
    new_row_result.scalar_one_or_none.return_value = None
    delete_result = MagicMock()
    session.execute.side_effect = [new_row_result, delete_result]

    all_deals: list[dict[str, object]] = [{"id": "deal-1", "properties": {}}]

    with (
        mock.patch(
            "reffie.hubspot.client.search_deals_by_stage_all",
            new=AsyncMock(return_value=all_deals),
        ),
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=_DEAL_DATA),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await refresh_all(_settings)

    session.add.assert_called_once()
    session.commit.assert_called_once()
    # Two execute calls: SELECT upsert check + DELETE stale rows.
    assert session.execute.call_count == 2


async def test_refresh_all_skips_delete_when_no_fetched_ids() -> None:
    """If no deals are fetched, stale-row delete is skipped (safety guard)."""
    session = _make_mock_session()
    session.execute.return_value = MagicMock()

    with (
        mock.patch(
            "reffie.hubspot.client.search_deals_by_stage_all",
            new=AsyncMock(return_value=[]),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await refresh_all(_settings)

    # No execute calls at all — nothing to upsert, delete skipped.
    session.execute.assert_not_called()
    session.commit.assert_called_once()


async def test_refresh_all_skips_when_no_stage_ids_configured() -> None:
    """refresh_all is a no-op when hubspot_upcoming_stage_ids is empty."""
    empty_settings = _settings.model_copy(update={"hubspot_upcoming_stage_ids": []})
    session = _make_mock_session()

    with mock.patch(
        "reffie.db.session.AsyncSessionLocal",
        MagicMock(return_value=session),
    ):
        await refresh_all(empty_settings)

    session.execute.assert_not_called()
    session.commit.assert_not_called()


async def test_refresh_all_swallows_db_error() -> None:
    session = _make_mock_session()
    session.execute.side_effect = SQLAlchemyError("DB error")

    with (
        mock.patch(
            "reffie.hubspot.client.search_deals_by_stage_all",
            new=AsyncMock(return_value=[{"id": "deal-1"}]),
        ),
        mock.patch(
            "reffie.hubspot.upcoming_deals._fetch_deal_data",
            new=AsyncMock(return_value=_DEAL_DATA),
        ),
        mock.patch(
            "reffie.db.session.AsyncSessionLocal",
            MagicMock(return_value=session),
        ),
    ):
        await refresh_all(_settings)
    # Must not raise.


# ---------------------------------------------------------------------------
# _fetch_deal_data — company and owner edge-case paths
# ---------------------------------------------------------------------------

_DEAL_RESPONSE_BLANK_OWNER: dict[str, object] = {
    "id": _DEAL_ID,
    "properties": {
        "dealname": "Test Deal",
        "dealstage": "1713761016",
        "amount": "50000",
        "closedate": "2026-10-01",
        "hubspot_owner_id": "",
    },
}

_DEAL_RESPONSE_WITH_OWNER: dict[str, object] = {
    "id": _DEAL_ID,
    "properties": {
        "dealname": "Test Deal",
        "dealstage": "1713761016",
        "amount": "50000",
        "closedate": "2026-10-01",
        "hubspot_owner_id": "owner-99",
    },
}


async def test_fetch_deal_data_no_company_returns_empty_tech_stack() -> None:
    """get_deal_company_id returning None → tech_stack is {}."""
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE_BLANK_OWNER),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await _fetch_deal_data(_DEAL_ID, _settings)

    assert result is not None
    assert result["tech_stack"] == {}


async def test_fetch_deal_data_company_fetch_error_returns_empty_tech_stack() -> None:
    """get_deal_company_id raising HubSpotAPIError → tech_stack is {}."""
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE_BLANK_OWNER),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(side_effect=HubSpotAPIError("API error")),
        ),
    ):
        result = await _fetch_deal_data(_DEAL_ID, _settings)

    assert result is not None
    assert result["tech_stack"] == {}


async def test_fetch_deal_data_blank_owner_id_returns_none_rep() -> None:
    """Blank hubspot_owner_id → sales_rep_name is None; get_owner never called."""
    mock_get_owner = AsyncMock()
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE_BLANK_OWNER),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
        ),
        mock.patch("reffie.hubspot.client.get_owner", mock_get_owner),
    ):
        result = await _fetch_deal_data(_DEAL_ID, _settings)

    assert result is not None
    assert result["sales_rep_name"] is None
    mock_get_owner.assert_not_called()


async def test_fetch_deal_data_owner_fetch_error_returns_none_rep() -> None:
    """get_owner raising HubSpotNotFoundError → sales_rep_name is None."""
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE_WITH_OWNER),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
        ),
        mock.patch(
            "reffie.hubspot.client.get_owner",
            new=AsyncMock(side_effect=HubSpotNotFoundError("404")),
        ),
    ):
        result = await _fetch_deal_data(_DEAL_ID, _settings)

    assert result is not None
    assert result["sales_rep_name"] is None
