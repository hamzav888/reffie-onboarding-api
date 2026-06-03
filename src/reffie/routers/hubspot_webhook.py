"""
HubSpot webhook receiver.

Authentication supports all three HubSpot signature versions (V1, V2, V3) and
dispatches by which headers are present. The route returns 200 immediately;
all side effects run as background tasks.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import reffie.hubspot.auto_create as auto_create_module
from reffie.config import Settings, get_settings
from reffie.schemas.hubspot_webhook import HubSpotWebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hubspot", tags=["hubspot"])


async def _verify_hubspot_signature(request: Request, settings: Settings) -> None:
    """Verify a HubSpot webhook signature. Supports V1, V2, and V3.

    Dispatches by which headers are present. V3 is preferred when available
    (includes replay protection).

    :param request: The incoming FastAPI request.
    :param settings: Application settings (must contain hubspot_webhook_secret).
    :raises HTTPException: 503 if secret is unconfigured; 401 on any signature failure.
    """
    secret = settings.hubspot_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    raw_body = await request.body()
    body_text = raw_body.decode("utf-8")
    method = request.method.upper()
    uri = str(request.url)

    sig_v3 = request.headers.get("X-HubSpot-Signature-V3")
    timestamp_header = request.headers.get("X-HubSpot-Request-Timestamp")
    if sig_v3 and timestamp_header:
        try:
            ts_ms = int(timestamp_header)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid timestamp") from exc
        if abs(time.time() * 1000 - ts_ms) > 5 * 60 * 1000:
            raise HTTPException(status_code=401, detail="Webhook timestamp too old")
        message = f"{method}{uri}{body_text}{timestamp_header}".encode()
        computed = base64.b64encode(
            hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
        ).decode("utf-8")
        if not hmac.compare_digest(computed, sig_v3):
            raise HTTPException(status_code=401, detail="Invalid V3 signature")
        return

    sig_legacy = request.headers.get("X-HubSpot-Signature")
    version_header = request.headers.get("X-HubSpot-Signature-Version", "v1")
    if sig_legacy:
        if version_header == "v2":
            message_str = f"{secret}{method}{uri}{body_text}"
        else:
            message_str = f"{secret}{body_text}"
        computed_hex = hashlib.sha256(message_str.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(computed_hex, sig_legacy):
            raise HTTPException(status_code=401, detail=f"Invalid {version_header} signature")
        return

    raise HTTPException(status_code=401, detail="Missing signature header")


@router.post("/webhook")
async def hubspot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """
    Receive HubSpot webhook events and dispatch background processing tasks.

    Verifies the HubSpot signature (V1/V2/V3) before processing. Returns 200
    immediately after scheduling side effects — HubSpot requires a fast
    response and retries on timeouts.

    :param request: Raw FastAPI request (needed for body bytes and headers).
    :param background_tasks: FastAPI background task queue.
    :param settings: Application settings providing webhook credentials.
    :returns: ``{"status": "ok"}`` on success.
    :raises HTTPException: 503 if the webhook secret is not configured.
    :raises HTTPException: 401 if the signature is missing or invalid.
    """
    await _verify_hubspot_signature(request, settings)

    raw_body = await request.body()
    events_raw: list[Any] = json.loads(raw_body)
    events = [HubSpotWebhookEvent.model_validate(e) for e in events_raw]

    logger.warning(
        "Webhook events count=%d closed_won_ids=%s",
        len(events),
        settings.hubspot_closed_won_stage_ids,
    )
    for event in events:
        logger.warning(
            "event subscription=%s property=%s value=%s",
            event.subscription_type,
            event.property_name,
            event.property_value,
        )
        if (
            event.subscription_type == "deal.propertyChange"
            and event.property_name == "dealstage"
            and event.property_value in settings.hubspot_closed_won_stage_ids
        ):
            background_tasks.add_task(
                auto_create_module.process_closed_won,
                str(event.object_id),
                settings,
            )
        else:
            logger.warning(
                "event skipped subscription=%s property=%s value=%s closed_won_ids=%s",
                event.subscription_type,
                event.property_name,
                event.property_value,
                settings.hubspot_closed_won_stage_ids,
            )

    return {"status": "ok"}
