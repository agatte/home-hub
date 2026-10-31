"""Deterministic contract tests: shadow diagnostics cannot actuate lights."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from backend.services.lighting_comfort_shadow import (
    PERIODS,
    MODES,
    audit_authored_matrix,
    audit_snapshot,
)
from scripts.lighting_comfort_shadow import validate_base_url, main


def snapshot(*, mode="watching", period="night", house="home", sync=False, desk=True):
    return {
        "automation_status": {
            "current_mode": mode,
            "time_period": period,
            "house_state": house,
            "mode_source": "process",
            "manual_override": False,
            "manual_light_overrides": [],
            "dnd_enabled": False,
            "secret": "MUST_NOT_EXPORT",
        },
        "automation_pipeline": {"current": {"inputs": {"scene_override": {"active": False}}}},
        "screen_sync_status": {
            "enabled_mode": sync,
            "last_source_authoritative": sync,
            "authoritative_targets": ["2", "5"],
            "raw_screenshot": "MUST_NOT_EXPORT",
        },
        "camera_status": {
            "calibrated": True,
            "ema_lux": 2.6,
            "baseline_lux": 74.0,
            "presence": {
                "at_desk_fresh": desk,
                "zone": "desk" if desk else None,
                "strongly_present": desk,
                "sources": {
                    "desktop": {
                        "fresh": desk,
                        "face_present": desk,
                        "zone": "desk" if desk else None,
                        "private_image": "MUST_NOT_EXPORT",
                    },
                    "latitude": {"fresh": True, "face_present": False},
                },
            },
        },
        "bedroom_lux": {
            "room": "bedroom",
            "calibrated": True,
            "ema_lux": 17.7,
            "baseline_lux": 127.3,
            "private_capture": "MUST_NOT_EXPORT",
        },
        "lights": [
            {"light_id": "1", "on": True, "bri": 76, "name": "SECRET"},
            {"light_id": "2", "on": True, "bri": 30, "private": "MUST_NOT_EXPORT"},
            {"light_id": "3", "on": False, "bri": 66},
            {"light_id": "4", "on": False, "bri": 66},
            {"light_id": "5", "on": True, "bri": 18},
            {"light_id": "6", "on": True, "bri": 20},
        ],
    }


def light(report, identifier):
    return next(x for x in report["lights"] if x["light_id"] == identifier)


def test_unowned_qualified_desk_shows_review_not_action():
    payload = snapshot(sync=False)
    before = deepcopy(payload)
    result = audit_snapshot(payload)
    assert result["kind"] == "lighting_comfort_shadow_v1"
    assert result["context"]["physical"]["desk_observation_qualified"]
    assert [x["light_id"] for x in result["review_candidates"]] == ["2"]
    assert result["review_candidates"][0]["status"] == "human_review_only"
    assert payload == before
    assert "MUST_NOT_EXPORT" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)


def test_screen_sync_ownership_blocks_l2_review_even_when_dark():
    result = audit_snapshot(snapshot(sync=True))
    assert result["review_candidates"] == []
    assert light(result, "2")["ownership_observed"] == "screen_sync"
    assert "screen_sync_reports_ownership" in light(result, "2")["reason_codes"]
    assert result["context"]["screen_sync_reported_ids"] == ["2", "5"]


@pytest.mark.parametrize("blocker", ["manual", "scene", "dnd", "away", "sleeping"])
def test_stronger_contexts_cannot_propose_review(blocker):
    value = snapshot(sync=False)
    if blocker == "manual":
        value["automation_status"]["manual_light_overrides"] = ["2"]
    elif blocker == "scene":
        value["automation_pipeline"]["current"]["inputs"]["scene_override"]["active"] = True
    elif blocker == "dnd":
        value["automation_status"]["dnd_enabled"] = True
    else:
        value["automation_status"]["house_state"] = blocker
    result = audit_snapshot(value)
    assert result["review_candidates"] == []
    if blocker == "manual":
        assert light(result, "2")["ownership_observed"] == "manual"


@pytest.mark.parametrize("source_change", ["absent", "stale", "wrong_room", "no_qualified_desk"])
def test_physical_source_uncertainty_abstains(source_change):
    value = snapshot(sync=False)
    d = value["camera_status"]["presence"]
    if source_change == "absent":
        d["sources"]["desktop"]["face_present"] = False
    elif source_change == "stale":
        d["sources"]["desktop"]["fresh"] = False
    elif source_change == "wrong_room":
        d["sources"]["desktop"]["zone"] = "bed"
    else:
        d["at_desk_fresh"] = False
    report = audit_snapshot(value)
    assert not report["context"]["physical"]["desk_observation_qualified"]
    assert report["review_candidates"] == []


def test_off_light_is_never_proposed_to_relight():
    value = snapshot(sync=False)
    value["lights"][1] = {"light_id": "2", "on": False, "bri": 254}
    result = audit_snapshot(value)
    assert result["review_candidates"] == []
    assert "light_off_do_not_relight" in light(result, "2")["reason_codes"]


def test_actual_and_authored_are_not_equated():
    value = snapshot(mode="general", period="night", sync=False)
    report = audit_snapshot(value)
    l2 = light(report, "2")
    assert l2["actual"]["bri"] == 30
    assert l2["authored_base"]["bri"] == 90
    assert "actual_below_uncomposed_static_target" in l2["reason_codes"]
    assert report["review_candidates"][0]["light_id"] == "2"
    assert "static_targets_not_final_owner_dispatch" in report["uncertainties"]


def test_invalid_or_missing_evidence_never_crashes_or_invents_brightness():
    value = snapshot(sync=False)
    value["automation_status"]["mode_source"] = ["malformed"]
    value["lights"][1]["bri"] = float("nan")
    value["bedroom_lux"]["ema_lux"] = True
    report = audit_snapshot(value)
    assert report["context"]["mode_source"] == "unknown"
    assert light(report, "2")["actual"]["bri"] is None
    assert report["context"]["bedroom_camera_proxy"]["relative_bucket"] == "unknown"
    assert report["review_candidates"] == []
    empty = audit_snapshot({})
    assert empty["review_candidates"] == []
    assert "missing_mode_or_period" in empty["global_blockers"]


def test_matrix_exercises_real_authored_table_not_simulated_owner_writes():
    report = audit_authored_matrix()
    assert report["row_count"] == len(PERIODS) * len(MODES) == 28
    assert report["assurance"].startswith("authored_base_only")
    watching_night = next(
        x for x in report["rows"] if x["activity"] == "watching" and x["period"] == "night"
    )
    assert {"light_id": "2", "authored_bri": 20, "reason": "low_static_brightness_screening"} in (
        watching_night["low_output_to_review"]
    )
    social = [x for x in report["rows"] if x["activity"] == "social"]
    assert len(social) == 4
    assert all(x["flat_palette"] for x in social)


def test_operator_cli_matrix_output_is_pure(capsys):
    assert main(["--matrix"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["row_count"] == 28


@pytest.mark.parametrize(
    "url",
    [
        "https://192.168.86.210:8000",
        "http://example.com:8000",
        "http://user:pass@192.168.86.210:8000",
        "http://8.8.8.8:8000",
        "http://192.168.86.210:8000/api/lights",
        "http://192.168.86.210:8000?auth=token",
    ],
)
def test_lan_read_boundary_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_lan_read_boundary_accepts_private_address():
    assert validate_base_url("http://192.168.86.210:8000/") == ("http://192.168.86.210:8000")


@pytest.mark.parametrize("missing", ["manual", "dnd", "scene", "sync"])
def test_missing_ownership_or_dnd_status_fail_closed(missing):
    value = snapshot(sync=False)
    if missing == "manual":
        value["automation_status"]["manual_light_overrides"] = None
    elif missing == "dnd":
        value["automation_status"].pop("dnd_enabled")
    elif missing == "scene":
        value["automation_pipeline"]["current"]["inputs"].pop("scene_override")
    else:
        value.pop("screen_sync_status")
    result = audit_snapshot(value)
    assert result["review_candidates"] == []
    assert any("unknown" in item for item in result["global_blockers"])


def test_active_screen_sync_dark_l2_is_detected_but_never_proposed_for_brightness():
    report = audit_snapshot(snapshot(sync=True))
    assert report["diagnostic_findings"] == [
        {
            "light_id": "2",
            "reason": "screen_sync_reports_low_output_at_bedroom_l2",
            "status": "technical_investigation_not_brightness_authority",
        }
    ]
    assert report["review_candidates"] == []
    assert "low_observed_brightness_screening" in light(report, "2")["reason_codes"]


def test_internal_idle_is_general_without_implying_away():
    value = snapshot(mode="idle", period="day", sync=False, desk=True)
    result = audit_snapshot(value)
    assert result["context"]["activity"] == "general"
    assert result["context"]["house_state"] == "home"
    assert light(result, "2")["authored_base"]["bri"] == 190
    assert "missing_mode_or_period" not in result["global_blockers"]


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8000",
        "http://169.254.1.2:8000",
        "http://100.64.0.1:8000",
    ],
)
def test_operator_cli_does_not_allow_non_lan_ipv4(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_operator_live_reader_uses_only_fixed_gets_without_proxy(monkeypatch):
    from scripts import lighting_comfort_shadow as cli

    calls = []
    handlers = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, count):
            return b"{}"

    class FakeOpener:
        def open(self, request, timeout):
            calls.append((request.get_method(), request.full_url, timeout))
            return Response()

    def fake_build_opener(*args):
        handlers.extend(args)
        return FakeOpener()

    monkeypatch.setattr(cli, "build_opener", fake_build_opener)
    data, errors = cli.read_only_snapshot("http://192.168.86.210:8000")
    assert errors == []
    assert set(data) == set(cli.ENDPOINTS)
    assert calls == [
        ("GET", "http://192.168.86.210:8000" + path, 3) for path in cli.ENDPOINTS.values()
    ]
    assert any(isinstance(h, cli.ProxyHandler) and h.proxies == {} for h in handlers)
    assert any(isinstance(h, cli._NoRedirect) for h in handlers)
