from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.music_curator import (
    CuratorFact,
    MusicCurator,
    MusicCuratorContext,
    MusicCuratorContextBuilder,
    MusicCuratorError,
    MusicCuratorUnavailable,
    MusicIntent,
)
from backend.services.music_taste import build_music_taste_snapshot
from backend.services.playlist_catalog import (
    SonosFavoritesCatalog,
    VerifiedMusicCandidate,
)


class FakeIntentProvider:
    def __init__(self, intent: MusicIntent | None = None, *, fail: bool = False):
        self.intent = intent or MusicIntent.from_mapping({
            "energy": 0.8,
            "familiarity": 0.7,
            "novelty": 0.3,
            "nostalgia": 0.4,
            "singalong": 0.8,
            "aggressiveness": 0.6,
            "background_focus": 0.2,
            "genres": ["rock"],
            "themes": ["stadium"],
            "search_concepts": ["stadium hype", "singalong rock"],
            "rationale": "High-energy pregame music.",
        })
        self.fail = fail
        self.calls = 0

    @property
    def configured(self) -> bool:
        return not self.fail

    async def generate(self, context):
        self.calls += 1
        if self.fail:
            raise MusicCuratorUnavailable("model offline")
        return self.intent


class FakeCatalog:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    async def search(self, intent, *, limit=12):
        self.calls += 1
        return list(self.candidates)[:limit]


class FakeContextBuilder:
    supported_modes = ("gameday", "social")



class FakeTasteProvider:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.calls = 0

    async def snapshot(self):
        self.calls += 1
        return self._snapshot



class FakeBandit:
    def __init__(self):
        self.calls = 0

    def get_status(self):
        self.calls += 1
        return {
            "top_arms": {
                "social": {
                    "any": [
                        {"title": "Known Favorite", "mean": 0.9},
                        {"title": "Other Favorite", "mean": 0.2},
                    ]
                }
            }
        }


def _candidate(title, *, verified=True, uri="uri://real", match=0.5):
    return VerifiedMusicCandidate(
        provider="test",
        provider_id=title.casefold().replace(" ", "-"),
        media_type="favorite",
        title=title,
        uri=uri,
        source="favorite",
        verified=verified,
        metadata={"catalog_match_score": match, "matched_concepts": []},
    )


def _context(mode="social", *, suppression=None, facts=None, age_seconds=0):
    return MusicCuratorContext(
        mode=mode,
        generated_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        facts=facts or {},
        suppression_reason=suppression,
    )


@pytest.mark.asyncio
async def test_curator_rejects_unverified_and_empty_uri_candidates():
    provider = FakeIntentProvider()
    catalog = FakeCatalog([
        _candidate("Fabricated", verified=False, match=1.0),
        _candidate("Empty URI", uri="", match=1.0),
        _candidate("Verified", match=0.4),
    ])
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=catalog,
    )

    result = await curator.curate(_context())

    assert result.status == "shadow_ready"
    assert result.shadow is True
    assert result.actuation_allowed is False
    assert [s.candidate.title for s in result.suggestions] == ["Verified"]


@pytest.mark.asyncio
async def test_stale_context_is_rejected_before_intent_provider_or_catalog():
    provider = FakeIntentProvider()
    catalog = FakeCatalog([_candidate("Verified")])
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=catalog,
    )

    with pytest.raises(MusicCuratorError, match="stale"):
        await curator.curate(_context(age_seconds=16 * 60))

    assert provider.calls == 0
    assert catalog.calls == 0


@pytest.mark.asyncio
async def test_hard_suppression_skips_intent_provider_and_catalog():
    provider = FakeIntentProvider()
    catalog = FakeCatalog([_candidate("Verified")])
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=catalog,
    )

    result = await curator.curate(_context(suppression="dnd_active"))

    assert result.status == "suppressed"
    assert result.note == "dnd_active"
    assert not result.suggestions
    assert provider.calls == 0
    assert catalog.calls == 0


