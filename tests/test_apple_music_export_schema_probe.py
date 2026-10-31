"""Synthetic header-only classification for local Apple music CSV exports."""
import csv

import pytest

from backend.services.apple_music_export_schema_probe import (
    HeaderRejected, classify_header, inspect_header,
)

DAILY = ["Track Description", "Date Played", "Play Count", "Play Duration Milliseconds"]
PLAY = ["Event Type", "Event End Timestamp", "Song Name"]
TRACK = ["Track Name", "Last Played Date", "Is User Initiated"]


def _file(tmp_path, header, rows=None):
    path = tmp_path / "private-selection.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows or [])
    return path


@pytest.mark.parametrize(("header", "classification"), [
    (DAILY, "daily_tracks"),
    (PLAY, "play_activity"),
    (TRACK, "track_play_history"),
    (["Personal", "Another Personal"], "unknown_or_unsupported"),
    (DAILY + ["Track Description"], "invalid_duplicate_column"),
])
def test_export_classification(tmp_path, header, classification):
    path = _file(tmp_path, header, [["PRIVATE_TRACK_NAME"] * len(header)])
    report = inspect_header(path)
    assert report["classification"] == classification
    assert "PRIVATE" not in repr(report)
    assert str(path) not in repr(report)


def test_diagnostics_are_allowlisted_counts_only(tmp_path):
    path = _file(tmp_path, ["Track Description", "Date Played", "Personal Field"])
    report = inspect_header(path)
    assert report["classification"] == "unknown_or_unsupported"
    assert report["daily_tracks_required_columns_present"] == 2
    assert report["daily_tracks_required_columns_total"] == 4
    assert "Personal Field" not in repr(report)


def test_unknown_and_duplicate_columns_never_echo(tmp_path):
    path = _file(tmp_path, ["PRIVATE_SECRET", "PRIVATE_SECRET"])
    report = inspect_header(path)
    assert report["has_duplicate_column_names"] is True
    assert "PRIVATE_SECRET" not in repr(report)


@pytest.mark.parametrize("input_bytes", [
    b"",
    b"\xff\xfePRIVATE_VALUE",
])
def test_malformed_or_oversized_file_rejected(tmp_path, input_bytes):
    path = tmp_path / "bad.csv"
    path.write_bytes(input_bytes)
    with pytest.raises(HeaderRejected) as error:
        inspect_header(path)
    assert "PRIVATE_VALUE" not in str(error.value)


def test_oversized_header_field_fails_closed(tmp_path):
    path = _file(tmp_path, ["X" * 9000, *DAILY])
    with pytest.raises(HeaderRejected):
        inspect_header(path)


def test_csv_header_quoted_comma_is_supported_without_leaks(tmp_path):
    path = _file(tmp_path, ["Extra, Field", *DAILY])
    report = inspect_header(path)
    assert report["classification"] == "daily_tracks"
    assert "Extra, Field" not in repr(report)


def test_header_direct_function_does_not_return_unknown_names():
    report = classify_header(["PRIVATE_NAME", "Track Name"])
    assert "PRIVATE_NAME" not in repr(report)
