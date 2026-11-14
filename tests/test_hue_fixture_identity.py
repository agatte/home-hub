"""Offline Hue v1 fixture identity audit: all samples synthetic, no I/O."""
from copy import deepcopy

import pytest

from backend.services.hue_fixture_identity import audit_hue_v1_fixture_bindings
from backend.services.light_state_calculator import ALL_LIGHT_IDS


def enrolled():
    # Synthetic identifiers; never put real bridge uniqueids into Git.
    return {light_id: f"synthetic-unique-{light_id}" for light_id in ALL_LIGHT_IDS}


def api():
    return {
        "lights": {
            light_id: {
                "name": f"Untrusted name {light_id}",
                "state": {"reachable": True},
                "uniqueid": f"synthetic-unique-{light_id}",
            }
            for light_id in ALL_LIGHT_IDS
        }
    }


def test_structural_match_only_for_all_six_preenrolled_fixtures():
    expected, observed = enrolled(), api()
    original = deepcopy(observed)
    result = audit_hue_v1_fixture_bindings(expected, observed)
    assert result == dict.fromkeys(ALL_LIGHT_IDS, "matched")
    assert observed == original
    # Not even one raw identifier/name may enter diagnostic result.
    assert all(uniqueid not in repr(result) for uniqueid in expected.values())
    assert "Untrusted name" not in repr(result)


@pytest.mark.parametrize("binding", [
    None,
    {},
])
def test_unenrolled_never_autotrusts_bridge_claims(binding):
    assert audit_hue_v1_fixture_bindings(binding, api()) == dict.fromkeys(
        ALL_LIGHT_IDS, "unenrolled",
    )


@pytest.mark.parametrize("invalid_enrollment", [
    {"7": "synthetic-other"},
    {"2": ""},
    {"2": " synthetic-unique-2"},
    {"2": "synthetic-unique-2\n"},
    {"2": None},
    {"2": "synthetic-unique-2", "3": "synthetic-unique-2"},
    {2: "synthetic-unique-2"},
])
def test_invalid_enrollment_does_not_grant_partial_identity(invalid_enrollment):
    assert audit_hue_v1_fixture_bindings(invalid_enrollment, api()) == dict.fromkeys(
        ALL_LIGHT_IDS, "invalid_enrollment",
    )


@pytest.mark.parametrize("snapshot", [
    None, {}, {"lights": None}, {"lights": []}, {"lights": "unsafe"},
])
def test_stale_or_invalid_bridge_snapshot_is_unavailable(snapshot):
    assert audit_hue_v1_fixture_bindings(enrolled(), snapshot) == dict.fromkeys(
        ALL_LIGHT_IDS, "inventory_unavailable",
    )


def test_wrong_uniqueid_is_mismatch_even_if_name_matches():
    snapshot = api()
    snapshot["lights"]["2"]["uniqueid"] = "synthetic-stranger"
    snapshot["lights"]["2"]["name"] = "Bedroom left"
    result = audit_hue_v1_fixture_bindings(enrolled(), snapshot)
    assert result["2"] == "mismatched"
    assert result["1"] == "matched"


def test_swap_reports_reindexed_but_never_enrolls_a_new_mapping():
    snapshot = api()
    a, b = snapshot["lights"]["2"], snapshot["lights"]["5"]
    a["uniqueid"], b["uniqueid"] = b["uniqueid"], a["uniqueid"]
    result = audit_hue_v1_fixture_bindings(enrolled(), snapshot)
    assert result["2"] == "reindexed"
    assert result["5"] == "reindexed"


def test_missing_and_missing_uniqueid_are_not_passing_states():
    snapshot = api()
    snapshot["lights"].pop("4")
    snapshot["lights"]["5"].pop("uniqueid")
    result = audit_hue_v1_fixture_bindings(enrolled(), snapshot)
    assert result["4"] == "missing"
    assert result["5"] == "missing_uniqueid"


def test_duplicate_under_unrecognized_bridge_id_blocks_affected_fixture():
    snapshot = api()
    snapshot["lights"]["97"] = {
        "name": "Unrecognized", "uniqueid": snapshot["lights"]["2"]["uniqueid"],
    }
    result = audit_hue_v1_fixture_bindings(enrolled(), snapshot)
    assert result["2"] == "duplicate_uniqueid"
    assert "97" not in result


def test_raw_bridge_names_never_count_as_evidence():
    snapshot = api()
    snapshot["lights"]["2"]["name"] = "Kitchen front"
    assert audit_hue_v1_fixture_bindings(enrolled(), snapshot)["2"] == "matched"
    snapshot["lights"]["2"]["uniqueid"] = None
    assert audit_hue_v1_fixture_bindings(enrolled(), snapshot)["2"] == "missing_uniqueid"


def test_unrecognized_fixture_cannot_be_discovered_into_expected_scope():
    snapshot = api()
    snapshot["lights"]["7"] = {
        "name": "Plant Wash again", "uniqueid": "synthetic-new-device",
    }
    result = audit_hue_v1_fixture_bindings(enrolled(), snapshot)
    assert set(result) == set(ALL_LIGHT_IDS)
    assert all(status == "matched" for status in result.values())


def test_partial_enrollment_never_marks_unenrolled_lights_matched():
    result = audit_hue_v1_fixture_bindings({"2": "synthetic-unique-2"}, api())
    assert result["2"] == "matched"
    assert all(result[light_id] == "unenrolled" for light_id in ALL_LIGHT_IDS if light_id != "2")
