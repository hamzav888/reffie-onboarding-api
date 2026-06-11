import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import reffie.hubspot.sync as sync_module
from reffie.auth import CurrentUser, get_current_user
from reffie.config import settings as _settings
from reffie.db.session import get_db_session
from reffie.hubspot.client import HubSpotAPIError, HubSpotNotFoundError

# Bound to the real function before the autouse stub patches the module attribute,
# so the aggregation tests below exercise the real implementation.
from reffie.hubspot.client import get_deal_line_items as real_get_deal_line_items
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

# HubSpot Company properties used in company-fetch tests.
_COMPANY_PROPS: dict[str, str | None] = {
    "pms_system": "Entrata",
    "tour_scheduling_platform": "Showing Suite",
    "uses_lockboxes": "false",
    "onboarding_cs_rep": None,  # not set at company level unless overridden in a specific test
    "applications_platform": "ResidentCheck",
    "zillow_tier": "Paid",
    "facebook_marketplace": "true",
    "shared_leasing_email": "false",
    "state": "California",
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
        archived=False,
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
        archived=False,
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


@pytest.fixture(autouse=True)
def stub_deal_line_items() -> Generator[AsyncMock]:
    """pull_deal fetches line items for the contract-length override; stub to empty by default."""
    with mock.patch(
        "reffie.hubspot.client.get_deal_line_items", new=AsyncMock(return_value=[])
    ) as m:
        yield m


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
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
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
    mock_session.add.assert_called_once()
    # No associated company → location defaults to "Unknown" (no longer deal-derived).
    created = mock_session.add.call_args.args[0]
    assert created.location == "Unknown"


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
        archived=False,
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
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
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
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
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


async def test_sync_pulls_company_and_sets_tech_stack(mock_session: AsyncMock) -> None:
    loaded = make_loaded_account()
    # Pre-set the expected post-sync state that the DB would return.
    loaded.hubspot_company_id = "company-1"
    loaded.tech_stack = {
        "pms": "Entrata",
        "tour": "Showing Suite",
        "lockboxes": False,
        "applications": "ResidentCheck",
        "zillow": "Paid",
        "facebook": True,
        "sharedEmail": False,
    }
    _setup_new_account_session(mock_session, loaded)

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
            new=AsyncMock(),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value="company-1"),
        ),
        mock.patch(
            "reffie.hubspot.client.get_company_properties",
            new=AsyncMock(return_value=_COMPANY_PROPS),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["hubspot_company_id"] == "company-1"
    assert body["tech_stack"]["pms"] == "Entrata"
    assert body["tech_stack"]["tour"] == "Showing Suite"
    assert body["tech_stack"]["applications"] == "ResidentCheck"
    assert body["tech_stack"]["zillow"] == "Paid"
    # location is sourced from the company's state property.
    created = mock_session.add.call_args.args[0]
    assert created.location == "California"


async def test_sync_no_company_defaults_tech_stack(mock_session: AsyncMock) -> None:
    loaded = make_loaded_account()
    # hubspot_company_id defaults to None; tech_stack defaults to {}.
    _setup_new_account_session(mock_session, loaded)

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
            new=AsyncMock(),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["hubspot_company_id"] is None
    assert body["tech_stack"] == {}
    # No company → no company state → location defaults to "Unknown".
    created = mock_session.add.call_args.args[0]
    assert created.location == "Unknown"


async def test_sync_skips_deleted_contact(mock_session: AsyncMock) -> None:
    """A 404 on one contact should be skipped; the rest of the sync should complete."""
    loaded = make_loaded_account()  # has 1 POC (Jane Doe, contact-1)
    _setup_new_account_session(mock_session, loaded)

    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_contact_ids",
            new=AsyncMock(return_value=["contact-deleted", "contact-1"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_contact_properties",
            new=AsyncMock(
                side_effect=[
                    HubSpotNotFoundError("contact contact-deleted not found"),
                    _CONTACT_RESPONSE,
                ]
            ),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    pocs = response.json()["pocs"]
    assert len(pocs) == 1
    assert pocs[0]["name"] == "Jane Doe"


async def test_sync_company_bool_fields_converted(mock_session: AsyncMock) -> None:
    """HubSpot 'true'/'false' strings must become Python bools in tech_stack."""
    loaded = make_loaded_account()
    loaded.hubspot_company_id = "company-2"
    loaded.tech_stack = {
        "pms": "",
        "tour": "",
        "lockboxes": True,
        "applications": "",
        "zillow": "",
        "facebook": True,
        "sharedEmail": False,
    }
    _setup_new_account_session(mock_session, loaded)

    bool_props: dict[str, str | None] = {
        "pms_system": None,
        "tour_scheduling_platform": None,
        "uses_lockboxes": "true",
        "applications_platform": None,
        "zillow_tier": None,
        "facebook_marketplace": "true",
        "shared_leasing_email": "false",
        "state": "Texas",
    }

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
            new=AsyncMock(),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value="company-2"),
        ),
        mock.patch(
            "reffie.hubspot.client.get_company_properties",
            new=AsyncMock(return_value=bool_props),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/hubspot/sync/{_DEAL_ID}")

    assert response.status_code == 200
    ts = response.json()["tech_stack"]
    assert ts["lockboxes"] is True
    assert ts["facebook"] is True
    assert ts["sharedEmail"] is False


async def test_sync_company_no_state_location_unknown(mock_session: AsyncMock) -> None:
    """A company with no ``state`` property must leave location as ``"Unknown"``."""
    _setup_new_account_session(mock_session, make_loaded_account())
    props_no_state: dict[str, str | None] = {**_COMPANY_PROPS, "state": None}

    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_contact_properties", new=AsyncMock()),
        mock.patch(
            "reffie.hubspot.client.get_deal_company_id",
            new=AsyncMock(return_value="company-3"),
        ),
        mock.patch(
            "reffie.hubspot.client.get_company_properties",
            new=AsyncMock(return_value=props_no_state),
        ),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)

    created = mock_session.add.call_args.args[0]
    assert created.location == "Unknown"


# ---------------------------------------------------------------------------
# Money-back-guarantee contract_length override
# ---------------------------------------------------------------------------


async def test_sync_money_back_overrides_contract_length(
    mock_session: AsyncMock, stub_deal_line_items: AsyncMock
) -> None:
    """A money-back line item forces contract_length, overriding the deal field."""
    _setup_new_account_session(mock_session, make_loaded_account())
    stub_deal_line_items.return_value = [
        {
            "id": "1",
            "name": "6-Month Money-Back Guarantee",
            "sku": "",
            "quantity": "1",
            "price": "0",
        }
    ]
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_deal_company_id", new=AsyncMock(return_value=None)),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)

    created = mock_session.add.call_args.args[0]
    # _DEAL_RESPONSE carries contract_length "12 months"; the override must win.
    assert created.contract_length == "6 months"


async def test_sync_no_money_back_keeps_deal_contract_length(mock_session: AsyncMock) -> None:
    """Without a money-back line item, the deal-level contract_length is preserved."""
    _setup_new_account_session(mock_session, make_loaded_account())
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_deal_company_id", new=AsyncMock(return_value=None)),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)

    created = mock_session.add.call_args.args[0]
    assert created.contract_length == "12 months"


def test_has_money_back_guarantee_matches_case_insensitive() -> None:
    items = [{"name": "6-Month Money-Back Guarantee"}]
    assert sync_module.has_money_back_guarantee(items) is True


def test_has_money_back_guarantee_false_for_other_products() -> None:
    items = [{"name": "Pro"}, {"name": "Add-on"}]
    assert sync_module.has_money_back_guarantee(items) is False


def test_has_money_back_guarantee_safe_on_missing_name() -> None:
    items: list[dict[str, Any]] = [{"sku": "PRO"}, {"name": None}, {}]
    assert sync_module.has_money_back_guarantee(items) is False


async def test_get_deal_line_items_aggregates_across_quotes() -> None:
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=["q1", "q2"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_quote_line_items",
            new=AsyncMock(side_effect=[[{"id": "1", "name": "Pro"}], [{"id": "2", "name": "MB"}]]),
        ),
    ):
        items = await real_get_deal_line_items(_DEAL_ID, _settings)
    assert [i["id"] for i in items] == ["1", "2"]


