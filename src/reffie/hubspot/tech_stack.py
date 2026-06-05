"""
Bi-directional mapping between HubSpot Company properties and the platform's
``tech_stack`` dict.

Only the 7 fields that live on the HubSpot Company object are handled here.
Platform-only keys (``sharedEmailAddr``, ``sharedEmailAddrs``, ``other``, etc.)
are never written to or read from HubSpot.
"""

from collections.abc import Mapping
from typing import Any

# HubSpot property name → platform tech_stack key
_HS_TO_TS: dict[str, str] = {
    "pms_system": "pms",
    "tour_scheduling_platform": "tour",
    "uses_lockboxes": "lockboxes",
    "applications_platform": "applications",
    "zillow_tier": "zillow",
    "facebook_marketplace": "facebook",
    "shared_leasing_email": "sharedEmail",
}

# Platform tech_stack key → HubSpot property name (reverse of above)
_TS_TO_HS: dict[str, str] = {v: k for k, v in _HS_TO_TS.items()}

# HubSpot property names that carry boolean values as 'true'/'false' strings.
_BOOL_HS_KEYS: frozenset[str] = frozenset(
    {"uses_lockboxes", "facebook_marketplace", "shared_leasing_email"}
)


def hubspot_to_ts(props: Mapping[str, str | None]) -> dict[str, Any]:
    """
    Map HubSpot Company properties to a platform ``tech_stack`` dict.

    Empty or ``None`` HubSpot values become safe platform defaults: ``""`` for
    string fields and ``False`` for boolean fields. Boolean fields accept
    HubSpot's ``'true'`` / ``'false'`` string format.

    :param props: Raw ``properties`` dict from a HubSpot company response.
    :returns: Platform ``tech_stack`` dict containing only the 7 HubSpot-mapped keys.
    """
    ts: dict[str, Any] = {}
    for hs_key, ts_key in _HS_TO_TS.items():
        raw = props.get(hs_key)
        if hs_key in _BOOL_HS_KEYS:
            ts[ts_key] = str(raw).strip().lower() in ("true", "yes", "1")
        else:
            ts[ts_key] = raw.strip() if raw else ""

    # "PMS System" is a HubSpot sentinel for applications_platform meaning the
    # applications platform is the same product as the PMS. Substitute the
    # resolved PMS value (already "" when unset) so the frontend can match it.
    if ts["applications"].strip().lower() == "pms system":
        ts["applications"] = ts["pms"]

    return ts


def ts_to_hubspot(ts: dict[str, Any]) -> dict[str, str]:
    """
    Map a platform ``tech_stack`` dict to HubSpot Company property name/value pairs.

    Only the 7 HubSpot-mapped keys are included. Platform-only keys are ignored.
    Boolean values are serialised as ``'true'`` / ``'false'`` strings.
    Empty strings are omitted so existing HubSpot values are not overwritten
    with blanks when the platform field is unset.

    :param ts: Platform ``tech_stack`` dict.
    :returns: Dict of HubSpot property name → string value, ready to PATCH.
    """
    result: dict[str, str] = {}
    for ts_key, hs_key in _TS_TO_HS.items():
        val = ts.get(ts_key)
        if val is None:
            continue
        if hs_key in _BOOL_HS_KEYS:
            result[hs_key] = "true" if val else "false"
        else:
            str_val = str(val)
            if str_val == "":
                continue
            result[hs_key] = str_val
    return result
