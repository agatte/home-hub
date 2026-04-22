"""
Automation control endpoints — activity reporting, mode overrides, and config.

Receives activity reports from the PC agent (process detection) and ambient
monitor (Blue Yeti mic). Provides the frontend with current automation state
and manual override controls.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from backend.config import settings
from backend.rate_limit import limiter

from backend.api.routes.routines import load_setting, save_setting
from backend.api.schemas.automation import (
    ActivityReport,
    AutomationConfig,
    AutomationStatus,
    LaptopLoopbackToggle,
    ManualOverride,
    MicCalibrationResult,
    ModeBrightnessConfig,
    PresenceConfigSchema,
    ScreenColorReport,
    TimeScheduleConfig,
)
from backend.services.automation_engine import (
    SCREEN_SYNC_MODES,
    DaySchedule,
    ScheduleConfig,
)

SCHEDULE_CONFIG_KEY = "time_schedule_config"
BRIGHTNESS_CONFIG_KEY = "mode_brightness_config"
SCREEN_SYNC_LAPTOP_KEY = "screen_sync_laptop_enabled"
WATCHING_POSTURE_KEY = "watching_posture_config"

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


@router.post("/activity")
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


@router.post("/agent-health")
async def report_agent_health(request: Request) -> dict:
    """Receive health heartbeat from the PC agent supervisor."""
    body = await request.json()
    request.app.state.agent_health = body
    return {"status": "ok"}


@router.get("/agent-health")
async def get_agent_health(request: Request) -> dict:
    """Get the latest agent supervisor health report."""
    health = getattr(request.app.state, "agent_health", None)
    if not health:
        return {"status": "no_report", "agents": {}}
    return health


@router.get("/status")
async def get_status(request: Request) -> AutomationStatus:
    """Get the full automation engine status."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return AutomationStatus()

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
    )


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


@router.post("/override")
@limiter.limit("10/minute")
async def set_override(override: ManualOverride, request: Request) -> dict:
    """
    Manually override the current automation mode.

    Set mode to 'auto' to clear the override and return to automatic detection.
    """
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    if override.mode == "auto":
        await engine.clear_override()
        return {"status": "ok", "message": "Override cleared — returning to auto"}

    await engine.set_manual_override(override.mode)
    return {"status": "ok", "mode": override.mode, "source": "manual"}


@router.post("/screen-color")
async def receive_screen_color(report: ScreenColorReport, request: Request) -> dict:
    """
    Receive a screen color sample from the desktop pc_agent or laptop loopback.

    The current automation mode gates application: colors only reach the
    bedroom lamp if the mode is in SCREEN_SYNC_MODES (gaming, watching).
    Off-mode colors are accepted (so the agent doesn't error) but dropped
    silently — the response distinguishes via the `applied` field.
    """
    engine = getattr(request.app.state, "automation", None)
    sync = getattr(request.app.state, "screen_sync", None)
    if not engine or not sync:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    if engine.current_mode not in SCREEN_SYNC_MODES:
        return {"status": "ok", "applied": False}

    # Pull zone + posture from the camera service so the sync cap can differ
    # between watching-at-desk (brighter bias), watching-in-bed-reclined
    # (hard projector-safe dim), and watching-in-bed-upright (middle ground).
    camera = getattr(request.app.state, "camera_service", None)
    zone = getattr(camera, "zone", None) if camera else None
    posture = getattr(camera, "posture", None) if camera else None

    await sync.apply_color(
        report.r,
        report.g,
        report.b,
        mode=engine.current_mode,
        source=report.source,
        zone=zone,
        posture=posture,
    )
    return {"status": "ok", "applied": True}


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


@router.put("/screen-sync/laptop-enabled")
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


@router.post("/mic/calibrate")
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


@router.put("/config")
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


@router.put("/schedule")
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


@router.put("/mode-brightness")
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
# Watching posture tuning — runtime knobs for projector-in-bed brightness
# ---------------------------------------------------------------------------

@router.get("/watching-posture")
async def get_watching_posture() -> dict:
    """Return the current watching-posture tuning values.

    Reads from persisted storage if present, otherwise returns the defaults
    that match the in-code fallback in screen_sync.py and automation_engine.
    """
    saved = await load_setting(WATCHING_POSTURE_KEY)
    return {**WATCHING_POSTURE_DEFAULTS, **(saved or {})}


@router.put("/watching-posture")
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


