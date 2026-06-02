"""
Tests for the HubSpot webhook receiver (HTTP endpoint) and the
process_closed_won background task.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from reffie.config import settings as _settings
from reffie.hubspot.auto_create import process_closed_won
from reffie.hubspot.client import HubSpotAPIError
from reffie.main import app
from reffie.models import Account

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105
_DEAL_ID = "deal-9001"
_CLOSED_WON_STAGE = "closedwon"
_WEBHOOK_URL = "http://test/hubspot/webhook"


def _sign(method: str, url: str, body: str) -> str:
    """Compute the expected HMAC-SHA256 signature for a test request."""
    payload = (_WEBHOOK_SECRET + method + url + body).encode()
    return hashlib.sha256(payload).hexdigest()


def _make_event(
    subscription_type: str = "deal.propertyChange",
    property_name: str | None = "dealstage",
    property_value: str | None = _CLOSED_WON_STAGE,
    object_id: int = 9001,
) -> dict[str, object]:
    return {
        "eventId": 1,
        "subscriptionType": subscription_type,
        "objectId": object_id,
        "propertyName": property_name,
        "propertyValue": property_value,
    }


def _make_account(deal_id: str = _DEAL_ID) -> Account:
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id=deal_id,
        company_name="Test Co",
        location="Austin, TX",
        property_type="SFR",
        cs_rep="Alice",
        onboarding_stage="Pre-kick off",
        tech_stack={},
        skipped_stages=[],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


def _patch_db(account: Account | None) -> mock._patch:  # type: ignore[type-arg]
    """Patch AsyncSessionLocal to yield a session with a single execute result."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = account
    mock_session.execute = AsyncMock(return_value=execute_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock.patch("reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session))


# ---------------------------------------------------------------------------
# Webhook endpoint tests
# ---------------------------------------------------------------------------


async def test_webhook_invalid_signature_returns_401() -> None:
    body = json.dumps([_make_event()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={"content-type": "application/json", "x-hubspot-signature-v3": "bad-sig"},
        )
    assert response.status_code == 401


async def test_webhook_missing_signature_returns_401() -> None:
    body = json.dumps([_make_event()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 401


async def test_webhook_irrelevant_event_no_task_scheduled() -> None:
    body = json.dumps([_make_event(subscription_type="contact.creation")])
    sig = _sign("POST", _WEBHOOK_URL, body)
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers={"content-type": "application/json", "x-hubspot-signature-v3": sig},
            )
    assert response.status_code == 200
    mock_process.assert_not_called()


async def test_webhook_non_closed_won_stage_no_task_scheduled() -> None:
    body = json.dumps([_make_event(property_value="appointmentscheduled")])
    sig = _sign("POST", _WEBHOOK_URL, body)
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers={"content-type": "application/json", "x-hubspot-signature-v3": sig},
            )
    assert response.status_code == 200
    mock_process.assert_not_called()


async def test_webhook_closed_won_schedules_task() -> None:
    body = json.dumps([_make_event(property_value=_CLOSED_WON_STAGE, object_id=9001)])
    sig = _sign("POST", _WEBHOOK_URL, body)
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers={"content-type": "application/json", "x-hubspot-signature-v3": sig},
            )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_process.assert_called_once_with("9001", _settings)


# ---------------------------------------------------------------------------
# process_closed_won unit tests
# ---------------------------------------------------------------------------


async def test_process_account_already_exists_is_noop() -> None:
    existing = _make_account()
    mock_stage = AsyncMock()
    with (
        _patch_db(existing),
        mock.patch("reffie.hubspot.client.get_deal_stage", mock_stage),
    ):
        await process_closed_won(_DEAL_ID, _settings)
    mock_stage.assert_not_called()


async def test_process_deal_no_longer_closed_won() -> None:
    mock_pull = AsyncMock()
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(return_value="dealstage_other"),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", mock_pull),
    ):
        await process_closed_won(_DEAL_ID, _settings)
    mock_pull.assert_not_called()


async def test_process_no_quotes_skips_creation() -> None:
    mock_pull = AsyncMock()
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(return_value=_CLOSED_WON_STAGE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=[]),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", mock_pull),
    ):
        await process_closed_won(_DEAL_ID, _settings)
    mock_pull.assert_not_called()


async def test_process_no_matching_product_skips_creation() -> None:
    mock_pull = AsyncMock()
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(return_value=_CLOSED_WON_STAGE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=["quote-1"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_quote_line_items",
            new=AsyncMock(
                return_value=[
                    {"id": "1", "name": "Basic", "sku": "BASIC", "quantity": "1", "price": "99"}
                ]
            ),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", mock_pull),
    ):
        await process_closed_won(_DEAL_ID, _settings)
    mock_pull.assert_not_called()


async def test_process_pro_product_creates_account() -> None:
    account = _make_account()
    mock_writeback = AsyncMock()
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(return_value=_CLOSED_WON_STAGE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=["quote-1"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_quote_line_items",
            new=AsyncMock(
                return_value=[
                    {"id": "1", "name": "Pro", "sku": "PRO", "quantity": "1", "price": "500"}
                ]
            ),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", new=AsyncMock(return_value=account)),
        mock.patch("reffie.hubspot.writeback.sync_stage_to_hubspot", mock_writeback),
    ):
        await process_closed_won(_DEAL_ID, _settings)

    assert account.onboarding_stage == "Pre-kick off"
    mock_writeback.assert_called_once_with(account.id, _settings)


async def test_process_pro_wins_when_multiple_products() -> None:
    account = _make_account()
    mock_writeback = AsyncMock()
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(return_value=_CLOSED_WON_STAGE),
        ),
        mock.patch(
            "reffie.hubspot.client.get_deal_quote_ids",
            new=AsyncMock(return_value=["quote-1"]),
        ),
        mock.patch(
            "reffie.hubspot.client.get_quote_line_items",
            new=AsyncMock(
                return_value=[
                    {"id": "1", "name": "Pro", "sku": "PRO", "quantity": "1", "price": "500"},
                    {"id": "2", "name": "Add-on", "sku": "ADDON", "quantity": "1", "price": "50"},
                ]
            ),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", new=AsyncMock(return_value=account)),
        mock.patch("reffie.hubspot.writeback.sync_stage_to_hubspot", mock_writeback),
    ):
        await process_closed_won(_DEAL_ID, _settings)

    assert account.onboarding_stage == "Pre-kick off"
    mock_writeback.assert_called_once()


async def test_process_hubspot_error_does_not_raise() -> None:
    with (
        _patch_db(None),
        mock.patch(
            "reffie.hubspot.client.get_deal_stage",
            new=AsyncMock(side_effect=HubSpotAPIError("500 error")),
        ),
    ):
        await process_closed_won(_DEAL_ID, _settings)
    # If we reach here without raising, the test passes.
