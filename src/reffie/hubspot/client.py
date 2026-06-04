import logging
from typing import Any

import httpx

import reffie.config as config_module
from reffie.config import Settings

logger = logging.getLogger(__name__)


class HubSpotError(Exception):
    """Base class for HubSpot API errors."""


class HubSpotNotFoundError(HubSpotError):
    """Raised when HubSpot returns 404 for a resource."""


class HubSpotAPIError(HubSpotError):
    """Raised for non-404 4xx/5xx responses from the HubSpot API."""


def _check_response(response: httpx.Response, context: str) -> None:
    """
    Inspect a HubSpot response and raise the appropriate exception on failure.

    :param response: The httpx response to inspect.
    :param context: Human-readable description used in the exception message.
    :raises HubSpotNotFoundError: If the response status is 404.
    :raises HubSpotAPIError: If the response status is any other 4xx or 5xx.
    """
    if response.status_code == 404:
        raise HubSpotNotFoundError(f"{context} not found in HubSpot")
    if response.status_code >= 400:
        raise HubSpotAPIError(
            f"HubSpot API error {response.status_code} for {context}: {response.text}"
        )


async def get_deal_properties(deal_id: str, properties: list[str]) -> dict[str, Any]:
    """
    Fetch deal properties from the HubSpot CRM v3 API.

    :param deal_id: HubSpot deal object ID.
    :param properties: Property names to include in the response.
    :returns: Raw HubSpot deal object containing ``id`` and ``properties`` keys.
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=config_module.settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {config_module.settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v3/objects/deals/{deal_id}",
            params={"properties": ",".join(properties)},
        )
    _check_response(response, f"deal {deal_id}")
    result: dict[str, Any] = response.json()
    return result


async def get_deal_contact_ids(deal_id: str) -> list[str]:
    """
    Return the IDs of contacts associated with a HubSpot deal via the v4 associations API.

    :param deal_id: HubSpot deal object ID.
    :returns: List of contact object ID strings (may be empty).
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=config_module.settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {config_module.settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v4/objects/deals/{deal_id}/associations/contacts",
        )
    _check_response(response, f"deal {deal_id} associations")
    data: dict[str, Any] = response.json()
    results: list[dict[str, Any]] = data.get("results", [])
    return [str(r["toObjectId"]) for r in results]


async def get_contact_properties(contact_id: str, properties: list[str]) -> dict[str, Any]:
    """
    Fetch contact properties from the HubSpot CRM v3 API.

    :param contact_id: HubSpot contact object ID.
    :param properties: Property names to include in the response.
    :returns: Raw HubSpot contact object containing ``id`` and ``properties`` keys.
    :raises HubSpotNotFoundError: If the contact does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=config_module.settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {config_module.settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v3/objects/contacts/{contact_id}",
            params={"properties": ",".join(properties)},
        )
    _check_response(response, f"contact {contact_id}")
    result: dict[str, Any] = response.json()
    return result


async def get_deal_stage(deal_id: str, settings: Settings) -> str | None:
    """
    Fetch only the ``dealstage`` property for a HubSpot deal.

    Used inside background tasks to confirm the deal is still Closed Won at
    processing time (the webhook may be delayed and the stage may have moved).

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: The ``dealstage`` property value, or ``None`` if absent.
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v3/objects/deals/{deal_id}",
            params={"properties": "dealstage"},
        )
    _check_response(response, f"deal {deal_id}")
    data: dict[str, Any] = response.json()
    val = data.get("properties", {}).get("dealstage")
    return str(val) if val is not None else None


