"""Pure, non-actuating technical lighting-comfort shadow audit.

This module does not infer subjective comfort or grant authority to brighten
lights. It reads supplied snapshots, removes unnecessary personal/source detail,
and compares the visible Hue state with *uncomposed* authored mode targets.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping

from backend.services.light_state_calculator import (
    ACTIVITY_LIGHT_STATES,
    ALL_LIGHT_IDS,
    resolve_activity_state,
)

PERIODS = ("day", "evening", "night", "late_night")
MODES = ("general", "working", "watching", "gaming", "relax", "social", "cooking")
# Screening thresholds, NOT comfort levels, safety floors, or actuation targets.
_SCREENING_MAXIMUM = {"1": 65, "2": 75}
_PHYSICAL_ZONES = {"desk", "couch", "bed"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _one_of(value: Any, permitted: tuple[str, ...] | set[str]) -> str | None:
    return value if isinstance(value, str) and value in permitted else None


def _brightness(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not isfinite(value) or int(value) != value or not 1 <= value <= 254:
        return None
    return int(value)


def _proxy_ratio(reading: Any) -> dict[str, Any]:
    """Expose only camera-proxy calibration and a coarse relative-light bucket."""
    d = _mapping(reading)
    calibrated = d.get("calibrated") is True
    reading_lux, baseline = d.get("ema_lux"), d.get("baseline_lux")
    if (
        not calibrated
        or isinstance(reading_lux, bool)
        or isinstance(baseline, bool)
        or not isinstance(reading_lux, (int, float))
        or not isinstance(baseline, (int, float))
        or not isfinite(reading_lux)
        or not isfinite(baseline)
        or reading_lux < 0
        or baseline <= 0
    ):
        return {"calibration_reported": calibrated, "relative_bucket": "unknown"}
    ratio = reading_lux / baseline
    bucket = (
        "below_half_baseline"
        if ratio < 0.5
        else ("below_baseline" if ratio < 0.9 else "at_or_above_baseline")
    )
    return {"calibration_reported": True, "relative_bucket": bucket}


def _actual_lights(value: Any) -> dict[str, dict[str, Any]]:
    """Whitelisted fixture data only; discard names and arbitrary device fields."""
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        light = _mapping(item)
        identifier = light.get("light_id")
        if not isinstance(identifier, str) or identifier not in ALL_LIGHT_IDS:
            continue
        on = light.get("on")
        if not isinstance(on, bool) or identifier in result:
            continue
        brightness = _brightness(light.get("bri")) if on else None
        result[identifier] = {"on": on, "bri": brightness}
    return result


def _physical_context(camera: Any) -> dict[str, Any]:
    presence = _mapping(_mapping(camera).get("presence"))
    sources = _mapping(presence.get("sources"))
    desktop = _mapping(sources.get("desktop"))
    latitude = _mapping(sources.get("latitude"))
    zone = _one_of(presence.get("zone"), _PHYSICAL_ZONES)
    # A fused zone on its own is not an authorization to brighten anything.
    qualified_desk = (
        presence.get("at_desk_fresh") is True
        and desktop.get("fresh") is True
        and desktop.get("face_present") is True
        and desktop.get("zone") == "desk"
    )
    return {
        "zone_reported": zone,
        "desk_observation_qualified": qualified_desk,
        "desktop_source_fresh": desktop.get("fresh") is True,
        "latitude_source_fresh": latitude.get("fresh") is True,
        "strong_presence_reported": presence.get("strongly_present") is True,
    }


def audit_snapshot(snapshot: Any) -> dict[str, Any]:
    """Compare a supplied raw API snapshot; never alter any attached system.

    This is a diagnostic/provenance triage only. Mode states are authored bases,
    NOT the final learner, weather, ScreenSync, external-scene or owner output.
    """
    payload = _mapping(snapshot)
    status = _mapping(payload.get("automation_status"))
    pipeline = _mapping(_mapping(payload.get("automation_pipeline")).get("current"))
    inputs = _mapping(pipeline.get("inputs"))
    scene = _mapping(inputs.get("scene_override"))
    sync = _mapping(payload.get("screen_sync_status"))
    observed_mode = status.get("current_mode")
    # Internal idle maps to the user-facing General fallback, never Away.
    mode = "general" if observed_mode == "idle" else _one_of(observed_mode, MODES)
    period = _one_of(status.get("time_period"), PERIODS)
    house = _one_of(status.get("house_state"), {"home", "away", "winding_down", "sleeping"})
    manual_mode = status.get("manual_override") is True
    dnd = status.get("dnd_enabled") is True
    manual_ids = status.get("manual_light_overrides")
    manual_ids = (
        set(manual_ids) & set(ALL_LIGHT_IDS)
        if (isinstance(manual_ids, list) and all(isinstance(x, str) for x in manual_ids))
        else set()
    )
    scene_override = scene.get("active") is True or scene.get("applied") is True

    sync_targets = sync.get("authoritative_targets")
    sync_ids = (
        set(sync_targets) & set(ALL_LIGHT_IDS)
        if (
            sync.get("enabled_mode") is True
            and sync.get("last_source_authoritative") is True
            and isinstance(sync_targets, list)
            and all(isinstance(x, str) for x in sync_targets)
        )
        else set()
    )
    physical = _physical_context(payload.get("camera_status"))
    actual = _actual_lights(payload.get("lights"))
    authored = resolve_activity_state(mode, period) if mode and period else {}

    context = {
        "house_state": house,
        "activity": mode,
        "period": period,
        "mode_source": _one_of(
            status.get("mode_source"),
            {"process", "manual", "ambient", "api", "schedule", "scene"},
        )
        or "unknown",
        "manual_activity": manual_mode,
        "manual_light_count": len(manual_ids),
        "dnd": dnd,
        "scene_override_reported": scene_override,
        "screen_sync_reported_ids": sorted(sync_ids),
        "physical": physical,
        "bedroom_camera_proxy": _proxy_ratio(payload.get("bedroom_lux")),
        "living_room_camera_proxy": _proxy_ratio(payload.get("camera_status")),
    }
    global_blockers = []
    if house != "home":
        global_blockers.append("home_awake_not_established")
    if dnd:
        global_blockers.append("dnd")
    if manual_mode:
        global_blockers.append("manual_activity_requires_review")
    if not isinstance(status.get("manual_override"), bool):
        global_blockers.append("manual_activity_ownership_unknown")
    if status.get("automation_enabled") is not True:
        global_blockers.append("automation_not_confirmed_enabled")
    if scene_override:
        global_blockers.append("explicit_scene")
    if not mode or not period:
        global_blockers.append("missing_mode_or_period")
    if not isinstance(status.get("dnd_enabled"), bool):
        global_blockers.append("dnd_status_unknown")
    if not isinstance(manual_ids_source := status.get("manual_light_overrides"), list) or not all(
        isinstance(identifier, str) for identifier in manual_ids_source
    ):
        global_blockers.append("manual_light_ownership_unknown")
    if not isinstance(scene.get("active"), bool):
        global_blockers.append("scene_ownership_unknown")
    if not isinstance(sync.get("enabled_mode"), bool) or (
        sync.get("enabled_mode") is True
        and (
            not isinstance(sync.get("authoritative_targets"), list)
            or not isinstance(sync.get("last_source_authoritative"), bool)
        )
    ):
        global_blockers.append("screen_sync_ownership_unknown")

    rows = []
    review = []
    diagnostic_findings = []
    for identifier in ALL_LIGHT_IDS:
        physical_state = actual.get(identifier)
        target = _mapping(authored.get(identifier))
        target_on = target.get("on") if isinstance(target.get("on"), bool) else None
        target_bri = _brightness(target.get("bri")) if target_on is True else None
        reasons = []
        if physical_state is None:
            reasons.append("actual_unavailable")
        if not target:
            reasons.append("authored_target_unavailable")
        if identifier in manual_ids:
            reasons.append("manual_light_protected")
        if identifier in sync_ids:
            reasons.append("screen_sync_reports_ownership")
        if scene_override:
            reasons.append("scene_overrides_static_target")
        if physical_state is not None and physical_state["on"] is False and target_on is True:
            reasons.append("light_off_do_not_relight")
        if (
            physical_state is not None
            and physical_state["on"] is True
            and physical_state["bri"] is not None
            and target_bri is not None
            and physical_state["bri"] < target_bri * 0.65
        ):
            reasons.append("actual_below_uncomposed_static_target")
        if (
            period in ("evening", "night", "late_night")
            and identifier in _SCREENING_MAXIMUM
            and physical_state is not None
            and physical_state["on"] is True
            and physical_state["bri"] is not None
            and physical_state["bri"] <= _SCREENING_MAXIMUM[identifier]
        ):
            reasons.append("low_observed_brightness_screening")
        if (
            mode
            and period in ("evening", "night", "late_night")
            and identifier in _SCREENING_MAXIMUM
            and target_on is True
            and target_bri is not None
            and target_bri <= _SCREENING_MAXIMUM[identifier]
        ):
            reasons.append("low_authored_brightness_screening")
        if (
            identifier == "2"
            and mode == "watching"
            and period in ("evening", "night", "late_night")
            and identifier in sync_ids
            and "low_observed_brightness_screening" in reasons
        ):
            diagnostic_findings.append(
                {
                    "light_id": identifier,
                    "reason": "screen_sync_reports_low_output_at_bedroom_l2",
                    "status": "technical_investigation_not_brightness_authority",
                }
            )
        # A shadow review is allowed only for an awake, positively qualified
        # desk with no known stronger owner. Not a device-write authorization.
        relevant_desk = identifier == "2" and physical["desk_observation_qualified"]
        eligible = (
            relevant_desk
            and not global_blockers
            and identifier not in manual_ids
            and identifier not in sync_ids
            and physical_state is not None
            and physical_state["on"] is True
            and physical_state["bri"] is not None
            and target_on is True
            and target_bri is not None
        )
        if eligible and (
            "low_authored_brightness_screening" in reasons
            or "actual_below_uncomposed_static_target" in reasons
        ):
            review.append(
                {
                    "light_id": identifier,
                    "reason_codes": [
                        reason
                        for reason in reasons
                        if reason
                        in {
                            "low_authored_brightness_screening",
                            "actual_below_uncomposed_static_target",
                        }
                    ],
                    "status": "human_review_only",
                }
            )
        rows.append(
            {
                "light_id": identifier,
                "actual": physical_state,
                "authored_base": {"on": target_on, "bri": target_bri},
                "ownership_observed": "manual"
                if identifier in manual_ids
                else ("screen_sync" if identifier in sync_ids else "unverified"),
                "reason_codes": reasons,
            }
        )
    return {
        "kind": "lighting_comfort_shadow_v1",
        "assurance": "technical_screening_not_photometric_or_subjective_comfort",
        "context": context,
        "global_blockers": global_blockers,
        "lights": rows,
        "review_candidates": review,
        "diagnostic_findings": diagnostic_findings,
        "uncertainties": [
            "static_targets_not_final_owner_dispatch",
            "screen_sync_status_not_proven_same_frame_or_ack",
            "camera_brightness_not_eye_level_lux",
            "camera_presence_tags_not_device_attestation",
            "no_automatic_brightness_change_authorized",
        ],
    }


def audit_authored_matrix() -> dict[str, Any]:
    """Offline uncomposed authored-base audit (not a mode/owner replay)."""
    rows = []
    for mode in MODES:
        flat = "day" not in _mapping(ACTIVITY_LIGHT_STATES.get(mode))
        for period in PERIODS:
            state = resolve_activity_state(mode, period)
            low = []
            for identifier, threshold in _SCREENING_MAXIMUM.items():
                item = _mapping(state.get(identifier))
                if item.get("on") is True:
                    brightness = _brightness(item.get("bri"))
                    if period != "day" and brightness is not None and brightness <= threshold:
                        low.append(
                            {
                                "light_id": identifier,
                                "authored_bri": brightness,
                                "reason": "low_static_brightness_screening",
                            }
                        )
            rows.append(
                {
                    "activity": mode,
                    "period": period,
                    "flat_palette": flat,
                    "low_output_to_review": low,
                }
            )
    return {
        "kind": "lighting_authored_matrix_shadow_v1",
        "assurance": "authored_base_only_not_final_dispatch_or_room_comfort",
        "screening_thresholds_only": dict(_SCREENING_MAXIMUM),
        "row_count": len(rows),
        "rows": rows,
    }
