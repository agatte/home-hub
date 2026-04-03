"""
Scheduled routine endpoints — morning routine, evening wind-down, and future automations.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.database import async_session
from backend.models import AppSetting

logger = logging.getLogger("home_hub.routines")

router = APIRouter(prefix="/api/routines", tags=["routines"])

MORNING_CONFIG_KEY = "morning_routine_config"
WINDDOWN_CONFIG_KEY = "winddown_routine_config"


# ---------------------------------------------------------------------------
# Generic settings helpers (reusable for any AppSetting key)
# ---------------------------------------------------------------------------

async def load_setting(key: str) -> dict:
    """Load a setting from app_settings table, returns {} if not found."""
    async with async_session() as session:
        result = await session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        setting = result.scalar_one_or_none()

    if setting:
        return setting.value
    return {}


async def save_setting(key: str, value: dict) -> None:
    """Upsert a setting in app_settings table."""
    async with async_session() as session:
        result = await session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
            setting.updated_at = datetime.now(timezone.utc)
        else:
            session.add(AppSetting(key=key, value=value))

        await session.commit()


# Backward-compatible aliases
async def load_morning_config() -> dict:
    """Load persisted morning routine config from database."""
    return await load_setting(MORNING_CONFIG_KEY)


class RoutineConfig(BaseModel):
    """Configuration for the morning routine."""

    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=40, ge=0, le=59)
    enabled: bool = Field(default=True)
    volume: int = Field(default=40, ge=0, le=100)


class WinddownConfig(BaseModel):
    """Configuration for the evening wind-down routine."""

    hour: int = Field(default=21, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    enabled: bool = Field(default=False)
    volume: int = Field(default=20, ge=0, le=100)
    activate_candlelight: bool = Field(default=True)
    weekdays_only: bool = Field(default=False)
    skip_if_active: bool = Field(default=True)


@router.get("")
async def list_routines(request: Request) -> dict:
    """List all scheduled routines with their status."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"routines": []}

    tasks = scheduler.get_tasks()

    # Attach config details to routine tasks
    morning = getattr(request.app.state, "morning_routine", None)
    winddown = getattr(request.app.state, "winddown_routine", None)
    for task in tasks:
        if task["name"] == "morning_routine" and morning:
            task["volume"] = morning._morning_volume
        elif task["name"] == "winddown_routine" and winddown:
            task["volume"] = winddown._volume
            task["activate_candlelight"] = winddown._activate_candlelight
            task["weekdays_only"] = winddown._weekdays_only
            task["skip_if_active"] = winddown._skip_if_active

    return {"routines": tasks}


@router.post("/morning/test")
async def test_morning_routine(request: Request) -> dict:
    """Trigger the morning routine immediately for testing."""
    morning = getattr(request.app.state, "morning_routine", None)
    if not morning:
        raise HTTPException(
            status_code=503,
            detail="Morning routine service not initialized",
        )

    success = await morning.execute()
    return {
        "status": "ok" if success else "partial_failure",
        "message": "Morning routine executed" if success else "Routine had errors",
    }


@router.put("/morning/config")
async def update_morning_config(config: RoutineConfig, request: Request) -> dict:
    """Update morning routine schedule and settings."""
    scheduler = getattr(request.app.state, "scheduler", None)
    morning = getattr(request.app.state, "morning_routine", None)

    if not scheduler or not morning:
        raise HTTPException(
            status_code=503,
            detail="Scheduler or morning routine not initialized",
        )

    # Update the scheduled task
    from backend.services.scheduler import ScheduledTask

    task = ScheduledTask(
        name="morning_routine",
        hour=config.hour,
        minute=config.minute,
        weekdays=[0, 1, 2, 3, 4],  # Monday-Friday
        callback=morning.execute,
        enabled=config.enabled,
    )
    scheduler.add_task(task)

    # Update volume in-memory
    morning._morning_volume = config.volume

    # Persist to database
    await save_setting(MORNING_CONFIG_KEY, config.model_dump())

    logger.info(
        f"Morning routine updated: {config.hour:02d}:{config.minute:02d}, "
        f"enabled={config.enabled}, volume={config.volume}"
    )

    return {"status": "ok", "config": config.model_dump()}


@router.post("/morning/toggle")
async def toggle_morning_routine(request: Request) -> dict:
    """Toggle the morning routine on/off."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")

    tasks = scheduler.get_tasks()
    morning_task = next(
        (t for t in tasks if t["name"] == "morning_routine"), None
    )

    if not morning_task:
        raise HTTPException(status_code=404, detail="Morning routine not found")

    if morning_task["enabled"]:
        scheduler.disable_task("morning_routine")
        return {"status": "ok", "enabled": False}
    else:
        scheduler.enable_task("morning_routine")
        return {"status": "ok", "enabled": True}


# ---------------------------------------------------------------------------
# Evening Wind-Down
# ---------------------------------------------------------------------------

@router.post("/winddown/test")
async def test_winddown(request: Request) -> dict:
    """Trigger the evening wind-down routine immediately for testing."""
    winddown = getattr(request.app.state, "winddown_routine", None)
    if not winddown:
        raise HTTPException(
            status_code=503,
            detail="Wind-down routine service not initialized",
        )

    success = await winddown.execute(force=True)
    return {
        "status": "ok" if success else "partial_failure",
        "message": "Wind-down executed" if success else "Wind-down had errors",
    }


@router.put("/winddown/config")
async def update_winddown_config(config: WinddownConfig, request: Request) -> dict:
    """Update evening wind-down schedule and settings."""
    scheduler = getattr(request.app.state, "scheduler", None)
    winddown = getattr(request.app.state, "winddown_routine", None)

    if not scheduler or not winddown:
        raise HTTPException(
            status_code=503,
            detail="Scheduler or wind-down routine not initialized",
        )

    from backend.services.scheduler import ScheduledTask

    weekdays = [0, 1, 2, 3, 4] if config.weekdays_only else [0, 1, 2, 3, 4, 5, 6]

    task = ScheduledTask(
        name="winddown_routine",
        hour=config.hour,
        minute=config.minute,
        weekdays=weekdays,
        callback=winddown.execute,
        enabled=config.enabled,
    )
    scheduler.add_task(task)

    # Update service settings in-memory
    winddown._volume = config.volume
    winddown._activate_candlelight = config.activate_candlelight
    winddown._weekdays_only = config.weekdays_only
    winddown._skip_if_active = config.skip_if_active

    # Persist to database
    await save_setting(WINDDOWN_CONFIG_KEY, config.model_dump())

    logger.info(
        f"Wind-down updated: {config.hour:02d}:{config.minute:02d}, "
        f"enabled={config.enabled}, volume={config.volume}"
    )

    return {"status": "ok", "config": config.model_dump()}
