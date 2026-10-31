"""All names and artists here are synthetic. Never uses the Apple export."""
from backend.services.apple_music_history_identity_match import (
    summarize_artist_join_coverage,
)


def test_unique_daily_suffix_is_provisional_not_verified():
    result = summarize_artist_join_coverage(
        ["Orbit", "Orbit", "Moonrise"],
        ["Synthetic Artist - Orbit", "Second Artist - Moonrise"],
    )
    assert result["provisional_artist_event_rows"] == 3
    assert result["provisional_artist_title_labels"] == 2
    assert result["distinct_event_titles"] == 2
    assert "Synthetic" not in repr(result)


def test_same_title_different_artists_abstains():
    result = summarize_artist_join_coverage(
        ["Orbit", "Orbit"], ["Artist One - Orbit", "Artist Two - Orbit"]
    )
    assert result["ambiguous_artist_event_rows"] == 2
    assert result.get("provisional_artist_event_rows", 0) == 0


def test_multiple_possible_hyphen_splits_abstain():
    result = summarize_artist_join_coverage(
        ["C", "B - C"], ["A - B - C"],
    )
    assert result["ambiguous_artist_event_rows"] == 2
    assert result.get("provisional_artist_event_rows", 0) == 0


def test_missing_or_unsupported_artist_never_invented():
    result = summarize_artist_join_coverage(
        ["Orbit", "", "Different"],
        ["Orbit", "Synthetic Artist: Orbit", "Artist - Unrelated"],
    )
    assert result["blank_or_invalid_event_titles"] == 1
    assert result["unmatched_artist_event_rows"] == 2
    assert result.get("provisional_artist_event_rows", 0) == 0


def test_preserves_punctuation_and_normalizes_case_whitespace():
    result = summarize_artist_join_coverage(
        ["  Space  Walk!  "], [" Synthetic Artist - space walk! "],
    )
    assert result["provisional_artist_event_rows"] == 1


def test_no_metadata_or_title_escapes_aggregates():
    secret = "PRIVATE_SOURCE_TRACK_TITLE"
    report = summarize_artist_join_coverage(
        [secret], ["PRIVATE_SOURCE_ARTIST - " + secret],
    )
    assert report["provisional_artist_event_rows"] == 1
    assert secret not in repr(report)
    assert "PRIVATE_SOURCE_ARTIST" not in repr(report)


def test_input_order_stable_and_never_sorts_by_artist():
    first = summarize_artist_join_coverage(
        ["Orbit", "Moonrise"],
        ["A - Orbit", "B - Orbit", "C - Moonrise"],
    )
    other = summarize_artist_join_coverage(
        ["Moonrise", "Orbit"],
        ["C - Moonrise", "B - Orbit", "A - Orbit"],
    )
    assert first == other
    assert first["ambiguous_artist_event_rows"] == 1
    assert first["provisional_artist_event_rows"] == 1


def test_oversized_values_refuse_provisional_join():
    long_title = "X" * 3000
    result = summarize_artist_join_coverage(
        [long_title], ["Artist - " + long_title],
    )
    assert result["blank_or_invalid_event_titles"] == 1
    assert result.get("provisional_artist_event_rows", 0) == 0
