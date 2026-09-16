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
