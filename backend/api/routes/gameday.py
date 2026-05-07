"""
Game Day routes — read-only state queries + a test endpoint for tuning.

Spec: docs/GAMEDAY_SPEC.md §4.3.

GET endpoints are unauthenticated (read-only, kiosk + LAN polling).
The POST test endpoint requires the API key the same way every write
endpoint does (auth bypass for localhost / RFC1918 / trusted-LAN).
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key
from backend.services.gameday_service import GameDayService

logger = logging.getLogger("home_hub.api.gameday")

router = APIRouter(prefix="/api/gameday", tags=["gameday"])


_VALID_TEST_EVENTS = {
    "touchdown", "field_goal", "kickoff", "end_of_game_win", "end_of_game_loss",
}

# Map test event names to the PlayType enum values that GameDayService accepts.
# `end_of_game_win` / `end_of_game_loss` aren't real PlayTypes; they synthesize
# as "other" and Slice B's orchestrator will key off the description.
_TEST_EVENT_TO_PLAY_TYPE: dict[str, Literal["touchdown", "field_goal", "kickoff", "other"]] = {
    "touchdown": "touchdown",
    "field_goal": "field_goal",
    "kickoff": "kickoff",
    "end_of_game_win": "other",
    "end_of_game_loss": "other",
}


def _service(request: Request) -> GameDayService:
    svc = getattr(request.app.state, "gameday", None)
    if svc is None:
        raise HTTPException(503, "GameDayService not initialized")
    return svc


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    """Return the current Colts game snapshot or `{"status": "no-game"}`."""
    svc = _service(request)
    state = svc.current_state()
    if state is None:
        return {"status": "no-game"}
    return asdict(state)


@router.get("/schedule")
async def get_schedule(request: Request) -> list[dict[str, Any]]:
    """Return the next 5 scheduled / in-progress Colts games."""
    svc = _service(request)
    return await svc.get_upcoming_schedule(limit=5)


@router.post("/test/{event}", dependencies=[Depends(require_api_key)])
async def test_event(event: str, request: Request) -> dict[str, Any]:
    """Fire a synthetic PlayEvent through the play-event subscribers.

    Used to tune CelebrationOrchestrator sequences without waiting for a
    real game. Until Slice B subscribes, no listeners — this just logs and
    returns ok. Auth-gated like all other write endpoints (localhost +
    RFC1918 LAN bypass).
    """
    if event not in _VALID_TEST_EVENTS:
        raise HTTPException(
            400,
            f"Unknown event: {event}. Valid: {sorted(_VALID_TEST_EVENTS)}",
        )
    svc = _service(request)
    play_type = _TEST_EVENT_TO_PLAY_TYPE[event]
    play = await svc.trigger_synthetic_play(play_type)
    return {
        "status": "ok",
        "event": event,
        "fired": {
            "play_type": play.play_type,
            "description": play.description,
        },
    }
