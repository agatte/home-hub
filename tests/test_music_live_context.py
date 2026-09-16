from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.music_curator import CuratorFact, MusicCuratorContext, MusicCuratorContextBuilder
from backend.services.music_live_context import MusicLiveContextService

NOW = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)


class FakeDiscovery:
    enabled = True

    def __init__(self):
        self.calls = []

    async def preview(self, mode, *, policy="gentle", count=6, tracks_per_artist=3, intent=None):
        self.calls.append({
            "mode": mode, "policy": policy, "count": count,
            "tracks_per_artist": tracks_per_artist, "intent": intent,
        })
        return SimpleNamespace(
            status="shadow_ready",
            to_dict=lambda: {
                "status": "shadow_ready", "mode": mode, "policy": policy,
                "clusters": [], "shadow": True, "actuation_allowed": False,
            },
        )


class FakeBuilder:
    supported_modes = ("gameday", "gaming", "social")

    def __init__(self, contexts):
        self.contexts = contexts
        self.calls = []

    async def build(self, mode):
        self.calls.append(mode)
        return self.contexts[mode]


def _context(mode, facts=None, suppression=None, generated_at=NOW):
    return MusicCuratorContext(
        mode=mode, generated_at=generated_at, facts=facts or {},
        suppression_reason=suppression,
    )


def _automation(*, mode, game=None, qualification=None, candidate_mode=None, age=1.0):
    class Automation:
        house_state = "home"
        current_mode = mode
        current_game = game
        last_activity_change = NOW - timedelta(minutes=40)

        def is_dnd_active(self):
            return False

        def get_activity_context(self):
            return {
                "current_activity": mode,
                "current_activity_source": "process",
                "process_observations_by_device": {
                    "desktop": {
                        "candidate_mode": candidate_mode,
                        "gaming_qualification": qualification,
                        "received_at": NOW.isoformat(),
                        "age_seconds": age,
                    }
                },
            }

    return Automation()


@pytest.mark.asyncio
async def test_gaming_adapter_exposes_only_fresh_foreground_game_as_trusted_identity():
    state = SimpleNamespace(
        automation=_automation(
            mode="gaming", game="valheim", qualification="foreground_game",
            candidate_mode="gaming", age=2.0,
        ),
        weather_service=None, music_mapper=SimpleNamespace(mapping={"gaming": []}),
        music_bandit=None, sonos=None,
    )
    builder = MusicCuratorContextBuilder(state, now_fn=lambda: NOW)

    context = await builder.build("gaming")

    assert context.facts["gaming_identity_trusted"].value is True
    assert context.facts["game"].value == "valheim"
    assert context.facts["game"].usable is True
    assert context.facts["game"].source == "automation_engine:desktop_foreground_game"


@pytest.mark.asyncio
async def test_gaming_adapter_does_not_trust_background_game_identity():
    state = SimpleNamespace(
        automation=_automation(
            mode="gaming", game="valheim", qualification="background_game_not_foreground",
            candidate_mode="working", age=2.0,
        ),
        weather_service=None, music_mapper=SimpleNamespace(mapping={"gaming": []}),
        music_bandit=None, sonos=None,
    )
    builder = MusicCuratorContextBuilder(state, now_fn=lambda: NOW)

    context = await builder.build("gaming")

    assert context.facts["gaming_identity_trusted"].value is False
    assert context.facts["game"].value == "valheim"
    assert context.facts["game"].usable is False
    assert context.facts["game"].source == "automation_engine:untrusted_game_context"


@pytest.mark.asyncio
async def test_stale_foreground_report_does_not_authorize_game_identity():
    state = SimpleNamespace(
        automation=_automation(
            mode="gaming", game="valheim", qualification="foreground_game",
            candidate_mode="gaming", age=31.0,
        ),
        weather_service=None, music_mapper=SimpleNamespace(mapping={"gaming": []}),
        music_bandit=None, sonos=None,
    )
    context = await MusicCuratorContextBuilder(state, now_fn=lambda: NOW).build("gaming")
    assert context.facts["gaming_identity_trusted"].value is False
    assert context.facts["game"].usable is False


@pytest.mark.asyncio
async def test_social_adapter_uses_bounded_session_phase_not_ever_changing_age():
    state = SimpleNamespace(
        automation=_automation(mode="social"), weather_service=None,
        music_mapper=SimpleNamespace(mapping={"social": []}), music_bandit=None,
        sonos=None,
    )
    context = await MusicCuratorContextBuilder(state, now_fn=lambda: NOW).build("social")
    assert context.facts["social_active"].value is True
    assert context.facts["social_session_phase"].value == "steady"


@pytest.mark.asyncio
async def test_gameday_music_context_uses_held_schedule_without_refreshing_provider():
    class Automation:
        house_state = "home"
        current_mode = "gameday"
        def is_dnd_active(self):
            return False

    class GameDay:
        def current_state(self):
            return None
        def peek_upcoming_schedule(self, limit=1):
            return [{
                "opponent": "Houston Texans",
                "colts_are_home": True,
                "kickoff_utc": NOW + timedelta(days=2),
            }][:limit]
        async def get_upcoming_schedule(self, limit=1):
            raise AssertionError("music context must not refresh ESPN schedule")

    state = SimpleNamespace(
        automation=Automation(), gameday=GameDay(), weather_service=None,
        music_mapper=SimpleNamespace(mapping={"pregameday": []}),
        music_bandit=None, sonos=None,
    )
    builder = MusicCuratorContextBuilder(
        state, setting_loader=lambda key: _none_async(), now_fn=lambda: NOW,
    )
    context = await builder.build("gameday")
    assert context.facts["opponent"].value == "Houston Texans"
    assert context.facts["opponent"].source == "gameday_schedule_cache"


