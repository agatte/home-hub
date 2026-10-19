from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.music_discovery import MusicDiscoveryService
from backend.services.music_semantics import (
    DeterministicSemanticIntentResolver,
    LastFmSemanticAnalyzer,
    SemanticMusicMatch,
)
from backend.services.recommendation_service import RecommendationService


class EmptyTasteProvider:
    async def snapshot(self):
        return None


class FakeDiscoverySource:
    enabled = True

    def __init__(self, candidates):
        self.candidates = candidates

    async def discover_artist_candidates(self, mode, *, count=8, tracks_per_artist=3):
        return list(self.candidates)[:count]


def _candidate(artist: str, match: float = 0.8) -> dict:
    return {
        "artist_name": artist,
        "seed_artist": "Seed",
        "source_match": match,
        "source": "lastfm_similar+itunes_search",
        "tracks": [{
            "provider": "itunes_search",
            "provider_id": f"{artist}-1",
            "artist_name": artist,
            "track_name": "Representative Track",
            "album_name": "Album",
            "preview_url": None,
            "artwork_url": None,
            "external_url": None,
        }],
    }


class FakeSemanticAnalyzer:
    enabled = True

    def __init__(self, scores=None, *, fail=False):
        self.scores = scores or {}
        self.fail = fail

    async def analyze(self, *, artist_name, track_name, intent):
        if self.fail:
            raise RuntimeError("semantic provider offline")
        score = self.scores.get(artist_name, 0.0)
        return SemanticMusicMatch(
            available=True,
            score=score,
            source="fake_semantics",
            matched_concepts=(intent.concepts[0][0],) if score else (),
            tags=("test-tag",),
            provenance=("fake",),
        )


def test_resolver_supports_valheim_and_freeform_mood_text():
    resolver = DeterministicSemanticIntentResolver()

    valheim = resolver.resolve(mode="gaming", request="Valheim")
    assert valheim.key == "valheim"
    assert {name for name, _ in valheim.concepts} >= {"norse", "viking", "folk", "epic"}

    energetic = resolver.resolve(mode="social", request="I'm feeling energetic")
    assert energetic.key == "energetic"
    assert {name for name, _ in energetic.concepts} >= {"energetic", "upbeat", "powerful"}

    viking = resolver.resolve(mode="gaming", request="play Viking music")
    assert viking.key == "valheim"

    custom = resolver.resolve(mode="gaming", request="dark ritual drums")
    assert custom.key == "dark ritual drums"
    assert {name for name, _ in custom.concepts} == {"dark", "ritual", "drums"}


@pytest.mark.parametrize("phrase", [
    "calm", "calming", "soothing", "peaceful", "play calming music",
    "relaxing music for a quiet evening", "calming music while working",
])
def test_explicit_calm_phrases_resolve_to_relax_preset(phrase):
    resolved = DeterministicSemanticIntentResolver().resolve(
        mode="working", request=phrase,
    )
    assert resolved.key == "relax"
    assert {"calm", "chill", "ambient"} <= {name for name, _ in resolved.concepts}


def test_mixed_mood_phrase_does_not_get_silently_rewritten_to_relax():
    resolved = DeterministicSemanticIntentResolver().resolve(
        mode="social", request="calming but energetic",
    )
    assert resolved.key == "calming but energetic"
    assert "energetic" in {name for name, _ in resolved.concepts}
    for request in ("not calming", "don't want calming", "avoid calming music", "calming music while gaming"):
        assert DeterministicSemanticIntentResolver().resolve(
            mode="working", request=request,
        ).key != "relax"


@pytest.mark.asyncio
async def test_semantic_fit_reorders_otherwise_equal_candidates():
    source = FakeDiscoverySource([_candidate("Alpha"), _candidate("Zulu")])
    analyzer = FakeSemanticAnalyzer({"Alpha": 0.1, "Zulu": 1.0})
    service = MusicDiscoveryService(
        source=source,
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=analyzer,
    )

    result = await service.preview("gameday", intent="gameday")

    assert [cluster.artist_name for cluster in result.clusters] == ["Zulu", "Alpha"]
    assert result.clusters[0].semantic_score == 1.0
    assert result.clusters[0].semantic_intent == "gameday"
    assert any("semantic gameday match" in reason for reason in result.clusters[0].reasons)


@pytest.mark.asyncio
async def test_semantic_failure_preserves_existing_discovery_order_and_score():
    candidates = [_candidate("Beta", 0.82), _candidate("Alpha", 0.79)]
    baseline = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
    )
    failing = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=FakeSemanticAnalyzer(fail=True),
    )

    expected = await baseline.preview("gaming", policy="gentle")
    actual = await failing.preview("gaming", policy="gentle", intent="energetic")

    assert [(c.artist_name, c.score) for c in actual.clusters] == [
        (c.artist_name, c.score) for c in expected.clusters
    ]
    assert all(c.semantic_score is None for c in actual.clusters)


