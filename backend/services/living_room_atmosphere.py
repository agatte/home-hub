"""Deterministic living-room atmosphere selection for couch-driven Relax.

This is intentionally a narrow first slice.  It ranks three local palettes,
owns only its session/decision bookkeeping, and returns an L1/L3/L4 overlay.
Hue writes stay in :class:`AutomationEngine`'s existing application pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select

from backend.models import SceneActivation

logger = logging.getLogger(__name__)

ATMOSPHERE_HISTORY_SOURCE = "atmosphere"
ATMOSPHERE_SCENE_PREFIX = "living_room_atmosphere:"
LIVING_ROOM_ATMOSPHERE_LIGHT_IDS = frozenset({"1", "3", "4"})
ORDINARY_RELAX_LIGHT_IDS = ("2", "5")
SETTLED_SECONDS = 15 * 60
EVOLUTION_SECONDS = 30 * 60
RECENT_HISTORY_LIMIT = 8
ATMOSPHERE_TRANSITION_TIME = 100  # Hue deciseconds = 10 seconds.


@dataclass(frozen=True)
class AtmosphereDefinition:
    atmosphere_id: str
    display_name: str
    priority: int
    palettes: dict[str, dict[str, dict[str, Any]]]


@dataclass(frozen=True)
class CandidateRank:
    atmosphere_id: str
    context_fit: int
    weather_fit: int
    period_fit: int
    recency_fit: int
    priority: int
    recently_used: bool
    reason_codes: tuple[str, ...]

    @property
    def core_score(self) -> tuple[int, int, int]:
        return (self.context_fit, self.weather_fit, self.period_fit)

    @property
    def score(self) -> tuple[int, int, int, int, int]:
        return (*self.core_score, self.recency_fit, self.priority)


@dataclass(frozen=True)
class AtmospherePlan:
    atmosphere_id: Optional[str]
    period: str
    palette: dict[str, dict[str, Any]]
    should_apply: bool
    record_history: bool
    action: str
    reason_codes: tuple[str, ...]


def _period_palettes(
    *,
    day: tuple[dict[str, Any], dict[str, Any]],
    evening: tuple[dict[str, Any], dict[str, Any]],
    night: tuple[dict[str, Any], dict[str, Any]],
    late_night: tuple[dict[str, Any], dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Expand L1 + matched-kitchen tuples into period-specific overlays."""
    return {
        period: {
            "1": living.copy(),
            "3": kitchen.copy(),
            "4": kitchen.copy(),
        }
        for period, (living, kitchen) in {
            "day": day,
            "evening": evening,
            "night": night,
            "late_night": late_night,
        }.items()
    }


ATMOSPHERES: dict[str, AtmosphereDefinition] = {
    "moss_ember": AtmosphereDefinition(
        atmosphere_id="moss_ember",
        display_name="Moss & Ember",
        priority=30,
        palettes=_period_palettes(
            day=(
                {"on": True, "bri": 95, "hue": 7500, "sat": 200},
                {"on": True, "bri": 30, "hue": 20000, "sat": 100},
            ),
            evening=(
                {"on": True, "bri": 70, "hue": 6000, "sat": 230},
                {"on": True, "bri": 15, "hue": 20000, "sat": 100},
            ),
            night=(
                {"on": True, "bri": 38, "hue": 5000, "sat": 254},
                {"on": True, "bri": 8, "hue": 20000, "sat": 100},
            ),
            late_night=(
                {"on": True, "bri": 34, "hue": 3000, "sat": 240},
                {"on": True, "bri": 5, "hue": 20000, "sat": 100},
            ),
        ),
    ),
    "rainy_forest": AtmosphereDefinition(
        atmosphere_id="rainy_forest",
        display_name="Rainy Forest",
        priority=20,
        palettes=_period_palettes(
            day=(
                {"on": True, "bri": 90, "hue": 7000, "sat": 180},
                {"on": True, "bri": 35, "hue": 39500, "sat": 120},
            ),
            evening=(
                {"on": True, "bri": 65, "hue": 5500, "sat": 210},
                {"on": True, "bri": 20, "hue": 39500, "sat": 130},
            ),
            night=(
                {"on": True, "bri": 42, "hue": 5000, "sat": 220},
                {"on": True, "bri": 12, "hue": 39500, "sat": 130},
            ),
            late_night=(
                {"on": True, "bri": 36, "hue": 4000, "sat": 220},
                {"on": True, "bri": 8, "hue": 39500, "sat": 120},
            ),
        ),
    ),
    "listening_glow": AtmosphereDefinition(
        atmosphere_id="listening_glow",
        display_name="Listening Glow",
        priority=10,
        palettes=_period_palettes(
            day=(
                {"on": True, "bri": 115, "hue": 48000, "sat": 140},
                {"on": True, "bri": 40, "hue": 6500, "sat": 170},
            ),
            evening=(
                {"on": True, "bri": 85, "hue": 48000, "sat": 150},
                {"on": True, "bri": 28, "hue": 6000, "sat": 185},
            ),
            night=(
                {"on": True, "bri": 55, "hue": 47000, "sat": 150},
                {"on": True, "bri": 18, "hue": 5500, "sat": 190},
            ),
            late_night=(
                {"on": True, "bri": 45, "hue": 46000, "sat": 130},
                {"on": True, "bri": 12, "hue": 5000, "sat": 175},
            ),
        ),
    ),
}


