"""Unit tests for the HubSpot ↔ platform tech_stack mapping functions."""

from reffie.hubspot.tech_stack import hubspot_to_ts, ts_to_hubspot

# ---------------------------------------------------------------------------
# hubspot_to_ts — HubSpot Company props → platform dict
# ---------------------------------------------------------------------------


def test_hubspot_to_ts_string_fields_mapped() -> None:
    props = {
        "pms_system": "Entrata",
        "tour_scheduling_platform": "Showing Suite",
        "uses_lockboxes": "false",
        "applications_platform": "ResidentCheck",
        "zillow_tier": "Paid",
        "facebook_marketplace": "true",
        "shared_leasing_email": "false",
    }
    ts = hubspot_to_ts(props)
    assert ts["pms"] == "Entrata"
    assert ts["tour"] == "Showing Suite"
    assert ts["applications"] == "ResidentCheck"
    assert ts["zillow"] == "Paid"


def test_hubspot_to_ts_bool_true() -> None:
    props = {
        "pms_system": None,
        "tour_scheduling_platform": None,
        "uses_lockboxes": "true",
        "applications_platform": None,
        "zillow_tier": None,
        "facebook_marketplace": "true",
        "shared_leasing_email": "true",
    }
    ts = hubspot_to_ts(props)
    assert ts["lockboxes"] is True
    assert ts["facebook"] is True
    assert ts["sharedEmail"] is True


def test_hubspot_to_ts_bool_false() -> None:
    props = {
        "pms_system": None,
        "tour_scheduling_platform": None,
        "uses_lockboxes": "false",
        "applications_platform": None,
        "zillow_tier": None,
        "facebook_marketplace": "false",
        "shared_leasing_email": "false",
    }
    ts = hubspot_to_ts(props)
    assert ts["lockboxes"] is False
    assert ts["facebook"] is False
    assert ts["sharedEmail"] is False


def test_hubspot_to_ts_none_values_become_safe_defaults() -> None:
    props = {
        "pms_system": None,
        "tour_scheduling_platform": None,
        "uses_lockboxes": None,
        "applications_platform": None,
        "zillow_tier": None,
        "facebook_marketplace": None,
        "shared_leasing_email": None,
    }
    ts = hubspot_to_ts(props)
    assert ts["pms"] == ""
    assert ts["tour"] == ""
    assert ts["lockboxes"] is False
    assert ts["applications"] == ""
    assert ts["zillow"] == ""
    assert ts["facebook"] is False
    assert ts["sharedEmail"] is False


def test_hubspot_to_ts_missing_keys_become_safe_defaults() -> None:
    ts = hubspot_to_ts({})
    assert ts["pms"] == ""
    assert ts["lockboxes"] is False


# ---------------------------------------------------------------------------
# ts_to_hubspot — platform dict → HubSpot Company props
# ---------------------------------------------------------------------------


def test_ts_to_hubspot_strings_serialised() -> None:
    ts = {
        "pms": "Entrata",
        "tour": "Showing Suite",
        "applications": "ResidentCheck",
        "zillow": "Paid",
    }
    result = ts_to_hubspot(ts)
    assert result["pms_system"] == "Entrata"
    assert result["tour_scheduling_platform"] == "Showing Suite"
    assert result["applications_platform"] == "ResidentCheck"
    assert result["zillow_tier"] == "Paid"


def test_ts_to_hubspot_bool_true_serialised() -> None:
    ts = {"lockboxes": True, "facebook": True, "sharedEmail": True}
    result = ts_to_hubspot(ts)
    assert result["uses_lockboxes"] == "true"
    assert result["facebook_marketplace"] == "true"
    assert result["shared_leasing_email"] == "true"


def test_ts_to_hubspot_bool_false_serialised() -> None:
    ts = {"lockboxes": False, "facebook": False, "sharedEmail": False}
    result = ts_to_hubspot(ts)
    assert result["uses_lockboxes"] == "false"
    assert result["facebook_marketplace"] == "false"
    assert result["shared_leasing_email"] == "false"


def test_ts_to_hubspot_empty_strings_skipped() -> None:
    ts = {"pms": "", "tour": "", "applications": ""}
    result = ts_to_hubspot(ts)
    assert "pms_system" not in result
    assert "tour_scheduling_platform" not in result
    assert "applications_platform" not in result


def test_ts_to_hubspot_platform_only_keys_excluded() -> None:
    ts = {
        "pms": "Entrata",
        "sharedEmailAddr": "leasing@example.com",
        "sharedEmailAddrs": ["a@b.com"],
        "other": "some notes",
    }
    result = ts_to_hubspot(ts)
    assert "sharedEmailAddr" not in result
    assert "sharedEmailAddrs" not in result
    assert "other" not in result
    assert result["pms_system"] == "Entrata"


def test_ts_to_hubspot_all_empty_returns_empty_dict() -> None:
    ts = {"pms": "", "tour": "", "applications": "", "zillow": ""}
    assert ts_to_hubspot(ts) == {}


def test_ts_to_hubspot_none_value_skipped() -> None:
    ts = {"pms": None, "tour": "Showing Suite"}
    result = ts_to_hubspot(ts)
    assert "pms_system" not in result
    assert result["tour_scheduling_platform"] == "Showing Suite"
