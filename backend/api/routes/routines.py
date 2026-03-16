"""
Scheduled routine endpoints — morning routine and future automations.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.database import async_session
from backend.models import AppSetting

logger = logging.getLogger("home_hub.routines")

router = APIRouter(prefix="/api/routines", tags=["routines"])

MORNING_CONFIG_KEY = "morning_routine_config"


class RoutineConfig(BaseModel):
    """Configuration for the morning routine."""

    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=40, ge=0, le=59)
    enabled: bool = Field(default=True)
    volume: int = Field(default=40, ge=0, le=100)


async def load_morning_config() -> dict:
    """Load persisted morning routine config from database."""
    async with async_session() as session:
        result = await session.execute(
            select(AppSetting).where(AppSetting.key == MORNING_CONFIG_KEY)
        )
        setting = result.scalar_one_or_none()

    if setting:
        return setting.value
    return {}


async def _save_morning_config(config: dict) -> None:
    """Persist morning routine config to database."""
    async with async_session() as session:
        result = await session.execute(
            select(AppSetting).where(AppSetting.key == MORNING_CONFIG_KEY)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = config
            setting.updated_at = datetime.now(timezone.utc)
        else:
            session.add(AppSetting(
                key=MORNING_CONFIG_KEY,
                value=config,
            ))

        await session.commit()


@router.get("")
async def list_routines(request: Request) -> dict:
    """List all scheduled routines with their status."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"routines": []}

    tasks = scheduler.get_tasks()

    # Attach volume to morning routine from the service instance
    morning = getattr(request.app.state, "morning_routine", None)
    if morning:
        for task in tasks:
            if task["name"] == "morning_routine":
                task["volume"] = morning._morning_volume
                break

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
    await _save_morning_config(config.model_dump())

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