async def _none_async():
    return None


@pytest.mark.asyncio
async def test_live_gaming_valheim_specializes_only_from_trusted_game_fact():
    context = _context("gaming", facts={
        "game": CuratorFact("valheim", "automation_engine:desktop_foreground_game", usable=True),
        "gaming_identity_trusted": CuratorFact(True, "automation_engine:desktop_process"),
    })
    discovery = FakeDiscovery()
    service = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="gaming")),
        context_builder=FakeBuilder({"gaming": context}), discovery=discovery,
    )

    result = await service.preview(policy="explore", count=4, tracks_per_artist=2)

    assert result["status"] == "shadow_ready"
    assert result["live_context"]["semantic_request"] == "valheim"
    assert discovery.calls == [{
        "mode": "gaming", "policy": "explore", "count": 4,
        "tracks_per_artist": 2, "intent": "valheim",
    }]


@pytest.mark.asyncio
async def test_untrusted_game_fact_keeps_generic_gaming_semantics():
    context = _context("gaming", facts={
        "game": CuratorFact("valheim", "automation_engine:untrusted_game_context", usable=False),
    })
    discovery = FakeDiscovery()
    service = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="gaming")),
        context_builder=FakeBuilder({"gaming": context}), discovery=discovery,
    )
    status = await service.status()
    assert status["semantic_request"] == "gaming"
    assert "no trusted foreground" in status["semantic_reason"]


@pytest.mark.asyncio
async def test_gameday_reuses_existing_clutch_stakes_policy_for_semantic_flavor():
    context = _context("gameday", facts={
        "opponent": CuratorFact("Texans", "gameday_state"),
        "season_week": CuratorFact(15, "gameday_playoff_state"),
        "playoff_probability": CuratorFact(0.6, "gameday_playoff_state"),
        "division_gap_games": CuratorFact(1, "gameday_playoff_state"),
        "is_preseason": CuratorFact(False, "gameday_playoff_state"),
        "is_eliminated": CuratorFact(False, "gameday_playoff_state"),
    })
    discovery = FakeDiscovery()
    service = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="gameday")),
        context_builder=FakeBuilder({"gameday": context}), discovery=discovery,
    )

    status = await service.status()

    assert status["consumer"] == "gameday"
    assert status["semantic_request"] == "gameday_clutch"
    assert status["semantic_reason"] == "existing Game Day stakes tier: clutch"


@pytest.mark.asyncio
async def test_stale_gameday_stakes_do_not_drive_semantic_specialization():
    context = _context("gameday", facts={
        "season_week": CuratorFact(15, "gameday_playoff_state", usable=False),
        "division_gap_games": CuratorFact(0, "gameday_playoff_state", usable=False),
    })
    service = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="gameday")),
        context_builder=FakeBuilder({"gameday": context}), discovery=FakeDiscovery(),
    )
    status = await service.status()
    assert status["semantic_request"] == "gameday"
    assert status["semantic_reason"].endswith("standard")


@pytest.mark.asyncio
async def test_inactive_or_suppressed_live_context_never_calls_discovery():
    discovery = FakeDiscovery()
    inactive = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="working")),
        context_builder=FakeBuilder({}), discovery=discovery,
    )
    assert (await inactive.preview())["status"] == "inactive"

    suppressed_context = _context("social", suppression="dnd_active")
    suppressed = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="social")),
        context_builder=FakeBuilder({"social": suppressed_context}), discovery=discovery,
    )
    assert (await suppressed.preview())["status"] == "suppressed"
    assert discovery.calls == []


def test_context_signature_ignores_generation_timestamp_but_tracks_meaningful_fact_change():
    first = _context("social", facts={"current_track": CuratorFact("A", "sonos")}, generated_at=NOW)
    same = _context("social", facts={"current_track": CuratorFact("A", "sonos", "later")}, generated_at=NOW + timedelta(minutes=5))
    changed = _context("social", facts={"current_track": CuratorFact("B", "sonos")}, generated_at=NOW + timedelta(minutes=5))
    assert MusicLiveContextService._signature(first) == MusicLiveContextService._signature(same)
    assert MusicLiveContextService._signature(first) != MusicLiveContextService._signature(changed)


@pytest.mark.asyncio
async def test_same_live_context_reenters_discovery_so_fresh_taste_feedback_can_rerank():
    context = _context("social")
    discovery = FakeDiscovery()
    service = MusicLiveContextService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="social")),
        context_builder=FakeBuilder({"social": context}), discovery=discovery,
    )
    await service.preview()
    await service.preview()
    assert len(discovery.calls) == 2
    assert all(call["intent"] == "social" for call in discovery.calls)
