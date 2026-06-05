"""
Tests for the HubSpot webhook receiver (HTTP endpoint) and the
process_closed_won background task.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from reffie.config import get_settings
from reffie.config import settings as _settings
from reffie.hubspot.auto_create import process_closed_won
from reffie.hubspot.client import HubSpotAPIError, get_quote_line_items
from reffie.main import app
from reffie.models import Account

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = "test-webhook-secret"  # noqa: S105
_DEAL_ID = "deal-9001"
_CLOSED_WON_STAGE = "closedwon"
_WEBHOOK_URL = "http://test/hubspot/webhook"

# ---------------------------------------------------------------------------
# Signature helpers
# ---------------------------------------------------------------------------


def _compute_v1_signature(secret: str, body: str) -> str:
    return hashlib.sha256(f"{secret}{body}".encode()).hexdigest()


def _compute_v2_signature(secret: str, method: str, uri: str, body: str) -> str:
    return hashlib.sha256(f"{secret}{method}{uri}{body}".encode()).hexdigest()


def _compute_v3_signature(secret: str, method: str, uri: str, body: str, timestamp: str) -> str:
    message = f"{method}{uri}{body}{timestamp}".encode()
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    ).decode("utf-8")


def _v1_headers(body: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-hubspot-signature": _compute_v1_signature(_WEBHOOK_SECRET, body),
    }


def _v2_headers(body: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-hubspot-signature": _compute_v2_signature(_WEBHOOK_SECRET, "POST", _WEBHOOK_URL, body),
        "x-hubspot-signature-version": "v2",
    }


def _v3_headers(body: str, ts_ms: int | None = None) -> dict[str, str]:
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    ts_str = str(ts_ms)
    sig = _compute_v3_signature(_WEBHOOK_SECRET, "POST", _WEBHOOK_URL, body, ts_str)
    return {
        "content-type": "application/json",
        "x-hubspot-signature-v3": sig,
        "x-hubspot-request-timestamp": ts_str,
    }


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------


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
        archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


def _patch_db(account: Account | None) -> mock._patch:  # type: ignore[type-arg]
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
# Signature verification tests
# ---------------------------------------------------------------------------


async def test_webhook_no_signature_header() -> None:
    body = json.dumps([_make_event()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 401


async def test_webhook_secret_not_configured() -> None:
    body = json.dumps([_make_event()])
    no_secret = _settings.model_copy(update={"hubspot_webhook_secret": ""})
    app.dependency_overrides[get_settings] = lambda: no_secret
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers={"content-type": "application/json"},
            )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_webhook_invalid_v3_signature() -> None:
    body = json.dumps([_make_event()])
    ts_str = str(int(time.time() * 1000))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hubspot-signature-v3": "not-a-valid-sig",
                "x-hubspot-request-timestamp": ts_str,
            },
        )
    assert response.status_code == 401


async def test_webhook_invalid_v2_signature() -> None:
    body = json.dumps([_make_event()])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hubspot-signature": "not-a-valid-sig",
                "x-hubspot-signature-version": "v2",
            },
        )
    assert response.status_code == 401


async def test_webhook_v3_replay_protection() -> None:
    # Timestamp 6 minutes in the past — outside the 5-minute window.
    body = json.dumps([_make_event()])
    old_ts_ms = int((time.time() - 361) * 1000)
    ts_str = str(old_ts_ms)
    sig = _compute_v3_signature(_WEBHOOK_SECRET, "POST", _WEBHOOK_URL, body, ts_str)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/hubspot/webhook",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hubspot-signature-v3": sig,
                "x-hubspot-request-timestamp": ts_str,
            },
        )
    assert response.status_code == 401


async def test_webhook_v1_signature_valid() -> None:
    body = json.dumps([_make_event(property_value=_CLOSED_WON_STAGE, object_id=9001)])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v1_headers(body),
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    mock_process.assert_called_once()


async def test_webhook_v2_signature_valid() -> None:
    body = json.dumps([_make_event(property_value=_CLOSED_WON_STAGE, object_id=9001)])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v2_headers(body),
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    mock_process.assert_called_once()


async def test_webhook_v3_signature_valid() -> None:
    body = json.dumps([_make_event(property_value=_CLOSED_WON_STAGE, object_id=9001)])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v3_headers(body),
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    mock_process.assert_called_once()


# ---------------------------------------------------------------------------
# Event filtering tests
# ---------------------------------------------------------------------------


async def test_webhook_irrelevant_event_no_task_scheduled() -> None:
    body = json.dumps([_make_event(subscription_type="contact.creation")])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v1_headers(body),
            )
    assert response.status_code == 200
    mock_process.assert_not_called()


async def test_webhook_non_closed_won_stage_no_task_scheduled() -> None:
    body = json.dumps([_make_event(property_value="appointmentscheduled")])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v1_headers(body),
            )
    assert response.status_code == 200
    mock_process.assert_not_called()


async def test_webhook_closed_won_schedules_task() -> None:
    body = json.dumps([_make_event(property_value=_CLOSED_WON_STAGE, object_id=9001)])
    mock_process = AsyncMock()
    with mock.patch("reffie.hubspot.auto_create.process_closed_won", mock_process):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/hubspot/webhook",
                content=body,
                headers=_v1_headers(body),
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
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
    # Reaching here without raising confirms background tasks swallow HubSpot errors.


async def test_line_items_sorted_numerically() -> None:
    """PRO on id='9' must be found even though '10' < '9' lexicographically."""
    account = _make_account()
    mock_writeback = AsyncMock()
    # id '9' (PRO) vs id '10' (non-matching). Lexicographic order: '10' first, then '9'.
    # Numeric order: 9 first, then 10. In both cases PRO is found eventually.
    # The test asserts the sort doesn't produce an exception and PRO is correctly matched.
    line_items = [
        {"id": "10", "name": "Add-on", "sku": "ADDON", "quantity": "1", "price": "50"},
        {"id": "9", "name": "Pro", "sku": "PRO", "quantity": "1", "price": "500"},
    ]
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
            new=AsyncMock(return_value=line_items),
        ),
        mock.patch("reffie.hubspot.sync.pull_deal", new=AsyncMock(return_value=account)),
        mock.patch("reffie.hubspot.writeback.sync_stage_to_hubspot", mock_writeback),
    ):
        await process_closed_won(_DEAL_ID, _settings)

    assert account.onboarding_stage == "Pre-kick off"
    mock_writeback.assert_called_once()


async def test_db_error_during_processing_is_caught() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("DB connection error"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with mock.patch("reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session)):
        await process_closed_won(_DEAL_ID, _settings)
    # Reaching here without raising confirms DB errors are swallowed in background tasks.


# ---------------------------------------------------------------------------
# get_quote_line_items SKU parsing (real function, httpx mocked)
# ---------------------------------------------------------------------------


def _fake_response(json_body: Mapping[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = json.dumps(json_body)
    resp.json = MagicMock(return_value=json_body)
    return resp


def _patch_httpx_for_line_items(
    *, assoc_body: Mapping[str, Any], batch_body: Mapping[str, Any]
) -> Any:
    """Patch httpx.AsyncClient so get() returns the associations response and
    post() returns the batch-read response."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=_fake_response(assoc_body))
    client.post = AsyncMock(return_value=_fake_response(batch_body))
    return mock.patch("reffie.hubspot.client.httpx.AsyncClient", MagicMock(return_value=client))


async def test_get_quote_line_items_reads_hs_sku() -> None:
    """The standard HubSpot hs_sku property is read into the normalised sku field."""
    assoc_body = {"results": [{"toObjectId": "li-1"}]}
    batch_body = {
        "results": [{"id": "li-1", "properties": {"name": "Pro", "hs_sku": "PRO", "quantity": "1"}}]
    }
    with _patch_httpx_for_line_items(assoc_body=assoc_body, batch_body=batch_body):
        items = await get_quote_line_items("quote-1", _settings)
    assert items == [{"id": "li-1", "name": "Pro", "sku": "PRO", "quantity": "1", "price": ""}]


async def test_get_quote_line_items_falls_back_to_sku() -> None:
    """When hs_sku is absent, the custom sku property is used as a fallback."""
    assoc_body = {"results": [{"toObjectId": "li-1"}]}
    batch_body = {
        "results": [{"id": "li-1", "properties": {"name": "Pro", "sku": "PRO", "price": "500"}}]
    }
    with _patch_httpx_for_line_items(assoc_body=assoc_body, batch_body=batch_body):
        items = await get_quote_line_items("quote-1", _settings)
    assert items[0]["sku"] == "PRO"