def merge_living_room_atmosphere(
    ordinary_relax: dict[str, dict[str, Any]],
    overlay: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge only L1/L3/L4, preserving all ordinary Relax lamps otherwise."""
    merged = {
        light_id: state.copy()
        for light_id, state in ordinary_relax.items()
    }
    for light_id in LIVING_ROOM_ATMOSPHERE_LIGHT_IDS:
        if light_id in overlay:
            merged[light_id] = overlay[light_id].copy()
    return merged


def preserve_atmosphere_effect_scope(
    desired_effect: Optional[str | dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Keep Relax effects on ordinary L2/L5 so they do not flatten the overlay."""
    if desired_effect is None:
        return None
    if isinstance(desired_effect, str):
        return {"effect": desired_effect, "lights": list(ORDINARY_RELAX_LIGHT_IDS)}
    existing_lights = desired_effect.get("lights")
    lights = (
        list(ORDINARY_RELAX_LIGHT_IDS)
        if existing_lights is None
        else [
            light_id
            for light_id in ORDINARY_RELAX_LIGHT_IDS
            if light_id in existing_lights
        ]
    )
    if not lights:
        return None
    return {"effect": desired_effect.get("effect"), "lights": lights}


def _weather_context(snapshot: dict[str, Any]) -> str:
    weather = snapshot.get("weather") or {}
    if (
        weather.get("freshness") != "fresh"
        or weather.get("stale_fallback")
        or not weather.get("state")
    ):
        return "unknown"
    description = str(weather["state"]).lower()
    if "thunderstorm" in description or "storm" in description:
        return "storm"
    if "rain" in description or "drizzle" in description:
        return "rain"
    if "overcast" in description or "heavy cloud" in description:
        return "heavy_cloud"
    if "cloud" in description:
        return "clouds"
    if "clear" in description:
        return "clear"
    if "snow" in description:
        return "snow"
    return "other"


def _music_context(snapshot: dict[str, Any]) -> str:
    health = snapshot.get("music_sonos_health") or {}
    music = snapshot.get("music_state") or {}
    if health.get("status") != "healthy" or music.get("freshness") != "fresh":
        return "unknown"
    state = music.get("state")
    if state == "playing":
        return "playing"
    if state == "stopped":
        return "stopped"
    return "unknown"


def rank_atmospheres(
    *,
    period: str,
    weather: str,
    music: str,
    recent_history: tuple[str, ...] = (),
) -> tuple[CandidateRank, ...]:
    """Return all candidates in deterministic policy order."""
    recent = set(recent_history)
    rainy_weather = weather in {"rain", "storm", "heavy_cloud"}
    ranks: list[CandidateRank] = []
    for atmosphere_id, definition in ATMOSPHERES.items():
        if atmosphere_id == "listening_glow":
            context_fit = 3 if music == "playing" else 0
            weather_fit = 1
            period_fit = 2 if period in {"evening", "night"} else 1
            reasons = (
                ("fresh_sonos_playing",)
                if music == "playing"
                else (f"music_{music}",)
            )
        elif atmosphere_id == "rainy_forest":
            context_fit = 1 if music == "playing" else 2
            weather_fit = 3 if rainy_weather else 1 if weather == "unknown" else 0
            period_fit = 1 if period == "late_night" else 2
            reasons = (
                (f"weather_{weather}",)
                if rainy_weather
                else ("quiet_couch", f"weather_{weather}")
            )
        else:
            context_fit = 1 if music == "playing" else 2
            weather_fit = 1 if rainy_weather else 1 if weather == "unknown" else 2
            period_fit = 2
            reasons = ("quiet_couch", f"weather_{weather}")

        ranks.append(CandidateRank(
            atmosphere_id=atmosphere_id,
            context_fit=context_fit,
            weather_fit=weather_fit,
            period_fit=period_fit,
            recency_fit=0 if atmosphere_id in recent else 1,
            priority=definition.priority,
            recently_used=atmosphere_id in recent,
            reason_codes=reasons,
        ))

    return tuple(sorted(
        ranks,
        key=lambda rank: (
            -rank.context_fit,
            -rank.weather_fit,
            -rank.period_fit,
            -rank.recency_fit,
            -rank.priority,
            rank.atmosphere_id,
        ),
    ))


class LivingRoomAtmosphereCurator:
    """Own deterministic selection, one-evolution sessions, and history."""

    def __init__(
        self,
        *,
        enabled: bool,
        session_factory: Optional[Callable[..., Any]] = None,
        log_activation: Optional[
            Callable[[str, Optional[str], str, Optional[str]], Awaitable[None]]
        ] = None,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.enabled = enabled
        self._session_factory = session_factory
        self._log_activation = log_activation
        self._now = now_provider
        self._recent_history: list[str] = []
        self._session_key: Optional[str] = None
        self._session_started_at: Optional[datetime] = None
        self._session_not_before: Optional[datetime] = None
        self._selected_id: Optional[str] = None
        self._selected_period: Optional[str] = None
        self._evolved = False
        self._pending_history: Optional[tuple[str, str, str]] = None
        self._last_status: dict[str, Any] = self._empty_status()

    def _empty_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "selected_atmosphere": None,
            "reason_codes": ["no_authoritative_couch_session"],
            "candidates": [],
            "context": {"weather": "unknown", "music": "unknown"},
            "session": {
                "started_at": None,
                "age_seconds": None,
                "settled": False,
                "evolved": False,
                "next_evolution_eligible_at": None,
            },
            "application": {
                "state": "fallback",
                "reason": "no_authoritative_couch_session",
                "last_applied_at": None,
            },
        }

    async def load_recent_history(self) -> None:
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(SceneActivation.scene_id)
                    .where(SceneActivation.source == ATMOSPHERE_HISTORY_SOURCE)
                    .order_by(SceneActivation.timestamp.desc())
                    .limit(RECENT_HISTORY_LIMIT)
                )
            self._recent_history = [
                scene_id.removeprefix(ATMOSPHERE_SCENE_PREFIX)
                for scene_id in result.scalars()
                if scene_id.startswith(ATMOSPHERE_SCENE_PREFIX)
            ]
        except Exception:
            logger.error("Living-room atmosphere history load failed", exc_info=True)

    def reset_session(self, reason: str) -> None:
        self._session_key = None
        self._session_started_at = None
        self._selected_id = None
        self._selected_period = None
        self._evolved = False
        self._pending_history = None
        reset_at = self._now()
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)
        self._session_not_before = reset_at.astimezone(timezone.utc)
        self._last_status = self._empty_status()
        self._last_status["reason_codes"] = [reason]
        self._last_status["application"]["reason"] = reason

    def _session_fields(self, now: datetime) -> dict[str, Any]:
        if self._session_started_at is None:
            return self._empty_status()["session"]
        age = max(0.0, (now - self._session_started_at).total_seconds())
        next_at = self._session_started_at + timedelta(seconds=EVOLUTION_SECONDS)
        return {
            "started_at": self._session_started_at.isoformat(),
            "age_seconds": round(age, 3),
            "settled": age >= SETTLED_SECONDS,
            "evolved": self._evolved,
            "next_evolution_eligible_at": (
                None if self._evolved else next_at.isoformat()
            ),
        }

    @staticmethod
    def _candidate_payload(
        ranks: tuple[CandidateRank, ...],
    ) -> list[dict[str, Any]]:
        return [
            {
                "atmosphere_id": rank.atmosphere_id,
                "score": {
                    "context_fit": rank.context_fit,
                    "weather_fit": rank.weather_fit,
                    "period_fit": rank.period_fit,
                    "recency_fit": rank.recency_fit,
                    "priority": rank.priority,
                },
                "recently_used": rank.recently_used,
                "reason_codes": list(rank.reason_codes),
            }
            for rank in ranks
        ]

    def decide(
        self,
        envelope: Optional[dict[str, Any]],
        *,
        period: str,
        provenance: Optional[str],
        session_started_at: Optional[datetime],
        scene_override_active: bool,
    ) -> AtmospherePlan:
        """Choose/retain an atmosphere and update the observable session state."""
        now = self._now()
        snapshot = (envelope or {}).get("snapshot") or {}
        decision = (envelope or {}).get("decision") or {}
        weather = _weather_context(snapshot)
        music = _music_context(snapshot)
        ranks = rank_atmospheres(
            period=period,
            weather=weather,
            music=music,
            recent_history=tuple(self._recent_history),
        )
        candidate_payload = self._candidate_payload(ranks)

        if provenance != "physical_context_relax":
            self.reset_session("not_physical_context_relax")
            self._last_status["candidates"] = candidate_payload
            self._last_status["context"] = {"weather": weather, "music": music}
            return AtmospherePlan(
                None, period, {}, False, False, "fallback",
                ("not_physical_context_relax",),
            )

        gate_reasons = tuple(decision.get("reason_codes") or ())
        eligible = bool(decision.get("eligible_for_scene_curator"))
        if not eligible:
            hard_loss = {
                "apartment_away",
                "dnd_active",
                "sleeping_active",
                "manual_mode_override_active",
            }
            hard_reason = next(
                (reason for reason in gate_reasons if reason in hard_loss),
                None,
            )
            if hard_reason is not None:
                self.reset_session(hard_reason)
            reasons = gate_reasons or ("living_room_gate_unavailable",)
            selected = self._selected_id or ranks[0].atmosphere_id
            self._last_status.update({
                "selected_atmosphere": selected,
                "reason_codes": list(reasons),
                "candidates": candidate_payload,
                "context": {"weather": weather, "music": music},
                "session": self._session_fields(now),
                "application": {
                    **self._last_status["application"],
                    "state": "fallback",
                    "reason": reasons[0],
                },
            })
            return AtmospherePlan(
                selected, period, {}, False, False, "fallback", reasons,
            )

        if scene_override_active:
            reasons = ("scene_override_configured",)
            self._last_status.update({
                "selected_atmosphere": self._selected_id or ranks[0].atmosphere_id,
                "reason_codes": list(reasons),
                "candidates": candidate_payload,
                "context": {"weather": weather, "music": music},
                "session": self._session_fields(now),
                "application": {
                    **self._last_status["application"],
                    "state": "fallback",
                    "reason": reasons[0],
                },
            })
            return AtmospherePlan(
                None, period, {}, False, False, "fallback", reasons,
            )

        started_at = session_started_at or now
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        started_at = started_at.astimezone(timezone.utc)
        if (
            self._session_not_before is not None
            and started_at < self._session_not_before
        ):
            started_at = self._session_not_before
        key = started_at.astimezone(timezone.utc).isoformat()
        record_history = False
        action = "hold"
        reasons: tuple[str, ...]

        if self._session_key != key or self._selected_id is None:
            self._session_key = key
            self._session_started_at = started_at.astimezone(timezone.utc)
            self._session_not_before = None
            self._selected_id = ranks[0].atmosphere_id
            self._selected_period = period
            self._evolved = False
            record_history = True
            action = "apply_initial"
            reasons = (*ranks[0].reason_codes, "session_started")
        else:
            age = max(0.0, (now - self._session_started_at).total_seconds())
            if period != self._selected_period:
                self._selected_period = period
                record_history = True
                action = "reconcile_period"
                reasons = ("time_period_reconciliation",)
            elif age < EVOLUTION_SECONDS:
                reasons = ("evolution_threshold_not_reached",)
            elif self._evolved:
                reasons = ("session_already_evolved",)
            else:
                current_rank = next(
                    rank for rank in ranks
                    if rank.atmosphere_id == self._selected_id
                )
                best_core = ranks[0].core_score
                alternatives = [
                    rank for rank in ranks
                    if rank.atmosphere_id != self._selected_id
                    and rank.core_score == best_core
                    and rank.context_fit >= current_rank.context_fit
                ]
                if alternatives:
                    chosen = alternatives[0]
                    self._selected_id = chosen.atmosphere_id
                    self._evolved = True
                    record_history = True
                    action = "evolve"
                    reasons = (*chosen.reason_codes, "single_session_evolution")
                else:
                    reasons = ("no_equally_appropriate_evolution_candidate",)

        definition = ATMOSPHERES[self._selected_id]
        palette = definition.palettes.get(period, definition.palettes["night"])
        if record_history:
            self._pending_history = (self._selected_id, period, action)
        elif self._pending_history is not None:
            pending_id, pending_period, _pending_action = self._pending_history
            record_history = (
                pending_id == self._selected_id and pending_period == period
            )
        should_apply = self.enabled
        application_state = "held" if should_apply else "fallback"
        application_reason = action if should_apply else "feature_disabled"
        visible_reasons = reasons if should_apply else (*reasons, "feature_disabled")
        self._last_status.update({
            "enabled": self.enabled,
            "selected_atmosphere": self._selected_id,
            "reason_codes": list(visible_reasons),
            "candidates": candidate_payload,
            "context": {
                "weather": weather,
                "music": music,
                "period": period,
                "provenance": provenance,
            },
            "session": self._session_fields(now),
            "application": {
                **self._last_status["application"],
                "state": application_state,
                "reason": application_reason,
            },
        })
        return AtmospherePlan(
            self._selected_id,
            period,
            {light_id: state.copy() for light_id, state in palette.items()},
            should_apply,
            record_history,
            action,
            visible_reasons,
        )

    async def observe_application(
        self,
        plan: AtmospherePlan,
        result: Any,
    ) -> None:
        """Record only an established target; persist only a genuine write."""
        if not plan.should_apply or plan.atmosphere_id is None:
            return
        if isinstance(result, bool):
            established = result
            genuine_write = result
        else:
            successful = set(getattr(result, "successful", set()))
            deduplicated = set(getattr(result, "deduplicated", set()))
            failed = set(getattr(result, "failed", set()))
            skipped = set(getattr(result, "skipped", set()))
            required = set(plan.palette) - skipped
            established = (
                not (failed & required)
                and required <= successful | deduplicated
            )
            genuine_write = established and bool(successful & required)

        now = self._now()
        if not established:
            self._last_status["application"].update({
                "state": "fallback",
                "reason": "living_room_write_incomplete",
            })
            return

        self._last_status["application"].update({
            "state": "applied" if genuine_write else "held",
            "reason": plan.action if genuine_write else "deduplicated_no_write",
            "last_applied_at": (
                now.isoformat()
                if genuine_write
                else self._last_status["application"].get("last_applied_at")
            ),
        })
        if not plan.record_history or not genuine_write:
            return

        scene_id = f"{ATMOSPHERE_SCENE_PREFIX}{plan.atmosphere_id}"
        definition = ATMOSPHERES[plan.atmosphere_id]
        if self._log_activation is not None:
            try:
                await self._log_activation(
                    scene_id,
                    definition.display_name,
                    ATMOSPHERE_HISTORY_SOURCE,
                    "relax",
                )
            except Exception:
                logger.error(
                    "Living-room atmosphere history write failed",
                    exc_info=True,
                )
                return
        self._pending_history = None
        self._recent_history.insert(0, plan.atmosphere_id)
        self._recent_history = self._recent_history[:RECENT_HISTORY_LIMIT]

    def current_status(self) -> dict[str, Any]:
        status = {
            **self._last_status,
            "session": self._session_fields(self._now()),
        }
        return status

    async def history(self, limit: int) -> list[dict[str, Any]]:
        if self._session_factory is None:
            return []
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(SceneActivation)
                    .where(SceneActivation.source == ATMOSPHERE_HISTORY_SOURCE)
                    .order_by(SceneActivation.timestamp.desc())
                    .limit(limit)
                )
        except Exception:
            logger.error("Living-room atmosphere history read failed", exc_info=True)
            return []
        return [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "atmosphere_id": row.scene_id.removeprefix(
                    ATMOSPHERE_SCENE_PREFIX
                ),
                "display_name": row.scene_name,
                "source": row.source,
                "mode_at_time": row.mode_at_time,
            }
            for row in result.scalars()
        ]
