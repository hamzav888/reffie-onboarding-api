"""
Tests for the upcoming-deals router (GET list, GET by ID, POST refresh).
"""

import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.config import get_settings
from reffie.config import settings as _settings
from reffie.db.session import get_db_session
from reffie.main import app
from reffie.models import UpcomingDeal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_upcoming_deal(**kwargs: object) -> UpcomingDeal:
    """Build a transient UpcomingDeal instance with sensible defaults."""
    row = UpcomingDeal(
        id=kwargs.get("id", uuid.uuid4()),
        hubspot_deal_id=kwargs.get("hubspot_deal_id", "deal-1"),
        company_name=kwargs.get("company_name", "Acme Corp"),
        deal_stage=kwargs.get("deal_stage", "1713761016"),
        tech_stack=kwargs.get("tech_stack", {}),
        sales_rep_name=kwargs.get("sales_rep_name", "Bob Sales"),
        arr=kwargs.get("arr", Decimal("50000.00")),
        close_date=kwargs.get("close_date", date(2026, 9, 1)),
        last_synced_at=kwargs.get("last_synced_at", datetime.now(UTC)),
        created_at=kwargs.get("created_at", datetime.now(UTC)),
        updated_at=kwargs.get("updated_at", datetime.now(UTC)),
    )
    return row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def override_deps(mock_session: AsyncMock) -> Generator[None]:
    async def fake_db() -> AsyncGenerator[AsyncSession]:
        yield mock_session  # type: ignore[misc]

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        email="cs@reffie.me", name="CS Rep"
    )
    app.dependency_overrides[get_db_session] = fake_db
    app.dependency_overrides[get_settings] = lambda: _settings
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_refresh() -> Generator[None]:
    """Suppress the real refresh_all background task for router tests."""
    with mock.patch(
        "reffie.hubspot.upcoming_deals.refresh_all", new=AsyncMock()
    ):
        yield


# ---------------------------------------------------------------------------
# GET /upcoming-deals
# ---------------------------------------------------------------------------


async def test_list_upcoming_deals_empty(mock_session: AsyncMock) -> None:
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = execute_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/upcoming-deals")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_upcoming_deals_returns_rows(mock_session: AsyncMock) -> None:
    deal_id = uuid.uuid4()
    deal = make_upcoming_deal(id=deal_id, hubspot_deal_id="deal-42", company_name="Beta Corp")
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [deal]
    mock_session.execute.return_value = execute_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/upcoming-deals")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["hubspot_deal_id"] == "deal-42"
    assert body[0]["company_name"] == "Beta Corp"
    assert body[0]["id"] == str(deal_id)


async def test_list_upcoming_deals_multiple_rows(mock_session: AsyncMock) -> None:
    deals = [
        make_upcoming_deal(hubspot_deal_id="deal-1", close_date=date(2026, 8, 1)),
        make_upcoming_deal(hubspot_deal_id="deal-2", close_date=date(2026, 9, 1)),
    ]
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = deals
    mock_session.execute.return_value = execute_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/upcoming-deals")

    assert response.status_code == 200
    assert len(response.json()) == 2


# ---------------------------------------------------------------------------
# GET /upcoming-deals/{deal_id}
# ---------------------------------------------------------------------------


async def test_get_upcoming_deal_not_found(mock_session: AsyncMock) -> None:
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = execute_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/upcoming-deals/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Upcoming deal not found"


async def test_get_upcoming_deal_found(mock_session: AsyncMock) -> None:
    deal_id = uuid.uuid4()
    deal = make_upcoming_deal(id=deal_id, hubspot_deal_id="deal-99")
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = deal
    mock_session.execute.return_value = execute_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/upcoming-deals/{deal_id}")

    assert response.status_code == 200
    assert response.json()["hubspot_deal_id"] == "deal-99"


# ---------------------------------------------------------------------------
# POST /upcoming-deals/refresh
# ---------------------------------------------------------------------------


async def test_trigger_refresh_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upcoming-deals/refresh")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_trigger_refresh_dispatches_background_task() -> None:
    with mock.patch(
        "reffie.hubspot.upcoming_deals.refresh_all", new_callable=AsyncMock
    ) as mock_refresh_all:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/upcoming-deals/refresh")

    assert response.status_code == 200
    mock_refresh_all.assert_called_once_with(_settings)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


async def test_list_requires_auth() -> None:
    # Remove the current_user override for this test.
    app.dependency_overrides.pop(get_current_user, None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/upcoming-deals")
        assert response.status_code == 401
    finally:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            email="cs@reffie.me", name="CS Rep"
        )
