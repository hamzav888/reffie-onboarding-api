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
                "properties": ["name", "sku", "hs_sku", "hs_product_id", "quantity", "price"],
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
        # HubSpot's standard line-item SKU property is hs_sku; some portals
        # populate the custom sku property instead. Prefer hs_sku, fall back to sku.
        sku_value = props.get("hs_sku") or props.get("sku") or ""
        items.append(
            {
                "id": str(result.get("id", "")),
                "name": props.get("name") or "",
                "sku": sku_value,
                "quantity": props.get("quantity") or "",
                "price": props.get("price") or "",
            }
        )
    return items


async def get_deal_line_items(deal_id: str, settings: Settings) -> list[dict[str, Any]]:
    """
    Return all line items across every quote associated with a HubSpot deal.

    Walks deal → quotes → line items. A failure fetching one quote's line items
    is logged and skipped so a single bad quote does not abort the whole deal.

    :param deal_id: HubSpot deal object ID.
    :param settings: Application settings providing the HubSpot credentials.
    :returns: Combined list of normalised line-item dicts (may be empty).
    :raises HubSpotNotFoundError: If the deal does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses fetching the quote list.
    """
    quote_ids = await get_deal_quote_ids(deal_id, settings)
    items: list[dict[str, Any]] = []
    for quote_id in quote_ids:
        try:
            items.extend(await get_quote_line_items(quote_id, settings))
        except (HubSpotAPIError, HubSpotNotFoundError):
            logger.exception("Failed to fetch line items for quote %s", quote_id)
            continue
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

# Company-level properties used to derive the account's location. Kept separate
# from TECH_STACK_PROPERTIES so the two concerns can evolve independently.
COMPANY_LOCATION_PROPERTIES: list[str] = ["state"]

# Company-level onboarding properties. Kept separate so each concern can grow
# independently without touching the others.
COMPANY_ONBOARDING_PROPERTIES: list[str] = ["onboarding_cs_rep"]


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


async def search_deals_by_stage(
    stage_ids: list[str],
    settings: Settings,
    after: str | None = None,
) -> dict[str, Any]:
    """
    Search HubSpot deals whose ``dealstage`` is one of ``stage_ids``.

    Uses the CRM v3 Search API with an ``IN`` filter. Returns the raw
    response dict containing ``results`` and optionally ``paging``.

    :param stage_ids: List of HubSpot stage IDs to filter on.
    :param settings: Application settings providing HubSpot credentials.
    :param after: Pagination cursor from a previous response's ``paging.next.after``.
    :returns: Raw HubSpot search response dict.
    :raises HubSpotAPIError: For 4xx/5xx responses.
    """
    body: dict[str, Any] = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "dealstage",
                        "operator": "IN",
                        "values": stage_ids,
                    }
                ]
            }
        ],
        "properties": ["dealname", "dealstage", "amount", "closedate", "hubspot_owner_id"],
        "limit": 100,
    }
    if after is not None:
        body["after"] = after
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.post("/crm/v3/objects/deals/search", json=body)
    _check_response(response, "deals search by stage")
    result: dict[str, Any] = response.json()
    return result


async def search_deals_by_stage_all(
    stage_ids: list[str],
    settings: Settings,
) -> list[dict[str, Any]]:
    """
    Paginate through all HubSpot deals in the given stages.

    Repeatedly calls :func:`search_deals_by_stage`, following
    ``paging.next.after`` until no further pages exist.

    :param stage_ids: List of HubSpot stage IDs to filter on.
    :param settings: Application settings providing HubSpot credentials.
    :returns: Combined list of all deal result dicts across all pages.
    :raises HubSpotAPIError: For 4xx/5xx responses on any page.
    """
    all_results: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        page = await search_deals_by_stage(stage_ids, settings, after=after)
        all_results.extend(page.get("results", []))
        next_page: dict[str, Any] | None = page.get("paging", {}).get("next")
        if next_page is None:
            break
        after = next_page.get("after")
        if after is None:
            break
    return all_results


async def get_owner(owner_id: str, settings: Settings) -> dict[str, Any]:
    """
    Fetch a HubSpot owner record by ID.

    :param owner_id: HubSpot owner object ID.
    :param settings: Application settings providing HubSpot credentials.
    :returns: Raw owner dict (contains ``firstName``, ``lastName``, ``email``, etc.).
    :raises HubSpotNotFoundError: If the owner does not exist.
    :raises HubSpotAPIError: For other 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        base_url=settings.hubspot_base_url,
        headers={"Authorization": f"Bearer {settings.hubspot_token}"},
    ) as client:
        response = await client.get(f"/crm/v3/owners/{owner_id}")
    _check_response(response, f"owner {owner_id}")
    result: dict[str, Any] = response.json()
    return result


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