class MoodTagSource:
    enabled = True

    async def get_semantic_tags(self, artist_name, *, track_name=None, limit=20):
        if track_name:
            return []
        return (
            [{"name": "chillout"}, {"name": "ambient"}, {"name": "acoustic"}]
            if artist_name == "Gentle"
            else [{"name": "hard rock"}, {"name": "energetic"}]
        )


@pytest.mark.asyncio
async def test_explicit_calming_ranks_verified_mood_tags_above_rock_adjacency():
    source = FakeDiscoverySource([
        _candidate("Hard Rock", 0.98),
        _candidate("Gentle", 0.77),
    ])
    service = MusicDiscoveryService(
        source=source,
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(MoodTagSource()),
    )

    ordinary = await service.preview("working", policy="gentle")
    inferred = await service.preview("working", policy="gentle", intent="calming")
    calming = await service.preview(
        "working", policy="gentle", intent="calming", explicit_user_intent=True,
    )

    assert [cluster.artist_name for cluster in ordinary.clusters] == ["Hard Rock", "Gentle"]
    assert [cluster.artist_name for cluster in inferred.clusters] == ["Hard Rock", "Gentle"]
    assert [cluster.artist_name for cluster in calming.clusters] == ["Gentle"]
    assert calming.clusters[0].semantic_intent == "relax"
    assert set(calming.clusters[0].matched_semantics) & {"calm", "chill", "ambient", "acoustic"}
    assert all(
        cluster.tracks[0].playback_capability == "metadata_only"
        for cluster in calming.clusters
    )


@pytest.mark.asyncio
async def test_explicit_calming_preserves_baseline_when_semantic_provider_fails():
    candidates = [_candidate("Hard Rock", 0.98), _candidate("Gentle", 0.77)]
    baseline = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
    )
    outage = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=FakeSemanticAnalyzer(fail=True),
    )

    expected = await baseline.preview("working", policy="gentle")
    actual = await outage.preview(
        "working", policy="gentle", intent="calming", explicit_user_intent=True,
    )

    assert len(expected.clusters) == 2
    assert actual.clusters == ()
    assert actual.status == "no_candidates"


class EmptyMoodTagSource:
    enabled = True

    async def get_semantic_tags(self, artist_name, *, track_name=None, limit=20):
        return []


@pytest.mark.asyncio
async def test_explicit_calming_preserves_baseline_when_tags_have_no_evidence():
    candidates = [_candidate("Hard Rock", 0.98), _candidate("Gentle", 0.77)]
    baseline = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
    )
    empty_tags = MusicDiscoveryService(
        source=FakeDiscoverySource(candidates),
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(EmptyMoodTagSource()),
    )

    expected = await baseline.preview("working", policy="gentle")
    actual = await empty_tags.preview(
        "working", policy="gentle", intent="calming", explicit_user_intent=True,
    )

    assert len(expected.clusters) == 2
    assert actual.clusters == ()
    assert actual.status == "no_candidates"


class AcousticOnlySource:
    enabled = True

    async def get_semantic_tags(self, artist_name, *, track_name=None, limit=20):
        return [{"name": "acoustic"}] if not track_name else []


@pytest.mark.asyncio
async def test_explicit_calm_does_not_accept_acoustic_tag_alone():
    service = MusicDiscoveryService(
        source=FakeDiscoverySource([_candidate("Loud Acoustic Artist")]),
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(AcousticOnlySource()),
    )
    actual = await service.preview(
        "relax", intent="calming", explicit_user_intent=True,
    )
    assert actual.status == "no_candidates"
    assert actual.clusters == ()


class MoodAwareDiscoverySource(FakeDiscoverySource):
    def __init__(self):
        super().__init__([_candidate("Hard Rock", 0.99)])
        self.mood_calls = []
        self.mode_calls = []

    async def discover_artist_candidates(self, mode, *, count=8, tracks_per_artist=3):
        self.mode_calls.append(mode)
        return await super().discover_artist_candidates(
            mode, count=count, tracks_per_artist=tracks_per_artist,
        )

    async def discover_mood_candidates(self, mood, *, count=8, tracks_per_artist=3):
        self.mood_calls.append(mood)
        candidate = _candidate("Gentle", 0.70)
        candidate["source"] = "lastfm_mood_tag+itunes_search"
        candidate["seed_artist"] = "tag:chillout"
        return [candidate]


@pytest.mark.asyncio
async def test_explicit_calming_uses_mood_retrieval_and_separate_source_cache():
    source = MoodAwareDiscoverySource()
    service = MusicDiscoveryService(
        source=source,
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(MoodTagSource()),
    )

    calming = await service.preview(
        "gaming", intent="calming", explicit_user_intent=True,
    )
    second_calming = await service.preview(
        "gaming", intent="calming", explicit_user_intent=True,
    )
    implicit = await service.preview("gaming")

    assert [c.artist_name for c in calming.clusters] == ["Gentle"]
    assert calming.clusters[0].source == "lastfm_mood_tag+itunes_search"
    assert "mood-tag candidate: chillout" in calming.clusters[0].reasons[0]
    assert [c.artist_name for c in implicit.clusters] == ["Hard Rock"]
    assert source.mood_calls == ["relax"]
    assert source.mode_calls == ["gaming"]
    assert calming.source_cache_hit is False
    assert second_calming.source_cache_hit is True
    assert implicit.source_cache_hit is False
    assert calming.shadow and not calming.actuation_allowed


