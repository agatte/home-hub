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
from pydantic import BaseModel, Field

from backend.api.auth import require_api_key
from backend.services.gameday_service import GameDayService
from backend.services.pregame_audio_policy import (
    TIER_ELIMINATED,
    TIER_PRESEASON,
    VALID_TIERS,
)


# /test/pregame accepts the same regular-season tier names the policy
# module knows, plus the two specials that the policy reaches via
# is_preseason/is_eliminated branches rather than direct tier classification.
_VALID_STAKES_TIERS = VALID_TIERS | {TIER_PRESEASON, TIER_ELIMINATED}


class TestPregameRequest(BaseModel):
    """Body for POST /api/gameday/test/pregame (GAMEDAY_SPEC §10.6)."""
    opponent: str = Field(..., min_length=1, max_length=80)
    stakes_tier: str = Field("standard", description="Stakes tier override for the audio policy")

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


# IMPORTANT — /test/pregame MUST be registered BEFORE /test/{event}. FastAPI
# resolves routes in registration order; the wildcard {event} swallows
# `pregame` first and returns 400 before the dedicated handler runs.
# Caught by deploy-verifier 2026-05-15 on first ship.
@router.post("/test/pregame", dependencies=[Depends(require_api_key)])
async def test_pregame(body: TestPregameRequest, request: Request) -> dict[str, Any]:
    """Synthetic T-60 pregameday fire (GAMEDAY_SPEC §10.6).

    Flips automation to pregameday for 30 seconds, dispatches the audio
    policy with the supplied stakes_tier (TTS + optional Sonos hype),
    then auto-clears.
    """
    if body.stakes_tier not in _VALID_STAKES_TIERS:
        raise HTTPException(
            400,
            f"Unknown stakes_tier: {body.stakes_tier}. "
            f"Valid: {sorted(_VALID_STAKES_TIERS)}",
        )
    svc = _service(request)
    result = await svc.trigger_synthetic_pregame(
        opponent=body.opponent,
        stakes_tier=body.stakes_tier,
    )

    # Audio dispatch — short-circuits the stakes ladder via tier_override path.
    # Suppressions still apply (sleeping/DND) — the test endpoint inherits
    # apartment-context silence the same way a real game would.
    music_mapper = getattr(request.app.state, "music_mapper", None)
    automation = getattr(request.app.state, "automation", None)
    if music_mapper is not None:
        from backend.services.pregame_audio_policy import decision_for_tier
        sleeping = automation is not None and automation.current_mode == "sleeping"
        dnd = automation is not None and automation.is_dnd_active()
        decision = decision_for_tier(
            tier=body.stakes_tier,
            opponent=body.opponent,
            sleeping_mode=sleeping,
            dnd_active=dnd,
        )
        # Fire-and-forget — caller doesn't wait for TTS/Sonos to finish.
        import asyncio
        asyncio.create_task(music_mapper.dispatch_pregame_audio(decision))
        result["audio"] = {
            "tier": decision.tier,
            "tts_queued": bool(decision.tts_line),
            "sonos_hype_queued": decision.sonos_hype_play,
        }
    return result


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
