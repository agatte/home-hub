"""
Automation control endpoints — activity reporting, mode overrides, and config.

Receives activity reports from the PC agent (process detection) and ambient
monitor (Blue Yeti mic). Provides the frontend with current automation state
and manual override controls.
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from backend.api.routes.routines import load_setting, save_setting
from backend.api.schemas.automation import (
    ActivityReport,
    AutomationConfig,
    AutomationStatus,
    ManualOverride,
    MicCalibrationResult,
    ModeBrightnessConfig,
    TimeScheduleConfig,
)
from backend.services.automation_engine import DaySchedule, ScheduleConfig

SCHEDULE_CONFIG_KEY = "time_schedule_config"
BRIGHTNESS_CONFIG_KEY = "mode_brightness_config"

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

    await engine.report_activity(report.mode, report.source)

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
    )


@router.post("/override")
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


@router.get("/social-styles")
async def get_social_styles(request: Request) -> dict:
    """List available party sub-modes for social mode."""
    from backend.services.automation_engine import SOCIAL_STYLES

    engine = getattr(request.app.state, "automation", None)
    current = engine.social_style if engine else "color_cycle"

    return {
        "styles": [
            {
                "id": style_id,
                "display_name": style["display_name"],
                "description": style["description"],
            }
            for style_id, style in SOCIAL_STYLES.items()
        ],
        "active": current,
    }


@router.post("/social-style")
async def set_social_style(request: Request) -> dict:
    """Switch the active party sub-mode."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    body = await request.json()
    style = body.get("style", "")

    from backend.services.automation_engine import SOCIAL_STYLES
    if style not in SOCIAL_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown style: {style}. Options: {list(SOCIAL_STYLES.keys())}",
        )

    await engine.set_social_style(style)
    return {"status": "ok", "style": style}


@router.get("/screen-sync/status")
async def get_screen_sync_status(request: Request) -> dict:
    """Check if screen sync is running."""
    engine = getattr(request.app.state, "automation", None)
    sync = engine.screen_sync if engine else None
    running = sync._running if sync else False
    return {"running": running}


@router.post("/screen-sync/start")
async def start_screen_sync(request: Request) -> dict:
    """Manually start screen sync."""
    engine = getattr(request.app.state, "automation", None)
    sync = engine.screen_sync if engine else None
    if not sync:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    await sync.start()
    return {"status": "ok", "running": True}


@router.post("/screen-sync/stop")
async def stop_screen_sync(request: Request) -> dict:
    """Manually stop screen sync."""
    engine = getattr(request.app.state, "automation", None)
    sync = engine.screen_sync if engine else None
    if not sync:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    await sync.stop()
    return {"status": "ok", "running": False}


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
        social_effect=engine.social_effect,
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
    engine.social_effect = config.social_effect

    logger.info(f"Automation config updated: enabled={config.enabled}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Schedule config
# ---------------------------------------------------------------------------

def _dict_to_schedule_config(data: dict) -> ScheduleConfig:
    """Convert saved JSON dict to ScheduleConfig dataclass."""
    config = ScheduleConfig()
    if "weekday" in data:
        config.weekday = DaySchedule(**data["weekday"])
    if "weekend" in data:
        config.weekend = DaySchedule(**data["weekend"])
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
        },
        "weekend": {
            "wake_hour": sc.weekend.wake_hour,
            "wake_brightness": sc.weekend.wake_brightness,
            "ramp_start_hour": sc.weekend.ramp_start_hour,
            "ramp_duration_minutes": sc.weekend.ramp_duration_minutes,
            "evening_start_hour": sc.weekend.evening_start_hour,
            "winddown_start_hour": sc.weekend.winddown_start_hour,
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
