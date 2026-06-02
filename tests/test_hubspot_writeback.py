import uuid
from datetime import UTC, datetime
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from reffie.config import settings as _settings
from reffie.hubspot.client import HubSpotAPIError
from reffie.hubspot.writeback import sync_stage_to_hubspot
from reffie.models import Account, ChecklistItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEAL_ID = "hs-deal-123"


def _make_account(
    onboarding_stage: str,
    hubspot_deal_id: str | None = _DEAL_ID,
    checklist_items: list[ChecklistItem] | None = None,
) -> Account:
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id=hubspot_deal_id,
        company_name="Test Co",
        location="Austin, TX",
        property_type="multifamily",
        cs_rep="Alice",
        onboarding_stage=onboarding_stage,
        tech_stack={},
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.checklist_items = checklist_items if checklist_items is not None else []
    return account


def _make_item(step_id: str, *, done: bool) -> ChecklistItem:
    return ChecklistItem(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        step_id=step_id,
        done=done,
        note="",
    )


def _patch_db(account: Account | None) -> mock._patch:  # type: ignore[type-arg]
    """Return a patch for AsyncSessionLocal that loads `account` from the mock session."""
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


async def test_no_deal_id_skips_writeback() -> None:
    account = _make_account("Pre-kick off", hubspot_deal_id=None)
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    mock_update.assert_not_called()


async def test_pre_kick_off_pending() -> None:
    account = _make_account("Pre-kick off")
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    mock_update.assert_called_once()
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Kick-Off Pending"}


async def test_pre_kick_off_schedule_done() -> None:
    account = _make_account(
        "Pre-kick off",
        checklist_items=[_make_item("pre-kick-off__schedule-kickoff", done=True)],
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Kick-Off Scheduled"}


async def test_validation_call_training_pending() -> None:
    # Kick-off stage is past (stage_idx 2 > 1), no training schedule step done → Training Pending
    account = _make_account("Validation call")
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Training Pending"}


async def test_kick_off_call_schedule_training_done() -> None:
    account = _make_account(
        "Kick-off call",
        checklist_items=[_make_item("kick-off-call__schedule-training", done=True)],
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Training Scheduled"}


async def test_validation_call_schedule_training_done() -> None:
    account = _make_account(
        "Validation call",
        checklist_items=[_make_item("validation-call__schedule-training", done=True)],
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Training Scheduled"}


async def test_check_in_pending() -> None:
    # Training stage is past (stage_idx 6 > 3), no schedule-checkin done → Check-in Pending
    account = _make_account("30-day check-in")
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Check-in Pending"}


async def test_training_call_schedule_checkin_done() -> None:
    account = _make_account(
        "Training call",
        checklist_items=[_make_item("training-call__schedule-checkin", done=True)],
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props == {"onboarding_stage": "Check-In Scheduled"}


async def test_sixty_day_complete() -> None:
    account = _make_account(
        "60-day check-in",
        checklist_items=[
            _make_item("60-day-check-in__item1", done=True),
            _make_item("60-day-check-in__item2", done=True),
        ],
    )
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    expected_date = datetime.now(UTC).date().isoformat()
    assert called_props["onboarding_stage"] == "Onboarding Complete"
    assert called_props["onboarding_complete_date"] == expected_date


async def test_sixty_day_no_items_not_complete() -> None:
    # No 60-day-check-in__* items → sixty_day_complete is False → falls through to Check-in Pending
    account = _make_account("60-day check-in", checklist_items=[])
    mock_update = AsyncMock()
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    _, called_props, _ = mock_update.call_args[0]
    assert called_props["onboarding_stage"] != "Onboarding Complete"
    assert called_props == {"onboarding_stage": "Check-in Pending"}


async def test_hubspot_api_error_does_not_raise() -> None:
    account = _make_account("Pre-kick off")
    mock_update = AsyncMock(side_effect=HubSpotAPIError("HubSpot 500"))
    with (
        _patch_db(account),
        mock.patch("reffie.hubspot.client.update_deal_properties", mock_update),
    ):
        await sync_stage_to_hubspot(account.id, _settings)
    mock_update.assert_called_once()