@router.put("/mode-scenes/{mode}/{time_period}")
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


@router.delete("/mode-scenes/{mode}/{time_period}")
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


# ------------------------------------------------------------------
# Presence detection
# ------------------------------------------------------------------

PRESENCE_CONFIG_KEY = "presence_config"


@router.get("/presence/status")
async def get_presence_status(request: Request) -> dict:
    """Get current presence detection state."""
    presence = getattr(request.app.state, "presence", None)
    if not presence:
        return {"state": "disabled"}
    return presence.get_status()


@router.get("/presence/config")
async def get_presence_config(request: Request) -> dict:
    """Get presence detection configuration."""
    presence = getattr(request.app.state, "presence", None)
    if not presence:
        return {}
    return presence.config_dict()


@router.put("/presence/config")
async def update_presence_config(
    config: PresenceConfigSchema, request: Request,
) -> dict:
    """Update presence detection configuration."""
    presence = getattr(request.app.state, "presence", None)
    if not presence:
        raise HTTPException(
            status_code=503, detail="Presence service not initialized"
        )
    new_config = config.model_dump()
    await presence.update_config(new_config)
    await save_setting(PRESENCE_CONFIG_KEY, new_config)
    return {"status": "ok"}


@router.post("/presence/test-arrival")
@limiter.limit("2/minute")
async def test_arrival(request: Request) -> dict:
    """Trigger a test arrival sequence (for development/debugging)."""
    import asyncio
    from datetime import timedelta

    presence = getattr(request.app.state, "presence", None)
    if not presence:
        raise HTTPException(
            status_code=503, detail="Presence service not initialized"
        )
    asyncio.create_task(presence._arrival_sequence(timedelta(hours=2)))
    return {"status": "ok", "message": "Test arrival sequence triggered"}


# ---------------------------------------------------------------------------
# Shortcut webhooks — iPhone Personal Automations POST here on WiFi
# connect/disconnect. Shared-secret auth via X-Presence-Token header.
# ---------------------------------------------------------------------------


def _authorize_presence_webhook(request: Request) -> None:
    """Reject the request unless it carries the configured shared secret."""
    expected = settings.PRESENCE_WEBHOOK_TOKEN
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Presence webhook disabled — PRESENCE_WEBHOOK_TOKEN not set",
        )
    supplied = request.headers.get("x-presence-token")
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid presence token")


async def _read_webhook_source(request: Request) -> str:
    """Pull ``source`` from the JSON body, defaulting to ios_shortcut."""
    try:
        body = await request.json()
        if isinstance(body, dict):
            source = body.get("source")
            if isinstance(source, str) and source:
                return source[:64]  # Cap for log hygiene
    except Exception:
        pass
    return "ios_shortcut"


@router.post("/presence/arrived")
@limiter.limit("20/minute")
async def presence_arrived(request: Request) -> dict:
    """
    Webhook: phone just connected to home WiFi.

    Fires the welcome-home ceremony immediately, bypassing the ARP
    debounce. Idempotent — returns ``noop`` if already home.
    """
    _authorize_presence_webhook(request)
    presence = getattr(request.app.state, "presence", None)
    if not presence:
        raise HTTPException(
            status_code=503, detail="Presence service not initialized"
        )

    source = await _read_webhook_source(request)
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "presence.webhook.arrived client=%s source=%s", client_ip, source
    )
    result = await presence.on_shortcut_arrival(source=source)
    return {"status": "ok", "action": result, "state": presence.get_status()["state"]}


@router.post("/presence/departed")
@limiter.limit("20/minute")
async def presence_departed(request: Request) -> dict:
    """
    Webhook: phone just disconnected from home WiFi.

    Fires the departure sequence immediately, bypassing the manual
    override guard (WiFi disconnect is direct evidence of leaving).
    Idempotent — returns ``noop`` if already away.
    """
    _authorize_presence_webhook(request)
    presence = getattr(request.app.state, "presence", None)
    if not presence:
        raise HTTPException(
            status_code=503, detail="Presence service not initialized"
        )

    source = await _read_webhook_source(request)
    client_ip = request.client.host if request.client else "unknown"
    logger.info(
        "presence.webhook.departed client=%s source=%s", client_ip, source
    )
    result = await presence.on_shortcut_departure(source=source)
    return {"status": "ok", "action": result, "state": presence.get_status()["state"]}
