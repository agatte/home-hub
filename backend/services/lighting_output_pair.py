"""Offline, non-actuating output-vs-reported-owner comparison for #244.

Two operator-provided snapshots do not prove causality, atomicity, or Hue ACK.
Never feeds a light writer, autonomous learning, or device action.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

from backend.services.lighting_comfort_shadow import audit_snapshot

_LIGHTS = ("1", "2", "3", "4", "5", "6")
_AFTER_DARK = ("evening", "night", "late_night")
_LUMINOUS_SCREENING = {"1": 65, "2": 75}
_FEEDBACK = {"too_dark", "comfortable", "too_bright"}


def _dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _frame(frame: Any) -> tuple[datetime | None, Mapping[str, Any], dict]:
    wrapped = _dict(frame)
    raw = _dict(wrapped.get("snapshot"))
    return _iso(wrapped.get("collected_at")), raw, audit_snapshot(raw)


def _fresh_sync(raw: Mapping[str, Any], collected_at: datetime | None) -> dict:
    status = _dict(raw.get("screen_sync_status"))
    last = _iso(status.get("last_color_at"))
    authority = status.get("authoritative_source")
    targets = status.get("authoritative_targets")
    fresh = (
        collected_at is not None
        and last is not None
        and timedelta(seconds=-2) <= collected_at - last <= timedelta(seconds=10)
    )
    known_targets = (
        isinstance(targets, list)
        and bool(targets)
        and all(isinstance(v, str) and v in _LIGHTS for v in targets)
    )
    qualified = (
        status.get("enabled_mode") is True
        and status.get("source_authority_enforced") is True
        and status.get("last_source_authoritative") is True
        and status.get("last_source") == authority
        and authority in ("desktop", "laptop")
        and known_targets
        and fresh
    )
    return {
        "fresh": bool(fresh),
        "qualified_report": bool(qualified),
        "source": authority if authority in ("desktop", "laptop") else "unknown",
        "targets": sorted(set(targets)) if known_targets and qualified else [],
        "reason": "recent_authoritative_color_report"
        if qualified
        else ("missing_or_stale_frame" if not fresh else "owner_status_not_qualified"),
        "proof_of_hue_write": False,
    }


def _desk_evidence(raw: Mapping[str, Any], report: Mapping[str, Any]) -> tuple[bool, str]:
    """Require two consistent named-source Desk observations, not process inference.

    Merged physical zone may choose Couch/Bed when a stronger/fresher source
    disagrees with Desktop. Such conflicts must abstain, not invent Desk.
    """
    presence = _dict(_dict(raw.get("camera_status")).get("presence"))
    physical = _dict(_dict(report.get("context")).get("physical"))
    latitude = _dict(_dict(presence.get("sources")).get("latitude"))
    if latitude.get("fresh") is True and latitude.get("zone") in ("bed", "couch"):
        return False, "latitude_reports_other_room"
    if presence.get("zone") in ("bed", "couch"):
        return False, "fused_zone_reports_other_room"
    if not physical.get("desk_observation_qualified"):
        return False, "fresh_named_desktop_desk_not_established"
    if presence.get("at_desk_source") != "desktop":
        return False, "named_desk_attribution_not_established"
    if presence.get("zone") != "desk":
        return False, "fused_desk_zone_not_confirmed"
    return True, "source_qualified_physical_desk"


def _automation_cache(raw: Mapping[str, Any], light_id: str) -> dict | None:
    """Whitelisted engine last-applied cache, NOT a final owner or Hue ACK."""
    pipeline = _dict(_dict(raw.get("automation_pipeline")).get("current"))
    output = _dict(pipeline.get("output"))
    candidate = _dict(_dict(output.get("lights")).get(light_id))
    on = candidate.get("on")
    if not isinstance(on, bool):
        return None
    brightness = candidate.get("bri")
    if on:
        if (
            isinstance(brightness, bool)
            or not isinstance(brightness, (float, int))
            or not isfinite(brightness)
            or int(brightness) != brightness
            or not 1 <= brightness <= 254
        ):
            return {"on": on, "bri": None}
        return {"on": on, "bri": int(brightness)}
    return {"on": on, "bri": None}


def _cache_comparison(actual: dict | None, cached: dict | None) -> str:
    if cached is None:
        return "automation_cache_not_available"
    if actual is None:
        return "fixture_not_available"
    if cached["on"] != actual["on"]:
        return "on_state_disagrees_cache_not_final_ack"
    if actual["on"] and (actual["bri"] is None or cached["bri"] is None):
        return "brightness_not_comparable"
    if actual["on"] and actual["bri"] != cached["bri"]:
        return "brightness_disagrees_cache_not_final_ack"
    return "matching_cache_not_final_ack"


def compare_frames(frames: Any) -> dict[str, Any]:
    """Return source-qualified technical hypotheses only, never control advice.

    Each input: {"collected_at": timezone-aware ISO8601, "snapshot": raw GET map}.
    Requires two chronologically close observations, never fetches a device.
    """
    if not isinstance(frames, list) or len(frames) != 2:
        raise ValueError("exactly two operator-provided frames are required")
    first_at, first_raw, first_report = _frame(frames[0])
    last_at, last_raw, last_report = _frame(frames[1])
    blockers: list[str] = []
    if first_at is None or last_at is None:
        blockers.append("missing_timezone_aware_collection_time")
    elif not timedelta(0) < last_at - first_at <= timedelta(minutes=2):
        blockers.append("frame_span_outside_two_minutes")
    bctx = first_report["context"]
    actx = last_report["context"]
    if (bctx["activity"], bctx["period"], bctx["house_state"]) != (
        actx["activity"],
        actx["period"],
        actx["house_state"],
    ):
        blockers.append("mode_period_or_house_changed")
    if actx["house_state"] != "home":
        blockers.append("home_not_confirmed")
    if actx["period"] not in _AFTER_DARK:
        blockers.append("not_after_dark")
    desk_first, desk_first_reason = _desk_evidence(first_raw, first_report)
    desk_last, desk_last_reason = _desk_evidence(last_raw, last_report)
    if not desk_first or not desk_last:
        blockers.append("source_qualified_desk_not_confirmed_in_both_frames")
    for report in (first_report, last_report):
        if report["global_blockers"]:
            blockers.append("one_or_both_frames_have_ownership_blockers")
        if report["context"]["manual_light_count"]:
            blockers.append("manual_light_override_present")
    if not isinstance(_dict(last_raw.get("automation_status")).get("automation_enabled"), bool):
        blockers.append("automation_status_missing")
    ss_before = _fresh_sync(first_raw, first_at)
    ss_after = _fresh_sync(last_raw, last_at)
    before_color_at = _iso(_dict(first_raw.get("screen_sync_status")).get("last_color_at"))
    after_color_at = _iso(_dict(last_raw.get("screen_sync_status")).get("last_color_at"))
    color_time_ordered = (
        before_color_at is not None
        and after_color_at is not None
        and before_color_at <= after_color_at
    )
    if ss_before["qualified_report"] and ss_after["qualified_report"] and not color_time_ordered:
        blockers.append("screen_color_time_reversed")
    sync_continuous = (
        ss_before["qualified_report"]
        and ss_after["qualified_report"]
        and color_time_ordered
        and ss_before["source"] == ss_after["source"]
        and ss_before["targets"] == ss_after["targets"]
    )
    if ss_before["source"] != ss_after["source"]:
        blockers.append("screen_source_changed")
    before_lights = {x["light_id"]: x for x in first_report["lights"]}
    after_lights = {x["light_id"]: x for x in last_report["lights"]}
    rows: list[dict] = []
    findings: list[dict] = []
    for light_id in _LIGHTS:
        previous = before_lights[light_id]["actual"]
        current = after_lights[light_id]["actual"]
        cached_before = _automation_cache(first_raw, light_id)
        cached_after = _automation_cache(last_raw, light_id)
        cache_gap = _cache_comparison(current, cached_after)
        start = previous["bri"] if previous and previous["on"] else None
        end = current["bri"] if current and current["on"] else None
        manual = (
            before_lights[light_id]["ownership_observed"] == "manual"
            or after_lights[light_id]["ownership_observed"] == "manual"
        )
        belongs_to_sync = sync_continuous and not blockers and light_id in ss_after["targets"]
        provenance = (
            "manual_reported"
            if manual
            else (
                "recent_screen_sync_color_correlated"
                if belongs_to_sync
                else "unverified_no_final_write_proven"
            )
        )
        reasons = []
        if previous is None or current is None:
            reasons.append("fixture_missing")
        elif not previous["on"] or not current["on"]:
            reasons.append("off_state_preserve_intent")
        elif start is None or end is None:
            reasons.append("brightness_missing")
        else:
            if end != start:
                reasons.append("actual_brightness_changed")
            if light_id in _LUMINOUS_SCREENING and end <= _LUMINOUS_SCREENING[light_id]:
                reasons.append("low_output_heuristic_only")
            if light_id == "5":
                reasons.append("clear_housing_glare_cap_not_fill_source")
        if (
            not blockers
            and not manual
            and "low_output_heuristic_only" in reasons
            and light_id in _LUMINOUS_SCREENING
        ):
            findings.append(
                {
                    "light_id": light_id,
                    "hypothesis": "recent_screen_sync_report_coincides_with_low_output"
                    if belongs_to_sync
                    else "low_output_under_unverified_final_owner",
                    "status": "inspect_final_owner_and_hue_ack_not_actuation",
                }
            )
        rows.append(
            {
                "light_id": light_id,
                "before": previous,
                "after": current,
                "brightness_delta": end - start if start is not None and end is not None else None,
                "reported_provenance": provenance,
                "automation_last_applied_cache": {
                    "before": cached_before,
                    "after": cached_after,
                },
                "actual_vs_automation_cache": cache_gap,
                "reason_codes": reasons,
            }
        )
    return {
        "kind": "lighting_output_pair_v1",
        "assurance": "non_atomic_correlation_not_causation_or_hue_ack",
        "context": {
            "activity": actx["activity"],
            "period": actx["period"],
            "house_state": actx["house_state"],
            "physical_desk": {
                "both_frames_qualified": desk_first and desk_last,
                "before_reason": desk_first_reason,
                "after_reason": desk_last_reason,
            },
        },
        "screen_sync": {
            "before": ss_before,
            "after": ss_after,
            "continuity_reported": bool(sync_continuous),
        },
        "comparison_blockers": sorted(set(blockers)),
        "rows": rows,
        "technical_findings": findings,
        "limitations": [
            "distinct_GET_endpoints_are_not_atomic",
            "screen_sync_status_does_not_prove_per_light_final_write_or_bridge_ack",
            "automation_last_applied_cache_may_be_stale_or_superseded_by_stronger_writer",
            "camera_brightness_and_hue_bri_are_not_human_comfort_measurements",
            "manual_scene_external_off_protected_ownership_can_be_unobserved",
            "no_recurring_capture_no_control_actions",
        ],
    }


def frozen_feedback(snapshot: Any, preference: str) -> dict[str, Any]:
    """Freeze an explicitly provided rating with minimal pre-feedback context.

    The result never persists, learns, or calls a writer; this is not a UI.
    """
    if not isinstance(preference, str) or preference not in _FEEDBACK:
        raise ValueError("preference must be too_dark, comfortable or too_bright")
    report = audit_snapshot(snapshot)
    ctx = report["context"]
    return {
        "kind": "lighting_feedback_preview_v1",
        "preference": preference,
        "context_before_feedback": {
            "activity": ctx["activity"],
            "period": ctx["period"],
            "house_state": ctx["house_state"],
            "manual_activity": ctx["manual_activity"],
            "manual_light_count": ctx["manual_light_count"],
            "dnd": ctx["dnd"],
            "reported_screen_sync_ids": ctx["screen_sync_reported_ids"],
            "lights": [
                {
                    "light_id": x["light_id"],
                    "on": x["actual"]["on"] if x["actual"] else None,
                    "bri": x["actual"]["bri"] if x["actual"] else None,
                }
                for x in report["lights"]
            ],
        },
        "learning_action": "none_preview_only",
        "writes": False,
    }
