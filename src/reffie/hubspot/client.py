from typing import Any

import httpx

import reffie.config as config_module


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
