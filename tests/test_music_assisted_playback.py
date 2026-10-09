from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import MusicAssistedPlaybackEvent, SonosPlaybackEvent
from backend.services.audio_ownership import AudioOwnershipService
from backend.services.music_assisted_playback import MusicAssistedPlaybackService
from backend.services.music_mapper import MusicMapper
from backend.services.music_taste import CandidateTasteMatch
from backend.services.music_trust import MusicApprovalService, MusicTrustPolicy
from backend.services.playlist_catalog import VerifiedMusicCandidate


class FakeCatalog:
    def __init__(self, candidate):
        self.candidate = candidate
        self.lookups = []

    async def get_by_identity(self, provider, provider_id):
        self.lookups.append((provider, provider_id))
        if self.candidate is None:
            return None
        if (provider, provider_id) != (
            self.candidate.provider,
            self.candidate.provider_id,
        ):
            return None
        return self.candidate


class FakeTasteSnapshot:
    def __init__(self, classification="exploratory"):
        self.classification = classification
        self.generated_at = datetime.now(timezone.utc)

    def classify_candidate(self, candidate, *, mode=None):
        return CandidateTasteMatch(
            classification=self.classification,
            familiarity=1.0 if self.classification in {"familiar", "proven"} else 0.2,
            preference=0.8 if self.classification == "proven" else 0.2,
            artist_depth=3 if self.classification == "proven" else 0,
            positive_weight=3.0 if self.classification == "proven" else 0.0,
            negative_weight=0.0,
            sources=("test",),
        )


class FakeTasteProvider:
    def __init__(self, classification="exploratory"):
        self.classification = classification

    async def snapshot(self):
        return FakeTasteSnapshot(self.classification)


class FakeAutomation:
    def __init__(self):
        self.current_mode = "gaming"
        self.dnd = False
        self.period = "evening"

    def is_dnd_active(self):
        return self.dnd

    def _get_time_period(self):
        return self.period


class FakeSonos:
    def __init__(self):
        self.connected = True
        self.breaker_open = False
        self.state = "STOPPED"
        self.track = ""
        self.uri = ""
        self.loaded_track_after_enqueue = "Bang!"
        self.loaded_uri_after_enqueue = (
            "x-sonosapi-hls-static:song%3a1713833576?sid=204&flags=8232&sn=2"
        )
        self.loaded_state_after_enqueue = "STOPPED"
        self.volume = 22
        self.mute = False
        self.play_mode = "NORMAL"
        self.queue_size = 100
        self.play_result = True
        self.fail_after_enqueue = False
        self.play_calls = []
        self.volume_calls = []

    async def get_status(self):
        return {
            "state": self.state,
            "track": self.track,
            "volume": self.volume,
            "mute": self.mute,
        }

    async def get_current_media_uri(self):
        return self.uri

    async def get_queue_context(self):
        return {
            "available": True,
            "play_mode": self.play_mode,
            "queue_size": self.queue_size,
        }

    async def set_volume(self, value):
        self.volume_calls.append(value)
        self.volume = value
        return True

    async def play_apple_music_share_link(
        self, provider_id, share_url, *, expected_queue_size=None, before_play=None,
        mutation_runner=None, verification_guard=None, verification_boundary_guard=None,
    ):
        async def setup():
            self.play_calls.append((provider_id, share_url))
            if not self.play_result:
                return None
            self.queue_size += 1
            self.state = self.loaded_state_after_enqueue
            self.track = self.loaded_track_after_enqueue
            self.uri = self.loaded_uri_after_enqueue
            if before_play is not None:
                guard = await before_play()
                if isinstance(guard, dict):
                    if guard.get("reason") is not None:
                        return None
                elif not guard:
                    return None
            if self.fail_after_enqueue:
                return None
            self.state = "PLAYING"
            self.track = "Bang!"
            return True
        result = await mutation_runner(setup) if mutation_runner else await setup()
        if not result:
            return False
        if verification_boundary_guard is not None:
            return verification_boundary_guard()
        return await verification_guard() if verification_guard else True


class FakeAmbient:
    def __init__(self):
        self.playing = False
        self.active = False
        self.pending = False

    def get_state(self):
        return {
            "playing": self.playing,
            "sonos_ambient_active": self.active,
            "sonos_ambient_pending": self.pending,
        }


class FakeEventLogger:
    def __init__(self):
        self.calls = []

    async def log_sonos_event(self, **kwargs):
        self.calls.append(kwargs)


class FakeWs:
    async def broadcast(self, *_args, **_kwargs):
        return None


def apple_candidate(*, adapter="sonos_apple_music_share_link"):
    return VerifiedMusicCandidate(
        provider="itunes_search",
        provider_id="1713833576",
        media_type="track",
        title="Bang!",
        uri="https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4",
        source="itunes_search+sonos_share_link",
        verified=True,
        catalog_verified=True,
        playback_capability="supported",
        playback_adapter=adapter,
        playback_reference="https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4",
        metadata={"artist_name": "AJR", "track_name": "Bang!"},
    )


