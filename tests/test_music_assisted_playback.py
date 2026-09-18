from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models import MusicAssistedPlaybackEvent, SonosPlaybackEvent
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
        self.volume = 20
        self.mute = False
        self.play_mode = "NORMAL"
        self.queue_size = 100
        self.play_result = True
        self.play_calls = []
        self.volume_calls = []

    async def get_status(self):
        return {
            "state": self.state,
            "track": self.track,
            "volume": self.volume,
            "mute": self.mute,
        }

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
    ):
        self.play_calls.append((provider_id, share_url))
        if not self.play_result:
            return False
        self.queue_size += 1
        if before_play is not None:
            guard = await before_play()
            if isinstance(guard, dict):
                if guard.get("reason") is not None:
                    return False
            elif not guard:
                return False
        self.state = "PLAYING"
        self.track = "Bang!"
        return True


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
    assert rows[0].volume == 20
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
    assert result2["status"] == "played"
    assert result2["volume_used"] == 8
    assert app2.sonos.volume_calls == []


@pytest.mark.asyncio
async def test_failed_playback_never_writes_volume_or_learning_evidence(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    app.sonos.volume = 20
    app.sonos.play_result = False
    result = await service.play_exact(
        client_event_id="play-fails", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "playback_failed"
    assert app.sonos.volume_calls == []
    assert app.sonos.volume == 20
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
    calls = 0

    def dnd_changes_after_enqueue():
        nonlocal calls
        calls += 1
        return calls >= 3

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
            app.automation.current_mode = "social"
        return await real_lookup(provider, provider_id)

    service._catalog.get_by_identity = changing_lookup
    result = await service.play_exact(
        client_event_id="play-mode-changed-before-enqueue",
        provider="itunes_search", provider_id="1713833576", source="test",
    )
    assert result["status"] == "suppressed"
    assert result["reason"] == "activity_changed_before_play"
    assert result["mode"] == "social"
    assert app.sonos.play_calls == []
    assert logger.calls == []


@pytest.mark.asyncio
async def test_success_uses_post_enqueue_guard_volume_for_learning_evidence(db_engine):
    service, app, logger, _approval, factory = await build_service(db_engine)
    real_status = app.sonos.get_status
    calls = 0

    async def changing_status():
        nonlocal calls
        calls += 1
        if calls >= 3:
            app.sonos.volume = 8
        return await real_status()

    app.sonos.get_status = changing_status
    result = await service.play_exact(
        client_event_id="play-final-volume", provider="itunes_search",
        provider_id="1713833576", source="test",
    )
    assert result["status"] == "played"
    assert result["volume_used"] == 8
    assert logger.calls == []
    async with factory() as session:
        assisted = (await session.execute(
            select(MusicAssistedPlaybackEvent).where(
                MusicAssistedPlaybackEvent.client_event_id == "play-final-volume"
            )
        )).scalar_one()
        learning = list((await session.execute(select(SonosPlaybackEvent))).scalars())
    assert assisted.mode_at_time == "gaming"
    assert assisted.volume_before == 8
    assert assisted.volume_used == 8
    assert len(learning) == 1
    assert learning[0].mode_at_time == "gaming"
    assert learning[0].volume == 8
