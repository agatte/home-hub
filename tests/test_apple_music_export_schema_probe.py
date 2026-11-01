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


def test_utf8_split_at_sample_end_after_complete_valid_header(tmp_path):
    header = ("\ufeff" + ",".join(DAILY) + "\r\n").encode("utf-8")
    row = b"A - C,20260101,1,1000\r\n"
    blob = bytearray(header)
    while len(blob) + len(row) < 32738:
        blob.extend(row)
    remaining = 32767 - len(blob) - 4
    assert 0 <= remaining < 8190
    blob.extend(b"B - " + b"x" * remaining + b"\xc3\xa9,20260101,1,1000\r\n")
    assert blob[32767] == 0xC3 and blob[32768] == 0xA9
    path = tmp_path / "synthetic.csv"
    path.write_bytes(bytes(blob))
    assert inspect_header(path)["classification"] == "daily_tracks"


def test_oversized_header_column_count_is_rejected_without_echo(tmp_path):
    path = tmp_path / "columns.csv"
    path.write_bytes(b"PRIVATE," + b"," * 12000 + b"\n")
    with pytest.raises(HeaderRejected) as error:
        inspect_header(path)
    assert "PRIVATE" not in str(error.value)


def test_quoted_newline_does_not_make_truncated_header_complete(tmp_path):
    # A newline inside a quoted header field cannot establish that the
    # *logical* header ends within the 32 KiB sample.
    prefix = (b'\xef\xbb\xbf"private\nfield",' +
              ",".join(DAILY).encode("ascii") + b",")
    filler = bytearray(prefix)
    while len(filler) + 6001 < 32000:
        filler.extend(b"Q" * 6000 + b",")
    remaining = 32767 - len(filler)
    assert 0 < remaining <= 8192
    filler.extend(b"R" * remaining + b"\xc3")
    assert len(filler) == 32768
    # Malformed byte outside sample must not be ignored as data, because
    # the sampled first logical header never ended.
    path = tmp_path / "partial-private-header.csv"
    path.write_bytes(bytes(filler) + b"\xff,tail\r\n")
    with pytest.raises(HeaderRejected) as error:
        inspect_header(path)
    assert "private" not in str(error.value).lower()


def test_complete_multiline_header_accepts_split_utf8_data_row(tmp_path):
    header = (b'\xef\xbb\xbf"private\nfield",' +
              ",".join(DAILY).encode("ascii") + b"\r\n")
    filler = bytearray(header)
    row = b"A - C,20260101,1,1000\r\n"
    while len(filler) + len(row) < 32738:
        filler.extend(row)
    remaining = 32767 - len(filler) - 4
    assert 0 <= remaining < 8192
    filler.extend(b"B - " + b"x" * remaining + b"\xc3\xa9,20260101,1,1000\r\n")
    assert filler[32767] == 0xC3
    path = tmp_path / "valid-multiline-header.csv"
    path.write_bytes(bytes(filler))
    assert inspect_header(path)["classification"] == "daily_tracks"