async def build_service(
    db_engine,
    *,
    approved=True,
    classification="exploratory",
    candidate=None,
    lifecycle=None,
):
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    sonos = FakeSonos()
    automation = FakeAutomation()
    ambient = FakeAmbient()
    event_logger = FakeEventLogger()
    mapper = MusicMapper(sonos, FakeWs())
    cand = candidate if candidate is not None else apple_candidate()
    approval = MusicApprovalService(session_factory=factory)
    if approved:
        await approval.record(
            client_event_id="approval-1",
            action="approve",
            candidate=cand,
            source="test",
        )
    app_state = SimpleNamespace(
        automation=automation,
        away_manager=SimpleNamespace(away=False),
        sonos=sonos,
        tts=SimpleNamespace(is_speaking=False),
        ambient_sound=ambient,
        music_mapper=mapper,
    )

    async def load_setting(_key):
        return {}

    async def save_authority(_key, _value):
        pass

    app_state.audio_ownership = AudioOwnershipService(
        setting_loader=load_setting, setting_saver=save_authority,
    )
    service = MusicAssistedPlaybackService(
        app_state=app_state,
        catalog=FakeCatalog(cand),
        taste_provider=FakeTasteProvider(classification),
        approval_service=approval,
        trust_policy=MusicTrustPolicy(),
        setting_loader=load_setting,
        session_factory=factory,
        lifecycle_state=lambda: lifecycle or {"travel": False, "returning_home": False},
    )
    return service, app_state, event_logger, approval, factory


@pytest.mark.asyncio
async def test_status_reports_exact_mode_target_read_only_volume_contract(db_engine):
    service, *_ = await build_service(db_engine)

    status = service.status()

    assert status["volume_policy"] == "require_exact_current_mode_target_never_write"


