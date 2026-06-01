import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.db.session import get_db_session
from reffie.main import app
from reffie.models import Account


def make_account(**kwargs: object) -> Account:
    """Build a transient Account instance with sensible defaults for testing."""
    account = Account(
        id=kwargs.get("id", uuid.uuid4()),
        company_name=kwargs.get("company_name", "Acme Corp"),
        location=kwargs.get("location", "New York"),
        property_type=kwargs.get("property_type", "commercial"),
        arr=kwargs.get("arr", Decimal("100000.00")),
        cs_rep=kwargs.get("cs_rep", "Alice"),
        onboarding_stage=kwargs.get("onboarding_stage", "kick-off"),
        skipped_stages=kwargs.get("skipped_stages", []),
        created_at=kwargs.get("created_at", datetime.now(UTC)),
        updated_at=kwargs.get("updated_at", datetime.now(UTC)),
    )
    # Set relationships manually to avoid async lazy-load on detached instances.
    account.pocs = []
    account.checklist_items = []
    return account


@pytest.fixture
def mock_session() -> AsyncMock:
    """Async mock that satisfies the AsyncSession interface used by the routers."""
    session = AsyncMock()
    session.add = MagicMock()      # sync method on AsyncSession
    session.add_all = MagicMock()  # sync method on AsyncSession
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def override_deps(mock_session: AsyncMock) -> Generator[None]:
    """Replace auth and DB dependencies for every test in this module."""

    async def fake_db() -> AsyncGenerator[AsyncSession]:
        yield mock_session  # type: ignore[misc]

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        email="cs@reffie.me", name="CS Rep"
    )
    app.dependency_overrides[get_db_session] = fake_db
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /accounts
# ---------------------------------------------------------------------------


async def test_list_accounts_returns_summaries(mock_session: AsyncMock) -> None:
    account = make_account()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [account]
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/accounts")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["company_name"] == "Acme Corp"
    assert data[0]["cs_rep"] == "Alice"


async def test_list_accounts_empty(mock_session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/accounts")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /accounts/{account_id}
# ---------------------------------------------------------------------------


async def test_get_account_returns_detail(mock_session: AsyncMock) -> None:
    account = make_account()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = account
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/accounts/{account.id}")

    assert response.status_code == 200
    assert response.json()["company_name"] == "Acme Corp"
    assert response.json()["pocs"] == []
    assert response.json()["checklist_items"] == []


async def test_get_account_not_found(mock_session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/accounts/{uuid.uuid4()}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /accounts
# ---------------------------------------------------------------------------


async def test_create_account_returns_201(mock_session: AsyncMock) -> None:
    created = make_account(company_name="New Co", onboarding_stage="pre-kick-off")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = created
    mock_session.execute.return_value = mock_result

    payload = {
        "company_name": "New Co",
        "location": "Boston",
        "property_type": "residential",
        "cs_rep": "Bob",
        "onboarding_stage": "pre-kick-off",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/accounts", json=payload)

    assert response.status_code == 201
    assert response.json()["company_name"] == "New Co"


async def test_create_account_missing_required_field() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/accounts", json={"company_name": "Incomplete"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /accounts/{account_id}
# ---------------------------------------------------------------------------


async def test_patch_account_updates_field(mock_session: AsyncMock) -> None:
    account = make_account(onboarding_stage="kick-off")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = account
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/accounts/{account.id}", json={"onboarding_stage": "post-kick-off"}
        )

    assert response.status_code == 200
    assert response.json()["onboarding_stage"] == "post-kick-off"


async def test_patch_account_not_found(mock_session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/accounts/{uuid.uuid4()}", json={"cs_rep": "X"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /accounts/{account_id}
# ---------------------------------------------------------------------------


async def test_delete_account_returns_204(mock_session: AsyncMock) -> None:
    account = make_account()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = account
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/accounts/{account.id}")

    assert response.status_code == 204
    mock_session.delete.assert_called_once_with(account)


async def test_delete_account_not_found(mock_session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/accounts/{uuid.uuid4()}")

    assert response.status_code == 404
