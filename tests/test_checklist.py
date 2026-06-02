import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from reffie.auth import CurrentUser, get_current_user
from reffie.db.session import get_db_session
from reffie.main import app
from reffie.models import Account, ChecklistItem


def make_account() -> Account:
    """Minimal transient Account for checklist tests."""
    account = Account(
        id=uuid.uuid4(),
        company_name="Acme",
        location="NY",
        property_type="commercial",
        cs_rep="Alice",
        onboarding_stage="kick-off",
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


def make_checklist_item(account_id: uuid.UUID, step_id: str = "step__one") -> ChecklistItem:
    """Minimal transient ChecklistItem for tests."""
    return ChecklistItem(
        id=uuid.uuid4(),
        account_id=account_id,
        step_id=step_id,
        done=False,
        note="",
    )


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()  # sync method on AsyncSession
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


@pytest.fixture(autouse=True)
def mock_writeback() -> Generator[None]:
    """Suppress HubSpot write-back background tasks — tests don't need a real DB session."""
    with mock.patch(
        "reffie.hubspot.writeback.sync_stage_to_hubspot",
        new=AsyncMock(),
    ):
        yield


async def test_upsert_existing_item_updates_fields(mock_session: AsyncMock) -> None:
    account = make_account()
    item = make_checklist_item(account.id)

    account_result = MagicMock()
    account_result.scalar_one_or_none.return_value = account
    item_result = MagicMock()
    item_result.scalar_one_or_none.return_value = item
    mock_session.execute.side_effect = [account_result, item_result]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/accounts/{account.id}/checklist/{item.step_id}",
            json={"done": True, "note": "Confirmed"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["done"] is True
    assert body["note"] == "Confirmed"
    assert body["step_id"] == item.step_id


async def test_upsert_creates_item_when_missing(mock_session: AsyncMock) -> None:
    account = make_account()
    step_id = "pre-kick-off__confirm"

    account_result = MagicMock()
    account_result.scalar_one_or_none.return_value = account
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    mock_session.execute.side_effect = [account_result, empty_result]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/accounts/{account.id}/checklist/{step_id}",
            json={"done": True},
        )

    assert response.status_code == 200
    assert response.json()["step_id"] == step_id
    assert response.json()["done"] is True
    mock_session.add.assert_called_once()


async def test_upsert_account_not_found(mock_session: AsyncMock) -> None:
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = not_found

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/accounts/{uuid.uuid4()}/checklist/some-step",
            json={"done": True},
        )

    assert response.status_code == 404


async def test_upsert_sets_first_touched_at(mock_session: AsyncMock) -> None:
    account = make_account()
    item = make_checklist_item(account.id)
    touched = datetime.now(UTC)

    account_result = MagicMock()
    account_result.scalar_one_or_none.return_value = account
    item_result = MagicMock()
    item_result.scalar_one_or_none.return_value = item
    mock_session.execute.side_effect = [account_result, item_result]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/accounts/{account.id}/checklist/{item.step_id}",
            json={"first_touched_at": touched.isoformat()},
        )

    assert response.status_code == 200
    assert response.json()["first_touched_at"] is not None