@pytest.mark.asyncio
async def test_intent_provider_failure_degrades_only_to_verified_existing_fallback_pool():
    provider = FakeIntentProvider(fail=True)
    catalog = FakeCatalog([
        _candidate("It's Lit!", match=0.0),
        _candidate("Unrelated Favorite", match=1.0),
        _candidate("Fake Fallback", verified=False, match=1.0),
    ])
    facts = {
        "mapped_playlists": CuratorFact([], "music_mapper:pregameday"),
        "deterministic_fallback_titles": CuratorFact(["It's Lit!"], "policy"),
    }
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=catalog,
    )

    result = await curator.curate(_context("gameday", facts=facts))

    assert result.status == "fallback"
    assert result.intent.source == "deterministic_fallback"
    assert [s.candidate.title for s in result.suggestions] == ["It's Lit!"]
    assert result.suggestions[0].candidate.verified is True


@pytest.mark.asyncio
async def test_bandit_evidence_ranks_without_mutation():
    provider = FakeIntentProvider(MusicIntent.from_mapping({
        "familiarity": 0.7,
        "novelty": 0.3,
        "search_concepts": [],
    }))
    catalog = FakeCatalog([
        _candidate("Other Favorite", match=0.0),
        _candidate("Known Favorite", match=0.0),
    ])
    bandit = FakeBandit()
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=catalog,
        bandit=bandit,
    )

    result = await curator.curate(_context("social"))

    assert [s.candidate.title for s in result.suggestions][:1] == ["Known Favorite"]
    assert result.suggestions[0].bandit_mean == 0.9
    assert bandit.calls >= 1
    assert not hasattr(bandit, "record_reward")


@pytest.mark.asyncio
async def test_context_builder_does_not_inject_derived_bandit_posterior():
    class Automation:
        house_state = "home"
        current_mode = "social"

        def is_dnd_active(self):
            return False

    class Mapper:
        mapping = {"social": []}

    bandit = FakeBandit()
    state = SimpleNamespace(
        automation=Automation(), music_mapper=Mapper(), music_bandit=bandit,
        weather_service=None, sonos=None,
    )
    builder = MusicCuratorContextBuilder(state)

    context = await builder.build("social")

    assert "bandit_top_arms" not in context.facts
    assert bandit.calls == 0


@pytest.mark.asyncio
async def test_context_builder_uses_provenance_and_team_form_without_inference():
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)

    class Automation:
        house_state = "home"
        current_mode = "general"
        def is_dnd_active(self):
            return False

    class Weather:
        def get_cache_snapshot(self):
            return {
                "condition_family": "rain",
                "provenance": "stale_display",
                "observed_at": "2026-09-15T20:00:00+00:00",
                "fresh": False,
            }

    class GameDay:
        def current_state(self):
            return None
        async def get_upcoming_schedule(self, limit=1):
            return [{
                "opponent": "Kansas City Chiefs",
                "colts_are_home": False,
                "kickoff_utc": datetime(2026, 9, 21, 0, 20, tzinfo=timezone.utc),
            }]

    class Mapper:
        mapping = {"pregameday": []}

    values = {
        "gameday_playoff_state": {
            "season_week": 2,
            "division_gap_games": 0,
            "is_eliminated": False,
            "is_preseason": False,
            "record": [1, 1, 0],
            "refreshed_at": "2026-09-15T10:00:00+00:00",
        },
        "gameday_team_form": {
            "last4_record": [1, 1],
            "win_streak": 0,
            "last_game_result": "L",
            "last_game_margin": -3,
            "season_record": [1, 1, 0],
            "refreshed_at": "2026-09-15T10:00:00+00:00",
        },
    }
    async def load_setting(key):
        return values.get(key)

    state = SimpleNamespace(
        automation=Automation(),
        weather_service=Weather(),
        gameday=GameDay(),
        music_mapper=Mapper(),
        music_bandit=None,
    )
    builder = MusicCuratorContextBuilder(
        state, setting_loader=load_setting, now_fn=lambda: now,
    )

    context = await builder.build("gameday")

    assert context.suppression_reason is None
    assert context.facts["opponent"].value == "Kansas City Chiefs"
    assert context.facts["opponent"].source == "gameday_schedule"
    assert context.facts["home_away"].value == "away"
    assert context.facts["last_game_result"].value == "L"
    assert context.facts["last_game_margin"].value == -3
    assert context.facts["last_game_margin"].source == "gameday_team_form"
    assert context.facts["weather"].value == "rain"
    assert context.facts["weather"].usable is False


