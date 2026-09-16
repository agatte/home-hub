from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services.music_discovery import MusicDiscoveryService
from backend.services.music_taste import (
    CandidateTasteMatch,
    build_music_taste_snapshot,
)
from backend.services.recommendation_service import RecommendationService

NOW = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)


def _track(artist: str, title: str, provider_id: str) -> dict:
    return {
        "provider": "itunes_search",
        "provider_id": provider_id,
        "artist_name": artist,
        "track_name": title,
        "album_name": "Album",
        "preview_url": f"https://audio.example/{provider_id}.m4a",
        "artwork_url": None,
        "external_url": f"https://music.example/{provider_id}",
    }


def _artist_candidate(
    artist: str,
    *,
    seed: str = "Seed Artist",
    match: float = 0.8,
    tracks: list[dict] | None = None,
) -> dict:
    return {
        "artist_name": artist,
        "seed_artist": seed,
        "source_match": match,
        "source": "lastfm_similar+itunes_search",
        "tracks": tracks or [_track(artist, "New Song", f"{artist}-1")],
    }


class FakeSource:
    def __init__(self, candidates, *, enabled=True):
        self.candidates = candidates
        self._enabled = enabled
        self.calls = 0

    @property
    def enabled(self):
        return self._enabled

    async def discover_artist_candidates(self, mode, *, count=8, tracks_per_artist=3):
        self.calls += 1
        return list(self.candidates)[:count]


class FakeTasteProvider:
    def __init__(self, snapshot=None, *, fail=False):
        self._snapshot = snapshot
        self._fail = fail

    async def snapshot(self):
        if self._fail:
            raise RuntimeError("taste offline")
        return self._snapshot


def _snapshot(*, artists=None, recommendations=None, feedback=None):
    return build_music_taste_snapshot(
        artists=artists or [],
        recommendations=recommendations or [],
        playback_events=[],
        explicit_feedback=feedback or [],
        generated_at=NOW,
    )


def _artist(name, *, play_count=0, track_count=1):
    return SimpleNamespace(
        name=name,
        source="import",
        play_count=play_count,
        track_count=track_count,
        rating_avg=None,
        created_at=NOW,
    )


def _rec(artist, track, status, *, mode="gaming"):
    return SimpleNamespace(
        artist_name=artist,
        track_name=track,
        status=status,
        source_mode=mode,
        created_at=NOW,
    )


def _feedback(artist, action, *, mode="gaming"):
    return SimpleNamespace(
        artist_name=artist,
        action=action,
        target_kind="artist",
        target_track_name=None,
        provider="itunes_search",
        provider_id=f"{artist}-1",
        mode=mode,
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_familiar_artist_does_not_make_unseen_tracks_familiar():
    snapshot = _snapshot(artists=[_artist("Known Artist", track_count=5)])
    source = FakeSource([_artist_candidate(
        "Known Artist",
        tracks=[_track("Known Artist", "Never Heard One", "1"), _track("Known Artist", "Never Heard Two", "2")],
    )])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(snapshot))

    result = await service.preview("gaming")

    cluster = result.clusters[0]
    assert cluster.artist_classification == "familiar"
    assert cluster.novelty_ratio == 1.0
    assert {track.taste_classification for track in cluster.tracks} == {"exploratory"}


@pytest.mark.asyncio
async def test_dismissed_artist_is_suppressed_from_shadow_discovery():
    snapshot = _snapshot(recommendations=[_rec("No Thanks", "Song", "dismissed")])
    source = FakeSource([_artist_candidate("No Thanks")])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(snapshot))

    result = await service.preview("gaming")

    assert result.status == "no_candidates"
    assert result.clusters == ()


@pytest.mark.asyncio
async def test_multiple_liked_tracks_surface_artist_depth_and_explanation():
    snapshot = _snapshot(recommendations=[
        _rec("Promising Artist", "Song One", "liked"),
        _rec("Promising Artist", "Song Two", "liked"),
    ])
    source = FakeSource([_artist_candidate(
        "Promising Artist",
        tracks=[_track("Promising Artist", "Song Three", "3"), _track("Promising Artist", "Song Four", "4")],
    )])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(snapshot))

    result = await service.preview("gaming")

    cluster = result.clusters[0]
    assert cluster.artist_depth == 2
    assert cluster.artist_classification == "proven"
    assert any("artist depth 2" in reason for reason in cluster.reasons)
    assert all(track.taste_classification == "exploratory" for track in cluster.tracks)


class PolicySnapshot:
    def classify_candidate(self, candidate, *, mode=None):
        artist = candidate.metadata.get("artist_name")
        track = candidate.metadata.get("track_name")
        if artist == "Known Artist" and candidate.media_type == "artist":
            return CandidateTasteMatch("familiar", 1.0, 0.0, 0, 0.0, 0.0, ())
        if artist == "Known Artist" and track == "Known Track":
            return CandidateTasteMatch("familiar", 1.0, 0.0, 0, 0.0, 0.0, ())
        return CandidateTasteMatch("exploratory", 0.0, 0.0, 0, 0.0, 0.0, ())


@pytest.mark.asyncio
async def test_gentle_and_explore_policies_materially_change_ranking():
    source = FakeSource([
        _artist_candidate(
            "Known Artist", match=0.80,
            tracks=[_track("Known Artist", "Known Track", "k1"), _track("Known Artist", "New Track", "k2")],
        ),
        _artist_candidate(
            "New Artist", match=0.80,
            tracks=[_track("New Artist", "New One", "n1"), _track("New Artist", "New Two", "n2")],
        ),
    ])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(PolicySnapshot()))

    gentle = await service.preview("gaming", policy="gentle")
    explore = await service.preview("gaming", policy="explore")

    assert gentle.clusters[0].artist_name == "Known Artist"
    assert explore.clusters[0].artist_name == "New Artist"


