from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.services.music_taste import build_music_taste_snapshot
from backend.services.playlist_catalog import VerifiedMusicCandidate

NOW = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)


def _artist(name, *, plays=0, tracks=1, rating=None):
    return SimpleNamespace(
        name=name, source="import", play_count=plays, track_count=tracks,
        rating_avg=rating, created_at=NOW,
    )


def _rec(artist, track, status, *, mode="general"):
    return SimpleNamespace(
        artist_name=artist, track_name=track, status=status,
        source_mode=mode, created_at=NOW,
    )


def _event(title, event_type, *, triggered_by="manual", mode="social"):
    return SimpleNamespace(
        favorite_title=title, event_type=event_type, triggered_by=triggered_by,
        mode_at_time=mode, timestamp=NOW,
    )


def _candidate(media_type, title, *, artist=None, track=None):
    metadata = {}
    if artist:
        metadata["artist_name"] = artist
    if track:
        metadata["track_name"] = track
    return VerifiedMusicCandidate(
        provider="test", provider_id=title.casefold().replace(" ", "-"),
        media_type=media_type, title=title, uri="test://real", source="test",
        metadata=metadata,
    )


def _snapshot(*, artists=None, recommendations=None, events=None, bandit=None):
    return build_music_taste_snapshot(
        artists=artists or [], recommendations=recommendations or [],
        playback_events=events or [], bandit_status=bandit, generated_at=NOW,
    )


def test_empty_snapshot_classifies_unknown_candidate_as_exploratory():
    snapshot = _snapshot()
    match = snapshot.classify_candidate(_candidate("track", "Unknown Song"))
    assert match.classification == "exploratory"
    assert match.familiarity == 0.0
    assert snapshot.summary()["entity_counts"] == {
        "artists": 0, "tracks": 0, "favorites": 0,
    }


def test_familiar_artist_does_not_make_unknown_track_familiar():
    snapshot = _snapshot(artists=[_artist("Known Artist", plays=40, tracks=8, rating=4.5)])
    match = snapshot.classify_candidate(
        _candidate("track", "Brand New Song", artist="Known Artist", track="Brand New Song")
    )
    assert match.classification == "exploratory"
    assert match.familiarity == 0.0
    assert match.artist_depth == 8
    assert match.preference > 0
    assert "library_import" in match.sources


def test_multiple_liked_tracks_build_artist_depth_and_positive_affinity():
    snapshot = _snapshot(recommendations=[
        _rec("Promising Artist", "Song One", "liked", mode="gaming"),
        _rec("Promising Artist", "Song Two", "liked", mode="gaming"),
    ])
    artist = snapshot.artists["promising artist"]
    assert artist.depth == 2
    assert artist.preference > 0.7
    match = snapshot.classify_candidate(
        _candidate("artist", "Promising Artist", artist="Promising Artist"), mode="gaming"
    )
    assert match.classification == "proven"
    assert match.artist_depth == 2


def test_repeated_manual_favorite_plays_become_proven():
    snapshot = _snapshot(events=[
        _event("Known Favorite", "play"),
        _event("Known Favorite", "play"),
        _event("Known Favorite", "play"),
    ])
    match = snapshot.classify_candidate(_candidate("favorite", "Known Favorite"), mode="social")
    assert match.classification == "proven"
    assert match.familiarity == 1.0
    assert match.positive_weight == 4.5


def test_repeated_skips_reject_favorite_instead_of_calling_it_proven():
    snapshot = _snapshot(events=[
        _event("Bad Fit", "skip"),
        _event("Bad Fit", "skip"),
        _event("Bad Fit", "skip"),
    ])
    match = snapshot.classify_candidate(_candidate("favorite", "Bad Fit"), mode="social")
    assert match.classification == "rejected"
    assert match.preference < -0.5
    assert match.negative_weight == 4.5


def test_conflicting_explicit_artist_feedback_stays_familiar_not_proven():
    snapshot = _snapshot(recommendations=[
        _rec("Mixed Artist", "Track A", "liked"),
        _rec("Mixed Artist", "Track B", "dismissed"),
    ])
    match = snapshot.classify_candidate(
        _candidate("artist", "Mixed Artist", artist="Mixed Artist")
    )
    assert match.classification == "familiar"
    assert abs(match.preference) < 0.01
    assert match.positive_weight == 3.0
    assert match.negative_weight == 3.0


def test_bandit_context_is_evidence_without_replacing_raw_history():
    bandit = {
        "top_arms": {
            "gameday": {
                "clear": [{"title": "It's Lit!", "mean": 0.9}],
                "any": [{"title": "It's Lit!", "mean": 0.7}],
            }
        }
    }
    snapshot = _snapshot(bandit=bandit)
    evidence = snapshot.favorites["it's lit!"]
    assert evidence.preference == 0.0
    assert evidence.contexts["gameday"].bandit_mean == 0.8
    assert evidence.contexts["gameday"].preference == 0.6
    assert "music_bandit" in evidence.sources


def test_same_track_title_for_different_artists_keeps_separate_evidence():
    snapshot = _snapshot(recommendations=[
        _rec("Artist One", "Home", "liked"),
        _rec("Artist Two", "Home", "dismissed"),
    ])
    liked = snapshot.classify_candidate(
        _candidate("track", "Home", artist="Artist One", track="Home")
    )
    dismissed = snapshot.classify_candidate(
        _candidate("track", "Home", artist="Artist Two", track="Home")
    )
    assert liked.classification == "proven"
    assert liked.preference > 0
    assert dismissed.classification == "rejected"
    assert dismissed.preference < 0