@pytest.mark.asyncio
async def test_preview_cache_reuses_same_context_without_second_intent_provider_call():
    provider = FakeIntentProvider()
    catalog = FakeCatalog([_candidate("Verified", match=0.7)])

    class Builder:
        supported_modes = ("social",)

        async def build(self, mode):
            return _context(mode, facts={
                "local_period": CuratorFact("evening", "home_clock"),
            })

    curator = MusicCurator(
        context_builder=Builder(),
        intent_provider=provider,
        catalog=catalog,
    )

    first = await curator.preview("social", limit=3)
    second = await curator.preview("social", limit=3)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert provider.calls == 1
    assert catalog.calls == 1
    assert second.suggestions == first.suggestions


@pytest.mark.asyncio
async def test_stale_persisted_gameday_facts_are_diagnostic_not_authoritative():
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)

    class Automation:
        house_state = "home"
        current_mode = "general"
        def is_dnd_active(self):
            return False

    class GameDay:
        def current_state(self):
            return None
        async def get_upcoming_schedule(self, limit=1):
            return []

    class Mapper:
        mapping = {"pregameday": []}

    stale_at = "2026-09-01T00:00:00+00:00"
    values = {
        "gameday_playoff_state": {
            "is_eliminated": True,
            "is_preseason": False,
            "season_week": 1,
            "refreshed_at": stale_at,
        },
        "gameday_team_form": {
            "last_game_result": "L",
            "last_game_margin": -20,
            "refreshed_at": stale_at,
        },
    }
    async def load_setting(key):
        return values.get(key)

    state = SimpleNamespace(
        automation=Automation(),
        gameday=GameDay(),
        music_mapper=Mapper(),
        music_bandit=None,
        weather_service=None,
    )
    builder = MusicCuratorContextBuilder(
        state, setting_loader=load_setting, now_fn=lambda: now,
    )

    context = await builder.build("gameday")

    assert context.suppression_reason is None
    assert context.facts["is_eliminated"].usable is False
    assert context.facts["last_game_result"].usable is False


@pytest.mark.asyncio
async def test_sonos_catalog_returns_only_real_queueable_unique_favorites():
    class Sonos:
        connected = True
        async def get_favorites(self):
            return [
                {"title": "It's Lit!", "uri": "sonos://lit", "source": "favorite"},
                {"title": "It's Lit!", "uri": "sonos://lit", "source": "favorite"},
                {"title": "Empty", "uri": "", "source": "favorite"},
                {
                    "title": "Unsupported Shortcut", "uri": "sonos://looks-real",
                    "source": "favorite", "playback_supported": False,
                },
                {
                    "title": "Stadium Rock", "uri": "sonos://rock",
                    "source": "favorite", "playback_supported": True,
                },
            ]

    intent = MusicIntent.from_mapping({
        "search_concepts": ["stadium rock"],
        "themes": ["hype"],
    })
    catalog = SonosFavoritesCatalog(Sonos())

    results = await catalog.search(intent)

    assert [r.title for r in results] == ["Stadium Rock", "It's Lit!"]
    assert all(r.verified and r.catalog_verified and r.uri for r in results)
    assert all(r.playback_capable for r in results)
    assert all(r.playback_adapter == "sonos_favorite_title" for r in results)
    assert results[0].playback_reference == "Stadium Rock"
    assert results[0].metadata["catalog_match_score"] > results[1].metadata["catalog_match_score"]


