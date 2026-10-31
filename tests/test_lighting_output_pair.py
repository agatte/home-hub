"""Safety and provenance tests for offline, non-actuating output pair analysis."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from backend.services.lighting_output_pair import compare_frames, frozen_feedback
from scripts.lighting_output_pair import main


BASE = datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)


def observed(mode="watching", period="night", *, screen=True, light2=30):
    return {
        "automation_status": {
            "current_mode": mode,
            "house_state": "home",
            "time_period": period,
            "automation_enabled": True,
            "manual_override": False,
            "manual_light_overrides": [],
            "dnd_enabled": False,
            "mode_source": "process",
            "secret_token": "NEVER_COPY",
        },
        "automation_pipeline": {
            "current": {
                "inputs": {"scene_override": {"active": False}},
                "output": {
                    "lights": {
                        "1": {"on": True, "bri": 45},
                        "2": {"on": True, "bri": 110, "private_source": "NEVER_COPY"},
                    }
                },
            }
        },
        "screen_sync_status": {
            "enabled_mode": screen,
            "source_authority_enforced": screen,
            "authoritative_source": "desktop" if screen else None,
            "last_source": "desktop" if screen else None,
            "last_source_authoritative": screen,
            "authoritative_targets": ["2", "5"] if screen else None,
            "last_color_at": BASE.isoformat() if screen else None,
            "pixel_data": "NEVER_COPY",
        },
        "camera_status": {
            "presence": {
                "at_desk_fresh": True,
                "at_desk_source": "desktop",
                "zone": "desk",
                "strongly_present": True,
                "sources": {
                    "desktop": {
                        "fresh": True,
                        "face_present": True,
                        "zone": "desk",
                        "picture": "NEVER_COPY",
                    },
                    "latitude": {"fresh": True},
                },
            }
        },
        "lights": [
            {"light_id": "1", "on": True, "bri": 45},
            {"light_id": "2", "on": True, "bri": light2, "name": "NEVER_COPY"},
            {"light_id": "3", "on": False},
            {"light_id": "4", "on": False},
            {"light_id": "5", "on": True, "bri": 18},
            {"light_id": "6", "on": True, "bri": 20},
        ],
    }


def pair(before=None, after=None, *, interval=3):
    return [
        {"collected_at": BASE.isoformat(), "snapshot": before or observed()},
        {
            "collected_at": (BASE + timedelta(seconds=interval)).isoformat(),
            "snapshot": after or observed(),
        },
    ]


def light(result, target):
    return next(x for x in result["rows"] if x["light_id"] == target)


def test_matching_recent_screen_source_is_correlation_not_ack_or_action():
    frames = pair()
    unchanged = deepcopy(frames)
    result = compare_frames(frames)
    assert frames == unchanged
    assert result["comparison_blockers"] == []
    assert result["screen_sync"]["continuity_reported"] is True
    assert result["screen_sync"]["after"]["proof_of_hue_write"] is False
    assert light(result, "2")["reported_provenance"] == "recent_screen_sync_color_correlated"
    assert light(result, "1")["reported_provenance"] == "unverified_no_final_write_proven"
    assert any(
        x["light_id"] == "2"
        and x["hypothesis"] == "recent_screen_sync_report_coincides_with_low_output"
        for x in result["technical_findings"]
    )
    assert "NEVER_COPY" not in json.dumps(result)
    assert "23:00:00" not in json.dumps(result)


def test_actual_difference_is_reported_without_claiming_cause():
    before = observed(light2=30)
    after = observed(light2=42)
    result = compare_frames(pair(before, after))
    assert light(result, "2")["brightness_delta"] == 12
    assert "actual_brightness_changed" in light(result, "2")["reason_codes"]
    assert result["assurance"] == "non_atomic_correlation_not_causation_or_hue_ack"


@pytest.mark.parametrize("offset", [-20, 20])
def test_stale_or_future_screen_color_does_not_prove_owner(offset):
    first, last = observed(), observed()
    first["screen_sync_status"]["last_color_at"] = (BASE + timedelta(seconds=offset)).isoformat()
    last["screen_sync_status"]["last_color_at"] = (BASE + timedelta(seconds=offset)).isoformat()
    report = compare_frames(pair(first, last))
    assert report["screen_sync"]["continuity_reported"] is False
    assert light(report, "2")["reported_provenance"] == "unverified_no_final_write_proven"


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_time",
        "naive_time",
        "reversed",
        "too_far",
        "changed_mode",
        "changed_house",
        "changed_source",
    ],
)
def test_frame_clock_or_context_uncertainty_abstains(corruption):
    frames = pair()
    if corruption == "missing_time":
        frames[1]["collected_at"] = None
    elif corruption == "naive_time":
        frames[1]["collected_at"] = "2026-10-31T23:00:03"
    elif corruption == "reversed":
        frames[1]["collected_at"] = (BASE - timedelta(seconds=3)).isoformat()
    elif corruption == "too_far":
        frames[1]["collected_at"] = (BASE + timedelta(minutes=3)).isoformat()
    elif corruption == "changed_mode":
        frames[1]["snapshot"]["automation_status"]["current_mode"] = "working"
    elif corruption == "changed_house":
        frames[1]["snapshot"]["automation_status"]["house_state"] = "sleeping"
    else:
        frames[1]["snapshot"]["screen_sync_status"]["authoritative_source"] = "laptop"
    report = compare_frames(frames)
    assert report["comparison_blockers"]
    assert report["technical_findings"] == []


@pytest.mark.parametrize(
    "block",
    [
        "manual_light",
        "manual_activity",
        "scene",
        "dnd",
        "disabled",
        "missing_manual",
        "missing_enabled",
    ],
)
def test_known_and_unknown_strong_owners_block_technical_findings(block):
    frames = pair()
    for frame in frames:
        status = frame["snapshot"]["automation_status"]
        if block == "manual_light":
            status["manual_light_overrides"] = ["2"]
        elif block == "manual_activity":
            status["manual_override"] = True
        elif block == "scene":
            frame["snapshot"]["automation_pipeline"]["current"]["inputs"]["scene_override"][
                "active"
            ] = True
        elif block == "dnd":
            status["dnd_enabled"] = True
        elif block == "disabled":
            status["automation_enabled"] = False
        elif block == "missing_manual":
            status.pop("manual_override")
        else:
            status.pop("automation_enabled")
    report = compare_frames(frames)
    assert report["technical_findings"] == []


def test_off_fixture_is_not_inferred_as_underlighting():
    frames = pair()
    frames[1]["snapshot"]["lights"][1] = {"light_id": "2", "on": False}
    result = compare_frames(frames)
    assert "off_state_preserve_intent" in light(result, "2")["reason_codes"]
    assert not any(x["light_id"] == "2" for x in result["technical_findings"])


def test_missing_fixture_does_not_invent_brightness():
    frames = pair()
    frames[1]["snapshot"]["lights"] = []
    result = compare_frames(frames)
    assert result["technical_findings"] == []
    assert "fixture_missing" in light(result, "2")["reason_codes"]


def test_no_screen_source_unknown_owner_does_not_become_screen_sync():
    result = compare_frames(pair(observed(screen=False), observed(screen=False)))
    assert result["screen_sync"]["continuity_reported"] is False
    assert light(result, "2")["reported_provenance"] == "unverified_no_final_write_proven"
    assert any(
        x["hypothesis"] == "low_output_under_unverified_final_owner"
        for x in result["technical_findings"]
    )


def test_daytime_does_not_generate_low_output_findings():
    report = compare_frames(pair(observed(period="day"), observed(period="day")))
    assert report["technical_findings"] == []
    assert "not_after_dark" in report["comparison_blockers"]


@pytest.mark.parametrize("feedback", ["too_dark", "comfortable", "too_bright"])
def test_explicit_feedback_is_frozen_before_mutations_and_no_learning(feedback):
    source = observed()
    captured = frozen_feedback(source, feedback)
    source["lights"][1]["bri"] = 200
    assert captured["context_before_feedback"]["lights"][1]["bri"] == 30
    assert captured["preference"] == feedback
    assert captured["learning_action"] == "none_preview_only"
    assert captured["writes"] is False
    assert "NEVER_COPY" not in json.dumps(captured)


@pytest.mark.parametrize("value", ["dark", "", None, 2, {"result": "too_dark"}])
def test_no_inferred_or_untrusted_feedback(value):
    with pytest.raises(ValueError):
        frozen_feedback(observed(), value)


@pytest.mark.parametrize("frames", [[], [{}], [{}, {}, {}], None, "bad"])
def test_pair_requires_two_frames(frames):
    with pytest.raises(ValueError):
        compare_frames(frames)


def test_cli_offline_only_and_sanitized(tmp_path, capsys):
    input_path = tmp_path / "private-pair.json"
    input_path.write_text(json.dumps({"samples": pair()}), encoding="utf-8")
    assert main(["--frames", str(input_path)]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["kind"] == "lighting_output_pair_v1"
    assert "NEVER_COPY" not in printed
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(json.dumps(observed()), encoding="utf-8")
    assert main(["--feedback-snapshot", str(feedback_path), "--rating", "too_dark"]) == 0
    assert json.loads(capsys.readouterr().out)["learning_action"] == "none_preview_only"


@pytest.mark.parametrize(
    "mutate",
    [
        "no_desk",
        "desktop_stale",
        "unknown_source",
        "missing_fused_zone",
        "fused_couch",
        "fused_bed",
        "latitude_couch",
        "latitude_bed",
        "couch_second_frame",
    ],
)
def test_desk_findings_require_consistent_named_physical_evidence(mutate):
    frames = pair()
    sample = frames[1]["snapshot"]["camera_status"]["presence"]
    if mutate == "no_desk":
        sample["at_desk_fresh"] = False
    elif mutate == "desktop_stale":
        sample["sources"]["desktop"]["fresh"] = False
    elif mutate == "unknown_source":
        sample["at_desk_source"] = None
    elif mutate == "missing_fused_zone":
        sample["zone"] = None
    elif mutate == "fused_couch":
        sample["zone"] = "couch"
    elif mutate == "fused_bed":
        sample["zone"] = "bed"
    elif mutate == "latitude_couch":
        sample["sources"]["latitude"].update({"fresh": True, "zone": "couch", "face_present": True})
    elif mutate == "latitude_bed":
        sample["sources"]["latitude"].update({"fresh": True, "zone": "bed", "face_present": True})
    else:
        sample["zone"] = "couch"
    result = compare_frames(frames)
    assert "source_qualified_desk_not_confirmed_in_both_frames" in result["comparison_blockers"]
    assert result["technical_findings"] == []
    assert light(result, "2")["reported_provenance"] == "unverified_no_final_write_proven"
    assert result["context"]["physical_desk"]["both_frames_qualified"] is False


def test_stale_opposing_latitude_is_not_automatically_a_current_room_veto():
    frames = pair()
    for frame in frames:
        frame["snapshot"]["camera_status"]["presence"]["sources"]["latitude"] = {
            "fresh": False,
            "zone": "couch",
            "face_present": True,
        }
    report = compare_frames(frames)
    assert report["context"]["physical_desk"]["both_frames_qualified"]
    assert not report["comparison_blockers"]


def test_missing_desktop_physical_evidence_in_both_frames_abstains():
    frames = pair()
    for frame in frames:
        frame["snapshot"]["camera_status"]["presence"] = {
            "at_desk_fresh": False,
            "zone": None,
            "sources": {},
        }
    report = compare_frames(frames)
    assert report["technical_findings"] == []
    assert "source_qualified_desk_not_confirmed_in_both_frames" in report["comparison_blockers"]


def test_engine_cache_is_diagnostic_not_a_proven_final_writer():
    result = compare_frames(pair())
    l1, l2 = light(result, "1"), light(result, "2")
    assert l1["actual_vs_automation_cache"] == "matching_cache_not_final_ack"
    assert l2["actual_vs_automation_cache"] == "brightness_disagrees_cache_not_final_ack"
    assert l2["automation_last_applied_cache"]["after"] == {"on": True, "bri": 110}
    assert result["screen_sync"]["after"]["proof_of_hue_write"] is False
    assert (
        "automation_last_applied_cache_may_be_stale_or_superseded_by_stronger_writer"
        in result["limitations"]
    )
    assert "NEVER_COPY" not in json.dumps(result)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -1, 0, 255, "210"])
def test_malformed_engine_cache_brightness_is_not_trusted(bad):
    frames = pair()
    for frame in frames:
        frame["snapshot"]["automation_pipeline"]["current"]["output"]["lights"]["2"]["bri"] = bad
    report = compare_frames(frames)
    l2 = light(report, "2")
    assert l2["automation_last_applied_cache"]["after"] == {"on": True, "bri": None}
    assert l2["actual_vs_automation_cache"] == "brightness_not_comparable"


def test_missing_and_off_engine_cache_dont_invent_disagreement():
    frames = pair()
    frames[0]["snapshot"]["automation_pipeline"]["current"].pop("output")
    frames[1]["snapshot"]["automation_pipeline"]["current"]["output"]["lights"]["2"] = {
        "on": False,
        "bri": 254,
    }
    result = compare_frames(frames)
    l2 = light(result, "2")
    assert l2["automation_last_applied_cache"]["before"] is None
    assert l2["automation_last_applied_cache"]["after"] == {"on": False, "bri": None}
    assert l2["actual_vs_automation_cache"] == "on_state_disagrees_cache_not_final_ack"


def test_missing_pipeline_output_means_unverified_cache_not_device_failure():
    frames = pair()
    for frame in frames:
        frame["snapshot"]["automation_pipeline"]["current"].pop("output")
    result = compare_frames(frames)
    assert light(result, "2")["actual_vs_automation_cache"] == "automation_cache_not_available"
    assert result["assurance"] == "non_atomic_correlation_not_causation_or_hue_ack"


def test_empty_reported_sync_targets_do_not_qualify_owner():
    frames = pair()
    for frame in frames:
        frame["snapshot"]["screen_sync_status"]["authoritative_targets"] = []
    result = compare_frames(frames)
    assert result["screen_sync"]["continuity_reported"] is False
    assert all(
        not x["qualified_report"]
        for x in (result["screen_sync"]["before"], result["screen_sync"]["after"])
    )
    assert light(result, "2")["reported_provenance"] == "unverified_no_final_write_proven"


def test_reversed_color_timestamps_abstain_even_when_individually_fresh():
    frames = pair()
    frames[0]["snapshot"]["screen_sync_status"]["last_color_at"] = (
        BASE + timedelta(seconds=1)
    ).isoformat()
    frames[1]["snapshot"]["screen_sync_status"]["last_color_at"] = (
        BASE - timedelta(seconds=1)
    ).isoformat()
    report = compare_frames(frames)
    assert report["screen_sync"]["before"]["qualified_report"] is True
    assert report["screen_sync"]["after"]["qualified_report"] is True
    assert report["screen_sync"]["continuity_reported"] is False
    assert "screen_color_time_reversed" in report["comparison_blockers"]
    assert report["technical_findings"] == []
    assert light(report, "2")["reported_provenance"] == "unverified_no_final_write_proven"
