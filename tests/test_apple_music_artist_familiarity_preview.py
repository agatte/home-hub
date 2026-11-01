"""Purely invented Daily Tracks labels: no user data or real filesystem."""
from dataclasses import replace
from datetime import date, datetime

import pytest

from backend.services import apple_music_artist_familiarity_preview as artist

DAY = date(2026, 10, 1)


def row(**updates):
    return replace(artist.DailyArtistObservation(
        "Imaginary Artist - Invented Song", DAY, 6, 600_000,
    ), **updates)


def counts(*rows):
    return artist.preview_artist_label_days(rows)["counts"]


def test_single_day_is_never_six_independent_sessions():
    report = artist.preview_artist_label_days([row()])
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["artist_label_day_histogram"]["1_day"] == 1
    assert "Imaginary Artist" not in repr(report)
    assert "Invented Song" not in repr(report)
    assert "600000" not in repr(report)
    assert "2026-10-01" not in repr(report)


def test_exact_duplicate_replay_cannot_increase_familiarity():
    report = counts(row(), row(), row())
    assert report["input_daily_rows"] == 3
    assert report["candidate_artist_label_days"] == 1
    assert report["collapsed_repeated_or_multiple_song_rows"] == 2


def test_two_distinct_songs_same_artist_same_day_count_once():
    report = counts(row(), row(description="Imaginary Artist - Another Song"))
    assert report["candidate_artist_label_days"] == 1
    assert report["unambiguous_title_day_labels"] == 2


def test_distinct_days_same_label_bucket_by_days_not_plays():
    rows = [row(day=date(2026, 10, i), play_count=100) for i in range(1, 11)]
    report = artist.preview_artist_label_days(rows)
    assert report["counts"]["candidate_artist_label_days"] == 10
    assert report["artist_label_day_histogram"]["10_plus_days"] == 1
    assert report["artist_label_day_histogram"]["1_day"] == 0


def test_two_artist_labels_same_song_day_abstain_both():
    report = counts(
        row(), row(description="Different Artist - Invented Song"),
    )
    assert report["ambiguous_title_day_groups"] == 1
    assert report["abstain_ambiguous_or_conflicting_rows"] == 2
    assert report["candidate_artist_label_days"] == 0


def test_different_artists_with_distinct_songs_can_both_count():
    report = counts(
        row(), row(description="Different Artist - Different Song"),
    )
    assert report["candidate_artist_label_days"] == 2
    assert report["distinct_provisional_artist_labels"] == 2


def test_conflicting_metrics_for_exact_same_label_day_song_abstain():
    report = counts(
        row(), row(duration_ms=999_999),
    )
    assert report["conflicting_aggregate_title_day_groups"] == 1
    assert report["abstain_ambiguous_or_conflicting_rows"] == 2
    assert report["candidate_artist_label_days"] == 0


def test_ambiguity_only_affects_same_song_day_not_all_music():
    report = counts(
        row(), row(description="Different Artist - Invented Song"),
        row(description="Unrelated Artist - Separate Song"),
    )
    assert report["candidate_artist_label_days"] == 1
    assert report["abstain_ambiguous_or_conflicting_rows"] == 2


def test_artist_spelling_normalization_dedupes_case_unicode_and_space():
    report = counts(
        row(), row(description="  IMAGINARY   ARTIST - invented SONG  "),
    )
    assert report["candidate_artist_label_days"] == 1
    assert report["ambiguous_title_day_groups"] == 0


@pytest.mark.parametrize("description", [
    "", "No Separator", " - Song", "Artist - ", "Artist - Song - Remix",
    "Artist-Song", "a" * 2049,
])
def test_unparseable_or_ambiguous_grammar_is_never_guessed(description):
    report = counts(row(description=description))
    assert report["abstain_invalid_or_ambiguous_description_or_metrics"] == 1
    assert report["candidate_artist_label_days"] == 0


@pytest.mark.parametrize(("change"), [
    {"day": date(1999, 12, 31)},
    {"day": datetime(2026, 10, 1)},
    {"play_count": 0},
    {"play_count": -1},
    {"play_count": True},
    {"play_count": 100_001},
    {"play_count": 1.0},
    {"duration_ms": -1},
    {"duration_ms": 0},
    {"duration_ms": 7 * 24 * 60 * 60 * 1000 + 1},
    {"duration_ms": float("nan")},
    {"source": "sonos"},
])
def test_invalid_dates_counts_durations_or_sources_abstain(change):
    result = counts(row(**change))
    assert result["candidate_artist_label_days"] == 0
    assert result["abstain_invalid_or_ambiguous_description_or_metrics"] == 1