async def test_get_deal_line_items_skips_failing_quote() -> None:
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=["q1", "q2"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_quote_line_items",
            new=AsyncMock(side_effect=[HubSpotAPIError("boom"), [{"id": "2", "name": "X"}]]),
        ),
    ):
        items = await real_get_deal_line_items(_DEAL_ID, _settings)
    assert [i["id"] for i in items] == ["2"]


# ---------------------------------------------------------------------------
# property_type multi-select parsing
# ---------------------------------------------------------------------------


async def _run_pull_deal_with_property_type(mock_session: AsyncMock, raw_value: str) -> Account:
    """Run pull_deal with a HubSpot property_type value; return the created account."""
    _setup_new_account_session(mock_session, make_loaded_account())
    deal = {"id": _DEAL_ID, "properties": {"hs_object_id": _DEAL_ID, "property_type": raw_value}}
    with (
        mock.patch("reffie.hubspot.client.get_deal_properties", new=AsyncMock(return_value=deal)),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_deal_company_id", new=AsyncMock(return_value=None)),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)
    created: Account = mock_session.add.call_args.args[0]
    return created


async def test_property_type_multi_select_joins_with_comma(mock_session: AsyncMock) -> None:
    created = await _run_pull_deal_with_property_type(mock_session, "SFR;Condo")
    assert created.property_type == "SFR, Condo"


async def test_property_type_single_value_no_semicolons(mock_session: AsyncMock) -> None:
    created = await _run_pull_deal_with_property_type(mock_session, "SFR")
    assert created.property_type == "SFR"


async def test_property_type_empty_stays_empty(mock_session: AsyncMock) -> None:
    created = await _run_pull_deal_with_property_type(mock_session, "")
    assert created.property_type == ""


# ---------------------------------------------------------------------------
# Company-level onboarding_cs_rep wins over deal-level value
# ---------------------------------------------------------------------------


async def test_sync_company_cs_rep_wins_over_deal(mock_session: AsyncMock) -> None:
    """Company-level onboarding_cs_rep overrides the deal-level value when non-empty."""
    _setup_new_account_session(mock_session, make_loaded_account())
    company_props_with_rep: dict[str, str | None] = {
        **_COMPANY_PROPS,
        "onboarding_cs_rep": "Carol",
    }
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_deal_company_id", new=AsyncMock(return_value="co-1")),
        mock.patch(
            "reffie.hubspot.client.get_company_properties",
            new=AsyncMock(return_value=company_props_with_rep),
        ),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)

    created: Account = mock_session.add.call_args.args[0]
    # Deal has cs_rep "Alice" (from _DEAL_RESPONSE); company has "Carol" — company wins.
    assert created.cs_rep == "Carol"


async def test_sync_deal_cs_rep_used_when_company_value_empty(mock_session: AsyncMock) -> None:
    """When company-level onboarding_cs_rep is empty/None, deal value is preserved."""
    _setup_new_account_session(mock_session, make_loaded_account())
    company_props_no_rep: dict[str, str | None] = {
        **_COMPANY_PROPS,
        "onboarding_cs_rep": None,
    }
    with (
        mock.patch(
            "reffie.hubspot.client.get_deal_properties",
            new=AsyncMock(return_value=_DEAL_RESPONSE),
        ),
        mock.patch("reffie.hubspot.client.get_deal_contact_ids", new=AsyncMock(return_value=[])),
        mock.patch("reffie.hubspot.client.get_deal_company_id", new=AsyncMock(return_value="co-1")),
        mock.patch(
            "reffie.hubspot.client.get_company_properties",
            new=AsyncMock(return_value=company_props_no_rep),
        ),
    ):
        await sync_module.pull_deal(_DEAL_ID, mock_session, _settings)

    created: Account = mock_session.add.call_args.args[0]
    # Company has no rep; deal fallback "Alice" (from _DEAL_RESPONSE) is used.
    assert created.cs_rep == "Alice"
