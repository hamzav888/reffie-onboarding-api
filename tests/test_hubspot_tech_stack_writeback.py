import uuid
from datetime import UTC, datetime
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from reffie.config import settings as _settings
from reffie.hubspot.client import HubSpotAPIError
from reffie.hubspot.writeback import sync_tech_stack_to_hubspot
from reffie.models import Account

# ---------------------------------------------------------------------------
# Helpers — mirrors test_hubspot_writeback.py conventions
# ---------------------------------------------------------------------------

_COMPANY_ID = "hs-company-123"


def _make_account(
    tech_stack: dict,  # type: ignore[type-arg]
    hubspot_company_id: str | None = _COMPANY_ID,
) -> Account:
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id="hs-deal-123",
        hubspot_company_id=hubspot_company_id,
        company_name="Test Co",
        location="Austin, TX",
        property_type="multifamily",
        cs_rep="Alice",
        onboarding_stage="Pre-kick off",
        tech_stack=tech_stack,
        skipped_stages=[],
        archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.checklist_items = []
    return account


def _patch_db(account: Account | None) -> mock._patch:  # type: ignore[type-arg]
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = account
    mock_session.execute = AsyncMock(return_value=execute_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock.patch("reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_no_company_id_skips_writeback() -> None:
    account = _make_account({"pms": "Entrata"}, hubspot_company_id=None)
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_company_properties", mock_update),
    ):
        await sync_tech_stack_to_hubspot(account.id, _settings)
    mock_update.assert_not_called()


async def test_empty_ts_to_hubspot_skips_writeback() -> None:
    # All string fields are empty → ts_to_hubspot returns {} → no write
    account = _make_account({"pms": "", "tour": "", "applications": "", "zillow": ""})
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_company_properties", mock_update),
    ):
        await sync_tech_stack_to_hubspot(account.id, _settings)
    mock_update.assert_not_called()


async def test_tech_stack_with_values_writes_correct_props() -> None:
    account = _make_account(
        {
            "pms": "Entrata",
            "tour": "Showing Suite",
            "lockboxes": True,
            "applications": "ResidentCheck",
            "zillow": "Paid",
            "facebook": False,
            "sharedEmail": True,
        }
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_company_properties", mock_update),
    ):
        await sync_tech_stack_to_hubspot(account.id, _settings)

    mock_update.assert_called_once()
    called_company_id, called_props, _ = mock_update.call_args[0]
    assert called_company_id == _COMPANY_ID
    assert called_props["pms_system"] == "Entrata"
    assert called_props["tour_scheduling_platform"] == "Showing Suite"
    assert called_props["uses_lockboxes"] == "true"
    assert called_props["applications_platform"] == "ResidentCheck"
    assert called_props["zillow_tier"] == "Paid"
    assert called_props["facebook_marketplace"] == "false"
    assert called_props["shared_leasing_email"] == "true"


async def test_hubspot_api_error_does_not_raise() -> None:
    account = _make_account({"pms": "Entrata"})
    mock_update = AsyncMock(side_effect=HubSpotAPIError("500 error"))
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_company_properties", mock_update),
    ):
        await sync_tech_stack_to_hubspot(account.id, _settings)
    mock_update.assert_called_once()
