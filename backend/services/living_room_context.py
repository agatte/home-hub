"""Shadow-only living-room capability snapshot and decision gate.

The gate is deliberately read-only.  It receives a callable that builds a
typed snapshot from already-held service state, evaluates that snapshot with
pure logic, and optionally records the result.  It owns no device or
automation writer interface.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import delete, select

from backend.models import LivingRoomDecisionRecord
from backend.services.presence_fusion import STRONG_PRESENCE_FRESHNESS_S

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = "living_room_capability_snapshot.v1"
DECISION_VERSION = "living_room_decision_context.v1"
BEHAVIOR = "living_room_scene_curator_shadow_eligibility"
SHADOW_ONLY = True
LIVING_ROOM_LIGHT_IDS = frozenset({"1", "3", "4", "6"})
LUX_FRESHNESS_SECONDS = 30.0
WEATHER_FRESHNESS_SECONDS = 300.0
SCREEN_SYNC_FRESHNESS_SECONDS = 8.0
CHECKPOINT_SECONDS = 15 * 60
RETENTION_DAYS = 90


class CapabilityStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class FreshnessStatus(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class DecisionOutcome(str, Enum):
    ELIGIBLE = "eligible"
    DEGRADED_SKIP = "degraded_skip"
    SAFE_FALLBACK = "safe_fallback"


@dataclass(frozen=True)
class CapabilityHealth:
    name: str
    status: CapabilityStatus
    freshness: FreshnessStatus = FreshnessStatus.NOT_APPLICABLE
    configured: Optional[bool] = None
    connected: Optional[bool] = None
    breaker_state: Optional[str] = None
    consecutive_failures: int = 0
    heartbeat_age_seconds: Optional[float] = None
    last_success_at: Optional[str] = None
    post_start_success: bool = False
    detail_code: Optional[str] = None


@dataclass(frozen=True)
class Evidence:
    source: str
    status: CapabilityStatus
    freshness: FreshnessStatus
    observed_at: Optional[str] = None
    age_seconds: Optional[float] = None
    present: Optional[bool] = None
    zone: Optional[str] = None
    state: Optional[str] = None
    value: Optional[str | float | bool] = None
    confidence: Optional[float] = None
    stale_fallback: bool = False
    authoritative: bool = False


@dataclass(frozen=True)
class ProcessArbitration:
    """Engine-owned process/physical authority result and selected evidence."""

    state: str = "none"
    reason: str = "no_fresh_process_intent"
    source: Optional[str] = None
    device: Optional[str] = None
    committed_mode: Optional[str] = None
    candidate_mode: Optional[str] = None
    candidate_reason: Optional[str] = None
    idle_seconds: Optional[float] = None
    pending_mode: Optional[str] = None
    pending_dwell_age: Optional[float] = None
    gaming_qualification: Optional[str] = None
    received_at: Optional[str] = None
    age_seconds: Optional[float] = None


@dataclass(frozen=True)
class LightOwnership:
    active: bool
    source: Optional[str] = None
    light_ids: tuple[str, ...] = ()
    observed_at: Optional[str] = None
    age_seconds: Optional[float] = None
    freshness: FreshnessStatus = FreshnessStatus.NOT_APPLICABLE


@dataclass(frozen=True)
class CapabilitySnapshotV1:
    evaluated_at: str
    latitude_service_health: CapabilityHealth
    living_room_presence: Evidence
    couch_zone_evidence: Evidence
    desktop_physical_presence: Evidence
    process_activity: Evidence
    living_room_lux: Evidence
    hue_health: CapabilityHealth
    weather: Evidence
    music_sonos_health: CapabilityHealth
    music_state: Evidence
    mood_context: Evidence
    dnd_active: bool
    apartment_away: bool
    sleeping_active: bool
    manual_mode_override: Evidence
    manual_light_override: LightOwnership
    screen_sync_ownership: LightOwnership
    screen_sync_source_ownership: tuple[LightOwnership, ...]
    transit_ownership: LightOwnership
    desk_exit_ownership: LightOwnership
    other_protected_light_ownership: tuple[LightOwnership, ...]
    current_activity: str
    current_activity_source: str
    effective_mode: str
    effective_source: str
    decision_pipeline_health: CapabilityHealth
    season_event_context: Evidence
    process_arbitration: ProcessArbitration = field(
        default_factory=ProcessArbitration
    )
    version: str = SNAPSHOT_VERSION


@dataclass(frozen=True)
class DecisionContextV1:
    evaluated_at: str
    outcome: DecisionOutcome
    reason_codes: tuple[str, ...]
    optional_context_reason_codes: tuple[str, ...]
    eligible_for_scene_curator: bool
    scene_selected: bool = False
    actuation_attempted: bool = False
    actuation_outcome: str = "not_attempted"
    physical_authority: str = "latitude"
    process_arbitration_state: str = "none"
    process_arbitration_reason: str = "no_fresh_process_intent"
    behavior: str = BEHAVIOR
    version: str = DECISION_VERSION


@dataclass(frozen=True)
class DecisionEnvelope:
    snapshot: CapabilitySnapshotV1
    decision: DecisionContextV1


def _append_once(reasons: list[str], code: str) -> None:
    if code not in reasons:
        reasons.append(code)


def _is_process_activity_source(source: str) -> bool:
    return source == "process" or source.startswith("process:")


def evaluate_living_room_context(
    snapshot: CapabilitySnapshotV1,
) -> DecisionContextV1:
    """Pure, deterministic evaluation of one living-room snapshot."""
    degraded: list[str] = []
    vetoes: list[str] = []
    optional: list[str] = []

    latitude = snapshot.latitude_service_health
    presence = snapshot.living_room_presence
    couch = snapshot.couch_zone_evidence

    if latitude.status == CapabilityStatus.DISABLED:
        _append_once(degraded, "latitude_disabled")
    elif latitude.status in {
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.UNKNOWN,
    }:
        _append_once(degraded, "latitude_unavailable")
    elif presence.freshness == FreshnessStatus.MISSING:
        _append_once(degraded, "latitude_unavailable")
    elif (
        presence.freshness == FreshnessStatus.STALE
        or presence.age_seconds is None
        or presence.age_seconds > STRONG_PRESENCE_FRESHNESS_S
    ):
        _append_once(degraded, "latitude_evidence_stale")
    elif not presence.present:
        _append_once(degraded, "authoritative_living_room_absent")
        if (
            snapshot.process_activity.freshness == FreshnessStatus.FRESH
            and snapshot.process_activity.state == "watching"
            and _is_process_activity_source(snapshot.process_activity.source)
        ):
            _append_once(degraded, "process_physical_mismatch")
    elif couch.zone != "couch":
        _append_once(degraded, "couch_zone_uncommitted")

    if (
        presence.freshness == FreshnessStatus.FRESH
        and presence.present
        and couch.zone == "couch"
        and snapshot.desktop_physical_presence.freshness == FreshnessStatus.FRESH
        and snapshot.desktop_physical_presence.present
    ):
        _append_once(degraded, "physical_room_conflict")

    if snapshot.hue_health.status != CapabilityStatus.HEALTHY:
        _append_once(degraded, "hue_unavailable")

    process_arbitration = snapshot.process_arbitration
    if process_arbitration.state == "veto":
        _append_once(
            vetoes,
            process_arbitration.reason or "process_intent_active",
        )
    elif process_arbitration.state == "discounted":
        _append_once(
            optional,
            process_arbitration.reason or "stale_desktop_process_discounted",
        )

    if snapshot.apartment_away:
        _append_once(vetoes, "apartment_away")
    if snapshot.dnd_active:
        _append_once(vetoes, "dnd_active")
    if snapshot.sleeping_active:
        _append_once(vetoes, "sleeping_active")
    if snapshot.manual_mode_override.present:
        _append_once(vetoes, "manual_mode_override_active")
    if snapshot.manual_light_override.active:
        _append_once(vetoes, "manual_light_override_active")

    screen_ids = set(snapshot.screen_sync_ownership.light_ids)
    if (
        snapshot.screen_sync_ownership.active
        and snapshot.screen_sync_ownership.freshness == FreshnessStatus.FRESH
        and screen_ids & LIVING_ROOM_LIGHT_IDS
    ):
        _append_once(vetoes, "screen_sync_living_room_owner")

    protected_ids = set(snapshot.transit_ownership.light_ids)
    protected_ids.update(snapshot.desk_exit_ownership.light_ids)
    if (
        snapshot.transit_ownership.active
        or snapshot.desk_exit_ownership.active
    ) and protected_ids & LIVING_ROOM_LIGHT_IDS:
        _append_once(vetoes, "transit_or_desk_exit_living_room_owner")

    if snapshot.decision_pipeline_health.status != CapabilityStatus.HEALTHY:
        detail = snapshot.decision_pipeline_health.detail_code
        if detail == "decision_recording_unavailable":
            _append_once(vetoes, "decision_recording_unavailable")
        else:
            _append_once(vetoes, "decision_evaluator_unavailable")

    if snapshot.living_room_lux.freshness == FreshnessStatus.STALE:
        _append_once(optional, "living_room_lux_stale")
    if snapshot.weather.freshness == FreshnessStatus.STALE:
        _append_once(optional, "weather_stale")
    if snapshot.music_sonos_health.status != CapabilityStatus.HEALTHY:
        _append_once(optional, "music_unavailable")
    if not snapshot.mood_context.authoritative:
        _append_once(optional, "authoritative_mood_context_unavailable")
    if snapshot.season_event_context.state == "not_collected_in_v1":
        _append_once(optional, "not_collected_in_v1")

    reasons = tuple(degraded + vetoes)
    if vetoes:
        outcome = DecisionOutcome.SAFE_FALLBACK
    elif degraded:
        outcome = DecisionOutcome.DEGRADED_SKIP
    else:
        outcome = DecisionOutcome.ELIGIBLE

    return DecisionContextV1(
        evaluated_at=snapshot.evaluated_at,
        outcome=outcome,
        reason_codes=reasons,
        optional_context_reason_codes=tuple(optional),
        eligible_for_scene_curator=outcome == DecisionOutcome.ELIGIBLE,
        process_arbitration_state=process_arbitration.state,
        process_arbitration_reason=process_arbitration.reason,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def envelope_to_dict(envelope: DecisionEnvelope) -> dict[str, Any]:
    return {
        "shadow_only": SHADOW_ONLY,
        "snapshot": _jsonable(asdict(envelope.snapshot)),
        "decision": _jsonable(asdict(envelope.decision)),
    }


_FINGERPRINT_OMIT_KEYS = frozenset({
    "evaluated_at",
    "observed_at",
    "age_seconds",
    "heartbeat_age_seconds",
    "idle_seconds",
    "last_success_at",
    "pending_dwell_age",
    "received_at",
})

# These are exact telemetry values whose already-derived categorical fields
# carry every decision-relevant distinction. They remain in persisted
# snapshots; only the semantic comparison projection omits them.
_FINGERPRINT_OMIT_PATHS = frozenset({
    ("snapshot", "living_room_lux", "value"),
    ("snapshot", "living_room_presence", "confidence"),
    ("snapshot", "couch_zone_evidence", "confidence"),
    ("snapshot", "desktop_physical_presence", "confidence"),
})


def _semantic_value(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: _semantic_value(item, (*path, key))
            for key, item in value.items()
            if key not in _FINGERPRINT_OMIT_KEYS
            and (*path, key) not in _FINGERPRINT_OMIT_PATHS
        }
    if isinstance(value, list):
        return [_semantic_value(item, path) for item in value]
    return value


def semantic_fingerprint(envelope: DecisionEnvelope) -> str:
    semantic = _semantic_value(envelope_to_dict(envelope))
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class LivingRoomDecisionRecorder:
    """Semantic-change recorder with bounded checkpoints and history."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        checkpoint_seconds: int = CHECKPOINT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._checkpoint_seconds = checkpoint_seconds
        self._last_fingerprint: Optional[str] = None
        self._last_persisted_at: Optional[datetime] = None
        self._healthy = True
        self._last_error: Optional[str] = None

    @property
    def healthy(self) -> bool:
        return self._healthy

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._healthy else "degraded",
            "last_error": self._last_error,
            "last_persisted_at": (
                self._last_persisted_at.isoformat()
                if self._last_persisted_at else None
            ),
        }

    async def initialize(self) -> None:
        try:
            async with self._session_factory() as session:
                row = (await session.execute(
                    select(LivingRoomDecisionRecord)
                    .order_by(LivingRoomDecisionRecord.evaluated_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
            if row is not None:
                self._last_fingerprint = row.semantic_fingerprint
                self._last_persisted_at = _as_utc(row.evaluated_at)
            self._healthy = True
            self._last_error = None
        except Exception as exc:
            self._healthy = False
            self._last_error = type(exc).__name__
            logger.error("Living-room recorder initialization failed", exc_info=True)

    async def persist_if_needed(
        self,
        envelope: DecisionEnvelope,
        *,
        now: Optional[datetime] = None,
        force: bool = False,
    ) -> bool:
        now = _as_utc(now or datetime.now(timezone.utc))
        fingerprint = semantic_fingerprint(envelope)
        checkpoint_due = (
            self._last_persisted_at is None
            or (now - self._last_persisted_at).total_seconds()
            >= self._checkpoint_seconds
        )
        if (
            not force
            and fingerprint == self._last_fingerprint
            and not checkpoint_due
        ):
            return False

        payload = envelope_to_dict(envelope)
        try:
            async with self._session_factory() as session:
                row = LivingRoomDecisionRecord(
                    evaluated_at=now,
                    behavior=envelope.decision.behavior,
                    outcome=envelope.decision.outcome.value,
                    reason_codes=list(envelope.decision.reason_codes),
                    snapshot_version=envelope.snapshot.version,
                    snapshot=payload["snapshot"],
                    decision=payload["decision"],
                    semantic_fingerprint=fingerprint,
                )
                session.add(row)
                await session.commit()
        except Exception as exc:
            self._healthy = False
            self._last_error = type(exc).__name__
            logger.error("Living-room decision persistence failed", exc_info=True)
            return False

        self._last_fingerprint = fingerprint
        self._last_persisted_at = now
        self._healthy = True
        self._last_error = None
        return True

    async def history(self, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("history limit must be between 1 and 100")
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(LivingRoomDecisionRecord)
                .order_by(LivingRoomDecisionRecord.evaluated_at.desc())
                .limit(limit)
            )).scalars().all()
        return [
            {
                "id": row.id,
                "evaluated_at": _as_utc(row.evaluated_at).isoformat(),
                "shadow_only": SHADOW_ONLY,
                "behavior": row.behavior,
                "outcome": row.outcome,
                "reason_codes": row.reason_codes,
                "snapshot_version": row.snapshot_version,
                "snapshot": row.snapshot,
                "decision": row.decision,
                "semantic_fingerprint": row.semantic_fingerprint,
            }
            for row in rows
        ]

    async def prune(
        self, *, now: Optional[datetime] = None,
    ) -> int:
        cutoff = _as_utc(now or datetime.now(timezone.utc)) - timedelta(
            days=RETENTION_DAYS
        )
        async with self._session_factory() as session:
            result = await session.execute(
                delete(LivingRoomDecisionRecord).where(
                    LivingRoomDecisionRecord.evaluated_at < cutoff
                )
            )
            await session.commit()
        return result.rowcount or 0


def _freshness(
    age_seconds: Optional[float],
    threshold_seconds: float,
) -> FreshnessStatus:
    if age_seconds is None:
        return FreshnessStatus.MISSING
    if age_seconds <= threshold_seconds:
        return FreshnessStatus.FRESH
    return FreshnessStatus.STALE


class LivingRoomSnapshotBuilder:
    """Build typed snapshots from narrow, read-only source callables."""

    def __init__(
        self,
        *,
        latitude_configured: Callable[[], bool],
        camera_status: Callable[[], dict[str, Any]],
        presence_sources: Callable[[], dict[str, dict[str, Any]]],
        living_room_lux: Callable[[], dict[str, Any]],
        hue_status: Callable[[], dict[str, Any]],
        weather_status: Callable[[], dict[str, Any]],
        sonos_status: Callable[[], dict[str, Any]],
        activity_context: Callable[[], dict[str, Any]],
        policy_context: Callable[[], dict[str, Any]],
        ownership_context: Callable[[], dict[str, Any]],
        pipeline_status: Callable[[], dict[str, Any]],
        mood_status: Callable[[], dict[str, Any]],
    ) -> None:
        self._latitude_configured = latitude_configured
        self._camera_status = camera_status
        self._presence_sources = presence_sources
        self._living_room_lux = living_room_lux
        self._hue_status = hue_status
        self._weather_status = weather_status
        self._sonos_status = sonos_status
        self._activity_context = activity_context
        self._policy_context = policy_context
        self._ownership_context = ownership_context
        self._pipeline_status = pipeline_status
        self._mood_status = mood_status

    @staticmethod
    def _optional(
        getter: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return getter() or {}
        except Exception:
            logger.debug("Optional living-room context getter failed", exc_info=True)
            return {}

    def __call__(self) -> CapabilitySnapshotV1:
        now = datetime.now(timezone.utc)
        evaluated_at = now.isoformat()

        configured = bool(self._latitude_configured())
        camera = self._camera_status() or {}
        sources = self._presence_sources() or {}
        latitude_row = sources.get("latitude") or {}
        camera_enabled = bool(camera.get("enabled"))
        camera_paused = bool(camera.get("paused"))
        camera_heartbeat = camera.get("heartbeat") or {}
        if not configured:
            latitude_status = CapabilityStatus.DISABLED
            latitude_detail = "latitude_disabled"
        elif not camera_enabled or camera_paused:
            latitude_status = CapabilityStatus.UNAVAILABLE
            latitude_detail = "latitude_unavailable"
        elif camera_heartbeat.get("stale"):
            latitude_status = CapabilityStatus.DEGRADED
            latitude_detail = "latitude_heartbeat_stale"
        elif not camera_heartbeat:
            latitude_status = CapabilityStatus.UNKNOWN
            latitude_detail = "latitude_heartbeat_missing"
        elif not latitude_row:
            latitude_status = CapabilityStatus.UNKNOWN
            latitude_detail = "latitude_post_start_evidence_missing"
        else:
            latitude_status = CapabilityStatus.HEALTHY
            latitude_detail = None

        latitude_age = latitude_row.get("age_s")
        latitude_freshness = _freshness(
            latitude_age, STRONG_PRESENCE_FRESHNESS_S
        )
        latitude_health = CapabilityHealth(
            name="latitude",
            status=latitude_status,
            freshness=latitude_freshness,
            configured=configured,
            connected=camera_enabled and not camera_paused,
            heartbeat_age_seconds=camera_heartbeat.get("age_seconds"),
            last_success_at=latitude_row.get("last_at"),
            post_start_success=bool(latitude_row),
            detail_code=latitude_detail,
        )
        living_presence = Evidence(
            source="latitude",
            status=(
                CapabilityStatus.HEALTHY
                if latitude_row else CapabilityStatus.UNAVAILABLE
            ),
            freshness=latitude_freshness,
            observed_at=latitude_row.get("last_at"),
            age_seconds=latitude_age,
            present=bool(latitude_row.get("face_present"))
            if latitude_row else None,
            zone=latitude_row.get("zone"),
            confidence=latitude_row.get("face_confidence"),
            authoritative=True,
        )
        couch = replace(living_presence)

        desktop_row = sources.get("desktop") or {}
        desktop_age = desktop_row.get("age_s")
        desktop = Evidence(
            source="desktop",
            status=(
                CapabilityStatus.HEALTHY
                if desktop_row else CapabilityStatus.UNKNOWN
            ),
            freshness=_freshness(
                desktop_age, STRONG_PRESENCE_FRESHNESS_S
            ),
            observed_at=desktop_row.get("last_at"),
            age_seconds=desktop_age,
            present=bool(desktop_row.get("face_present"))
            if desktop_row else None,
            zone="desk" if desktop_row.get("face_present") else None,
            confidence=desktop_row.get("face_confidence"),
            authoritative=True,
        )

        activity = self._activity_context() or {}
        process_age = activity.get("current_activity_age_seconds")
        process_source = (
            activity.get("current_activity_source_key")
            or activity.get("current_activity_source", "unknown")
        )
        process = Evidence(
            source=process_source,
            status=CapabilityStatus.HEALTHY,
            freshness=(
                FreshnessStatus.FRESH
                if activity.get("current_activity_fresh")
                else _freshness(process_age, 300.0)
            ),
            observed_at=activity.get("current_activity_reported_at"),
            age_seconds=process_age,
            state=activity.get("current_activity"),
            authoritative=False,
        )
        arbitration_row = (
            activity.get("physical_context_process_arbitration") or {}
        )
        process_arbitration = ProcessArbitration(
            state=arbitration_row.get("state", "none"),
            reason=arbitration_row.get(
                "reason", "no_fresh_process_intent",
            ),
            source=arbitration_row.get("source"),
            device=arbitration_row.get("device"),
            committed_mode=arbitration_row.get("committed_mode"),
            candidate_mode=arbitration_row.get("candidate_mode"),
            candidate_reason=arbitration_row.get("candidate_reason"),
            idle_seconds=arbitration_row.get("idle_seconds"),
            pending_mode=arbitration_row.get("pending_mode"),
            pending_dwell_age=arbitration_row.get("pending_dwell_age"),
            gaming_qualification=arbitration_row.get(
                "gaming_qualification"
            ),
            received_at=arbitration_row.get("received_at"),
            age_seconds=arbitration_row.get("age_seconds"),
        )

        lux = self._optional(self._living_room_lux)
        lux_age = lux.get("age_seconds")
        lux_evidence = Evidence(
            source="latitude_lux",
            status=(
                CapabilityStatus.HEALTHY
                if lux.get("value") is not None else CapabilityStatus.UNKNOWN
            ),
            freshness=_freshness(lux_age, LUX_FRESHNESS_SECONDS),
            observed_at=lux.get("observed_at"),
            age_seconds=lux_age,
            value=lux.get("value"),
            authoritative=False,
        )

        hue = self._hue_status() or {}
        hue_configured = bool(hue.get("configured"))
        hue_connected = bool(hue.get("connected"))
        hue_breaker = hue.get("breaker_state")
        hue_failures = int(hue.get("consecutive_failures") or 0)
        hue_heartbeat = hue.get("heartbeat") or {}
        hue_last_success = hue.get("last_success_at")
        if not hue_configured:
            hue_capability = CapabilityStatus.DISABLED
            hue_detail = "hue_not_configured"
        elif not hue_connected or hue_breaker != "closed":
            hue_capability = CapabilityStatus.UNAVAILABLE
            hue_detail = "hue_disconnected_or_breaker_not_closed"
        elif hue_failures or hue_heartbeat.get("stale"):
            hue_capability = CapabilityStatus.DEGRADED
            hue_detail = "hue_failing_or_stale"
        elif not hue_last_success:
            hue_capability = CapabilityStatus.UNKNOWN
            hue_detail = "hue_post_start_success_missing"
        elif not hue_heartbeat:
            hue_capability = CapabilityStatus.UNKNOWN
            hue_detail = "hue_heartbeat_missing"
        else:
            hue_capability = CapabilityStatus.HEALTHY
            hue_detail = None
        hue_health = CapabilityHealth(
            name="hue",
            status=hue_capability,
            freshness=(
                FreshnessStatus.STALE
                if hue_heartbeat.get("stale")
                else FreshnessStatus.FRESH
                if hue_heartbeat
                else FreshnessStatus.MISSING
            ),
            configured=hue_configured,
            connected=hue_connected,
            breaker_state=hue_breaker,
            consecutive_failures=hue_failures,
            heartbeat_age_seconds=hue_heartbeat.get("age_seconds"),
            last_success_at=hue_last_success,
            post_start_success=bool(hue_last_success),
            detail_code=hue_detail,
        )

        weather = self._optional(self._weather_status)
        weather_age = weather.get("age_seconds")
        weather_evidence = Evidence(
            source="weather_cache",
            status=(
                CapabilityStatus.HEALTHY
                if weather.get("condition") is not None
                else CapabilityStatus.UNKNOWN
            ),
            freshness=_freshness(weather_age, WEATHER_FRESHNESS_SECONDS),
            observed_at=weather.get("observed_at"),
            age_seconds=weather_age,
            state=weather.get("condition"),
            stale_fallback=bool(weather.get("stale_fallback")),
            authoritative=False,
        )

        sonos = self._optional(self._sonos_status)
        sonos_age = sonos.get("age_seconds")
        sonos_fresh = bool(sonos.get("fresh"))
        if (
            sonos.get("connected")
            and sonos.get("breaker_state") == "closed"
            and sonos_fresh
            and sonos.get("last_successful_status_at")
        ):
            sonos_capability = CapabilityStatus.HEALTHY
            sonos_detail = None
        elif not sonos.get("configured"):
            sonos_capability = CapabilityStatus.DISABLED
            sonos_detail = "sonos_not_configured"
        else:
            sonos_capability = CapabilityStatus.UNAVAILABLE
            sonos_detail = "sonos_cached_status_unavailable"
        sonos_health = CapabilityHealth(
            name="sonos",
            status=sonos_capability,
            freshness=_freshness(sonos_age, 10.0),
            configured=sonos.get("configured"),
            connected=sonos.get("connected"),
            breaker_state=sonos.get("breaker_state"),
            consecutive_failures=int(sonos.get("consecutive_failures") or 0),
            last_success_at=sonos.get("last_successful_status_at"),
            post_start_success=bool(sonos.get("last_successful_status_at")),
            detail_code=sonos_detail,
        )
        music_state = Evidence(
            source="sonos_cached_status",
            status=sonos_capability,
            freshness=_freshness(sonos_age, 10.0),
            observed_at=sonos.get("last_successful_status_at"),
            age_seconds=sonos_age,
            state=sonos.get("state", "unknown"),
            authoritative=False,
        )

        mood = self._optional(self._mood_status)
        mood_context = Evidence(
            source="mood_context",
            status=(
                CapabilityStatus.DEGRADED
                if mood.get("enabled") else CapabilityStatus.DISABLED
            ),
            freshness=FreshnessStatus.NOT_APPLICABLE,
            state="no_explicit_authoritative_mood",
            authoritative=False,
        )

        policy = self._policy_context() or {}
        manual_mode_source = policy.get("manual_mode_source") or "none"
        # physical_context_relax is represented by the engine's override
        # machinery for lifecycle/release semantics, but it is autonomous
        # couch provenance rather than user-owned manual intent.
        user_manual_mode_active = bool(
            policy.get("manual_mode_active")
            and manual_mode_source != "physical_context_relax"
        )
        ownership = self._ownership_context() or {}
        manual = ownership.get("manual") or {}
        manual_ids = tuple(sorted(str(i) for i in manual.get("light_ids", [])))
        manual_stamps = manual.get("set_at_by_light") or {}
        manual_stamp = max(
            (manual_stamps.get(i) for i in manual_ids if manual_stamps.get(i)),
            default=None,
        )

        screen = ownership.get("screen_sync") or {}
        available_screen_ids = set(screen.get("available_light_ids") or [])
        screen_sources = dict(screen.get("sources") or {})
        legacy_source = screen.get("source")
        if legacy_source and legacy_source not in screen_sources:
            screen_sources[legacy_source] = {
                "last_color_at": screen.get("last_color_at"),
                "age_seconds": screen.get("age_seconds"),
            }

        source_targets = {
            "desktop": ("2", "5"),
            "laptop": ("1", "3", "4"),
        }
        screen_source_owners = tuple(
            LightOwnership(
                active=(
                    bool(source_ids)
                    and source_freshness == FreshnessStatus.FRESH
                ),
                source=source,
                light_ids=source_ids,
                observed_at=source_row.get("last_color_at"),
                age_seconds=source_age,
                freshness=source_freshness,
            )
            for source, targets in source_targets.items()
            if (source_row := screen_sources.get(source)) is not None
            for source_age in (source_row.get("age_seconds"),)
            for source_freshness in (
                _freshness(source_age, SCREEN_SYNC_FRESHNESS_SECONDS),
            )
            for source_ids in (
                tuple(i for i in targets if i in available_screen_ids),
            )
        )
        fresh_screen_owners = tuple(
            owner for owner in screen_source_owners if owner.active
        )
        screen_ids = tuple(sorted({
            light_id
            for owner in fresh_screen_owners
            for light_id in owner.light_ids
        }))
        newest_screen_owner = min(
            fresh_screen_owners or screen_source_owners,
            key=lambda owner: (
                owner.age_seconds
                if owner.age_seconds is not None else float("inf")
            ),
            default=None,
        )
        screen_owner = LightOwnership(
            active=bool(fresh_screen_owners),
            source=(
                "+".join(owner.source or "unknown" for owner in fresh_screen_owners)
                or None
            ),
            light_ids=screen_ids,
            observed_at=(
                newest_screen_owner.observed_at if newest_screen_owner else None
            ),
            age_seconds=(
                newest_screen_owner.age_seconds if newest_screen_owner else None
            ),
            freshness=(
                FreshnessStatus.FRESH
                if fresh_screen_owners
                else FreshnessStatus.STALE
                if screen_source_owners
                else FreshnessStatus.MISSING
            ),
        )

        transit = ownership.get("transit") or {}
        transit_owner = LightOwnership(
            active=bool(transit.get("active")),
            source="transit",
            light_ids=tuple(sorted(str(i) for i in transit.get("light_ids", []))),
            freshness=FreshnessStatus.NOT_APPLICABLE,
        )
        desk_exit = ownership.get("desk_exit") or {}
        desk_exit_owner = LightOwnership(
            active=bool(desk_exit.get("active")),
            source="desk_exit",
            light_ids=tuple(
                sorted(str(i) for i in desk_exit.get("light_ids", []))
            ),
            freshness=FreshnessStatus.NOT_APPLICABLE,
        )
        other_owners = tuple(
            owner for owner in (transit_owner, desk_exit_owner) if owner.active
        )

        pipeline = self._pipeline_status() or {}
        pipeline_health = CapabilityHealth(
            name="living_room_decision_pipeline",
            status=(
                CapabilityStatus.HEALTHY
                if pipeline.get("enabled") else CapabilityStatus.DEGRADED
            ),
            freshness=FreshnessStatus.FRESH,
            post_start_success=bool(pipeline.get("enabled")),
            detail_code=(
                None if pipeline.get("enabled") else "automation_pipeline_disabled"
            ),
        )

        return CapabilitySnapshotV1(
            evaluated_at=evaluated_at,
            latitude_service_health=latitude_health,
            living_room_presence=living_presence,
            couch_zone_evidence=couch,
            desktop_physical_presence=desktop,
            process_activity=process,
            living_room_lux=lux_evidence,
            hue_health=hue_health,
            weather=weather_evidence,
            music_sonos_health=sonos_health,
            music_state=music_state,
            mood_context=mood_context,
            dnd_active=bool(policy.get("dnd_active")),
            apartment_away=bool(policy.get("apartment_away")),
            sleeping_active=bool(policy.get("sleeping_active")),
            manual_mode_override=Evidence(
                source=manual_mode_source,
                status=CapabilityStatus.HEALTHY,
                freshness=FreshnessStatus.NOT_APPLICABLE,
                present=user_manual_mode_active,
                state=policy.get("manual_mode"),
                authoritative=True,
            ),
            manual_light_override=LightOwnership(
                active=bool(manual_ids),
                source="manual_per_light" if manual_ids else None,
                light_ids=manual_ids,
                observed_at=manual_stamp,
                freshness=FreshnessStatus.NOT_APPLICABLE,
            ),
            screen_sync_ownership=screen_owner,
            screen_sync_source_ownership=screen_source_owners,
            transit_ownership=transit_owner,
            desk_exit_ownership=desk_exit_owner,
            other_protected_light_ownership=other_owners,
            current_activity=activity.get("current_activity", "unknown"),
            current_activity_source=process_source,
            effective_mode=activity.get("effective_mode", "unknown"),
            effective_source=activity.get("effective_source", "unknown"),
            decision_pipeline_health=pipeline_health,
            season_event_context=Evidence(
                source="living_room_gate_v1",
                status=CapabilityStatus.DISABLED,
                freshness=FreshnessStatus.NOT_APPLICABLE,
                state="not_collected_in_v1",
                authoritative=False,
            ),
            process_arbitration=process_arbitration,
        )


def unavailable_snapshot(
    evaluated_at: datetime,
    *,
    pipeline_detail: str,
) -> CapabilitySnapshotV1:
    stamp = _as_utc(evaluated_at).isoformat()
    unavailable = CapabilityHealth(
        name="unavailable",
        status=CapabilityStatus.UNAVAILABLE,
        freshness=FreshnessStatus.MISSING,
        detail_code="snapshot_unavailable",
    )
    missing = Evidence(
        source="unavailable",
        status=CapabilityStatus.UNAVAILABLE,
        freshness=FreshnessStatus.MISSING,
    )
    no_owner = LightOwnership(active=False)
    return CapabilitySnapshotV1(
        evaluated_at=stamp,
        latitude_service_health=replace(unavailable, name="latitude"),
        living_room_presence=missing,
        couch_zone_evidence=missing,
        desktop_physical_presence=missing,
        process_activity=missing,
        living_room_lux=missing,
        hue_health=replace(unavailable, name="hue"),
        weather=missing,
        music_sonos_health=replace(unavailable, name="sonos"),
        music_state=missing,
        mood_context=missing,
        dnd_active=False,
        apartment_away=False,
        sleeping_active=False,
        manual_mode_override=missing,
        manual_light_override=no_owner,
        screen_sync_ownership=no_owner,
        screen_sync_source_ownership=(),
        transit_ownership=no_owner,
        desk_exit_ownership=no_owner,
        other_protected_light_ownership=(),
        current_activity="unknown",
        current_activity_source="unknown",
        effective_mode="unknown",
        effective_source="unknown",
        decision_pipeline_health=CapabilityHealth(
            name="living_room_decision_pipeline",
            status=CapabilityStatus.DEGRADED,
            freshness=FreshnessStatus.MISSING,
            detail_code=pipeline_detail,
        ),
        season_event_context=Evidence(
            source="living_room_gate_v1",
            status=CapabilityStatus.DISABLED,
            freshness=FreshnessStatus.NOT_APPLICABLE,
            state="not_collected_in_v1",
        ),
    )


class LivingRoomDecisionGate:
    """Evaluate and record read-only living-room context envelopes."""

    def __init__(
        self,
        snapshot_provider: Callable[[], CapabilitySnapshotV1],
        recorder: LivingRoomDecisionRecorder,
        *,
        evaluator: Callable[
            [CapabilitySnapshotV1], DecisionContextV1
        ] = evaluate_living_room_context,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._recorder = recorder
        self._evaluator = evaluator
        self._current: Optional[DecisionEnvelope] = None
        self._evaluated_at: Optional[datetime] = None
        self._evaluator_healthy = True
        self._last_evaluator_error: Optional[str] = None
        self._lock = asyncio.Lock()

    async def start(self) -> DecisionEnvelope:
        await self._recorder.initialize()
        return await self.evaluate(trigger="bootstrap")

    def _pipeline_health(
        self,
        base: Optional[CapabilityHealth] = None,
        *,
        assume_recorder_healthy: bool = False,
    ) -> CapabilityHealth:
        if not self._evaluator_healthy:
            return CapabilityHealth(
                name="living_room_decision_pipeline",
                status=CapabilityStatus.DEGRADED,
                freshness=FreshnessStatus.FRESH,
                detail_code="decision_evaluator_unavailable",
            )
        if not self._recorder.healthy and not assume_recorder_healthy:
            return CapabilityHealth(
                name="living_room_decision_pipeline",
                status=CapabilityStatus.DEGRADED,
                freshness=FreshnessStatus.FRESH,
                detail_code="decision_recording_unavailable",
            )
        if base is not None and base.status != CapabilityStatus.HEALTHY:
            return base
        return CapabilityHealth(
            name="living_room_decision_pipeline",
            status=CapabilityStatus.HEALTHY,
            freshness=FreshnessStatus.FRESH,
            post_start_success=True,
        )

    async def evaluate(self, *, trigger: str = "normal") -> DecisionEnvelope:
        del trigger  # Kept for call-site observability without fingerprint churn.
        async with self._lock:
            now = datetime.now(timezone.utc)
            self._evaluator_healthy = True
            self._last_evaluator_error = None
            base_pipeline_health: Optional[CapabilityHealth] = None
            try:
                snapshot = self._snapshot_provider()
                base_pipeline_health = snapshot.decision_pipeline_health
                snapshot = replace(
                    snapshot,
                    decision_pipeline_health=self._pipeline_health(
                        base_pipeline_health
                    ),
                )
                decision = self._evaluator(snapshot)
            except Exception as exc:
                self._evaluator_healthy = False
                self._last_evaluator_error = type(exc).__name__
                logger.error("Living-room decision evaluation failed", exc_info=True)
                snapshot = unavailable_snapshot(
                    now, pipeline_detail="decision_evaluator_unavailable"
                )
                decision = DecisionContextV1(
                    evaluated_at=snapshot.evaluated_at,
                    outcome=DecisionOutcome.SAFE_FALLBACK,
                    reason_codes=("decision_evaluator_unavailable",),
                    optional_context_reason_codes=("not_collected_in_v1",),
                    eligible_for_scene_curator=False,
                )

            envelope = DecisionEnvelope(snapshot=snapshot, decision=decision)
            recorder_was_healthy = self._recorder.healthy
            persistence_envelope = envelope
            if not recorder_was_healthy and self._evaluator_healthy:
                recovered_snapshot = replace(
                    snapshot,
                    decision_pipeline_health=self._pipeline_health(
                        base_pipeline_health,
                        assume_recorder_healthy=True,
                    ),
                )
                persistence_envelope = DecisionEnvelope(
                    snapshot=recovered_snapshot,
                    decision=self._evaluator(recovered_snapshot),
                )

            persisted = await self._recorder.persist_if_needed(
                persistence_envelope,
                now=now,
                force=not recorder_was_healthy,
            )
            if not self._recorder.healthy:
                snapshot = replace(
                    snapshot,
                    decision_pipeline_health=self._pipeline_health(
                        snapshot.decision_pipeline_health
                    ),
                )
                reasons = list(decision.reason_codes)
                _append_once(reasons, "decision_recording_unavailable")
                decision = replace(
                    decision,
                    outcome=DecisionOutcome.SAFE_FALLBACK,
                    reason_codes=tuple(reasons),
                    eligible_for_scene_curator=False,
                )
                envelope = DecisionEnvelope(snapshot=snapshot, decision=decision)
            elif not recorder_was_healthy and persisted:
                envelope = persistence_envelope

            self._current = envelope
            self._evaluated_at = now
            return envelope

    def current_envelope(self) -> Optional[dict[str, Any]]:
        if self._current is None:
            return None
        return envelope_to_dict(self._current)

    def current_status(self) -> dict[str, Any]:
        age = None
        if self._evaluated_at is not None:
            age = max(
                0.0,
                (datetime.now(timezone.utc) - self._evaluated_at).total_seconds(),
            )
        envelope = self.current_envelope()
        return {
            **(envelope or {"snapshot": None, "decision": None}),
            "evaluator_age_seconds": round(age, 3) if age is not None else None,
            "persistence_health": self._recorder.health(),
        }

    def health_summary(self) -> dict[str, Any]:
        malfunction = not self._evaluator_healthy or not self._recorder.healthy
        decision = self._current.decision if self._current is not None else None
        age = None
        if self._evaluated_at is not None:
            age = max(
                0.0,
                (datetime.now(timezone.utc) - self._evaluated_at).total_seconds(),
            )
        return {
            "status": "degraded" if malfunction else "healthy",
            "shadow_only": SHADOW_ONLY,
            "outcome": decision.outcome.value if decision else None,
            "reason_codes": list(decision.reason_codes) if decision else [],
            "evaluator_age_seconds": round(age, 3) if age is not None else None,
            "evaluator_error": self._last_evaluator_error,
            "persistence": self._recorder.health(),
        }

    async def history(self, limit: int) -> list[dict[str, Any]]:
        return await self._recorder.history(limit)
