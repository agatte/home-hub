"""Synthetic-only end-to-end tests for #431 cross-export audit."""
import csv

import pytest

from backend.services.apple_music_daily_join_audit import AuditRejected, analyze

DAILY = [
    "Track Description", "Date Played", "Play Count",
    "Play Duration Milliseconds", "Private Account", "IP Address",
]
PLAY = [
    "Event Type", "Event End Timestamp", "Song Name", "Private Device",
]


def _write(tmp_path, name, header, rows):
    path = tmp_path / name
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _play(tmp_path, rows):
    return _write(tmp_path, "play.csv", PLAY, rows)


def _daily(tmp_path, rows):
    return _write(tmp_path, "daily.csv", DAILY, rows)


def test_daily_only_schema_quality_aggregate(tmp_path):
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2026-01-01", "2", "400000", "secret", "IP"],
        ["Unparsed", "bad-date", "", "invalid", "secret2", "IP2"],
    ])
    report = analyze(daily)
    assert report["summary"]["daily_rows"] == 2
    assert report["summary"]["daily_rows_with_valid_date"] == 1
    assert report["summary"]["daily_rows_with_artist_song_separator"] == 1
    assert report["summary"]["daily_rows_invalid_play_count"] == 1
    assert "Artist A" not in repr(report)
    assert "secret" not in repr(report)
    assert "IP2" not in repr(report)


def test_same_day_and_adjacent_day_are_only_provisional(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-01T20:00:00Z", "Moonlight", "secret"],
        ["PLAY_END", "2026-01-02T00:30:00Z", "Moonlight", "secret"],
        ["PLAY_START", "2026-01-01T19:00:00Z", "Moonlight", "secret"],
    ])
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2026-01-01", "3", "500000", "secret", "IP"],
    ])
    report = analyze(daily, play)
    totals = report["summary"]
    assert totals["play_rows_scanned"] == 3
    assert totals["play_end_rows"] == 2
    assert totals["play_end_same_date_provisional"] == 1
    assert totals["play_end_adjacent_date_provisional"] == 1
    assert totals["provisional_results_are_not_verified_recordings"] == 1


def test_multiple_artists_abstain(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-01T20:00:00Z", "Moonlight", "secret"],
    ])
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2026-01-01", "1", "100000", "", ""],
        ["Artist B - Moonlight", "2026-01-01", "1", "100000", "", ""],
    ])
    report = analyze(daily, play)
    assert report["summary"]["play_end_ambiguous_artist"] == 1
    assert report["summary"].get("play_end_same_date_provisional", 0) == 0



def test_ambiguous_hyphen_split_never_pick_arbitrary_artist(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-01T20:00:00Z", "C", ""],
        ["PLAY_END", "2026-01-01T20:00:00Z", "B - C", ""],
    ])
    daily = _daily(tmp_path, [
        ["A - B - C", "2026-01-01", "1", "100000", "", ""],
    ])
    result = analyze(daily, play)["summary"]
    assert result["daily_rows_with_ambiguous_title_split"] == 1
    assert result["play_end_ambiguous_artist"] == 2


def test_title_only_overlap_without_near_date_does_not_claim_date_join(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-10-21T20:00:00Z", "Moonlight", ""],
    ])
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2020-01-01", "1", "100000", "", ""],
    ])
    result = analyze(daily, play)["summary"]
    assert result["play_end_title_only_no_near_date"] == 1
    assert result.get("play_end_same_date_provisional", 0) == 0


def test_same_title_invalid_timestamp_does_not_match(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "private-bad-timestamp", "Moonlight", ""],
    ])
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2026-01-01", "1", "100000", "", ""],
    ])
    result = analyze(daily, play)["summary"]
    assert result["play_end_invalid_end_date"] == 1
    assert result["play_end_undated_or_unmatched"] == 1
    assert "private-bad-timestamp" not in repr(result)


@pytest.mark.parametrize("fault", ["header", "duplicate", "row", "utf8"])
def test_fail_closed_without_leaking_csv_content(tmp_path, fault):
    rows = [["Artist - PrivateSong", "2026-01-01", "1", "1000", "", ""]]
    header = DAILY.copy()
    if fault == "header":
        header[0] = "Something Private"
    if fault == "duplicate":
        header[-1] = header[0]
    if fault == "row":
        rows[0] = rows[0][:2]
    path = _daily(tmp_path, rows) if fault not in {"header", "duplicate"} else (
        _write(tmp_path, "daily.csv", header, rows)
    )
    if fault == "utf8":
        path.write_bytes(b"\xff\xfePrivateSource")
    with pytest.raises(AuditRejected) as exc:
        analyze(path)
    assert "Private" not in str(exc.value)
    assert "Something Private" not in str(exc.value)


def test_equal_outputs_are_repeatable_and_aggregate_only(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-01T20:00:00Z", "PRIVATE_TITLE", ""],
    ])
    daily = _daily(tmp_path, [
        ["PRIVATE_ARTIST - PRIVATE_TITLE", "2026-01-01", "1", "1000", "", ""],
    ])
    expected = analyze(daily, play)
    assert expected == analyze(daily, play)
    assert "PRIVATE" not in repr(expected)


def test_single_suffix_on_multi_hyphen_description_still_abstains(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-01T20:00:00Z", "C", ""],
    ])
    daily = _daily(tmp_path, [
        ["A - B - C", "2026-01-01", "1", "100000", "", ""],
    ])
    counts = analyze(daily, play)["summary"]
    assert counts["daily_rows_with_ambiguous_title_split"] == 1
    assert counts["play_end_ambiguous_artist"] == 1
    assert counts.get("play_end_same_date_provisional", 0) == 0


def test_utc_normalization_before_day_join(tmp_path):
    play = _play(tmp_path, [
        ["PLAY_END", "2026-01-02T00:30:00+05:00", "Moonlight", ""],
    ])
    daily = _daily(tmp_path, [
        ["Artist A - Moonlight", "2026-01-01", "1", "100000", "", ""],
    ])
    counts = analyze(daily, play)["summary"]
    assert counts["play_end_same_date_provisional"] == 1


def test_extreme_comma_row_rejected_without_early_csv_allocation(tmp_path):
    path = _daily(tmp_path, [])
    with path.open("a", encoding="utf-8") as writer:
        writer.write("PRIVATE_EXCESSIVE_CELLS," + "," * 200_000 + "\n")
    with pytest.raises(AuditRejected) as error:
        analyze(path)
    assert "PRIVATE" not in str(error.value)


def test_csv_quoted_comma_in_private_unused_column_still_allowed(tmp_path):
    rows = [["Artist - Moonlight", "2026-01-01", "1", "1000",
             "secret, quoted", "private"]]
    result = analyze(_daily(tmp_path, rows))
    assert result["summary"]["daily_rows"] == 1
    assert "secret" not in repr(result)