@pytest.mark.asyncio
async def test_taste_failure_degrades_to_source_ranked_shadow_result():
    source = FakeSource([_artist_candidate("New Artist", match=0.9)])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(fail=True))

    result = await service.preview("gaming")

    assert result.status == "shadow_ready"
    assert result.taste_available is False
    assert "taste snapshot unavailable" in result.note
    assert result.clusters[0].artist_name == "New Artist"


@pytest.mark.asyncio
async def test_disabled_source_fails_quietly_without_calling_source():
    source = FakeSource([], enabled=False)
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(None))

    result = await service.preview("gaming")

    assert result.status == "source_unavailable"
    assert result.clusters == ()
    assert source.calls == 0


@pytest.mark.asyncio
async def test_source_cache_avoids_external_repeat_but_reapplies_fresh_taste_feedback():
    source = FakeSource([_artist_candidate("Maybe Artist", match=0.9)])
    first_snapshot = _snapshot()
    second_snapshot = _snapshot(
        recommendations=[_rec("Maybe Artist", "Song", "dismissed")]
    )

    class RotatingTasteProvider:
        def __init__(self):
            self.calls = 0
        async def snapshot(self):
            self.calls += 1
            return first_snapshot if self.calls == 1 else second_snapshot

    taste = RotatingTasteProvider()
    service = MusicDiscoveryService(source=source, taste_provider=taste)

    first = await service.preview("gaming")
    second = await service.preview("gaming")

    assert first.status == "shadow_ready"
    assert first.source_cache_hit is False
    assert second.status == "no_candidates"
    assert second.source_cache_hit is True
    assert source.calls == 1
    assert taste.calls == 2


@pytest.mark.asyncio
async def test_recommendation_service_discovery_is_non_persisting_and_multi_track(monkeypatch):
    service = RecommendationService(lastfm_api_key="test-key")
    profile = SimpleNamespace(top_artists=[{"name": "Owned Artist"}])

    async def load_profile():
        return profile

    similar_persist_flags = []

    async def similar(seed, *, persist_cache=True):
        similar_persist_flags.append(persist_cache)
        return [
            {"name": "Owned Artist", "match": 0.99},
            {"name": "New Artist", "match": 0.88},
        ]

    async def tracks(artist, *, limit=3):
        assert artist == "New Artist"
        return [_track(artist, "One", "1"), _track(artist, "Two", "2")][:limit]

    monkeypatch.setattr(service, "_load_profile", load_profile)
    monkeypatch.setattr(service, "_get_seed_artists", lambda profile, mode: ["Seed Artist"])
    monkeypatch.setattr(service, "_get_similar_artists", similar)
    monkeypatch.setattr(service, "_search_itunes_tracks", tracks)
    try:
        result = await service.discover_artist_candidates("gaming", count=5, tracks_per_artist=2)
    finally:
        await service.close()

    assert [item["artist_name"] for item in result] == ["New Artist"]
    assert [track["track_name"] for track in result[0]["tracks"]] == ["One", "Two"]
    assert result[0]["source"] == "lastfm_similar+itunes_search"
    assert similar_persist_flags == [False]


@pytest.mark.asyncio
async def test_itunes_discovery_verifies_exact_artist_and_dedupes(monkeypatch):
    service = RecommendationService(lastfm_api_key="test-key")

    class Response:
        status_code = 200
        def json(self):
            return {"results": [
                {"artistName": "Wanted Artist", "trackName": "Good One", "trackId": 1, "collectionName": "A"},
                {"artistName": "Other Artist", "trackName": "Wrong", "trackId": 2},
                {"artistName": "Wanted Artist", "trackName": "Good One", "trackId": 1, "collectionName": "A"},
                {"artistName": "Wanted Artist", "trackName": "Good Two", "trackId": 3, "collectionName": "B"},
            ]}

    class Http:
        async def get(self, *args, **kwargs):
            return Response()
        async def aclose(self):
            return None

    async def no_sleep(_):
        return None

    service._http = Http()
    monkeypatch.setattr("backend.services.recommendation_service.asyncio.sleep", no_sleep)
    try:
        tracks = await service._search_itunes_tracks("Wanted Artist", limit=3)
    finally:
        await service.close()

    assert [track["provider_id"] for track in tracks] == ["1", "3"]
    assert all(track["artist_name"] == "Wanted Artist" for track in tracks)


@pytest.mark.asyncio
async def test_explicit_feedback_suppresses_rejected_artist_and_boosts_fit_artist():
    snapshot = _snapshot(feedback=[
        _feedback("Best Fit", "fits_me"),
        _feedback("No Fit", "not_for_me"),
    ])
    source = FakeSource([
        _artist_candidate("Neutral", match=0.80),
        _artist_candidate("Best Fit", match=0.80),
        _artist_candidate("No Fit", match=0.95),
    ])
    service = MusicDiscoveryService(source=source, taste_provider=FakeTasteProvider(snapshot))

    result = await service.preview("gaming", policy="gentle")

    names = [cluster.artist_name for cluster in result.clusters]
    assert "No Fit" not in names
    assert names[0] == "Best Fit"
    assert any(
        "explicit_feedback:fits_me" in source
        for source in result.clusters[0].tracks[0].taste_sources
    )
    assert result.clusters[0].tracks[0].taste_classification == "exploratory"
    assert result.clusters[0].artist_preference > 0.7
    assert "explicit feedback: Fits me" in result.clusters[0].reasons
