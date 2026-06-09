"""
Automation control endpoints — activity reporting, mode overrides, and config.

Receives activity reports from the PC agent (process detection) and ambient
monitor (Blue Yeti mic). Provides the frontend with current automation state
and manual override controls.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key, source_from_request
from backend.config import settings
from backend.rate_limit import limiter

from backend.api.routes.routines import load_setting, save_setting
from backend.api.schemas.automation import (
    ActivityReport,
    AutomationConfig,
    AutomationStatus,
    DNDRequest,
    LaptopLoopbackToggle,
    ManualOverride,
    MicCalibrationResult,
    ModeBrightnessConfig,
    ModeVolumeCurvesConfig,
    ScreenColorReport,
    TimeScheduleConfig,
)
from backend.services.mode_volume_service import (
    MODE_VOLUME_CURVES_KEY,
    ModeVolumeService,
)
from backend.services.automation_engine import (
    SCREEN_SYNC_MODES,
    DaySchedule,
    ScheduleConfig,
)
from backend.services.light_state_calculator import lux_to_multiplier

SCHEDULE_CONFIG_KEY = "time_schedule_config"
BRIGHTNESS_CONFIG_KEY = "mode_brightness_config"
SCREEN_SYNC_LAPTOP_KEY = "screen_sync_laptop_enabled"
WATCHING_POSTURE_KEY = "watching_posture_config"
RUST_LIGHTING_KEY = "rust_lighting_config"
DND_STATE_KEY = "dnd_state"
OVERRIDE_STATE_KEY = "override_state"

# Settings-page defaults for the watching-posture tuning knobs. The values
# here mirror the hardcoded fall-back in screen_sync.py and automation_engine
# so a fresh SQLite row reads back the same numbers the in-code defaults use.
WATCHING_POSTURE_DEFAULTS = {
    "reclined_sync_cap": 25,   # screen-sync max_bri when watching+bed+reclined
    "reclined_l1_night": 25,   # L1 ambient at night; evening/late_night scale
    "upright_sync_cap":  60,   # screen-sync max_bri when watching+bed+upright
}

logger = logging.getLogger("home_hub.automation")

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.post("/activity", dependencies=[Depends(require_api_key)])
async def report_activity(report: ActivityReport, request: Request) -> dict:
    """
    Receive an activity report from the PC agent or ambient monitor.

    The automation engine decides whether to apply the mode change based on
    priority (gaming > social > watching > working > idle > away) and whether
    a manual override is active.
    """
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    await engine.report_activity(report.mode, report.source, factors=report.factors)

    # Fan the report to the LoL champion service so a champion factor (set
    # only when League's Live Client Data API returned 200) can drive the
    # bedroom-lamp color. Service is gaming-mode-gated internally; non-LoL
    # reports are a cheap no-op.
    lol_service = getattr(request.app.state, "lol_champion_service", None)
    if lol_service is not None:
        await lol_service.on_activity_report(report)

    return {
        "status": "ok",
        "accepted_mode": report.mode,
        "source": report.source,
    }


@router.get("/activity")
async def get_activity(request: Request) -> dict:
    """Get the current detected activity mode."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {"mode": "idle", "source": "none"}

    return {
        "mode": engine.current_mode,
        "source": engine.mode_source,
    }


@router.post("/agent-health", dependencies=[Depends(require_api_key)])
async def report_agent_health(request: Request) -> dict:
    """Receive health heartbeat from the PC agent supervisor."""
    body = await request.json()
    request.app.state.agent_health = body
    # Feed the watchdog so it can detect silence / stuck agents and alert.
    monitor = getattr(request.app.state, "agent_health_monitor", None)
    if monitor is not None:
        await monitor.record_report(body)
    return {"status": "ok"}


@router.get("/agent-health")
async def get_agent_health(request: Request) -> dict:
    """Get the latest agent supervisor health report + watchdog freshness."""
    health = getattr(request.app.state, "agent_health", None)
    monitor = getattr(request.app.state, "agent_health_monitor", None)
    watchdog = monitor.snapshot() if monitor is not None else None
    if not health:
        return {"status": "no_report", "agents": {}, "watchdog": watchdog}
    return {**health, "watchdog": watchdog}