@pytest.mark.asyncio
async def test_explicit_approved_track_plays_once_and_logs_canonical_manual_evidence(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    result = await service.play_exact(
        client_event_id="play-1", provider="itunes_search",
        provider_id="1713833576", source="dashboard:music_assisted",
    )
    assert result["status"] == "played"
    assert result["trust_state"] == "approved"
    assert app.sonos.play_calls == [("1713833576", apple_candidate().playback_reference)]
    assert logger.calls == []
    async with factory() as session:
        rows = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert len(rows) == 1
    assert rows[0].event_type == "play"
    assert rows[0].favorite_title == "Bang!"
    assert rows[0].mode_at_time == "gaming"
    assert rows[0].volume == 22
    assert rows[0].triggered_by == "manual"


@pytest.mark.asyncio
async def test_duplicate_client_event_is_restart_safe_and_does_not_replay_or_relog(db_engine):
    service, app, logger, approval, factory = await build_service(db_engine)
    kwargs = dict(
        client_event_id="play-duplicate",
        provider="itunes_search",
        provider_id="1713833576",
        source="dashboard:music_assisted",
    )
    first = await service.play_exact(**kwargs)

    # Reconstruct the service to model a process restart.
    restarted = MusicAssistedPlaybackService(
        app_state=app,
        catalog=FakeCatalog(apple_candidate()),
        taste_provider=FakeTasteProvider(),
        approval_service=approval,
        trust_policy=MusicTrustPolicy(),
        setting_loader=lambda _key: _async_value({}),
        session_factory=factory,
        lifecycle_state=lambda: {"travel": False, "returning_home": False},
    )
    second = await restarted.play_exact(**kwargs)

    assert first["status"] == "played"
    assert second["status"] == "played"
    assert second["duplicate"] is True
    assert len(app.sonos.play_calls) == 1
    assert logger.calls == []
    async with factory() as session:
        rows = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert len(rows) == 1


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_suggestion_only_candidate_cannot_reach_playback(db_engine):
    service, app, logger, _approval, _factory = await build_service(
        db_engine, approved=False, classification="exploratory",
    )
    result = await service.play_exact(
        client_event_id="play-untrusted",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == "trust_not_playback_eligible"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_proven_candidate_can_play_without_explicit_approval(db_engine):
    service, app, logger, _approval, _factory = await build_service(
        db_engine, approved=False, classification="proven",
    )
    result = await service.play_exact(
        client_event_id="play-proven",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["status"] == "played"
    assert result["trust_state"] == "proven"
    assert len(app.sonos.play_calls) == 1
    assert logger.calls == []


@pytest.mark.asyncio
async def test_revoke_immediately_removes_assisted_eligibility(db_engine):
    service, app, logger, approval, _factory = await build_service(db_engine)
    await approval.record(
        client_event_id="revoke-1",
        action="revoke",
        candidate=apple_candidate(),
        source="test",
    )
    result = await service.play_exact(
        client_event_id="play-revoked",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == "trust_revoked"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_unsupported_adapter_cannot_reach_music_mapper(db_engine):
    candidate = apple_candidate(adapter="sonos_favorite_title")
    service, app, logger, _approval, _factory = await build_service(
        db_engine, candidate=candidate,
    )
    result = await service.play_exact(
        client_event_id="play-wrong-adapter",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["reason"] == "unsupported_playback_adapter"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("dnd", "dnd_active"),
        ("sleeping", "sleeping_active"),
        ("away", "apartment_away"),
        ("tts", "tts_active"),
        ("ambient", "ambient_playback_owned"),
        ("busy", "sonos_busy"),
        ("shuffle", "sonos_play_mode_owned"),
        ("muted", "sonos_muted"),
    ],
)
async def test_live_authorities_suppress_before_actuation(db_engine, mutation, reason):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    if mutation == "dnd":
        app.automation.dnd = True
    elif mutation == "sleeping":
        app.automation.current_mode = "sleeping"
    elif mutation == "away":
        app.away_manager.away = True
    elif mutation == "tts":
        app.tts.is_speaking = True
    elif mutation == "ambient":
        app.ambient_sound.active = True
    elif mutation == "busy":
        app.sonos.state = "PLAYING"
        app.sonos.track = "User music"
    elif mutation == "shuffle":
        app.sonos.play_mode = "SHUFFLE"
    elif mutation == "muted":
        app.sonos.mute = True

    result = await service.play_exact(
        client_event_id=f"play-{mutation}",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == reason
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "reason"),
    [
        ({"travel": True, "returning_home": False}, "travel_mode_active"),
        ({"travel": False, "returning_home": True}, "returning_home_active"),
    ],
)
async def test_host_lifecycle_holds_suppress(db_engine, lifecycle, reason):
    service, app, logger, _approval, _factory = await build_service(
        db_engine, lifecycle=lifecycle,
    )
    result = await service.play_exact(
        client_event_id=f"play-{reason}",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["reason"] == reason
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_volume_above_policy_suppresses_without_writing_volume(db_engine):
    service, app, _logger, _approval, _factory = await build_service(db_engine)
    app.sonos.volume = 40
    result = await service.play_exact(
        client_event_id="play-volume-high", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == "sonos_volume_above_policy"
    assert result["volume_before"] == 40
    assert app.sonos.volume_calls == []
    assert app.sonos.play_calls == []

    service2, app2, _logger2, _approval2, _factory2 = await build_service(db_engine)
    app2.sonos.volume = 8
    result2 = await service2.play_exact(
        client_event_id="play-volume-low", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result2["status"] == "suppressed"
    assert result2["reason"] == "sonos_volume_below_playback_floor"
    assert result2["volume_before"] == 8
    assert app2.sonos.volume_calls == []
    assert app2.sonos.play_calls == []


@pytest.mark.asyncio
async def test_gaming_night_stale_volume_15_suppresses_without_volume_write(db_engine):
    service, app, _logger, _approval, _factory = await build_service(db_engine)
    app.automation.period = "night"
    app.sonos.volume = 15

    result = await service.play_exact(
        client_event_id="play-gaming-night-low", provider="itunes_search",
        provider_id="1713833576", source="test",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "sonos_volume_below_playback_floor"
    assert result["volume_before"] == 15
    assert app.sonos.volume_calls == []
    assert app.sonos.play_calls == []


@pytest.mark.asyncio
async def test_gaming_night_target_18_can_play_without_volume_write(db_engine):
    service, app, _logger, _approval, _factory = await build_service(db_engine)
    app.automation.period = "night"
    app.sonos.volume = 18

    result = await service.play_exact(
        client_event_id="play-gaming-night-target", provider="itunes_search",
        provider_id="1713833576", source="test",
    )

    assert result["status"] == "played"
    assert result["volume_used"] == 18
    assert app.sonos.volume_calls == []
    assert len(app.sonos.play_calls) == 1


@pytest.mark.asyncio
async def test_unverified_start_is_failed_without_learning_evidence(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    app.sonos.fail_after_enqueue = True

    result = await service.play_exact(
        client_event_id="play-start-unverified", provider="itunes_search",
        provider_id="1713833576", source="test",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "playback_start_unverified"
    assert app.sonos.queue_size == 101
    assert logger.calls == []
    async with factory() as session:
        rows = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert rows == []


@pytest.mark.asyncio
async def test_failed_playback_never_writes_volume_or_learning_evidence(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    app.sonos.volume = 22
    app.sonos.play_result = False
    result = await service.play_exact(
        client_event_id="play-fails", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "playback_failed"
    assert app.sonos.volume_calls == []
    assert app.sonos.volume == 22
    assert logger.calls == []
    async with factory() as session:
        rows = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert rows == []


@pytest.mark.asyncio
async def test_mode_without_music_volume_curve_fails_closed(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    app.automation.current_mode = "idle"
    result = await service.play_exact(
        client_event_id="play-idle",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["reason"] == "volume_policy_unavailable"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_interrupted_pending_request_never_replays_after_restart(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    async with factory() as session:
        session.add(MusicAssistedPlaybackEvent(
            client_event_id="play-pending",
            provider="itunes_search",
            provider_id="1713833576",
            title="Bang!",
            playback_adapter="sonos_apple_music_share_link",
            source="test",
            status="pending",
            reason="execution_claimed",
            trust_state="approved",
            mode_at_time="gaming",
            volume_before=20,
            volume_used=20,
        ))
        await session.commit()

    result = await service.play_exact(
        client_event_id="play-pending",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    assert result["status"] == "indeterminate"
    assert result["reason"] == "interrupted_after_claim_no_replay"
    assert result["duplicate"] is True
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_client_event_id_cannot_be_reused_for_different_candidate(db_engine):
    service, _app, _logger, _approval, _factory = await build_service(db_engine)
    await service.play_exact(
        client_event_id="same-id",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    with pytest.raises(ValueError, match="different candidate"):
        await service.play_exact(
            client_event_id="same-id",
            provider="itunes_search",
            provider_id="999",
            source="test",
        )


@pytest.mark.asyncio
async def test_authority_is_rechecked_after_durable_claim(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    calls = 0
    original = app.automation.is_dnd_active

    def dnd_changes_during_request():
        nonlocal calls
        calls += 1
        return False if calls == 1 else True

    app.automation.is_dnd_active = dnd_changes_during_request
    result = await service.play_exact(
        client_event_id="play-live-gate-changed",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )
    app.automation.is_dnd_active = original

    assert result["status"] == "suppressed"
    assert result["reason"] == "dnd_active"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_trust_is_rechecked_after_claim_and_new_revoke_wins(db_engine):
    service, app, logger, approval, _factory = await build_service(db_engine)
    calls = 0
    real_latest = approval.latest_actions

    async def changing_latest(candidates):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await real_latest(candidates)
        return {("itunes_search", "1713833576"): "revoke"}

    approval.latest_actions = changing_latest
    result = await service.play_exact(
        client_event_id="play-revoked-after-claim",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )

    assert result["status"] == "suppressed"
    assert result["reason"] == "trust_revoked"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_authority_change_after_enqueue_blocks_play_and_is_observable(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    def dnd_changes_after_enqueue():
        return bool(app.sonos.track)

    app.automation.is_dnd_active = dnd_changes_after_enqueue
    result = await service.play_exact(
        client_event_id="play-dnd-after-enqueue",
        provider="itunes_search",
        provider_id="1713833576",
        source="test",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "preplay_dnd_active"
    assert app.sonos.state == "STOPPED"
    assert app.sonos.queue_size == 101
    assert len(app.sonos.play_calls) == 1
    assert logger.calls == []


@pytest.mark.asyncio
async def test_mode_change_after_trust_recheck_suppresses_before_enqueue(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    real_lookup = service._catalog.get_by_identity
    calls = 0

    async def changing_lookup(provider, provider_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            app.automation.current_mode = "watching"
        return await real_lookup(provider, provider_id)

    service._catalog.get_by_identity = changing_lookup
    result = await service.play_exact(
        client_event_id="play-mode-changed-before-enqueue",
        provider="itunes_search", provider_id="1713833576", source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == "activity_changed_before_play"
    assert result["mode"] == "watching"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_post_enqueue_volume_drop_below_target_suppresses_without_learning(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    real_status = app.sonos.get_status
    async def changing_status():
        if app.sonos.track:
            app.sonos.volume = 8
        return await real_status()

    app.sonos.get_status = changing_status
    result = await service.play_exact(
        client_event_id="play-final-volume", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "preplay_sonos_volume_below_playback_floor"
    assert logger.calls == []
    async with factory() as session:
        assisted = (await session.execute(
            select(MusicAssistedPlaybackEvent).where(
                MusicAssistedPlaybackEvent.client_event_id == "play-final-volume"
            )
        )).scalar_one()
        learning = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert assisted.status == "failed"
    assert learning == []

@pytest.mark.asyncio
async def test_post_enqueue_wrong_loaded_provider_is_busy(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    app.sonos.loaded_uri_after_enqueue = (
        "x-sonosapi-hls-static:song%3a999?sid=204&flags=8232&sn=2"
    )
    result = await service.play_exact(
        client_event_id="play-wrong-loaded-provider",
        provider="itunes_search", provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "preplay_sonos_busy"
    assert app.sonos.state == "STOPPED"
    assert app.sonos.queue_size == 101
    assert logger.calls == []


@pytest.mark.asyncio
async def test_post_enqueue_missing_loaded_uri_is_busy(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    app.sonos.loaded_uri_after_enqueue = ""
    result = await service.play_exact(
        client_event_id="play-missing-loaded-uri",
        provider="itunes_search", provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "preplay_sonos_busy"
    assert app.sonos.queue_size == 101
    assert logger.calls == []


@pytest.mark.asyncio
async def test_post_enqueue_paused_exact_track_is_busy(db_engine):
    service, app, logger, _approval, _factory = await build_service(db_engine)
    app.sonos.loaded_state_after_enqueue = "PAUSED_PLAYBACK"
    result = await service.play_exact(
        client_event_id="play-paused-exact",
        provider="itunes_search", provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "preplay_sonos_busy"
    assert app.sonos.queue_size == 101
    assert logger.calls == []


async def install_settled_executor(app, monkeypatch, *, stage="enqueue", timeout=False,
                                   append_error=False, real_verifier=False):
    from backend.services.sonos_service import SonosService
    from tests.test_sonos_apple_music_sharelink import FakeDevice

    executor = SonosService()
    device = FakeDevice()
    device.play_mode = "NORMAL"
    device.queue_size = app.sonos.queue_size
    device.volume = app.sonos.volume
    executor._connected = True
    executor._device = device
    app.music_mapper._sonos = executor
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    events = []

    def barrier():
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3), "test did not release settled worker"

    def append(_url):
        events.append("append_started")
        if stage == "enqueue":
            barrier()
        device.queue_size += 1
        device.queue_update_id += 1
        app.sonos.queue_size += 1
        events.append("append_accepted")
        if append_error:
            raise RuntimeError("accepted append then connection lost")
        return device.queue_size

    original_snapshot = executor._queue_item_snapshot_sync

    def snapshot(*args, **kwargs):
        if stage == "post_enqueue" and not entered.is_set():
            barrier()
        return original_snapshot(*args, **kwargs)

    async def verify(*_args, **_kwargs):
        if stage == "verification":
            entered.set()
            await asyncio.to_thread(release.wait, 3)
        return True

    monkeypatch.setattr(executor, "_canonical_apple_music_share_link", lambda _: "song:1713833576")
    monkeypatch.setattr(executor, "_add_apple_music_share_link_sync", append)
    monkeypatch.setattr(executor, "_queue_item_snapshot_sync", snapshot)
    if not real_verifier:
        monkeypatch.setattr(executor, "_verify_queue_playback_started", verify)
    if timeout:
        executor._breaker.call_timeout = 0.02
    return executor, device, entered, release, events


def assisted_request(service, event="authority-race"):
    return service.play_exact(
        client_event_id=event, provider="itunes_search", provider_id="1713833576", source="test",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["enqueue", "post_enqueue", "verification"])
@pytest.mark.parametrize("action", ["replace", "play", "pause"])
async def test_shared_assisted_manual_takeover_retains_append_and_withholds_learning(
    db_engine, monkeypatch, stage, action,
):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, _, factory = await build_service(db_engine)
    _, device, entered, release, events = await install_settled_executor(app, monkeypatch, stage=stage)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)

    async def manual_write():
        events.append("manual_" + action)
        device.transport_state = "PAUSED_PLAYBACK" if action == "pause" else "PLAYING"
        if action == "replace":
            device.queue_size = 7
        return True

    manual = asyncio.create_task(app.audio_ownership.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="test", reason=action, operation=manual_write,
    ))
    await asyncio.sleep(0)
    if stage != "verification":
        assert not manual.done()
    else:
        assert await manual
    release.set()
    result = await task
    assert await manual
    assert result["status"] == "failed"
    assert events.index("append_accepted") < events.index("manual_" + action)
    plays = [call for call in device.calls if call[0] == "play_from_queue"]
    assert len(plays) == (1 if stage == "verification" else 0)
    assert device.queue_size == (7 if action == "replace" else 101)
    assert all(call[0] not in {"stop", "clear_queue", "remove_from_queue"} for call in device.calls)
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert (await app.audio_ownership.snapshot())["leases"] == []
    retry = await assisted_request(service)
    assert retry["duplicate"] and events.count("append_started") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("canceled", [False, True])
async def test_assisted_settled_worker_keeps_shared_authority_after_timeout_or_cancel(
    db_engine, monkeypatch, canceled,
):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, _, _ = await build_service(db_engine)
    _, device, entered, release, events = await install_settled_executor(
        app, monkeypatch, timeout=not canceled,
    )
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    if canceled:
        task.cancel()
    async def manual_write():
        events.append("manual")
        return True
    manual = asyncio.create_task(app.audio_ownership.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="pause", operation=manual_write,
    ))
    await asyncio.sleep(0.06)
    assert not task.done() and not manual.done()
    release.set()
    if canceled:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert (await task)["status"] == "failed"
    assert await manual
    assert events == ["append_started", "append_accepted", "manual"]
    assert device.queue_size == 101 and device.calls == []
    retry = await assisted_request(service)
    assert retry["status"] == ("indeterminate" if canceled else "failed")
    assert events.count("append_started") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["enqueue", "post_enqueue", "verification"])
@pytest.mark.parametrize("transition", ["physical_away", "semantic_away", "sleeping", "dnd", "tts", "ambient", "gameday"])
async def test_assisted_inflight_policy_fence_never_resumes_or_learns(
    db_engine, monkeypatch, stage, transition,
):
    service, app, _, _, factory = await build_service(db_engine)
    _, device, entered, release, _ = await install_settled_executor(app, monkeypatch, stage=stage)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    if transition == "physical_away":
        app.away_manager.away = True
    elif transition == "semantic_away":
        app.automation.current_mode = "idle"
    elif transition == "sleeping":
        app.automation.current_mode = "sleeping"
    elif transition == "dnd":
        app.automation.dnd = True
    elif transition == "tts":
        app.tts.is_speaking = True
    elif transition == "ambient":
        app.ambient_sound.pending = True
    else:
        app.automation.current_mode = "gameday"
    release.set()
    result = await task
    assert result["status"] == "failed"
    assert len(device.calls) == (1 if stage == "verification" else 0)
    assert device.queue_size == 101
    assert app.sonos.volume_calls == []
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())


@pytest.mark.asyncio
async def test_accepted_append_exception_is_retained_and_never_replayed(db_engine, monkeypatch):
    service, app, _, _, _ = await build_service(db_engine)
    _, device, entered, release, events = await install_settled_executor(app, monkeypatch, append_error=True)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    release.set()
    assert (await task)["status"] == "failed"
    assert device.queue_size == 101 and device.calls == []
    assert (await assisted_request(service))["duplicate"]
    assert events.count("append_started") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["tts", "ambient", "gameday", "music_mapper"])
async def test_shared_owner_before_admission_blocks_assisted_without_append(db_engine, owner):
    from backend.services.audio_ownership import INTERRUPTION, QUEUE_SOURCE, TRANSPORT

    service, app, _, _, _ = await build_service(db_engine)
    authority = app.audio_ownership
    if owner == "tts":
        lease = await authority.acquire_interruption(
            owner=owner, purpose="test", dimensions=(QUEUE_SOURCE, TRANSPORT, INTERRUPTION),
        )
    else:
        lease = await authority.acquire(owner=owner, purpose="test", dimensions=(QUEUE_SOURCE, TRANSPORT))
    result = await assisted_request(service)
    assert result["reason"] == "audio_ownership_busy"
    assert app.sonos.play_calls == []
    assert await authority.is_valid(lease["lease_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["enqueue", "post_enqueue", "verification"])
@pytest.mark.parametrize("manual_tts", [False, True])
async def test_tts_queued_admission_and_restore_fences_assisted_success(
    db_engine, monkeypatch, stage, manual_tts,
):
    from backend.services.audio_ownership import AUDIO_DIMENSIONS

    service, app, _, _, factory = await build_service(db_engine)
    _, device, entered, release, events = await install_settled_executor(app, monkeypatch, stage=stage)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    authority = app.audio_ownership
    tts = asyncio.create_task(authority.acquire_interruption(
        owner="tts", purpose="test", dimensions=AUDIO_DIMENSIONS,
        manual_source="dashboard" if manual_tts else None,
    ))
    await asyncio.sleep(0)
    if stage != "verification":
        assert not tts.done()
    release.set()
    lease = await tts
    assert lease is not None
    async def clip():
        events.append("tts_clip")
        return True
    async def restore():
        events.append("tts_restore")
        return True
    assert await authority.run_if_valid(lease["lease_id"], AUDIO_DIMENSIONS, clip) == (True, True)
    assert await authority.run_if_valid(lease["lease_id"], AUDIO_DIMENSIONS, restore) == (True, True)
    await authority.release(lease["lease_id"])
    assert (await task)["status"] == "failed"
    assert device.queue_size == 101
    assert len(device.calls) == (1 if stage == "verification" else 0)
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert (await authority.snapshot())["leases"] == []


@pytest.mark.asyncio
async def test_assisted_claim_fences_older_autonomous_token_preserves_volume_and_no_restart_lease(db_engine):
    from backend.services.audio_ownership import QUEUE_SOURCE, TRANSPORT, VOLUME

    service, app, _, _, _ = await build_service(db_engine)
    authority = app.audio_ownership
    old = await authority.capture_opportunistic((QUEUE_SOURCE, TRANSPORT))
    volume = await authority.acquire(owner="volume", purpose="test", dimensions=(VOLUME,))
    assert (await assisted_request(service))["status"] == "played"
    calls = []
    async def stale_play():
        calls.append("play")
    assert await authority.run_if_opportunistic(old, stale_play) == (False, None)
    assert calls == []
    assert await authority.is_valid(volume["lease_id"])
    assert [lease["owner"] for lease in (await authority.snapshot())["leases"]] == ["volume"]


@pytest.mark.asyncio
async def test_semantic_away_and_home_does_not_revive_old_assisted_request(db_engine, monkeypatch):
    service, app, _, _, _ = await build_service(db_engine)
    _, device, entered, release, _ = await install_settled_executor(app, monkeypatch)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    await app.music_mapper.on_mode_change("away")
    # Current mode alone cannot distinguish an old request from a new Home.
    app.automation.current_mode = "gaming"
    release.set()
    assert (await task)["status"] == "failed"
    assert device.queue_size == 101 and device.calls == []


@pytest.mark.asyncio
async def test_cancellation_during_stream_verification_releases_authority_without_replay(db_engine, monkeypatch):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, _, factory = await build_service(db_engine)
    _, device, entered, release, events = await install_settled_executor(app, monkeypatch, stage="verification")
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    async def manual():
        events.append("manual")
        return True
    assert await app.audio_ownership.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="pause", operation=manual,
    )
    assert (await assisted_request(service))["status"] == "indeterminate"
    assert events.count("append_started") == 1 and device.queue_size == 101
    assert (await app.audio_ownership.snapshot())["leases"] == []
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())


@pytest.mark.asyncio
async def test_missing_shared_authority_fails_closed_without_device_mutation(db_engine):
    service, app, _, _, _ = await build_service(db_engine)
    app.audio_ownership = None
    assert (await assisted_request(service))["reason"] == "audio_ownership_unavailable"
    assert app.sonos.play_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["refused", "acquisition_refused", "cancelled"])
@pytest.mark.parametrize("policy", ["ordinary", "ambient", "gameday"])
async def test_real_tts_acquisition_ingress_fences_settled_append(
    db_engine, monkeypatch, tmp_path, outcome, policy,
):
    from pathlib import Path
    from backend.services.tts_service import PreparedSpeech, TTSService

    service, app, _, _, factory = await build_service(db_engine)
    _, device, entered, release, _ = await install_settled_executor(app, monkeypatch)
    tts = TTSService(app.sonos, tmp_path, "127.0.0.1", audio_ownership=app.audio_ownership)
    app.tts = tts
    # Prepared audio is fake: synthesis, filesystem cleanup and speaker writes
    # are never reached. Refuse the snapshot after real lease acquisition.
    monkeypatch.setattr(tts, "_consume_prepared", lambda *_: Path("fake.mp3"))
    monkeypatch.setattr(tts, "_schedule_cleanup", lambda *_: None)
    async def no_evidence():
        return None
    monkeypatch.setattr(app.sonos, "get_playback_ownership_evidence", no_evidence, raising=False)
    monkeypatch.setattr(app.sonos, "get_current_playback_snapshot", no_evidence, raising=False)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    revision = app.audio_ownership.capture_manual_intent()
    reservation = None
    if outcome == "acquisition_refused":
        reservation = asyncio.create_task(app.audio_ownership.acquire(
            owner="gameday", purpose="reserved-test",
            dimensions=("queue_source", "transport"), evidence={"phase": "reserved"},
        ))
        await asyncio.sleep(0)
    speech = asyncio.create_task(tts._speak_with_ownership(
        "test", 20, manual_source=None, manual_reason=None,
        prepared_audio=PreparedSpeech("test", Path("fake.mp3")),
    ))
    await asyncio.sleep(0)
    assert not speech.done() and not tts.is_speaking
    assert app.audio_ownership.capture_manual_intent() == revision
    if policy == "ambient":
        app.ambient_sound.pending = True
    elif policy == "gameday":
        app.automation.current_mode = "gameday"
    if outcome == "cancelled":
        speech.cancel()
        with pytest.raises(asyncio.CancelledError):
            await speech
    release.set()
    assert (await task)["status"] == "failed"
    if outcome != "cancelled":
        assert await speech is False
    if reservation is not None:
        reserved = await reservation
        assert reserved is not None
        assert await app.audio_ownership.is_valid(reserved["lease_id"])
        await app.audio_ownership.release(reserved["lease_id"])
    assert device.queue_size == 101 and device.calls == []
    assert not tts.is_speaking
    assert (await app.audio_ownership.snapshot())["leases"] == []
    # Refusal/cancellation fences old tokens, without blocking future requests.
    assert await app.audio_ownership.capture_opportunistic(("queue_source", "transport")) is not None
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())


@pytest.mark.asyncio
@pytest.mark.parametrize("barrier", ["select", "commit", "refresh"])
@pytest.mark.parametrize("action", ["pause", "play", "replace"])
async def test_manual_during_completion_preserves_positive_history(
    db_engine, monkeypatch, barrier, action,
):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, approval, factory = await build_service(db_engine)
    _, device, _, _, events = await install_settled_executor(app, monkeypatch, stage="none", real_verifier=True)
    original_complete = service._complete_played_with_learning
    # Historical evidence for another request must remain unchanged.
    async with factory() as session:
        unrelated = SonosPlaybackEvent(
            event_type="play", favorite_title="Bang!", mode_at_time="gaming",
            volume=22, triggered_by="manual",
        )
        session.add(unrelated)
        await session.commit()
        unrelated_id = unrelated.id
    entered = asyncio.Event()
    release = asyncio.Event()

    async def complete(*args, **kwargs):
        original = getattr(AsyncSession, "execute" if barrier == "select" else barrier)
        used = False
        async def blocked(session, *a, **kw):
            nonlocal used
            result = await original(session, *a, **kw)
            if not used:
                used = True
                entered.set()
                await release.wait()
            return result
        with monkeypatch.context() as scoped:
            scoped.setattr(AsyncSession, "execute" if barrier == "select" else barrier, blocked)
            return await original_complete(*args, **kwargs)

    monkeypatch.setattr(service, "_complete_played_with_learning", complete)
    task = asyncio.create_task(assisted_request(service, "completion-race"))
    await asyncio.wait_for(entered.wait(), 2)
    async def manual_write():
        device.transport_state = "PAUSED_PLAYBACK" if action == "pause" else "PLAYING"
        if action == "replace":
            device.queue_size = 7
        return True

    assert await app.audio_ownership.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="test", reason=action, operation=manual_write,
    )
    release.set()
    result = await task
    assert result["status"] == "played"
    assert result["reason"] == "explicit_approved_candidate"
    async with factory() as session:
        rows = list((await session.execute(select(MusicAssistedPlaybackEvent))).scalars())
        assert len(rows) == 1 and rows[0].status == "played"
        learning = list((await session.execute(select(SonosPlaybackEvent))).scalars())
        assert len(learning) == 2
        assert unrelated_id in [event.id for event in learning]
    retry = await assisted_request(service, "completion-race")
    assert retry["duplicate"] and retry["reason"] == result["reason"]
    restarted = MusicAssistedPlaybackService(
        app_state=app, catalog=FakeCatalog(apple_candidate()),
        taste_provider=FakeTasteProvider(), approval_service=approval,
        trust_policy=MusicTrustPolicy(), setting_loader=lambda _key: _async_value({}),
        session_factory=factory,
        lifecycle_state=lambda: {"travel": False, "returning_home": False},
    )
    retry = await assisted_request(restarted, "completion-race")
    assert retry["duplicate"] and retry["reason"] == result["reason"]
    assert events.count("append_started") == 1
    assert len([call for call in device.calls if call[0] == "play_from_queue"]) == 1
    assert device.transport_state == ("PAUSED_PLAYBACK" if action == "pause" else "PLAYING")
    assert device.queue_size == (7 if action == "replace" else 101)
    assert all(call[0] not in {"stop", "clear_queue", "remove_from_queue"} for call in device.calls)
    assert (await app.audio_ownership.snapshot())["leases"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("real_verifier,manual_ingress", [(False, True), (True, True), (True, False)])
async def test_manual_pause_during_verification_reports_authority_change(db_engine, monkeypatch, real_verifier, manual_ingress):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, _, factory = await build_service(db_engine)
    executor, device, entered, release, events = await install_settled_executor(app, monkeypatch, stage="verification")
    if real_verifier:
        from backend.services.sonos_service import SonosService

        monkeypatch.setattr(executor, "_verify_queue_playback_started", SonosService._verify_queue_playback_started.__get__(executor))

        def sample(*_args):
            entered.set()
            assert release.wait(3)
            return {"state": device.transport_state, "position": 0}

        monkeypatch.setattr(executor, "_playback_start_sample_sync", sample)
    task = asyncio.create_task(assisted_request(service))
    await asyncio.wait_for(entered.wait(), 2)
    async def pause():
        events.append("pause")
        device.transport_state = "PAUSED_PLAYBACK"
        return True
    if manual_ingress:
        assert await app.audio_ownership.run_manual(
            MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="pause", operation=pause,
        )
    else:
        assert await pause()
    release.set()
    result = await task
    assert result["status"] == "failed"
    assert result["reason"] == (
        "playback_authority_changed" if manual_ingress else "playback_start_unverified"
    )
    assert device.queue_size == 101
    assert (await assisted_request(service))["duplicate"]
    assert events.count("append_started") == 1
    async with factory() as session:
        assert not list((await session.execute(select(SonosPlaybackEvent))).scalars())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["late_manual", "refresh", "first_commit"])
async def test_completion_transaction_preserves_verified_history_or_safe_pending(db_engine, monkeypatch, failure):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, approval, factory = await build_service(db_engine)
    _, device, _, _, events = await install_settled_executor(
        app, monkeypatch, stage="none", real_verifier=True,
    )
    original_complete = service._complete_played_with_learning
    entered, release = asyncio.Event(), asyncio.Event()

    async def complete(*args, **kwargs):
        original_commit = AsyncSession.commit
        commits = 0

        async def commit(session):
            nonlocal commits
            commits += 1
            if commits > 1:
                raise AssertionError("completion must commit exactly once")
            if failure == "first_commit":
                await session.flush()
                entered.set()
                await release.wait()
                raise RuntimeError("injected first commit failure")
            await original_commit(session)
            if commits == 1:
                entered.set()
                await release.wait()

        async def refresh(_session, *_args, **_kwargs):
            app.audio_ownership.record_manual_intent(MANUAL_TRANSPORT_DIMENSIONS)
            raise RuntimeError("injected refresh failure")

        with monkeypatch.context() as scoped:
            scoped.setattr(AsyncSession, "commit", commit)
            if failure == "refresh":
                scoped.setattr(AsyncSession, "refresh", refresh)
            return await original_complete(*args, **kwargs)

    monkeypatch.setattr(service, "_complete_played_with_learning", complete)
    task = asyncio.create_task(assisted_request(service, "db-failure"))
    await asyncio.wait_for(entered.wait(), 2)
    if failure != "refresh":
        app.audio_ownership.record_manual_intent(MANUAL_TRANSPORT_DIMENSIONS)
    release.set()
    if failure == "late_manual":
        assert (await task)["status"] == "played"
    else:
        with pytest.raises(RuntimeError, match="injected"):
            await task
    async with factory() as session:
        persisted = (await session.execute(select(MusicAssistedPlaybackEvent))).scalar_one()
        assert persisted.status == ("pending" if failure == "first_commit" else "played")
        evidence = list((await session.execute(select(SonosPlaybackEvent))).scalars())
        assert len(evidence) == (0 if failure == "first_commit" else 1)
    restarted = MusicAssistedPlaybackService(
        app_state=app, catalog=FakeCatalog(apple_candidate()),
        taste_provider=FakeTasteProvider(), approval_service=approval,
        trust_policy=MusicTrustPolicy(), setting_loader=lambda _key: _async_value({}),
        session_factory=factory,
        lifecycle_state=lambda: {"travel": False, "returning_home": False},
    )
    for retry_service in (service, restarted):
        result = await assisted_request(retry_service, "db-failure")
        assert result["duplicate"]
        assert result["status"] == ("indeterminate" if failure == "first_commit" else "played")
    assert events.count("append_started") == 1
    assert device.calls == [("play_from_queue", 100)]
    assert device.queue_size == 101
    async with factory() as session:
        rows = list((await session.execute(select(MusicAssistedPlaybackEvent))).scalars())
        assert len(rows) == 1
        assert rows[0].status == ("indeterminate" if failure == "first_commit" else "played")
        learning = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert len(learning) == (0 if failure == "first_commit" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_timing", ["after", "during"])
async def test_real_advancing_proof_freezes_authority_without_volume_lock(
    db_engine, monkeypatch, pause_timing,
):
    from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS

    service, app, _, _, factory = await build_service(db_engine)
    executor, device, _, _, events = await install_settled_executor(
        app, monkeypatch, stage="none", real_verifier=True,
    )
    loop = asyncio.get_running_loop()
    sample_entered, volume_entered, proof_accepted = (
        asyncio.Event(), asyncio.Event(), asyncio.Event()
    )
    sample_release = threading.Event()
    volume_release, completion_release = asyncio.Event(), asyncio.Event()
    original_sample = executor._playback_start_sample_sync
    samples = []

    def sample(*args):
        if not samples:
            loop.call_soon_threadsafe(sample_entered.set)
            assert sample_release.wait(3)
        result = original_sample(*args)
        samples.append(result)
        return result

    monkeypatch.setattr(executor, "_playback_start_sample_sync", sample)
    original_complete = service._complete_played_with_learning

    async def complete(*args, **kwargs):
        proof_accepted.set()
        await completion_release.wait()
        return await original_complete(*args, **kwargs)

    monkeypatch.setattr(service, "_complete_played_with_learning", complete)
    task = asyncio.create_task(assisted_request(service, "volume-proof"))
    await asyncio.wait_for(sample_entered.wait(), 2)

    async def volume_write():
        volume_entered.set()
        await volume_release.wait()
        # A volume-only writer may occupy the lock without changing Q/T or
        # the physical volume sampled by the verifier.
        device.volume = 22
        return True

    volume = asyncio.create_task(app.audio_ownership.run_manual(
        ("volume", "interruption"), source="test", reason="volume",
        operation=volume_write,
    ))
    await asyncio.wait_for(volume_entered.wait(), 2)

    async def pause_write():
        device.transport_state = "PAUSED_PLAYBACK"
        events.append("pause")
        return True

    if pause_timing == "after":
        sample_release.set()
        await asyncio.wait_for(proof_accepted.wait(), 2)
        assert samples[0] == {"state": "PLAYING", "position": 0.0}
        assert samples[-1]["position"] >= 1
    pause = asyncio.create_task(app.audio_ownership.run_manual(
        MANUAL_TRANSPORT_DIMENSIONS, source="test", reason="pause",
        operation=pause_write,
    ))
    await asyncio.sleep(0)
    assert not pause.done() and not volume.done()
    if pause_timing == "during":
        sample_release.set()
        result = await asyncio.wait_for(task, 2)
        assert result["reason"] == "playback_authority_changed"
        assert not proof_accepted.is_set()
    volume_release.set()
    assert await volume and await pause
    completion_release.set()
    result = await task
    assert result["status"] == ("played" if pause_timing == "after" else "failed")
    assert device.transport_state == "PAUSED_PLAYBACK"
    assert device.volume == 22 and not device.mute
    assert device.calls == [("play_from_queue", 100)]
    assert device.queue_size == 101
    assert events.count("append_started") == 1
    assert (await assisted_request(service, "volume-proof"))["duplicate"]
    assert device.calls == [("play_from_queue", 100)]
    async with factory() as session:
        learning = list((await session.execute(select(SonosPlaybackEvent))).scalars())
        assert len(learning) == (1 if pause_timing == "after" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_legacy_async_verification_guard_remains_supported(db_engine, monkeypatch, verified):
    service, app, _, _, _ = await build_service(db_engine)
    executor, device, _, _, _ = await install_settled_executor(
        app, monkeypatch, stage="none", real_verifier=True,
    )
    device.source_on_play = None if verified else "x-rincon-queue:OTHER#0"
    calls = []

    async def guard():
        await asyncio.sleep(0)
        calls.append("legacy")
        return True

    result = await executor.play_apple_music_share_link(
        "1713833576", apple_candidate().playback_reference,
        expected_queue_size=100, verification_guard=guard,
    )
    assert result is verified
    assert calls == ["legacy"]
