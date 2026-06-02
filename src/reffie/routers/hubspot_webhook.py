"""
HubSpot webhook receiver.

Authentication uses HMAC-SHA256 rather than the platform's Google JWT —
HubSpot signs requests itself.  The route must return 200 quickly; all side
effects are dispatched as background tasks.
"""

import hashlib
import hmac as hmac_stdlib
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

import reffie.hubspot.auto_create as auto_create_module
from reffie.config import Settings, get_settings
from reffie.schemas.hubspot_webhook import HubSpotWebhookEvent

router = APIRouter(prefix="/hubspot", tags=["hubspot"])


def _verify_signature(secret: str, method: str, uri: str, raw_body: bytes, header_sig: str) -> bool:
    """
    Verify a HubSpot V3 webhook signature.

    HubSpot computes SHA-256 over ``client_secret + method + uri + body`` and
    sends the hex digest in ``X-HubSpot-Signature-V3``.

    :param secret: The configured ``HUBSPOT_WEBHOOK_SECRET``.
    :param method: HTTP method from the incoming request (e.g. ``"POST"``).
    :param uri: Full request URI as a string.
    :param raw_body: Raw request body bytes.
    :param header_sig: Hex-encoded signature from the request header.
    :returns: ``True`` if signatures match, ``False`` otherwise.
    """
    payload = (secret + method + uri + raw_body.decode()).encode()
    expected = hashlib.sha256(payload).hexdigest()
    return hmac_stdlib.compare_digest(expected, header_sig)


@router.post("/webhook")
async def hubspot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """
    Receive HubSpot webhook events and dispatch background processing tasks.

    Verifies the HMAC-SHA256 signature before processing. Returns 200
    immediately after scheduling side effects — HubSpot requires a fast
    response and retries on timeouts.

    :param request: Raw FastAPI request (needed for body bytes and headers).
    :param background_tasks: FastAPI background task queue.
    :param settings: Application settings providing webhook credentials.
    :returns: ``{"status": "ok"}`` on success.
    :raises HTTPException: 503 if the webhook secret is not configured.
    :raises HTTPException: 401 if the HMAC signature is missing or invalid.
    """
    if not settings.hubspot_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    raw_body = await request.body()
    sig = request.headers.get("x-hubspot-signature-v3", "")

    if not sig or not _verify_signature(
        settings.hubspot_webhook_secret,
        request.method,
        str(request.url),
        raw_body,
        sig,
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    events_raw: list[Any] = json.loads(raw_body)
    events = [HubSpotWebhookEvent.model_validate(e) for e in events_raw]

    for event in events:
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

    return {"status": "ok"}