@router.get("/status")
async def get_status(request: Request) -> AutomationStatus:
    """Get the full automation engine status."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return AutomationStatus()

    dnd = engine.dnd_status()
    return AutomationStatus(
        current_mode=engine.current_mode,
        mode_source=engine.mode_source,
        manual_override=engine.manual_override,
        override_mode=engine.override_mode,
        last_activity_change=(
            engine.last_activity_change.isoformat()
            if engine.last_activity_change
            else None
        ),
        automation_enabled=engine.enabled,
        manual_light_overrides=list(engine.manual_light_overrides),
        dnd_enabled=dnd["enabled"],
        dnd_expiry_utc=dnd["expiry_utc"],
        dnd_minutes_remaining=dnd["minutes_remaining"],
        time_period=engine.get_time_period(),
    )


@router.get("/dnd")
async def get_dnd_status(request: Request) -> dict:
    """Get current Do Not Disturb state."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {
            "enabled": False,
            "expiry_utc": None,
            "minutes_remaining": 0,
            "duration_minutes": 0,
        }
    return engine.dnd_status()


@router.post("/dnd", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def enable_dnd_route(req: DNDRequest, request: Request) -> dict:
    """Activate Do Not Disturb for the given duration (default 2h)."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    state = await engine.enable_dnd(req.duration_minutes, source=caller)
    return {"status": "ok", **state}


@router.delete("/dnd", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def clear_dnd_route(request: Request) -> dict:
    """Clear Do Not Disturb immediately."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    state = await engine.clear_dnd(source=caller)
    return {"status": "ok", **state}


@router.get("/pipeline")
async def get_pipeline(request: Request) -> dict:
    """Get the current decision pipeline state and recent history."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {"current": None, "history": []}
    return {
        "current": engine._build_pipeline_state(),
        "history": list(engine._pipeline_history),
    }


@router.post("/override", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def set_override(override: ManualOverride, request: Request) -> dict:
    """
    Manually override the current automation mode.

    Set mode to 'auto' to clear the override and return to automatic detection.
    """
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    # Caller-context label for telemetry — answers "who flipped the override"
    # in journalctl after the fact. Includes the route's own client IP so we
    # can distinguish kiosk dashboard from dev desktop from external scripts.
    # The X-Source header (set by the Alexa lambda) overrides the IP-based
    # default so voice actions surface as `alexa:<intent>` instead of
    # `api:127.0.0.1` (the tunnel proxy's loopback).
    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    if override.mode == "auto":
        await engine.clear_override(source=caller)
        return {"status": "ok", "message": "Override cleared — returning to auto"}

    await engine.set_manual_override(override.mode, source=caller)
    return {"status": "ok", "mode": override.mode, "source": "manual"}


@router.post("/screen-color", dependencies=[Depends(require_api_key)])
async def receive_screen_color(report: ScreenColorReport, request: Request) -> dict:
    """
    Receive a screen color sample from the desktop pc_agent or laptop loopback.

    The current automation mode gates application: colors only reach the
    bedroom lamps if the mode is in SCREEN_SYNC_MODES (gaming, watching).
    Off-mode colors are accepted (so the agent doesn't error) but dropped
    silently — the response distinguishes via the ``applied`` field.

    Mirror dispatch: the single ``{r, g, b}`` is fan-out to every lamp the
    ScreenSyncService manages (currently L2 + L5). Per-light EMA, brightness
    caps, and luma compensation still differentiate the lamps' output —
    the input color is shared, the on-bridge state isn't.
    """
    engine = getattr(request.app.state, "automation", None)
    sync = getattr(request.app.state, "screen_sync", None)
    if not engine or not sync:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    if engine.current_mode not in SCREEN_SYNC_MODES:
        return {"status": "ok", "applied": False}

    # Pull zone + posture so the sync cap can differ between watching-at-desk
    # (brighter bias, L2 cap 180) and the dim couch/reclined variants. Source
    # from PresenceFusion, NOT the raw Latitude camera: since the 2026-05-27
    # living-room move the Latitude sees the COUCH (its ``zone`` is null when
    # nobody's there), so reading it directly hid the ``desk`` zone the desktop
    # pc_agent owns — the watching-desk L2 cap silently stopped firing for
    # screen-sync while the user watches at the desk. ``latest_zone()`` fuses
    # both sources (falls back to "desk" on a fresh desktop face), mirroring how
    # the engine's own light application already resolves zone. Falls back to
    # the raw camera if fusion isn't wired (boot / tests). Bed-variant caps stay
    # in MODE_ZONE_MAX_BRIGHTNESS for revival pending a future bed-zone source.
    presence = getattr(request.app.state, "presence", None)
    camera = getattr(request.app.state, "camera_service", None)
    if presence is not None:
        zone = presence.latest_zone()
        posture = presence.latest_posture()
    else:
        zone = getattr(camera, "zone", None) if camera else None
        posture = getattr(camera, "posture", None) if camera else None

    # Time period drives the per-period cap/floor envelope so the lamps
    # dim alongside the room as evening rolls into night.
    period = engine._get_time_period()

    # Rust profile: hold a fixed ember color and drive the bedroom lamps'
    # BRIGHTNESS from the screen's whole-frame luma, so the room dims as Rust's
    # day/night cycle goes dark (the user's "dark in game → dimmer room" ask).
    # Color is NOT synced — Rust has no coherent ambient color. Both L2 and L5
    # are luma-driven on per-light envelopes (L5 subordinate, ~50-55% of L2) so
    # the clear-housing accent dims WITH L2 instead of towering over it when L2
    # floors out (the glare-pop the curator flagged + live feedback confirmed
    # 2026-06-08). Other games fall through to the per-frame color sync below.
    if getattr(engine, "current_game", None) == "rust":
        luma = report.luma
        if luma is None:
            # Transitional fallback for an agent that predates the `luma` field
            # — derive it from the dominant color (a worse signal than real
            # frame luma, but keeps the path live until the desktop agent
            # restart ships it).
            luma = int(0.299 * report.r + 0.587 * report.g + 0.114 * report.b)
        applied_rust: list[str] = []
        skipped_rust: dict[str, str] = {}
        for target in ("2", "5"):
            if target not in sync.target_lights:
                skipped_rust[target] = "no_target"
                continue
            if target in engine.manual_light_overrides:
                skipped_rust[target] = "manual_override"
                continue
            await sync.apply_rust_brightness(
                target, luma, period=period, source=report.source,
            )
            applied_rust.append(target)
        resp: dict = {
            "status": "ok", "applied": bool(applied_rust),
            "lights": applied_rust, "profile": "rust",
        }
        if skipped_rust:
            resp["skipped"] = skipped_rust
        return resp

    # Ambient envelope lift: lux + weather scale the cap+floor so dim content
    # in a dim room doesn't drag L2 to eye-strain dimness. The screen-sync
    # service gates this internally (``_scale_for_ambient``): gaming + watching,
    # all periods, L2 only (L5's clear housing keeps its static caps to avoid
    # glare). Widened from gaming-day-only on 2026-06-02 (D4 task #7).
    #
    # D4 Part E: source the lux from the BEDROOM desktop-webcam channel, NOT
    # the living-room Latitude camera — L2/L5 are bedroom lamps, and a bright
    # living room must not dim them (the cross-room contamination that got
    # gaming dropped from LUX_MODES; bit us live 2026-06-02, living-room
    # mult 0.897 was throttling the bedroom gaming floors). Falls back to
    # neutral 1.0 when the channel is uncalibrated or stale (>60s ≈ 2.4×
    # the ~25s sample cadence, so a single missed sample can't flicker the
    # floor).
    lux_mult = 1.0
    bedroom_lux = getattr(request.app.state, "bedroom_lux", None)
    if bedroom_lux is not None and bedroom_lux.is_fresh(60.0):
        ema_lux = bedroom_lux.ema_lux
        baseline_lux = bedroom_lux.baseline_lux
        if ema_lux is not None and baseline_lux is not None:
            lux_mult = lux_to_multiplier(ema_lux, baseline_lux)
    weather_condition = engine._get_current_weather_condition()

    # Per-light skip gate. A lamp may sit out a frame because the user
    # dragged its slider (manual_light_overrides) or because the LoL
    # champion service owns it mid-match.
    lol_service = getattr(request.app.state, "lol_champion_service", None)
    applied: list[str] = []
    skipped: list[str] = []
    skip_reasons: dict[str, str] = {}
    for light_id in sync.target_lights:
        if light_id in engine.manual_light_overrides:
            skipped.append(light_id)
            skip_reasons[light_id] = "manual_override"
            continue
        if lol_service is not None and lol_service.is_owning(light_id):
            skipped.append(light_id)
            skip_reasons[light_id] = "lol_champion"
            continue
        await sync.apply_color(
            light_id,
            report.r,
            report.g,
            report.b,
            mode=engine.current_mode,
            source=report.source,
            zone=zone,
            posture=posture,
            period=period,
            lux_multiplier=lux_mult,
            weather_condition=weather_condition,
        )
        applied.append(light_id)

    response: dict = {"status": "ok", "applied": bool(applied), "lights": applied}
    if skipped:
        response["skipped"] = skipped
        response["skip_reasons"] = skip_reasons
        # ``reason`` retained for back-compat; reports the first skip's reason.
        response["reason"] = skip_reasons[skipped[0]]
    return response


@router.get("/screen-sync/status")
async def get_screen_sync_status(request: Request) -> dict:
    """
    Current screen sync state — whether the mode gate is open, when the
    last color arrived, what posted it, and whether the laptop loopback is on.
    """
    engine = getattr(request.app.state, "automation", None)
    sync = getattr(request.app.state, "screen_sync", None)
    loopback = getattr(request.app.state, "laptop_loopback", None)

    enabled_mode = (
        engine.current_mode in SCREEN_SYNC_MODES if engine else False
    )
    last_color_at = (
        sync.last_color_at.isoformat()
        if sync and sync.last_color_at
        else None
    )
    last_source = sync.last_source if sync else None
    laptop_loopback_running = loopback.running if loopback else False

    return {
        "enabled_mode": enabled_mode,
        "current_mode": engine.current_mode if engine else None,
        "last_color_at": last_color_at,
        "last_source": last_source,
        "laptop_loopback_enabled": laptop_loopback_running,
    }


@router.put("/screen-sync/laptop-enabled", dependencies=[Depends(require_api_key)])
async def set_laptop_loopback(
    toggle: LaptopLoopbackToggle, request: Request
) -> dict:
    """
    Toggle the in-process laptop screen capture loopback.

    This is the escape hatch for the rare TV-on-laptop scenario. Default off.
    Persists across restarts via the `screen_sync_laptop_enabled` app_setting.
    """
    loopback = getattr(request.app.state, "laptop_loopback", None)
    if loopback is None:
        raise HTTPException(
            status_code=503, detail="Laptop loopback not initialized"
        )

    if toggle.enabled:
        await loopback.start()
    else:
        await loopback.stop()

    await save_setting(SCREEN_SYNC_LAPTOP_KEY, {"enabled": toggle.enabled})
    logger.info(f"Laptop screen sync loopback set to enabled={toggle.enabled}")

    return {"status": "ok", "enabled": toggle.enabled}


@router.post("/mic/calibrate", dependencies=[Depends(require_api_key)])
async def calibrate_mic(request: Request) -> MicCalibrationResult:
    """
    Calibrate the ambient noise baseline.

    Measures background noise for 5 seconds and sets the detection threshold
    to 2x the average (to avoid false positives from normal room noise).
    """
    # This endpoint is a placeholder — actual calibration runs on the
    # ambient_monitor script. The server stores the threshold for reference.
    return MicCalibrationResult(threshold=800, avg_floor=400.0)


@router.get("/config")
async def get_config(request: Request) -> AutomationConfig:
    """Get current automation configuration."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return AutomationConfig()

    return AutomationConfig(
        enabled=engine.enabled,
        override_timeout_hours=engine.override_timeout_hours,
        gaming_effect=engine.gaming_effect,
    )


@router.put("/config", dependencies=[Depends(require_api_key)])
async def update_config(config: AutomationConfig, request: Request) -> dict:
    """Update automation configuration."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    engine.enabled = config.enabled
    engine.override_timeout_hours = config.override_timeout_hours
    engine.gaming_effect = config.gaming_effect

    logger.info(f"Automation config updated: enabled={config.enabled}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Schedule config
# ---------------------------------------------------------------------------

def _dict_to_schedule_config(data: dict) -> ScheduleConfig:
    """Convert saved JSON dict to ScheduleConfig dataclass."""
    import dataclasses
    valid_fields = {f.name for f in dataclasses.fields(DaySchedule)}

    config = ScheduleConfig()
    if "weekday" in data:
        filtered = {k: v for k, v in data["weekday"].items() if k in valid_fields}
        config.weekday = DaySchedule(**filtered)
    if "weekend" in data:
        filtered = {k: v for k, v in data["weekend"].items() if k in valid_fields}
        config.weekend = DaySchedule(**filtered)
    return config


@router.get("/schedule")
async def get_schedule(request: Request) -> dict:
    """Get the current time-based lighting schedule."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return TimeScheduleConfig().model_dump()

    sc = engine.schedule_config
    return {
        "weekday": {
            "wake_hour": sc.weekday.wake_hour,
            "wake_brightness": sc.weekday.wake_brightness,
            "ramp_start_hour": sc.weekday.ramp_start_hour,
            "ramp_duration_minutes": sc.weekday.ramp_duration_minutes,
            "evening_start_hour": sc.weekday.evening_start_hour,
            "winddown_start_hour": sc.weekday.winddown_start_hour,
            "late_night_start_hour": sc.weekday.late_night_start_hour,
        },
        "weekend": {
            "wake_hour": sc.weekend.wake_hour,
            "wake_brightness": sc.weekend.wake_brightness,
            "ramp_start_hour": sc.weekend.ramp_start_hour,
            "ramp_duration_minutes": sc.weekend.ramp_duration_minutes,
            "evening_start_hour": sc.weekend.evening_start_hour,
            "winddown_start_hour": sc.weekend.winddown_start_hour,
            "late_night_start_hour": sc.weekend.late_night_start_hour,
        },
    }


@router.put("/schedule", dependencies=[Depends(require_api_key)])
async def update_schedule(config: TimeScheduleConfig, request: Request) -> dict:
    """Update the time-based lighting schedule."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    # Convert to engine dataclass
    schedule = ScheduleConfig(
        weekday=DaySchedule(**config.weekday.model_dump()),
        weekend=DaySchedule(**config.weekend.model_dump()),
    )
    engine.update_schedule_config(schedule)

    # Persist to database
    await save_setting(SCHEDULE_CONFIG_KEY, config.model_dump())

    logger.info("Time schedule updated")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Mode brightness
# ---------------------------------------------------------------------------

@router.get("/mode-brightness")
async def get_mode_brightness(request: Request) -> dict:
    """Get per-mode brightness multipliers."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return ModeBrightnessConfig().model_dump()

    return engine.mode_brightness


@router.put("/mode-brightness", dependencies=[Depends(require_api_key)])
async def update_mode_brightness(
    config: ModeBrightnessConfig, request: Request
) -> dict:
    """Update per-mode brightness multipliers."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    brightness = config.model_dump()
    engine.update_mode_brightness(brightness)

    # Persist to database
    await save_setting(BRIGHTNESS_CONFIG_KEY, brightness)

    logger.info(f"Mode brightness updated: {brightness}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Mode volume curves (GH#17 — per-mode Sonos volume targets + fade)
# ---------------------------------------------------------------------------

@router.get("/mode-volume")
async def get_mode_volume() -> dict:
    """Return the merged per-mode volume curves (defaults + persisted overrides)."""
    persisted = await load_setting(MODE_VOLUME_CURVES_KEY)
    return ModeVolumeService.merged_config(persisted)


@router.put("/mode-volume", dependencies=[Depends(require_api_key)])
async def update_mode_volume(
    config: ModeVolumeCurvesConfig, request: Request
) -> dict:
    """Update per-mode Sonos volume curves.

    Partial updates supported — any mode set to None is left at its
    previous persisted value (or the default if no persisted value exists).
    """
    src = source_from_request(request, fallback="api:automation")
    incoming = config.model_dump(exclude_none=True)
    existing = await load_setting(MODE_VOLUME_CURVES_KEY) or {}
    # Merge: incoming overrides existing per-mode, but preserves other modes.
    merged: dict[str, dict[str, int]] = {**existing, **incoming}
    await save_setting(MODE_VOLUME_CURVES_KEY, merged)
    logger.info("Mode volume curves updated by %s: %s", src, list(incoming.keys()))
    return {"status": "ok", "config": merged}


# ---------------------------------------------------------------------------
# Watching posture tuning — runtime knobs for projector-in-bed brightness.
# DORMANT since 2026-05-27 (Latitude→living-room move retired the zone="bed"
# source the underlying overlay branches depend on); endpoint + storage kept
# so values stay editable for revival pending a future bed-zone source.
# ---------------------------------------------------------------------------

@router.get("/watching-posture")
async def get_watching_posture() -> dict:
    """Return the current watching-posture tuning values.

    Reads from persisted storage if present, otherwise returns the defaults
    that match the in-code fallback in screen_sync.py and automation_engine.
    """
    saved = await load_setting(WATCHING_POSTURE_KEY)
    return {**WATCHING_POSTURE_DEFAULTS, **(saved or {})}


@router.put("/watching-posture", dependencies=[Depends(require_api_key)])
async def update_watching_posture(config: dict, request: Request) -> dict:
    """Update the watching-posture tuning values.

    Accepts any subset of the three keys; each value is clamped to 1..100.
    Writes through to the live screen_sync + automation engine so the change
    takes effect on the next reconciliation without a restart.
    """
    cleaned: dict[str, int] = {}
    for key in WATCHING_POSTURE_DEFAULTS:
        if key in config and config[key] is not None:
            cleaned[key] = max(1, min(100, int(config[key])))

    if not cleaned:
        raise HTTPException(status_code=400, detail="No valid keys provided")

    saved = await load_setting(WATCHING_POSTURE_KEY) or {}
    merged = {**WATCHING_POSTURE_DEFAULTS, **saved, **cleaned}
    await save_setting(WATCHING_POSTURE_KEY, merged)

    sync = getattr(request.app.state, "screen_sync", None)
    engine = getattr(request.app.state, "automation", None)
    if sync is not None:
        sync.set_cap_override("watching", "bed", "reclined", merged["reclined_sync_cap"])
        sync.set_cap_override("watching", "bed", "upright",  merged["upright_sync_cap"])
    if engine is not None:
        engine.set_bed_reclined_l1_night(merged["reclined_l1_night"])

    logger.info(f"Watching posture tuning updated: {cleaned}")
    return {"status": "ok", "config": merged}


@router.get("/rust-lighting")
async def get_rust_lighting(request: Request) -> dict:
    """Return the live Rust luma-brightness config (envelope + ember + luma).

    Reads from the live screen_sync service so it reflects defaults merged with
    any persisted tweaks. Shape matches the PUT body. 503 if screen_sync isn't
    wired (boot/tests)."""
    sync = getattr(request.app.state, "screen_sync", None)
    if sync is None:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")
    return {"status": "ok", "config": sync.get_rust_config()}


@router.put("/rust-lighting", dependencies=[Depends(require_api_key)])
async def update_rust_lighting(config: dict, request: Request) -> dict:
    """Live-tune the Rust luma-brightness profile WITHOUT a redeploy.

    Accepts a full or partial config — e.g. ``{"envelope": {"2": {"night":
    [50, 170]}}}`` bumps only L2's night range. The service validates/clamps,
    applies it to the live knobs (effective on the next screen-color frame,
    ~2.5s), and the full resolved config is persisted to app_settings so it
    survives restarts. This is the no-deploy tuning loop for "a tad dimmer /
    brighter" feedback."""
    sync = getattr(request.app.state, "screen_sync", None)
    if sync is None:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    merged = sync.apply_rust_config(config)
    await save_setting(RUST_LIGHTING_KEY, merged)
    logger.info("Rust lighting config updated: %s", config)
    return {"status": "ok", "config": merged}


# ---------------------------------------------------------------------------
# Mode → Scene overrides (use Hue scenes instead of hardcoded light states)
# ---------------------------------------------------------------------------

VALID_MODES = {"gaming", "working", "watching", "relax", "cooking", "social"}
VALID_PERIODS = {"day", "evening", "night"}


@router.get("/mode-scenes")
async def get_mode_scene_overrides(request: Request) -> dict:
    """List all mode → scene overrides."""
    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(ModeSceneOverride))
        overrides = result.scalars().all()

    return {
        "overrides": [
            {
                "mode": o.mode,
                "time_period": o.time_period,
                "scene_id": o.scene_id,
                "scene_source": o.scene_source,
                "scene_name": o.scene_name,
            }
            for o in overrides
        ]
    }


@router.put("/mode-scenes/{mode}/{time_period}", dependencies=[Depends(require_api_key)])
async def set_mode_scene_override(
    mode: str, time_period: str, request: Request
) -> dict:
    """Map a scene to a mode + time period, overriding default light states."""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    if time_period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period: {time_period}")

    body = await request.json()
    scene_id = body.get("scene_id")
    scene_source = body.get("scene_source", "bridge")
    scene_name = body.get("scene_name", "")

    if not scene_id:
        raise HTTPException(status_code=400, detail="scene_id is required")

    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(ModeSceneOverride).where(
                ModeSceneOverride.mode == mode,
                ModeSceneOverride.time_period == time_period,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.scene_id = scene_id
            existing.scene_source = scene_source
            existing.scene_name = scene_name
        else:
            session.add(ModeSceneOverride(
                mode=mode,
                time_period=time_period,
                scene_id=scene_id,
                scene_source=scene_source,
                scene_name=scene_name,
            ))
        await session.commit()

    # Reload overrides cache in the automation engine
    engine = getattr(request.app.state, "automation", None)
    if engine:
        await engine.load_scene_overrides()

    logger.info("Mode scene override set: %s/%s → %s (%s)", mode, time_period, scene_name, scene_source)
    return {"status": "ok"}


@router.delete("/mode-scenes/{mode}/{time_period}", dependencies=[Depends(require_api_key)])
async def delete_mode_scene_override(
    mode: str, time_period: str, request: Request
) -> dict:
    """Remove a mode → scene override, reverting to default light states."""
    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(ModeSceneOverride).where(
                ModeSceneOverride.mode == mode,
                ModeSceneOverride.time_period == time_period,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.commit()

    # Reload overrides cache
    engine = getattr(request.app.state, "automation", None)
    if engine:
        await engine.load_scene_overrides()

    logger.info("Mode scene override removed: %s/%s", mode, time_period)
    return {"status": "ok"}


# Phone-presence detection (WiFi/ARP/iPhone Shortcut webhooks) was retired
# 2026-04-27 — iOS Shortcut flap was unfixable, BLE-on-iPhone is impractical
# without a custom app, and camera + activity signals already cover "is
# someone here?". Hue native geofencing handles arrival/departure lighting.