async def get_deal_quote_ids(deal_id: str, settings: Settings) -> list[str]:
    """
    Return associated quote IDs for a HubSpot deal.

    Uses the v4 associations API (``/crm/v4/objects/deals/{id}/associations/quotes``).
    The v4 response uses ``toObjectId`` to identify the associated object.

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: List of quote object ID strings (may be empty).
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v4/objects/deals/{deal_id}/associations/quotes",
        )
    _check_response(response, f"deal {deal_id} quote associations")
    logger.warning(
        "get_deal_quote_ids deal=%s status=%s body=%s",
        deal_id,
        response.status_code,
        response.text,
    )
    data: dict[str, Any] = response.json()
    results: list[dict[str, Any]] = data.get("results", [])
    return [str(r["toObjectId"]) for r in results]


async def get_quote_line_items(quote_id: str, settings: Settings) -> list[dict[str, Any]]:
    """
    Return line items for a HubSpot quote as a normalised list.

    Two-step fetch:

    1. ``GET /crm/v4/objects/quotes/{id}/associations/line_items`` — collect IDs.
    2. ``POST /crm/v3/objects/line_items/batch/read`` — batch-fetch properties.

    Each returned item contains ``id``, ``name``, ``sku``, ``quantity``, ``price``.

    :param quote_id: HubSpot quote object ID.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: List of line-item dicts (may be empty).
    :raises HubSpotNotFoundError: If the quote does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        assoc_response = await client.get(
            f"/crm/v4/objects/quotes/{quote_id}/associations/line_items",
        )
    _check_response(assoc_response, f"quote {quote_id} line item associations")
    logger.warning(
        "get_quote_line_items_assoc quote=%s status=%s body=%s",
        quote_id,
        assoc_response.status_code,
        assoc_response.text,
    )
    assoc_data: dict[str, Any] = assoc_response.json()
    li_ids = [str(r["toObjectId"]) for r in assoc_data.get("results", [])]

    if li_ids == []:
        return []

    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        batch_response = await client.post(
            "/crm/v3/objects/line_items/batch/read",
            json={
                "properties": ["name", "sku", "quantity", "price"],
                "inputs": [{"id": li_id} for li_id in li_ids],
            },
        )
    _check_response(batch_response, f"line_items batch for quote {quote_id}")
    logger.warning(
        "get_quote_line_items_batch quote=%s status=%s body=%s",
        quote_id,
        batch_response.status_code,
        batch_response.text,
    )
    batch_data: dict[str, Any] = batch_response.json()

    items: list[dict[str, Any]] = []
    for result in batch_data.get("results", []):
        props: dict[str, Any] = result.get("properties", {})
        items.append(
            {
                "id": str(result.get("id", "")),
                "name": props.get("name") or "",
                "sku": props.get("sku") or "",
                "quantity": props.get("quantity") or "",
                "price": props.get("price") or "",
            }
        )
    return items


TECH_STACK_PROPERTIES: list[str] = [
    "pms_system",
    "tour_scheduling_platform",
    "uses_lockboxes",
    "applications_platform",
    "zillow_tier",
    "facebook_marketplace",
    "shared_leasing_email",
]


async def get_deal_company_id(deal_id: str, settings: Settings) -> str | None:
    """
    Return the primary associated company ID for a HubSpot deal.

    Uses the v4 associations API. Returns ``None`` if no company is linked.

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: Company object ID string, or ``None`` if no company is associated.
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v4/objects/deals/{deal_id}/associations/companies",
        )
    _check_response(response, f"deal {deal_id} company associations")
    data: dict[str, Any] = response.json()
    results: list[dict[str, Any]] = data.get("results", [])
    if results == []:
        return None
    return str(results[0]["toObjectId"])


async def get_company_properties(
    company_id: str,
    properties: list[str],
    settings: Settings,
) -> dict[str, str | None]:
    """
    Fetch properties from a HubSpot company object.

    :param company_id: HubSpot company object ID.
    :param properties: Property names to include in the response.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: Dict of property name → string value (``None`` if unset in HubSpot).
    :raises HubSpotNotFoundError: If the company does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.get(
            f"/crm/v3/objects/companies/{company_id}",
            params={"properties": ",".join(properties)},
        )
    _check_response(response, f"company {company_id}")
    data: dict[str, Any] = response.json()
    raw: dict[str, Any] = data.get("properties", {})
    return {k: (str(v) if v is not None else None) for k, v in raw.items()}


async def update_company_properties(
    company_id: str,
    properties: dict[str, str],
    settings: Settings,
) -> None:
    """
    PATCH company properties in HubSpot CRM.

    :param company_id: HubSpot company object ID.
    :param properties: Property name/value pairs to write.
    :param settings: Application settings providing the HubSpot credentials.
    :raises HubSpotNotFoundError: If the company does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.patch(
            f"/crm/v3/objects/companies/{company_id}",
            json={"properties": properties},
        )
    _check_response(response, f"company {company_id}")


async def update_deal_properties(
    deal_id: str,
    properties: dict[str, str],
    settings: Settings,
) -> None:
    """
    PATCH deal properties in HubSpot CRM.

    :param deal_id: HubSpot deal object ID.
    :param properties: Property name/value pairs to write. ``kickoff_call_date``
        is permanently forbidden — passing it raises :class:`ValueError` immediately.
    :param settings: Application settings providing the HubSpot credentials.
    :raises ValueError: If ``kickoff_call_date`` appears in ``properties``.
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    if "kickoff_call_date" in properties:
        raise ValueError("kickoff_call_date is read-only and must never be written back to HubSpot")
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.patch(
            f"/crm/v3/objects/deals/{deal_id}",
            json={"properties": properties},
        )
    _check_response(response, f"deal {deal_id}")
