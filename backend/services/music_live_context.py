"""Real HomeHub context -> shared shadow Music Intelligence (#264)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from backend.services.music_curator import MusicCuratorContext, MusicCuratorContextBuilder
from backend.services.music_discovery import MusicDiscoveryService
from backend.services.pregame_audio_policy import compute_pregame_audio

ACTIVE_MODE_TO_CONSUMER = {
    "pregameday": "gameday",
    "gameday": "gameday",
    "social": "social",
    "gaming": "gaming",
}
GAME_SEMANTIC_INTENTS = {"valheim": "valheim"}
GAMEDAY_TIER_INTENTS = {
    "big_stakes": "gameday_big_stakes",
    "clutch": "gameday_clutch",
    "victory_lap": "gameday_victory_lap",
    "preseason": "gameday_preseason",
}


@dataclass(frozen=True)
class LiveMusicContextResolution:
    status: str
    consumer: Optional[str]
    context: Optional[MusicCuratorContext]
    semantic_request: Optional[str]
    semantic_reason: Optional[str]
    context_signature: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "consumer": self.consumer,
            "semantic_request": self.semantic_request,
            "semantic_reason": self.semantic_reason,
            "context_signature": self.context_signature,
            "context": self.context.to_dict() if self.context else None,
        }


class MusicLiveContextService:
    """Resolves current HomeHub context and delegates ranking to discovery."""

    def __init__(
        self,
        *,
        app_state: Any,
        context_builder: MusicCuratorContextBuilder,
        discovery: MusicDiscoveryService,
    ) -> None:
        self._app_state = app_state
        self._context_builder = context_builder
        self._discovery = discovery

    @property
    def supported_consumers(self) -> tuple[str, ...]:
        return tuple(consumer for consumer in ("gameday", "social", "gaming") if consumer in self._context_builder.supported_modes)

    def _active_consumer(self) -> Optional[str]:
        automation = getattr(self._app_state, "automation", None)
        mode = getattr(automation, "current_mode", None) if automation is not None else None
        return ACTIVE_MODE_TO_CONSUMER.get(str(mode or "").casefold())

    async def resolve(self) -> LiveMusicContextResolution:
        consumer = self._active_consumer()
        if consumer is None or consumer not in self.supported_consumers:
            return LiveMusicContextResolution(
                status="inactive", consumer=None, context=None, semantic_request=None,
                semantic_reason=None, context_signature=None,
            )
        context = await self._context_builder.build(consumer)
        request, reason = self._semantic_request(context)
        return LiveMusicContextResolution(
            status="suppressed" if context.suppression_reason else "active",
            consumer=consumer,
            context=context,
            semantic_request=request,
            semantic_reason=reason,
            context_signature=self._signature(context),
        )

    async def status(self) -> dict[str, Any]:
        resolved = await self.resolve()
        return {
            "shadow": True,
            "actuation_allowed": False,
            "supported_consumers": list(self.supported_consumers),
            **resolved.to_dict(),
        }

    async def preview(
        self,
        *,
        policy: str = "gentle",
        count: int = 6,
        tracks_per_artist: int = 3,
    ) -> dict[str, Any]:
        resolved = await self.resolve()
        payload: dict[str, Any] = {
            "shadow": True,
            "actuation_allowed": False,
            "live_context": resolved.to_dict(),
            "discovery": None,
        }
        if resolved.status != "active" or resolved.consumer is None:
            payload["status"] = resolved.status
            return payload
        discovery = await self._discovery.preview(
            resolved.consumer,
            policy=policy,
            count=count,
            tracks_per_artist=tracks_per_artist,
            intent=resolved.semantic_request,
        )
        payload["status"] = discovery.status
        payload["discovery"] = discovery.to_dict()
        return payload

    def _semantic_request(self, context: MusicCuratorContext) -> tuple[str, str]:
        if context.mode == "gaming":
            game = self._usable_fact(context, "game")
            if isinstance(game, str) and game.strip():
                slug = game.strip().casefold()
                request = GAME_SEMANTIC_INTENTS.get(slug, "gaming")
                return request, f"trusted foreground game: {slug}"
            return "gaming", "generic gaming; no trusted foreground game identity"
        if context.mode == "social":
            phase = self._usable_fact(context, "social_session_phase")
            return "social", f"live social context{f' ({phase})' if phase else ''}"
        tier = self._gameday_tier(context)
        return GAMEDAY_TIER_INTENTS.get(tier, "gameday"), f"existing Game Day stakes tier: {tier}"

    def _gameday_tier(self, context: MusicCuratorContext) -> str:
        def integer(key: str, default: int) -> int:
            value = self._usable_fact(context, key)
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        probability = self._usable_fact(context, "playoff_probability")
        try:
            probability = float(probability) if probability is not None else None
        except (TypeError, ValueError):
            probability = None
        gap = self._usable_fact(context, "division_gap_games")
        try:
            gap = int(gap) if gap is not None else None
        except (TypeError, ValueError):
            gap = None
        decision = compute_pregame_audio(
            opponent=str(self._usable_fact(context, "opponent") or "opponent"),
            season_week=integer("season_week", 1),
            is_preseason=bool(self._usable_fact(context, "is_preseason") or False),
            playoff_probability=probability,
            is_eliminated=bool(self._usable_fact(context, "is_eliminated") or False),
            division_gap_games=gap,
            sleeping_mode=False,
            dnd_active=False,
        )
        return decision.tier

    @staticmethod
    def _usable_fact(context: MusicCuratorContext, key: str) -> Any:
        fact = context.facts.get(key)
        return fact.value if fact is not None and fact.usable else None

    @staticmethod
    def _signature(context: MusicCuratorContext) -> str:
        stable = {
            "mode": context.mode,
            "suppression_reason": context.suppression_reason,
            "facts": {
                key: {"value": fact.value, "source": fact.source, "usable": fact.usable}
                for key, fact in sorted(context.facts.items())
            },
        }
        encoded = json.dumps(stable, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
