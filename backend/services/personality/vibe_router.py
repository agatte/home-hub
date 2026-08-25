"""Natural-language vibe router for staged arrival lighting.

The v1 surface is intentionally narrow: free-form text comes from a trusted
iOS Shortcut/Alexa-style caller, maps to an existing mode plus optional curated
scene, and controls lights only. Music stays out of scope until the Sonos
failure modes are handled separately.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from sqlalchemy import func, select

from backend.api.routes.scenes import (
    SCENE_PRESETS,
    _activate_scene_safely,
    _curated_effect_target,
)
from backend.config import settings
from backend.database import async_session
from backend.models import VibeRequest

logger = logging.getLogger("home_hub.personality.vibe_router")

PENDING_ARRIVAL_VIBE_KEY = "pending_arrival_vibe"
VIBE_DAILY_COST_CAP_KEY = "vibe_daily_cost_cap_usd"
DEFAULT_DAILY_COST_CAP_USD = 0.50

VALID_MODES = {
    "idle",
    "working",
    "gaming",
    "watching",
    "cooking",
    "relax",
    "social",
    "sleeping",
    "gameday",
    "pregameday",
}


class VibeRouterError(RuntimeError):
    """Expected user-facing vibe-router failure."""


@dataclass(slots=True)
class VibePlan:
    """Validated command plan produced from a transcript."""

    mode: str
    scene_id: Optional[str]
    acknowledgement: str
    confidence: float
    parser: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VibeRouter:
    """Parse, stage, and apply natural-language lighting vibe commands."""

    def __init__(
        self,
        *,
        app_state: Any,
        save_setting: Callable[..., Any],
        load_setting: Callable[..., Any],
        session_factory: Callable[..., Any] = async_session,
        anthropic_api_key: Optional[str] = None,
        anthropic_model: Optional[str] = None,
    ) -> None:
        self._app_state = app_state
        self._save_setting = save_setting
        self._load_setting = load_setting
        self._session_factory = session_factory
        self._anthropic_api_key = (
            settings.ANTHROPIC_API_KEY if anthropic_api_key is None else anthropic_api_key
        )
        self._anthropic_model = (
            settings.ANTHROPIC_MODEL if anthropic_model is None else anthropic_model
        )
        self._cache: dict[str, tuple[float, VibePlan]] = {}

    async def handle_request(
        self,
        *,
        transcript: str,
        source: str,
        timing: str = "arrival_if_away",
    ) -> dict[str, Any]:
        """Parse then either stage or apply the vibe command."""
        cleaned = _clean_transcript(transcript)
        if not cleaned:
            raise VibeRouterError("Transcript cannot be empty")

        started = time.perf_counter()
        plan, cache_hit, cost_usd = await self.parse(cleaned)
        latency_ms = (time.perf_counter() - started) * 1000

        away_manager = getattr(self._app_state, "away_manager", None)
        is_away = bool(getattr(away_manager, "away", False))
        should_stage = timing == "arrival_if_away" and is_away

        applied = False
        staged = False
        if should_stage:
            await self.stage_for_arrival(plan, transcript=cleaned, source=source)
            staged = True
        else:
            await self.apply_plan(plan, source=source)
            applied = True

        await self._log_request(
            transcript=cleaned,
            source=source,
            plan=plan,
            applied=applied,
            staged=staged,
            cache_hit=cache_hit,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

        if staged:
            await self._notify(
                title="Arrival vibe staged",
                body=plan.acknowledgement,
                kind="vibe_staged",
            )
        return {
            "status": "ok",
            "plan": plan.to_dict(),
            "staged": staged,
            "applied": applied,
            "acknowledgement": plan.acknowledgement,
            "cache_hit": cache_hit,
        }

    async def parse(self, transcript: str) -> tuple[VibePlan, bool, float]:
        """Return `(plan, cache_hit, cost_usd)` for a normalized transcript."""
        normalized = _normalize(transcript)
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < 24 * 60 * 60:
            return cached[1], True, 0.0

        rule_plan = self._parse_rules(normalized)
        if rule_plan:
            self._cache[key] = (time.time(), rule_plan)
            return rule_plan, False, 0.0

        plan, cost = await self._parse_with_anthropic(transcript)
        self._cache[key] = (time.time(), plan)
        return plan, False, cost

    async def stage_for_arrival(
        self, plan: VibePlan, *, transcript: str, source: str,
    ) -> None:
        payload = {
            "plan": plan.to_dict(),
            "transcript": transcript,
            "source": source,
            "staged_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        await self._save_setting(PENDING_ARRIVAL_VIBE_KEY, payload)

    async def apply_pending_arrival(self, *, source: str) -> Optional[dict[str, Any]]:
        pending = await self._load_setting(PENDING_ARRIVAL_VIBE_KEY)
        if not isinstance(pending, dict):
            return None
        plan_data = pending.get("plan")
        if not isinstance(plan_data, dict):
            await self._save_setting(PENDING_ARRIVAL_VIBE_KEY, {})
            return None

        plan = self._validate_plan(plan_data, parser="pending")
        await self.apply_plan(plan, source=source)
        await self._save_setting(PENDING_ARRIVAL_VIBE_KEY, {})
        await self._log_request(
            transcript=str(pending.get("transcript") or ""),
            source=source,
            plan=plan,
            applied=True,
            staged=False,
            cache_hit=False,
            cost_usd=0.0,
            latency_ms=None,
        )
        return {"status": "ok", "plan": plan.to_dict()}

    async def apply_plan(self, plan: VibePlan, *, source: str) -> None:
        """Apply mode first, then optional scene so the scene remains visible."""
        automation = getattr(self._app_state, "automation", None)
        if automation is None:
            raise VibeRouterError("Automation engine not initialized")

        apply_source = _user_apply_source(source)
        await automation.set_manual_override(plan.mode, source=apply_source)

        if not plan.scene_id:
            return

        hue = getattr(self._app_state, "hue", None)
        if not hue or not getattr(hue, "connected", False):
            raise VibeRouterError("Hue bridge not connected")

        preset = SCENE_PRESETS[plan.scene_id]
        effect_manager = getattr(self._app_state, "effect_manager", None)
        ws_manager = getattr(self._app_state, "ws_manager", None)

        success = await _activate_scene_safely(
            automation,
            effect_manager,
            preset["lights"],
            _curated_effect_target(preset.get("effect")),
        )
        if not success:
            raise VibeRouterError(
                "Scene transition aborted: safe effect release not established"
            )

        for light_id in preset["lights"]:
            automation.mark_light_manual(
                str(light_id), preset["lights"][light_id],
            )

        if ws_manager is not None:
            lights = await hue.get_all_lights()
            for light in lights:
                await ws_manager.broadcast("light_update", light)

        event_logger = getattr(self._app_state, "event_logger", None)
        if event_logger is not None:
            await event_logger.log_scene_activation(
                scene_id=plan.scene_id,
                scene_name=preset.get("display_name"),
                source=apply_source,
                mode_at_time=getattr(automation, "current_mode", None),
            )

    def _parse_rules(self, normalized: str) -> Optional[VibePlan]:
        if _contains_any(normalized, ("party", "friends", "people over", "guests", "pregame")):
            return VibePlan(
                mode="social",
                scene_id="house_party",
                acknowledgement="Staged House Party lighting for when you arrive.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("neon", "tokyo", "cyberpunk")):
            return VibePlan(
                mode="relax",
                scene_id="neon_tokyo",
                acknowledgement="Staged Neon Tokyo lighting.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("miami", "vice")):
            return VibePlan(
                mode="relax",
                scene_id="miami_vice",
                acknowledgement="Staged Miami Vice lighting.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("arcade", "retro", "game night")):
            return VibePlan(
                mode="social",
                scene_id="arcade",
                acknowledgement="Staged Arcade lighting.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("aurora", "northern lights")):
            return VibePlan(
                mode="relax",
                scene_id="northern_lights",
                acknowledgement="Staged Northern Lights lighting.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("sunset", "golden hour")):
            return VibePlan(
                mode="relax",
                scene_id="sunset_strip",
                acknowledgement="Staged Sunset Strip lighting.",
                confidence=0.95,
                parser="rules",
            )
        if _contains_any(normalized, ("chill", "cozy", "calm", "relax")):
            return VibePlan(
                mode="relax",
                scene_id=None,
                acknowledgement="Staged relax mode lighting.",
                confidence=0.85,
                parser="rules",
            )
        if _contains_any(normalized, ("cook", "dinner", "kitchen")):
            return VibePlan(
                mode="cooking",
                scene_id=None,
                acknowledgement="Staged cooking lighting.",
                confidence=0.85,
                parser="rules",
            )
        return None

    async def _parse_with_anthropic(self, transcript: str) -> tuple[VibePlan, float]:
        if not self._anthropic_api_key:
            raise VibeRouterError("No deterministic vibe match and ANTHROPIC_API_KEY is not set")

        cap = await self._daily_cap_usd()
        spent = await self._daily_spend_usd()
        if spent >= cap:
            raise VibeRouterError("Daily vibe parsing cost cap reached")

        payload = {
            "model": self._anthropic_model,
            "max_tokens": 300,
            "temperature": 0,
            "system": (
                "Map a Home Hub vibe request to JSON only. "
                "Valid modes: social, relax, cooking, watching, gaming, working. "
                "Valid scene_id values: house_party, neon_tokyo, miami_vice, "
                "arcade, northern_lights, sunset_strip, or null. "
                "Return keys: mode, scene_id, acknowledgement, confidence. "
                "Do not include music or TTS actions."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": f"Vibe request: {transcript}",
                }
            ],
        }
        headers = {
            "x-api-key": self._anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise VibeRouterError(f"Anthropic parse failed: HTTP {response.status_code}")

        data = response.json()
        text = _anthropic_text(data)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VibeRouterError("Anthropic parse returned invalid JSON") from exc

        plan = self._validate_plan(parsed, parser="anthropic")
        usage = data.get("usage") or {}
        cost = _estimate_anthropic_cost_usd(usage)
        return plan, cost

    def _validate_plan(self, data: dict[str, Any], *, parser: str) -> VibePlan:
        mode = str(data.get("mode") or "").strip()
        scene_id_raw = data.get("scene_id")
        scene_id = str(scene_id_raw).strip() if scene_id_raw else None
        acknowledgement = str(data.get("acknowledgement") or "Vibe command ready.").strip()
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        if mode not in VALID_MODES:
            raise VibeRouterError(f"Invalid vibe mode: {mode!r}")
        if scene_id is not None and scene_id not in SCENE_PRESETS:
            raise VibeRouterError(f"Invalid vibe scene_id: {scene_id!r}")
        return VibePlan(
            mode=mode,
            scene_id=scene_id,
            acknowledgement=acknowledgement[:200],
            confidence=max(0.0, min(1.0, confidence)),
            parser=parser,
        )

    async def _daily_cap_usd(self) -> float:
        stored = await self._load_setting(VIBE_DAILY_COST_CAP_KEY)
        if isinstance(stored, dict):
            value = stored.get("usd", DEFAULT_DAILY_COST_CAP_USD)
        else:
            value = stored if stored is not None else DEFAULT_DAILY_COST_CAP_USD
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_DAILY_COST_CAP_USD

    async def _daily_spend_usd(self) -> float:
        today = datetime.now(timezone.utc).date()
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(VibeRequest.cost_usd), 0.0))
                .where(func.date(VibeRequest.timestamp) == today.isoformat())
            )
            return float(result.scalar_one() or 0.0)

    async def _log_request(
        self,
        *,
        transcript: str,
        source: str,
        plan: VibePlan,
        applied: bool,
        staged: bool,
        cache_hit: bool,
        cost_usd: float,
        latency_ms: Optional[float],
    ) -> None:
        response = plan.to_dict()
        response["staged"] = staged
        async with self._session_factory() as session:
            session.add(VibeRequest(
                transcript=transcript[:500],
                response=response,
                applied=applied,
                cache_hit=cache_hit,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                source=source[:50],
            ))
            await session.commit()

    async def _notify(self, *, title: str, body: str, kind: str) -> None:
        notifier = getattr(self._app_state, "notifier", None)
        if notifier is None:
            return
        try:
            await notifier.emit_alert(title=title, body=body, kind=kind, force=False)
        except Exception:
            logger.warning("Vibe notification failed", exc_info=True)


def _clean_transcript(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize(value: str) -> str:
    return _clean_transcript(value).lower()


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _user_apply_source(source: str) -> str:
    """Make user-origin commands pass AutomationEngine's DND/user gates."""
    cleaned = (source or "vibe").strip() or "vibe"
    if cleaned.startswith(("api:", "alexa:", "guest", "rule_suggestion_accept:")):
        return cleaned[:50]
    return f"api:{cleaned}"[:50]


def _anthropic_text(data: dict[str, Any]) -> str:
    blocks = data.get("content") or []
    parts = [
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(parts).strip()


def _estimate_anthropic_cost_usd(usage: dict[str, Any]) -> float:
    try:
        input_tokens = float(usage.get("input_tokens") or 0)
        output_tokens = float(usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return 0.0
    # Claude 3 Haiku ballpark: $0.25 / MTok input, $1.25 / MTok output.
    return (input_tokens * 0.25 / 1_000_000) + (output_tokens * 1.25 / 1_000_000)