@pytest.mark.asyncio
async def test_registered_context_adapter_extends_curator_without_core_branching():
    class GamingAdapter:
        mode = "gaming"
        mapping_mode = "gaming"
        fallback_titles = ()

        async def augment(self, facts, now):
            facts["game_title"] = CuratorFact("Valheim", "pc_agent")
            facts["game_theme"] = CuratorFact("norse_survival", "game_context")
            return None

    class Automation:
        house_state = "home"
        current_mode = "gaming"

        def is_dnd_active(self):
            return False

    class Mapper:
        mapping = {"gaming": []}

    state = SimpleNamespace(
        automation=Automation(),
        weather_service=None,
        music_mapper=Mapper(),
        music_bandit=None,
    )
    builder = MusicCuratorContextBuilder(state, adapters=[GamingAdapter()])
    curator = MusicCurator(
        context_builder=builder,
        intent_provider=FakeIntentProvider(),
        catalog=FakeCatalog([_candidate("Verified")]),
    )

    assert curator.supported_modes == ("gaming",)
    assert curator.supports_mode("gaming") is True
    context = await builder.build("gaming")
    assert context.facts["game_title"].value == "Valheim"
    assert context.facts["game_title"].source == "pc_agent"
    result = await curator.curate(context)
    assert result.status == "shadow_ready"


@pytest.mark.asyncio
async def test_taste_snapshot_ranks_proven_above_rejected_without_double_bandit():
    now = datetime.now(timezone.utc)
    events = [
        SimpleNamespace(
            favorite_title="Proven Favorite", event_type="play", triggered_by="manual",
            mode_at_time="social", timestamp=now,
        ),
        SimpleNamespace(
            favorite_title="Proven Favorite", event_type="play", triggered_by="manual",
            mode_at_time="social", timestamp=now,
        ),
        SimpleNamespace(
            favorite_title="Rejected Favorite", event_type="skip", triggered_by="manual",
            mode_at_time="social", timestamp=now,
        ),
        SimpleNamespace(
            favorite_title="Rejected Favorite", event_type="skip", triggered_by="manual",
            mode_at_time="social", timestamp=now,
        ),
    ]
    snapshot = build_music_taste_snapshot(
        artists=[], recommendations=[], playback_events=events, generated_at=now,
    )
    provider = FakeIntentProvider(MusicIntent.from_mapping({
        "familiarity": 0.8, "novelty": 0.2, "search_concepts": [],
    }))
    taste = FakeTasteProvider(snapshot)
    curator = MusicCurator(
        context_builder=FakeContextBuilder(),
        intent_provider=provider,
        catalog=FakeCatalog([
            _candidate("Rejected Favorite", match=0.5),
            _candidate("Proven Favorite", match=0.5),
        ]),
        bandit=FakeBandit(),
        taste_provider=taste,
    )

    result = await curator.curate(_context("social"))

    assert [item.candidate.title for item in result.suggestions] == [
        "Proven Favorite", "Rejected Favorite",
    ]
    assert result.suggestions[0].taste_classification == "proven"
    assert result.suggestions[1].taste_classification == "rejected"
    assert result.suggestions[0].bandit_mean is None
    assert taste.calls == 1
    assert curator._bandit.calls == 0


@pytest.mark.asyncio
async def test_fresh_preseason_and_elimination_are_context_not_curator_suppression():
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)

    class Automation:
        house_state = "home"
        current_mode = "general"

        def is_dnd_active(self):
            return False

    class GameDay:
        def current_state(self):
            return None

        async def get_upcoming_schedule(self, limit=1):
            return []

    class Mapper:
        mapping = {"pregameday": []}

    values = {
        "gameday_playoff_state": {
            "is_eliminated": True,
            "is_preseason": True,
            "season_week": 0,
            "refreshed_at": "2026-09-15T10:00:00+00:00",
        },
        "gameday_team_form": {
            "refreshed_at": "2026-09-15T10:00:00+00:00",
        },
    }

    async def load_setting(key):
        return values.get(key)

    state = SimpleNamespace(
        automation=Automation(), gameday=GameDay(), music_mapper=Mapper(),
        music_bandit=None, weather_service=None,
    )
    builder = MusicCuratorContextBuilder(
        state, setting_loader=load_setting, now_fn=lambda: now,
    )

    context = await builder.build("gameday")

    assert context.suppression_reason is None
    assert context.facts["is_eliminated"].value is True
    assert context.facts["is_eliminated"].usable is True
    assert context.facts["is_preseason"].value is True
    assert context.facts["is_preseason"].usable is True
