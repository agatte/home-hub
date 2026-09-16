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


def _feedback(artist, action, *, target_kind="artist", track=None, mode="gaming"):
    return SimpleNamespace(
        artist_name=artist,
        action=action,
        target_kind=target_kind,
        target_track_name=track,
        provider="itunes_search",
        provider_id=f"{artist}-{track or 'artist'}",
        mode=mode,
        created_at=NOW,
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


def _snapshot(*, artists=None, recommendations=None, events=None, feedback=None):
    return build_music_taste_snapshot(
        artists=artists or [], recommendations=recommendations or [],
        playback_events=events or [], explicit_feedback=feedback or [],
        generated_at=NOW,
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


def test_playback_history_is_canonical_and_bandit_posterior_is_not_reinjected():
    snapshot = _snapshot(events=[_event("Known Favorite", "play", mode="gameday")])
    evidence = snapshot.favorites["known favorite"]
    context = evidence.contexts["gameday"]
    assert evidence.sources == ("sonos_playback",)
    assert evidence.positive_weight == 1.5
    assert context.positive_weight == 1.5
    assert context.bandit_mean is None
    assert snapshot.summary()["evidence_policy"] == {
        "playback_source": "sonos_playback_events",
        "bandit_posterior_injected": False,
        "bandit_role": "music_mapper_selection_model",
    }


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


def test_explicit_artist_feedback_changes_affinity_without_inventing_familiarity():
    snapshot = _snapshot(feedback=[_feedback("Wardruna", "fits_me")])
    artist = snapshot.classify_candidate(
        _candidate("artist", "Wardruna", artist="Wardruna"), mode="gaming"
    )
    unseen_track = snapshot.classify_candidate(
        _candidate("track", "Helvegen", artist="Wardruna", track="Helvegen"),
        mode="gaming",
    )
    assert artist.classification == "exploratory"
    assert artist.familiarity == 0.0
    assert artist.preference > 0.7
    assert unseen_track.classification == "exploratory"
    assert unseen_track.familiarity == 0.0
    assert unseen_track.preference > 0.0
    assert any(source.startswith("explicit_feedback:fits_me") for source in artist.sources)


def test_interesting_is_weaker_than_fits_me_and_not_for_me_rejects_artist():
    interesting = _snapshot(feedback=[_feedback("Maybe", "interesting")])
    fits = _snapshot(feedback=[_feedback("Maybe", "fits_me")])
    rejected = _snapshot(feedback=[_feedback("Maybe", "not_for_me")])
    interesting_match = interesting.classify_candidate(
        _candidate("artist", "Maybe", artist="Maybe")
    )
    fits_match = fits.classify_candidate(_candidate("artist", "Maybe", artist="Maybe"))
    rejected_match = rejected.classify_candidate(
        _candidate("artist", "Maybe", artist="Maybe")
    )
    assert 0 < interesting_match.preference < fits_match.preference
    assert rejected_match.classification == "rejected"
    assert rejected_match.preference < -0.5


def test_contradictory_explicit_feedback_preserves_both_sides():
    snapshot = _snapshot(feedback=[
        _feedback("Mixed", "fits_me"),
        _feedback("Mixed", "not_for_me"),
    ])
    match = snapshot.classify_candidate(_candidate("artist", "Mixed", artist="Mixed"))
    assert match.classification == "exploratory"
    assert match.positive_weight == 3.0
    assert match.negative_weight == 3.0
    assert abs(match.preference) < 0.01


def test_track_feedback_is_identity_safe_and_does_not_mark_track_familiar():
    snapshot = _snapshot(feedback=[
        _feedback("Artist One", "fits_me", target_kind="track", track="Home"),
        _feedback("Artist Two", "not_for_me", target_kind="track", track="Home"),
    ])
    liked = snapshot.classify_candidate(
        _candidate("track", "Home", artist="Artist One", track="Home")
    )
    rejected = snapshot.classify_candidate(
        _candidate("track", "Home", artist="Artist Two", track="Home")
    )
    assert liked.classification == "exploratory"
    assert liked.familiarity == 0.0
    assert liked.preference > 0.6
    assert rejected.classification == "rejected"
