"""Pure authority, persistence, and no-actuation tests for the shadow gate."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import LivingRoomDecisionRecord
from backend.services.living_room_context import (
    CapabilityHealth,
    CapabilitySnapshotV1,
    CapabilityStatus,
    DecisionContextV1,
    DecisionEnvelope,
    DecisionOutcome,
    Evidence,
    FreshnessStatus,
    LightOwnership,
    ProcessArbitration,
    LivingRoomDecisionGate,
    LivingRoomDecisionRecorder,
    LivingRoomSnapshotBuilder,
    envelope_to_dict,
    evaluate_living_room_context,
    semantic_fingerprint,
)
from backend.services.sonos_service import SonosService


NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)


def _health(
    name: str,
    status: CapabilityStatus = CapabilityStatus.HEALTHY,
    *,
    detail_code: str | None = None,
) -> CapabilityHealth:
    return CapabilityHealth(
        name=name,
        status=status,
        freshness=FreshnessStatus.FRESH,
        configured=True,
        connected=True,
        breaker_state="closed",
        heartbeat_age_seconds=1.0,
        last_success_at=(NOW - timedelta(seconds=1)).isoformat(),
        post_start_success=True,
        detail_code=detail_code,
    )


def _evidence(
    source: str,
    *,
    present: bool | None = None,
    zone: str | None = None,
    state: str | None = None,
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    age_seconds: float | None = 1.0,
    authoritative: bool = False,
) -> Evidence:
    return Evidence(
        source=source,
        status=CapabilityStatus.HEALTHY,
        freshness=freshness,
        observed_at=(NOW - timedelta(seconds=age_seconds or 0)).isoformat(),
        age_seconds=age_seconds,
        present=present,
        zone=zone,
        state=state,
        authoritative=authoritative,
    )


def _snapshot(**changes) -> CapabilitySnapshotV1:
    no_owner = LightOwnership(active=False)
    base = CapabilitySnapshotV1(
        evaluated_at=NOW.isoformat(),
        latitude_service_health=_health("latitude"),
        living_room_presence=_evidence(
            "latitude", present=True, zone="couch", authoritative=True
        ),
        couch_zone_evidence=_evidence(
            "latitude", present=True, zone="couch", authoritative=True
        ),
        desktop_physical_presence=Evidence(
            source="desktop",
            status=CapabilityStatus.UNKNOWN,
            freshness=FreshnessStatus.MISSING,
        ),
        process_activity=_evidence("process", state="idle"),
        living_room_lux=replace(
            _evidence("latitude_lux"),
            value=120.0,
        ),
        hue_health=_health("hue"),
        weather=_evidence("weather_cache", state="Clear"),
        music_sonos_health=_health("sonos"),
        music_state=_evidence("sonos_cached_status", state="stopped"),
        mood_context=replace(
            _evidence("mood_context", state="explicit"),
            authoritative=True,
        ),
        dnd_active=False,
        apartment_away=False,
        sleeping_active=False,
        manual_mode_override=Evidence(
            source="none",
            status=CapabilityStatus.HEALTHY,
            freshness=FreshnessStatus.NOT_APPLICABLE,
            present=False,
            authoritative=True,
        ),
        manual_light_override=no_owner,
        screen_sync_ownership=no_owner,
        screen_sync_source_ownership=(),
        transit_ownership=no_owner,
        desk_exit_ownership=no_owner,
        other_protected_light_ownership=(),
        current_activity="idle",
        current_activity_source="time",
        effective_mode="idle",
        effective_source="time",
        decision_pipeline_health=_health("living_room_decision_pipeline"),
        season_event_context=Evidence(
            source="living_room_gate_v1",
            status=CapabilityStatus.DISABLED,
            freshness=FreshnessStatus.NOT_APPLICABLE,
            state="not_collected_in_v1",
        ),
    )
    return replace(base, **changes)


def _decision(snapshot: CapabilitySnapshotV1) -> DecisionContextV1:
    return evaluate_living_room_context(snapshot)


def test_fresh_latitude_couch_and_healthy_hue_is_shadow_eligible() -> None:
    result = _decision(_snapshot())
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert result.eligible_for_scene_curator is True
    assert result.scene_selected is False
    assert result.actuation_attempted is False
    assert result.actuation_outcome == "not_attempted"


def test_active_process_veto_makes_gate_ineligible() -> None:
    arbitration = ProcessArbitration(
        state="veto",
        reason="desktop_process_intent_active",
        source="process",
        device="desktop",
        committed_mode="working",
        candidate_mode="working",
        candidate_reason="foreground_working",
        idle_seconds=0.0,
    )

    result = _decision(_snapshot(process_arbitration=arbitration))

    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert result.eligible_for_scene_curator is False
    assert "desktop_process_intent_active" in result.reason_codes
    assert result.process_arbitration_state == "veto"
    assert result.process_arbitration_reason == "desktop_process_intent_active"


def test_discounted_desktop_intent_is_observable_but_non_blocking() -> None:
    arbitration = ProcessArbitration(
        state="discounted",
        reason="stale_desktop_process_discounted",
        source="process",
        device="desktop",
        committed_mode="gaming",
        candidate_mode="gaming",
        candidate_reason="foreground_game",
        idle_seconds=0.0,
        gaming_qualification="foreground_game",
    )

    result = _decision(_snapshot(process_arbitration=arbitration))

    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert result.eligible_for_scene_curator is True
    assert result.reason_codes == ()
    assert "stale_desktop_process_discounted" in (
        result.optional_context_reason_codes
    )
    assert result.process_arbitration_state == "discounted"


def test_process_watching_cannot_replace_fresh_latitude_absence() -> None:
    absent = _evidence(
        "latitude", present=False, zone=None, authoritative=True
    )
    result = _decision(_snapshot(
        living_room_presence=absent,
        couch_zone_evidence=absent,
        process_activity=_evidence("process", state="watching"),
    ))
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert "process_physical_mismatch" in result.reason_codes
    assert "authoritative_living_room_absent" in result.reason_codes


@pytest.mark.parametrize(
    "source",
    [
        "manual",
        "alexa:watching",
        "api:dashboard",
        "fusion_auto_apply",
        "camera",
    ],
)
def test_non_process_watching_does_not_emit_process_mismatch(
    source: str,
) -> None:
    absent = _evidence(
        "latitude", present=False, zone=None, authoritative=True
    )
    result = _decision(_snapshot(
        living_room_presence=absent,
        couch_zone_evidence=absent,
        process_activity=_evidence(source, state="watching"),
    ))

    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert "authoritative_living_room_absent" in result.reason_codes
    assert "process_physical_mismatch" not in result.reason_codes


def test_device_qualified_process_watching_emits_process_mismatch() -> None:
    absent = _evidence(
        "latitude", present=False, zone=None, authoritative=True
    )
    result = _decision(_snapshot(
        living_room_presence=absent,
        couch_zone_evidence=absent,
        process_activity=_evidence("process:desktop", state="watching"),
    ))

    assert "process_physical_mismatch" in result.reason_codes


def test_desktop_presence_plus_latitude_absence_remains_living_room_absent() -> None:
    absent = _evidence(
        "latitude", present=False, zone=None, authoritative=True
    )
    result = _decision(_snapshot(
        living_room_presence=absent,
        couch_zone_evidence=absent,
        desktop_physical_presence=_evidence(
            "desktop", present=True, zone="desk", authoritative=True
        ),
    ))
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert "authoritative_living_room_absent" in result.reason_codes
    assert "physical_room_conflict" not in result.reason_codes


@pytest.mark.parametrize(
    ("age_seconds", "expected_freshness", "expected_outcome"),
    [
        (7.999, FreshnessStatus.FRESH, DecisionOutcome.ELIGIBLE),
        (8.0, FreshnessStatus.FRESH, DecisionOutcome.ELIGIBLE),
        (8.001, FreshnessStatus.STALE, DecisionOutcome.DEGRADED_SKIP),
    ],
)
def test_latitude_eight_second_freshness_boundary(
    age_seconds: float,
    expected_freshness: FreshnessStatus,
    expected_outcome: DecisionOutcome,
) -> None:
    builder = _builder(presence_sources=lambda: {
        "latitude": {
            "last_at": NOW.isoformat(),
            "age_s": age_seconds,
            "face_present": True,
            "face_confidence": 0.9,
            "zone": "couch",
        }
    })
    snapshot = builder()
    result = _decision(snapshot)

    assert snapshot.living_room_presence.freshness == expected_freshness
    assert result.outcome == expected_outcome
    assert (
        "latitude_evidence_stale" in result.reason_codes
    ) is (age_seconds > 8.0)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (CapabilityStatus.DISABLED, "latitude_disabled"),
        (CapabilityStatus.DEGRADED, "latitude_unavailable"),
        (CapabilityStatus.UNAVAILABLE, "latitude_unavailable"),
    ],
)
def test_latitude_disabled_and_unavailable_are_distinct(
    status: CapabilityStatus, reason: str,
) -> None:
    missing = Evidence(
        source="latitude",
        status=status,
        freshness=FreshnessStatus.MISSING,
    )
    result = _decision(_snapshot(
        latitude_service_health=_health("latitude", status),
        living_room_presence=missing,
        couch_zone_evidence=missing,
        process_activity=_evidence("process", state="watching"),
    ))
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert reason in result.reason_codes
    assert result.eligible_for_scene_curator is False


def test_uncommitted_couch_zone_skips() -> None:
    uncommitted = _evidence(
        "latitude", present=True, zone=None, authoritative=True
    )
    result = _decision(_snapshot(
        living_room_presence=uncommitted,
        couch_zone_evidence=uncommitted,
    ))
    assert "couch_zone_uncommitted" in result.reason_codes


def test_stale_weather_is_ignored_for_eligibility() -> None:
    result = _decision(_snapshot(weather=_evidence(
        "weather_cache",
        state="Rain",
        freshness=FreshnessStatus.STALE,
        age_seconds=301,
    )))
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert "weather_stale" in result.optional_context_reason_codes


def test_stale_living_room_lux_is_ignored() -> None:
    result = _decision(_snapshot(living_room_lux=_evidence(
        "latitude_lux",
        state="100",
        freshness=FreshnessStatus.STALE,
        age_seconds=31,
    )))
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert "living_room_lux_stale" in result.optional_context_reason_codes


def test_sonos_unavailable_is_ignored() -> None:
    result = _decision(_snapshot(
        music_sonos_health=_health(
            "sonos", CapabilityStatus.UNAVAILABLE
        )
    ))
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert "music_unavailable" in result.optional_context_reason_codes


def test_face_emotion_is_not_authoritative_mood_context() -> None:
    result = _decision(_snapshot(mood_context=replace(
        _evidence("emotion_detector", state="healthy"),
        authoritative=False,
    )))
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert (
        "authoritative_mood_context_unavailable"
        in result.optional_context_reason_codes
    )


@pytest.mark.parametrize(
    "status",
    [
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNKNOWN,
    ],
)
def test_hue_unhealthy_never_eligible(status: CapabilityStatus) -> None:
    result = _decision(_snapshot(hue_health=_health("hue", status)))
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert "hue_unavailable" in result.reason_codes


@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("apartment_away", "apartment_away"),
        ("dnd_active", "dnd_active"),
        ("sleeping_active", "sleeping_active"),
    ],
)
def test_policy_vetoes_safe_fallback(
    field_name: str, reason: str,
) -> None:
    result = _decision(_snapshot(**{field_name: True}))
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert reason in result.reason_codes


def test_manual_mode_and_source_are_preserved() -> None:
    manual = Evidence(
        source="api:dashboard",
        status=CapabilityStatus.HEALTHY,
        freshness=FreshnessStatus.NOT_APPLICABLE,
        present=True,
        state="relax",
        authoritative=True,
    )
    snapshot = _snapshot(manual_mode_override=manual)
    result = _decision(snapshot)
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "manual_mode_override_active" in result.reason_codes
    assert snapshot.manual_mode_override.source == "api:dashboard"
    assert snapshot.manual_mode_override.state == "relax"


def test_physical_context_relax_is_not_user_manual_intent() -> None:
    snapshot = _builder(policy_context=lambda: {
        "manual_mode_active": True,
        "manual_mode": "relax",
        "manual_mode_source": "physical_context_relax",
    })()
    result = _decision(snapshot)
    assert snapshot.manual_mode_override.present is False
    assert snapshot.manual_mode_override.source == "physical_context_relax"
    assert result.eligible_for_scene_curator is True
    assert "manual_mode_override_active" not in result.reason_codes


def test_actual_user_selected_relax_remains_manual_veto() -> None:
    snapshot = _builder(policy_context=lambda: {
        "manual_mode_active": True,
        "manual_mode": "relax",
        "manual_mode_source": "api:dashboard",
    })()
    result = _decision(snapshot)
    assert snapshot.manual_mode_override.present is True
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "manual_mode_override_active" in result.reason_codes


@pytest.mark.parametrize(
    "camera_status",
    [
        {"enabled": False, "paused": False},
        {"enabled": True, "paused": True},
        {
            "enabled": True,
            "paused": False,
            "heartbeat": {"age_seconds": 120, "stale": True},
        },
    ],
)
def test_privacy_or_camera_health_loss_blocks_curator(
    camera_status: dict,
) -> None:
    snapshot = _builder(camera_status=lambda: camera_status)()
    result = _decision(snapshot)
    assert result.eligible_for_scene_curator is False
    assert any(code.startswith("latitude_") for code in result.reason_codes)


def test_manual_per_light_ids_are_exact_and_veto_v1() -> None:
    owner = LightOwnership(
        active=True,
        source="manual_per_light",
        light_ids=("2", "4"),
    )
    result = _decision(_snapshot(manual_light_override=owner))
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "manual_light_override_active" in result.reason_codes
    assert owner.light_ids == ("2", "4")


def test_desktop_screen_sync_bedroom_pair_is_nonblocking() -> None:
    owner = LightOwnership(
        active=True,
        source="desktop",
        light_ids=("2", "5"),
        freshness=FreshnessStatus.FRESH,
    )
    result = _decision(_snapshot(screen_sync_ownership=owner))
    assert result.outcome == DecisionOutcome.ELIGIBLE
    assert "screen_sync_living_room_owner" not in result.reason_codes


def test_laptop_screen_sync_living_room_is_safe_fallback() -> None:
    owner = LightOwnership(
        active=True,
        source="laptop",
        light_ids=("1", "3", "4"),
        freshness=FreshnessStatus.FRESH,
    )
    result = _decision(_snapshot(screen_sync_ownership=owner))
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "screen_sync_living_room_owner" in result.reason_codes


@pytest.mark.parametrize(
    (
        "sources",
        "expected_ids",
        "expected_sources",
        "expected_outcome",
    ),
    [
        (
            {"laptop": 1.0},
            ("1", "3", "4"),
            (("laptop", True, "fresh"),),
            DecisionOutcome.SAFE_FALLBACK,
        ),
        (
            {"desktop": 1.0},
            ("2", "5"),
            (("desktop", True, "fresh"),),
            DecisionOutcome.ELIGIBLE,
        ),
        (
            {"laptop": 2.0, "desktop": 1.0},
            ("1", "2", "3", "4", "5"),
            (("desktop", True, "fresh"), ("laptop", True, "fresh")),
            DecisionOutcome.SAFE_FALLBACK,
        ),
        (
            {"desktop": 2.0, "laptop": 1.0},
            ("1", "2", "3", "4", "5"),
            (("desktop", True, "fresh"), ("laptop", True, "fresh")),
            DecisionOutcome.SAFE_FALLBACK,
        ),
        (
            {"desktop": 1.0, "laptop": 8.1},
            ("2", "5"),
            (("desktop", True, "fresh"), ("laptop", False, "stale")),
            DecisionOutcome.ELIGIBLE,
        ),
        (
            {"desktop": 8.1, "laptop": 1.0},
            ("1", "3", "4"),
            (("desktop", False, "stale"), ("laptop", True, "fresh")),
            DecisionOutcome.SAFE_FALLBACK,
        ),
        (
            {"desktop": 8.1, "laptop": 8.2},
            (),
            (("desktop", False, "stale"), ("laptop", False, "stale")),
            DecisionOutcome.ELIGIBLE,
        ),
    ],
)
def test_screen_sync_source_overlap_union_and_serialization(
    sources: dict[str, float],
    expected_ids: tuple[str, ...],
    expected_sources: tuple[tuple[str, bool, str], ...],
    expected_outcome: DecisionOutcome,
) -> None:
    builder = _builder(ownership_context=lambda: {
        "manual": {"light_ids": [], "set_at_by_light": {}},
        "screen_sync": {
            "source": min(sources, key=sources.get),
            "available_light_ids": ["1", "2", "3", "4", "5"],
            "sources": {
                source: {
                    "last_color_at": (
                        NOW - timedelta(seconds=age_seconds)
                    ).isoformat(),
                    "age_seconds": age_seconds,
                }
                for source, age_seconds in sources.items()
            },
        },
        "transit": {},
        "desk_exit": {},
    })
    snapshot = builder()
    result = _decision(snapshot)

    assert snapshot.screen_sync_ownership.light_ids == expected_ids
    assert tuple(
        (owner.source, owner.active, owner.freshness.value)
        for owner in snapshot.screen_sync_source_ownership
    ) == expected_sources
    assert result.outcome == expected_outcome
    assert (
        "screen_sync_living_room_owner" in result.reason_codes
    ) is (expected_outcome == DecisionOutcome.SAFE_FALLBACK)


@pytest.mark.parametrize("owner_field", ["transit_ownership", "desk_exit_ownership"])
def test_transit_and_desk_exit_living_room_ownership_veto(
    owner_field: str,
) -> None:
    owner = LightOwnership(
        active=True,
        source=owner_field,
        light_ids=("1", "3"),
    )
    result = _decision(_snapshot(**{owner_field: owner}))
    assert result.outcome == DecisionOutcome.SAFE_FALLBACK
    assert (
        "transit_or_desk_exit_living_room_owner"
        in result.reason_codes
    )
    assert owner.active is True


def test_simultaneous_couch_and_desktop_physical_presence_conflicts() -> None:
    result = _decision(_snapshot(
        desktop_physical_presence=_evidence(
            "desktop", present=True, zone="desk", authoritative=True
        )
    ))
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP
    assert "physical_room_conflict" in result.reason_codes


def test_latitude_streaming_never_becomes_physical_authority() -> None:
    builder = _builder(
        latitude_configured=lambda: True,
        camera_status=lambda: {"enabled": True, "paused": False},
        presence_sources=lambda: {
            "latitude_streaming": {
                "last_at": NOW.isoformat(),
                "age_s": 1.0,
                "face_present": True,
                "zone": "couch",
            }
        },
    )
    snapshot = builder()
    result = _decision(snapshot)
    assert snapshot.living_room_presence.source == "latitude"
    assert snapshot.living_room_presence.present is None
    assert "latitude_unavailable" in result.reason_codes


def test_restart_without_latitude_or_hue_post_start_evidence_never_eligible() -> None:
    builder = _builder(
        presence_sources=lambda: {},
        hue_status=lambda: {
            "configured": True,
            "connected": True,
            "breaker_state": "closed",
            "consecutive_failures": 0,
            "last_success_at": None,
            "heartbeat": {"age_seconds": 0.1, "stale": False},
        },
    )
    snapshot = builder()
    result = _decision(snapshot)
    assert snapshot.latitude_service_health.status == CapabilityStatus.UNKNOWN
    assert snapshot.hue_health.status == CapabilityStatus.UNKNOWN
    assert result.outcome == DecisionOutcome.DEGRADED_SKIP


@pytest.mark.parametrize(
    "hue_patch",
    [
        {"connected": False},
        {"breaker_state": "open"},
        {"breaker_state": "half_open"},
        {"consecutive_failures": 2},
        {"heartbeat": {"age_seconds": 20, "stale": True}},
        {"last_success_at": None},
    ],
)
def test_hue_health_requires_all_read_side_signals(hue_patch: dict) -> None:
    base = {
        "configured": True,
        "connected": True,
        "breaker_state": "closed",
        "consecutive_failures": 0,
        "last_success_at": NOW.isoformat(),
        "heartbeat": {"age_seconds": 1, "stale": False},
    }
    base.update(hue_patch)
    snapshot = _builder(hue_status=lambda: base)()
    assert snapshot.hue_health.status != CapabilityStatus.HEALTHY
    assert "hue_unavailable" in _decision(snapshot).reason_codes


def test_sonos_cached_snapshot_is_coarse_and_read_only() -> None:
    service = SonosService("127.0.0.1")
    service._connected = True
    service._device = object()
    service._last_successful_status = {
        "state": "PLAYING",
        "track": "must not leak",
        "artist": "must not leak",
    }
    service._last_successful_status_at = datetime.now(timezone.utc)
    snapshot = service.get_cached_status_snapshot()
    assert snapshot["state"] == "playing"
    assert snapshot["fresh"] is True
    assert "track" not in snapshot
    assert "artist" not in snapshot


def _builder(**overrides) -> LivingRoomSnapshotBuilder:
    defaults = {
        "latitude_configured": lambda: True,
        "camera_status": lambda: {
            "enabled": True,
            "paused": False,
            "heartbeat": {"age_seconds": 1, "stale": False},
        },
        "presence_sources": lambda: {
            "latitude": {
                "last_at": NOW.isoformat(),
                "age_s": 1.0,
                "face_present": True,
                "face_confidence": 0.9,
                "zone": "couch",
            }
        },
        "living_room_lux": lambda: {
            "value": 100.0,
            "observed_at": NOW.isoformat(),
            "age_seconds": 1.0,
        },
        "hue_status": lambda: {
            "configured": True,
            "connected": True,
            "breaker_state": "closed",
            "consecutive_failures": 0,
            "last_success_at": NOW.isoformat(),
            "heartbeat": {"age_seconds": 1, "stale": False},
        },
        "weather_status": lambda: {
            "condition": "Clear",
            "observed_at": NOW.isoformat(),
            "age_seconds": 1.0,
            "stale_fallback": False,
        },
        "sonos_status": lambda: {
            "configured": True,
            "connected": True,
            "breaker_state": "closed",
            "consecutive_failures": 0,
            "last_successful_status_at": NOW.isoformat(),
            "age_seconds": 1.0,
            "fresh": True,
            "state": "stopped",
        },
        "activity_context": lambda: {
            "current_activity": "idle",
            "current_activity_source": "time",
            "current_activity_reported_at": NOW.isoformat(),
            "current_activity_age_seconds": 1.0,
            "current_activity_fresh": True,
            "effective_mode": "idle",
            "effective_source": "time",
        },
        "policy_context": lambda: {},
        "ownership_context": lambda: {
            "manual": {"light_ids": [], "set_at_by_light": {}},
            "screen_sync": {},
            "transit": {},
            "desk_exit": {},
        },
        "pipeline_status": lambda: {"enabled": True},
        "mood_status": lambda: {"enabled": False},
    }
    defaults.update(overrides)
    return LivingRoomSnapshotBuilder(**defaults)


def test_snapshot_projects_engine_arbitration_without_recreating_policy() -> None:
    activity = {
        "current_activity": "working",
        "current_activity_source": "process",
        "current_activity_source_key": "process:desktop",
        "current_activity_reported_at": NOW.isoformat(),
        "current_activity_age_seconds": 0.5,
        "current_activity_fresh": True,
        "effective_mode": "relax",
        "effective_source": "physical_context_relax",
        "physical_context_process_arbitration": {
            "state": "discounted",
            "reason": "stale_desktop_process_discounted",
            "source": "process",
            "device": "desktop",
            "committed_mode": "working",
            "candidate_mode": "idle",
            "candidate_reason": "fallback_idle",
            "idle_seconds": 45.0,
            "pending_mode": "idle",
            "pending_dwell_age": 12.0,
            "gaming_qualification": None,
            "received_at": NOW.isoformat(),
            "age_seconds": 0.5,
        },
    }

    snapshot = _builder(activity_context=lambda: activity)()
    decision = _decision(snapshot)

    assert snapshot.process_arbitration.state == "discounted"
    assert snapshot.process_arbitration.candidate_mode == "idle"
    assert snapshot.process_arbitration.candidate_reason == "fallback_idle"
    assert snapshot.process_arbitration.idle_seconds == 45.0
    assert snapshot.process_arbitration.pending_dwell_age == 12.0
    assert decision.process_arbitration_state == "discounted"
    assert decision.eligible_for_scene_curator is True


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def _row_count(session_factory) -> int:
    async with session_factory() as session:
        return (await session.scalar(
            select(func.count()).select_from(LivingRoomDecisionRecord)
        )) or 0


async def test_persistence_semantic_change_checkpoint_and_history_bound(
    session_factory,
) -> None:
    recorder = LivingRoomDecisionRecorder(session_factory)
    snapshot = _snapshot()
    envelope = DecisionEnvelope(snapshot, _decision(snapshot))

    assert await recorder.persist_if_needed(envelope, now=NOW) is True
    same_snapshot = replace(
        snapshot,
        evaluated_at=(NOW + timedelta(minutes=1)).isoformat(),
        living_room_presence=replace(
            snapshot.living_room_presence,
            age_seconds=7.0,
            observed_at=(NOW + timedelta(seconds=1)).isoformat(),
        ),
    )
    same_envelope = DecisionEnvelope(
        same_snapshot,
        replace(
            envelope.decision,
            evaluated_at=same_snapshot.evaluated_at,
        ),
    )
    assert await recorder.persist_if_needed(
        same_envelope, now=NOW + timedelta(minutes=14)
    ) is False
    assert await _row_count(session_factory) == 1
    assert await recorder.persist_if_needed(
        same_envelope, now=NOW + timedelta(minutes=15)
    ) is True

    away_snapshot = replace(same_snapshot, apartment_away=True)
    away_envelope = DecisionEnvelope(away_snapshot, _decision(away_snapshot))
    assert await recorder.persist_if_needed(
        away_envelope, now=NOW + timedelta(minutes=16)
    ) is True
    assert await _row_count(session_factory) == 3
    history = await recorder.history(100)
    assert len(history) == 3
    assert history[0]["outcome"] == "safe_fallback"
    with pytest.raises(ValueError):
        await recorder.history(101)


def test_semantic_fingerprint_ignores_only_raw_continuous_evidence() -> None:
    snapshot = _snapshot()
    envelope = DecisionEnvelope(snapshot, _decision(snapshot))
    jittered = replace(
        snapshot,
        living_room_lux=replace(snapshot.living_room_lux, value=121.7),
        living_room_presence=replace(
            snapshot.living_room_presence,
            confidence=0.91,
        ),
        couch_zone_evidence=replace(
            snapshot.couch_zone_evidence,
            confidence=0.91,
        ),
        desktop_physical_presence=replace(
            snapshot.desktop_physical_presence,
            confidence=0.22,
        ),
    )
    jittered_envelope = DecisionEnvelope(jittered, _decision(jittered))

    assert semantic_fingerprint(jittered_envelope) == semantic_fingerprint(
        envelope
    )

    heartbeat = replace(
        snapshot,
        process_arbitration=ProcessArbitration(
            state="discounted",
            reason="stale_desktop_process_discounted",
            source="process",
            device="desktop",
            committed_mode="working",
            candidate_mode="idle",
            candidate_reason="fallback_idle",
            idle_seconds=45.0,
            received_at=NOW.isoformat(),
            age_seconds=0.0,
        ),
    )
    repeated_heartbeat = replace(
        heartbeat,
        process_arbitration=replace(
            heartbeat.process_arbitration,
            received_at=(NOW + timedelta(seconds=15)).isoformat(),
            age_seconds=0.2,
            idle_seconds=60.0,
            pending_dwell_age=15.0,
        ),
    )
    assert semantic_fingerprint(
        DecisionEnvelope(heartbeat, _decision(heartbeat))
    ) == semantic_fingerprint(
        DecisionEnvelope(repeated_heartbeat, _decision(repeated_heartbeat))
    )

    stale_lux = replace(
        jittered,
        living_room_lux=replace(
            jittered.living_room_lux,
            freshness=FreshnessStatus.STALE,
        ),
    )
    stale_envelope = DecisionEnvelope(stale_lux, _decision(stale_lux))
    assert semantic_fingerprint(stale_envelope) != semantic_fingerprint(
        jittered_envelope
    )


async def test_lux_jitter_dedups_but_transition_and_checkpoint_persist_exact(
    session_factory,
) -> None:
    recorder = LivingRoomDecisionRecorder(session_factory)
    initial = _snapshot()

    async def persist(snapshot, *, seconds: int) -> bool:
        return await recorder.persist_if_needed(
            DecisionEnvelope(snapshot, _decision(snapshot)),
            now=NOW + timedelta(seconds=seconds),
        )

    assert await persist(initial, seconds=0) is True
    for seconds, lux in ((15, 120.4), (30, 119.7), (45, 121.1)):
        jittered = replace(
            initial,
            evaluated_at=(NOW + timedelta(seconds=seconds)).isoformat(),
            living_room_lux=replace(initial.living_room_lux, value=lux),
        )
        assert await persist(jittered, seconds=seconds) is False

    transition_time = 60
    transitioned = replace(
        initial,
        evaluated_at=(NOW + timedelta(seconds=transition_time)).isoformat(),
        living_room_lux=replace(
            initial.living_room_lux,
            value=118.2,
            freshness=FreshnessStatus.STALE,
        ),
    )
    assert await persist(transitioned, seconds=transition_time) is True

    before_checkpoint = replace(
        transitioned,
        evaluated_at=(NOW + timedelta(minutes=15, seconds=59)).isoformat(),
        living_room_lux=replace(transitioned.living_room_lux, value=117.6),
    )
    assert await persist(before_checkpoint, seconds=15 * 60 + 59) is False

    checkpoint = replace(
        before_checkpoint,
        evaluated_at=(NOW + timedelta(minutes=16)).isoformat(),
        living_room_lux=replace(before_checkpoint.living_room_lux, value=117.4),
    )
    assert await persist(checkpoint, seconds=16 * 60) is True

    history = await recorder.history(100)
    assert len(history) == 3
    assert history[2]["snapshot"]["living_room_lux"]["value"] == 120.0
    assert history[1]["snapshot"]["living_room_lux"]["value"] == 118.2
    assert history[1]["decision"]["optional_context_reason_codes"] == [
        "living_room_lux_stale",
        "not_collected_in_v1",
    ]
    assert history[0]["snapshot"]["living_room_lux"]["value"] == 117.4


async def test_ninety_day_pruning_is_deterministic(session_factory) -> None:
    recorder = LivingRoomDecisionRecorder(session_factory)
    old = NOW - timedelta(days=91)
    current = NOW
    first = _snapshot(evaluated_at=old.isoformat())
    await recorder.persist_if_needed(
        DecisionEnvelope(first, _decision(first)), now=old
    )
    changed = _snapshot(apartment_away=True)
    await recorder.persist_if_needed(
        DecisionEnvelope(changed, _decision(changed)), now=current
    )
    assert await recorder.prune(now=current) == 1
    history = await recorder.history(100)
    assert len(history) == 1
    assert history[0]["outcome"] == "safe_fallback"


class _FailingSession:
    async def __aenter__(self):
        raise RuntimeError("database unavailable")

    async def __aexit__(self, *_args):
        return False


class _SwitchableSessionFactory:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self.fail_calls = 0

    def __call__(self):
        if self.fail_calls:
            self.fail_calls -= 1
            return _FailingSession()
        return self._session_factory()


class _WriterTripwire:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name):
        if name.startswith(("set_", "play", "pause", "speak", "notify")):
            async def _fail(*_args, **_kwargs):
                self.calls += 1
                raise AssertionError(f"writer called: {name}")
            return _fail
        raise AttributeError(name)

    def snapshot(self):
        return _snapshot()


async def test_gate_dependency_shape_cannot_reach_apartment_writers() -> None:
    class _NoopRecorder:
        healthy = True

        async def initialize(self):
            return None

        async def persist_if_needed(self, *_args, **_kwargs):
            return False

        def health(self):
            return {"status": "healthy"}

    source = _WriterTripwire()
    gate = LivingRoomDecisionGate(
        source.snapshot,
        _NoopRecorder(),  # type: ignore[arg-type]
    )
    envelope = await gate.start()
    assert envelope.decision.outcome == DecisionOutcome.ELIGIBLE
    assert source.calls == 0


async def test_persistence_failure_is_safe_and_never_actuates() -> None:
    tripwire = _WriterTripwire()
    recorder = LivingRoomDecisionRecorder(lambda: _FailingSession())
    gate = LivingRoomDecisionGate(_snapshot, recorder)
    envelope = await gate.start()
    assert envelope.decision.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "decision_recording_unavailable" in envelope.decision.reason_codes
    assert gate.health_summary()["status"] == "degraded"
    assert tripwire.calls == 0
    assert envelope.decision.scene_selected is False
    assert envelope.decision.actuation_attempted is False


async def test_recorder_recovery_reconciles_current_health_and_history_once(
    session_factory,
) -> None:
    switchable = _SwitchableSessionFactory(session_factory)

    class _SnapshotProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.snapshot = _snapshot()

        def __call__(self) -> CapabilitySnapshotV1:
            self.calls += 1
            if self.calls == 1:
                switchable.fail_calls = 1
            return self.snapshot

    provider = _SnapshotProvider()
    gate = LivingRoomDecisionGate(
        provider,
        LivingRoomDecisionRecorder(switchable),
    )

    failed = await gate.start()
    assert failed.decision.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "decision_recording_unavailable" in failed.decision.reason_codes
    assert gate.health_summary()["status"] == "degraded"
    assert await gate.history(100) == []

    recovered = await gate.evaluate(trigger="test_recovery")
    assert recovered.decision.outcome == DecisionOutcome.ELIGIBLE
    assert "decision_recording_unavailable" not in recovered.decision.reason_codes
    assert gate.current_envelope() == envelope_to_dict(recovered)
    assert gate.current_envelope()["shadow_only"] is True
    assert gate.current_status()["persistence_health"]["status"] == "healthy"
    assert gate.health_summary()["status"] == "healthy"
    assert gate.health_summary()["outcome"] == "eligible"

    history = await gate.history(100)
    assert len(history) == 1
    assert history[0]["shadow_only"] is True
    assert history[0]["snapshot"] == gate.current_envelope()["snapshot"]
    assert history[0]["decision"] == gate.current_envelope()["decision"]
    assert history[0]["outcome"] == "eligible"
    assert history[0]["reason_codes"] == []

    provider.snapshot = _snapshot(apartment_away=True)
    switchable.fail_calls = 1
    degraded_again = await gate.evaluate(trigger="test_later_failure")
    assert degraded_again.decision.outcome == DecisionOutcome.SAFE_FALLBACK
    assert "apartment_away" in degraded_again.decision.reason_codes
    assert (
        "decision_recording_unavailable"
        in degraded_again.decision.reason_codes
    )
    assert gate.health_summary()["status"] == "degraded"
    assert len(await gate.history(100)) == 1


async def test_evaluator_failure_is_visible_and_no_actuation() -> None:
    class _NoopRecorder:
        healthy = True

        async def initialize(self):
            return None

        async def persist_if_needed(self, *_args, **_kwargs):
            return False

        def health(self):
            return {"status": "healthy"}

    def broken(_snapshot_value):
        raise RuntimeError("boom")

    gate = LivingRoomDecisionGate(
        _snapshot,
        _NoopRecorder(),  # type: ignore[arg-type]
        evaluator=broken,
    )
    envelope = await gate.start()
    assert envelope.decision.outcome == DecisionOutcome.SAFE_FALLBACK
    assert envelope.decision.reason_codes == (
        "decision_evaluator_unavailable",
    )
    assert gate.health_summary()["status"] == "degraded"
    assert envelope_to_dict(envelope)["decision"]["actuation_attempted"] is False