def test_non_observation_input_is_rejected_without_echo():
    report = artist.preview_artist_label_days(["PRIVATE_TITLE"])
    assert report["counts"]["abstain_invalid_row"] == 1
    assert "PRIVATE_TITLE" not in repr(report)


def test_input_limit_has_constant_error(monkeypatch):
    monkeypatch.setattr(artist, "MAX_ROWS", 1)
    with pytest.raises(artist.ArtistPreviewRejected, match="row limit") as err:
        artist.preview_artist_label_days([row(), row()])
    assert "Invented" not in str(err.value)


def test_reordering_does_not_change_count_or_classification():
    rows = [
        row(), row(description="Different Artist - Invented Song"),
        row(description="Unrelated Artist - Separate Song"),
        row(duration_ms=2_000_000),
    ]
    assert artist.preview_artist_label_days(rows) == artist.preview_artist_label_days(
        list(reversed(rows))
    )


def test_in_memory_only_shadow_output_has_no_ratings_or_per_artist_values():
    report = artist.preview_artist_label_days([row()])
    assert set(report) == {
        "format", "counts", "artist_label_day_histogram", "warnings",
    }
    assert all(isinstance(v, int) for v in report["counts"].values())
    assert set(report["artist_label_day_histogram"]) == {
        "1_day", "2_to_3_days", "4_to_9_days", "10_plus_days",
    }
    for key in ("weights", "rating", "preference", "artist_name", "identifiers"):
        assert key not in report["counts"]
        assert key not in report["artist_label_day_histogram"]


def test_real_aggregate_36214_matches_cannot_be_converted_to_days():
    # Title/date matches are PLAY_END events, not Daily Tracks artist-days.
    assert counts() == {
        "ambiguous_title_day_groups": 0,
        "conflicting_aggregate_title_day_groups": 0,
        "candidate_artist_label_days": 0,
        "collapsed_repeated_or_multiple_song_rows": 0,
        "distinct_provisional_artist_labels": 0,
        "input_daily_rows": 0,
        "unambiguous_title_day_labels": 0,
        "abstain_ambiguous_or_conflicting_rows": 0,
    }


def test_near_spelling_aliases_are_distinct_labels_not_auto_catalog_merged():
    # Distinct song titles avoid the same-song/day ambiguity rule.
    rows = [
        row(description="Madeup & Band - First Song"),
        row(description="Madeup and Band - Second Song"),
    ]
    report = artist.preview_artist_label_days(rows)
    assert report["counts"]["distinct_provisional_artist_labels"] == 2
    assert report["artist_label_day_histogram"]["1_day"] == 2
    assert "Madeup" not in repr(report)


def test_same_title_day_conflict_does_not_revoke_different_day():
    rows = [
        row(),
        row(description="Other Label - Invented Song"),
        row(day=date(2026, 10, 2)),
    ]
    report = artist.preview_artist_label_days(rows)
    assert report["counts"]["abstain_ambiguous_or_conflicting_rows"] == 2
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["artist_label_day_histogram"]["1_day"] == 1


def test_reimport_same_daily_track_data_changes_diagnostics_not_histogram():
    rows = [
        row(),
        row(day=date(2026, 10, 2)),
        row(day=date(2026, 10, 3), play_count=999),
    ]
    once = artist.preview_artist_label_days(rows)
    twice = artist.preview_artist_label_days(rows + rows)
    assert once["artist_label_day_histogram"] == twice["artist_label_day_histogram"]
    assert once["counts"]["candidate_artist_label_days"] == 3
    assert twice["counts"]["candidate_artist_label_days"] == 3
    assert twice["counts"]["input_daily_rows"] == 6
    assert twice["counts"]["collapsed_repeated_or_multiple_song_rows"] == 3


def test_apple_only_source_contract_rejects_sonos_even_with_same_content():
    apple_row = row()
    sonos_row = row(source="sonos")
    report = artist.preview_artist_label_days([apple_row, sonos_row])
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["counts"]["abstain_invalid_or_ambiguous_description_or_metrics"] == 1
    assert report["artist_label_day_histogram"]["1_day"] == 1