@pytest.mark.asyncio
async def test_mixed_calm_gaming_text_uses_normal_mode_retrieval():
    source = MoodAwareDiscoverySource()
    service = MusicDiscoveryService(
        source=source,
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(MoodTagSource()),
    )

    result = await service.preview(
        "gaming", intent="calming music while gaming", explicit_user_intent=True,
    )

    assert source.mood_calls == []
    assert source.mode_calls == ["gaming"]
    assert [c.artist_name for c in result.clusters] == ["Hard Rock"]


@pytest.mark.asyncio
async def test_explicit_calm_mood_source_timeout_abstains_without_rock_fallback(monkeypatch):
    import asyncio
    import backend.services.music_discovery as discovery_module

    class SlowMoodSource(MoodAwareDiscoverySource):
        async def discover_mood_candidates(self, mood, *, count=8, tracks_per_artist=3):
            await asyncio.sleep(0.05)
            return await super().discover_mood_candidates(
                mood, count=count, tracks_per_artist=tracks_per_artist,
            )

    monkeypatch.setattr(discovery_module, "EXPLICIT_RELAX_SOURCE_TIMEOUT_SECONDS", 0.001)
    source = SlowMoodSource()
    service = MusicDiscoveryService(
        source=source,
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=LastFmSemanticAnalyzer(MoodTagSource()),
    )

    result = await service.preview(
        "gaming", intent="calming", explicit_user_intent=True,
    )
    assert result.clusters == ()
    assert result.status == "no_candidates"
    assert source.mode_calls == []


@pytest.mark.asyncio
async def test_explicit_calm_slow_semantics_abstains(monkeypatch):
    import asyncio
    import backend.services.music_discovery as discovery_module

    class SlowSemantics:
        enabled = True

        async def analyze(self, *, artist_name, track_name, intent):
            await asyncio.sleep(0.05)
            return SemanticMusicMatch(
                available=True, score=0.99, matched_concepts=("calm",),
            )

    monkeypatch.setattr(discovery_module, "EXPLICIT_RELAX_SEMANTIC_TIMEOUT_SECONDS", 0.001)
    service = MusicDiscoveryService(
        source=FakeDiscoverySource([_candidate("Hard Rock")]),
        taste_provider=EmptyTasteProvider(),
        semantic_analyzer=SlowSemantics(),
    )
    result = await service.preview("gaming", intent="calming", explicit_user_intent=True)
    assert result.clusters == ()
    assert result.status == "no_candidates"


class FakeTagSource:
    enabled = True

    async def get_semantic_tags(self, artist_name, *, track_name=None, limit=20):
        if track_name:
            return [{"name": "folk", "count": 80}, {"name": "atmospheric", "count": 60}]
        return [{"name": "viking metal", "count": 100}, {"name": "epic", "count": 75}]


@pytest.mark.asyncio
async def test_lastfm_semantic_analyzer_matches_valheim_concepts():
    analyzer = LastFmSemanticAnalyzer(FakeTagSource())
    intent = DeterministicSemanticIntentResolver().resolve(mode="gaming", request="valheim")

    match = await analyzer.analyze(
        artist_name="Wardruna",
        track_name="Helvegen",
        intent=intent,
    )

    assert match.available is True
    assert match.score > 0.4
    assert {"norse", "viking", "folk", "epic"} & set(match.matched_concepts)
    assert set(match.provenance) == {"lastfm_artist_tags", "lastfm_track_tags"}


@pytest.mark.asyncio
async def test_recommendation_service_semantic_tags_are_cached(monkeypatch):
    service = RecommendationService(lastfm_api_key="test-key")

    class Response:
        status_code = 200
        def json(self):
            return {"toptags": {"tag": [
                {"name": "energetic", "count": "100"},
                {"name": "party", "count": "80"},
            ]}}

    class Http:
        def __init__(self):
            self.calls = []
        async def get(self, *args, **kwargs):
            self.calls.append(kwargs["params"])
            return Response()
        async def aclose(self):
            return None

    async def no_sleep(_):
        return None

    http = Http()
    service._http = http
    monkeypatch.setattr("backend.services.recommendation_service.asyncio.sleep", no_sleep)
    try:
        first = await service.get_semantic_tags("Example Artist")
        second = await service.get_semantic_tags("Example Artist")
        track = await service.get_semantic_tags(
            "Example Artist", track_name="Example Track"
        )
    finally:
        await service.close()

    assert first == second
    assert first[0] == {"name": "energetic", "count": 100}
    assert len(http.calls) == 2
    assert http.calls[0]["method"] == "artist.gettoptags"
    assert http.calls[1]["method"] == "track.gettoptags"
    assert http.calls[1]["track"] == "Example Track"
    assert track == first
