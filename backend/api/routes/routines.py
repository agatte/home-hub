"""
Scheduled routine endpoints — morning routine and future automations.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("home_hub.routines")

router = APIRouter(prefix="/api/routines", tags=["routines"])


class RoutineConfig(BaseModel):
    """Configuration for the morning routine."""

    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=40, ge=0, le=59)
    enabled: bool = Field(default=True)
    volume: int = Field(default=40, ge=0, le=100)


@router.get("")
async def list_routines(request: Request) -> dict:
    """List all scheduled routines with their status."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"routines": []}

    return {"routines": scheduler.get_tasks()}


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

    # Update volume
    morning._morning_volume = config.volume

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
