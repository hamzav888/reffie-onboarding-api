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
from reffie.hubspot.client import HubSpotAPIError, HubSpotNotFoundError
from reffie.main import app
from reffie.models import Account, Poc

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DEAL_ID = "hs-deal-001"

_DEAL_RESPONSE: dict[str, object] = {
    "id": _DEAL_ID,
    "properties": {
        "hs_object_id": _DEAL_ID,
        "dealname": "Acme Corp",
        "onboarding_cs_rep": "Alice",
        "onboarding_stage": "kick-off",
        "kickoff_call_date": "2026-07-01",
        "amount": "120000",
        "contract_length": "12 months",
        "success_metrics": "Reduce vacancy to 5%",
        "property_type": "multifamily",
        "city": "New York",
        "state": "NY",
    },
}

_CONTACT_RESPONSE: dict[str, object] = {
    "id": "contact-1",
    "properties": {
        "firstname": "Jane",
        "lastname": "Doe",
        "email": "jane@acme.com",
        "phone": "555-0101",
        "jobtitle": "CEO",
    },
}


def make_synced_account() -> Account:
    """Transient Account that looks as though it was previously synced from HubSpot."""
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id=_DEAL_ID,
        company_name="Old Name",
        location="Chicago, IL",
        property_type="commercial",
        cs_rep="Bob",
        onboarding_stage="pre-kick-off",
        tech_stack={},
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


def make_loaded_account() -> Account:
    """
    Transient Account with pocs populated — simulates what the final selectinload returns.
    """
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id=_DEAL_ID,
        company_name="Acme Corp",
        location="New York, NY",
        property_type="multifamily",
        cs_rep="Alice",
        onboarding_stage="Pre-kick off",
        tech_stack={},
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    poc = Poc(
        id=uuid.uuid4(),
        account_id=account.id,
        name="Jane Doe",
        email="jane@acme.com",
        phone="555-0101",
        role="CEO",
    )
    account.pocs = [poc]
    account.checklist_items = []
    return account


@pytest.fixture
def mock_session() -> AsyncMock:
    """Async mock satisfying the AsyncSession interface used by pull_deal."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
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
# Helpers to configure mock session execute call sequence
# ---------------------------------------------------------------------------


def _setup_new_account_session(mock_session: AsyncMock, loaded_account: Account) -> None:
    """Configure mock_session for the create path (no existing account)."""
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None

    delete_result = MagicMock()

    final = MagicMock()
    final.scalar_one.return_value = loaded_account

    mock_session.execute.side_effect = [no_existing, delete_result, final]


def _setup_existing_account_session(
    mock_session: AsyncMock, existing_account: Account, loaded_account: Account
) -> None:
    """Configure mock_session for the update path (account already exists)."""
    found_existing = MagicMock()
    found_existing.scalar_one_or_none.return_value = existing_account

    delete_result = MagicMock()

    final = MagicMock()
    final.scalar_one.return_value = loaded_account

    mock_session.execute.side_effect = [found_existing, delete_result, final]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_sync_creates_new_account(mock_session: AsyncMock) -> None:
    loaded = make_loaded_account()
    _setup_new_account_session(mock_session, loaded)

    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_contact_ids",
            new=AsyncMock(return_value=["contact-1"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_contact_properties",
            new=AsyncMock(return_value=_CONTACT_RESPONSE),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "Acme Corp"
    assert body["cs_rep"] == "Alice"
    # New accounts start at the first platform stage — HubSpot does not own onboarding_stage.
    assert body["onboarding_stage"] == "Pre-kick off"
    assert body["location"] == "New York, NY"
    mock_session.add.assert_called_once()


async def test_sync_updates_existing_account(mock_session: AsyncMock) -> None:
    existing = make_synced_account()
    # Final SELECT returns account with the existing stage preserved — sync must not overwrite it.
    loaded = Account(
        id=existing.id,
        hubspot_deal_id=_DEAL_ID,
        company_name="Acme Corp",
        location="New York, NY",
        property_type="multifamily",
        cs_rep="Alice",
        onboarding_stage="pre-kick-off",  # same as existing, not overwritten by HubSpot data
        tech_stack={},
        skipped_stages=[],
        created_at=existing.created_at,
        updated_at=existing.updated_at,
    )
    loaded.pocs = []
    loaded.checklist_items = []
    _setup_existing_account_session(mock_session, existing, loaded)

    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_contact_ids",
            new=AsyncMock(return_value=[]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_contact_properties",
            new=AsyncMock(return_value=_CONTACT_RESPONSE),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    # Account fields were overwritten from HubSpot data
    assert response.json()["company_name"] == "Acme Corp"
    assert response.json()["cs_rep"] == "Alice"
    # onboarding_stage must NOT be overwritten — the platform owns it
    assert response.json()["onboarding_stage"] == "pre-kick-off"
    # add() was NOT called because the account already existed
    mock_session.add.assert_not_called()


async def test_sync_deal_not_found_returns_404(mock_session: AsyncMock) -> None:
    with mock.patch(
        "reffie.hubspot.client.get_deal_properties",
        new=AsyncMock(side_effect=HubSpotNotFoundError(f"deal {_DEAL_ID} not found")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    # No DB access should have happened
    mock_session.execute.assert_not_called()


async def test_sync_hubspot_api_error_returns_502(mock_session: AsyncMock) -> None:
    with mock.patch(
        "reffie.hubspot.client.get_deal_properties",
        new=AsyncMock(side_effect=HubSpotAPIError("HubSpot API error 500")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 502


async def test_sync_contacts_mapped_to_pocs(mock_session: AsyncMock) -> None:
    contact_2: dict[str, object] = {
        "id": "contact-2",
        "properties": {
            "firstname": "John",
            "lastname": "Smith",
            "email": "john@acme.com",
            "phone": None,
            "jobtitle": "CFO",
        },
    }

    loaded = make_loaded_account()
    # Simulate two pocs on the loaded account
    poc2 = Poc(
        id=uuid.uuid4(),
        account_id=loaded.id,
        name="John Smith",
        email="john@acme.com",
        phone=None,
        role="CFO",
    )
    loaded.pocs = [*loaded.pocs, poc2]
    _setup_new_account_session(mock_session, loaded)

    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_contact_ids",
            new=AsyncMock(return_value=["contact-1", "contact-2"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_contact_properties",
            new=AsyncMock(side_effect=[_CONTACT_RESPONSE, contact_2]),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    pocs = response.json()["pocs"]
    assert len(pocs) == 2
    names = {p["name"] for p in pocs}
    assert names == {"Jane Doe", "John Smith"}
    roles = {p["role"] for p in pocs}
    assert roles == {"CEO", "CFO"}
    # Second contact has no phone — must be None, not empty string
    john = next(p for p in pocs if p["name"] == "John Smith")
    assert john["phone"] is None
