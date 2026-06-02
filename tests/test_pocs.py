import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.db.session import get_db_session
from reffie.main import app
from reffie.models import Account


def make_account() -> Account:
    """Minimal transient Account for POC tests."""
    account = Account(
        id=uuid.uuid4(),
        company_name="Acme",
        location="NY",
        property_type="commercial",
        cs_rep="Alice",
        onboarding_stage="kick-off",
        tech_stack={},
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add_all = MagicMock()  # sync method on AsyncSession
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def override_deps(mock_session: AsyncMock) -> Generator[None]:
    async def fake_db() -> AsyncGenerator[AsyncSession]:
        yield mock_session  # type: ignore[misc]

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        email="cs@reffie.me", name="CS Rep"
    )
    app.dependency_overrides[get_db_session] = fake_db
    yield
    app.dependency_overrides.clear()


async def test_replace_pocs_inserts_new_list(mock_session: AsyncMock) -> None:
    account = make_account()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = account
    mock_session.execute.return_value = mock_result

    payload = [
        {"name": "Jane Doe", "email": "jane@client.com", "phone": "555-0100", "role": "CEO"},
        {"name": "John Smith", "email": "john@client.com"},
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(f"/accounts/{account.id}/pocs", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Jane Doe"
    assert data[0]["email"] == "jane@client.com"
    assert data[1]["name"] == "John Smith"
    assert data[1]["phone"] is None
    mock_session.add_all.assert_called_once()


async def test_replace_pocs_with_empty_list_removes_all(mock_session: AsyncMock) -> None:
    account = make_account()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = account
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(f"/accounts/{account.id}/pocs", json=[])

    assert response.status_code == 200
    assert response.json() == []


async def test_replace_pocs_account_not_found(mock_session: AsyncMock) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/accounts/{uuid.uuid4()}/pocs",
            json=[{"name": "X", "email": "x@x.com"}],
        )

    assert response.status_code == 404


async def test_replace_pocs_invalid_body() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/accounts/{uuid.uuid4()}/pocs",
            json=[{"name": "Missing email field"}],
        )

    assert response.status_code == 422
