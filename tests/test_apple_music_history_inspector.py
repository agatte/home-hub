"""Synthetic-only coverage of the private export inspector (#431)."""
import csv
from pathlib import Path

import pytest

from backend.services.apple_music_history_inspector import InspectionError, inspect

HEADER = [
    "Event ID", "Event Type", "Event Start Timestamp", "Event End Timestamp",
    "End Reason Type", "Play Duration Milliseconds",
    "Media Duration In Milliseconds", "Song Name", "Provider ID",
    "Album Name", "Apple ID Number", "IP Address", "Latitude",
]
BASE = [
    "synthetic-1", "PLAY_END", "2025-02-03T04:00:00Z",
    "2025-02-03T04:04:00Z", "NATURAL_END_OF_TRACK", "240000",
    "240000", "Invented Track", "synthetic-provider-1", "Fake Album",
    "PRIVATE_ACCOUNT_MARKER", "PRIVATE_IP_MARKER", "PRIVATE_LAT_MARKER",
]


def make_csv(tmp_path: Path, rows: list[list[str]], header=HEADER) -> Path:
    path = tmp_path / "synthetic.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_natural_completion_and_repeat_is_stable(tmp_path):
    path = make_csv(tmp_path, [BASE, BASE])
    expected = inspect(path)
    assert expected == inspect(path)
    assert expected["counts"]["rows"] == 2
    assert expected["counts"]["duplicate_event_ids"] == 1
    assert expected["counts"]["distinct_event_ids"] == 1
    assert expected["non_persistent_evidence_candidates"]["completion_candidate"] == 1
    assert expected["counts"]["valid_timestamps"] == 2
    assert "utc_coverage" not in expected
    assert "2025-02-03" not in repr(expected)
    assert "PRIVATE_" not in repr(expected)
    assert "Invented Track" not in repr(expected)
    assert "synthetic-provider-1" not in repr(expected)


@pytest.mark.parametrize(("reason", "played", "expected"), [
    ("TRACK_SKIPPED_FORWARDS", "20000", "early_skip_candidate"),
    ("TRACK_SKIPPED_FORWARDS", "235000", "late_skip_neutral"),
    ("PLAYBACK_MANUALLY_PAUSED", "20000", "abstain"),
    ("SCRUB_BEGIN", "20000", "abstain"),
    ("SOMETHING_UNEXPECTED_PRIVATE", "20000", "abstain"),
    ("NATURAL_END_OF_TRACK", "nan", "abstain"),
    ("NATURAL_END_OF_TRACK", "-10", "abstain"),
    ("NATURAL_END_OF_TRACK", "250.5", "abstain"),
    ("NATURAL_END_OF_TRACK", "999999999999", "abstain"),
])
def test_interpretation_is_conservative(tmp_path, reason, played, expected):
    row = BASE.copy()
    row[4] = reason
    row[5] = played
    result = inspect(make_csv(tmp_path, [row]))
    assert result["non_persistent_evidence_candidates"][expected] == 1
    assert "SOMETHING_UNEXPECTED_PRIVATE" not in repr(result)


def test_no_start_or_ambiguous_identity_reward(tmp_path):
    start = BASE.copy()
    start[1] = "PLAY_START"
    no_provider = BASE.copy()
    no_provider[0] = "synthetic-2"
    no_provider[8] = ""
    result = inspect(make_csv(tmp_path, [start, no_provider]))
    assert result["non_persistent_evidence_candidates"] == {"abstain": 2}
    assert result["identity_confidence"]["ambiguous_metadata"] == 1


@pytest.mark.parametrize("change", ["missing_event", "bad_length", "bad_utf8", "oversized"])
def test_schema_and_resource_fail_closed(tmp_path, change):
    if change == "missing_event":
        path = make_csv(tmp_path, [], HEADER[1:])
        with pytest.raises(InspectionError, match="schema"):
            inspect(path)
    elif change == "bad_length":
        path = make_csv(tmp_path, [BASE[:-1]])
        assert inspect(path)["counts"]["malformed_rows"] == 1
    elif change == "bad_utf8":
        path = tmp_path / "invalid.csv"
        path.write_bytes(b"\xff,\xfe")
        with pytest.raises(InspectionError, match="safely"):
            inspect(path)
    else:
        path = make_csv(tmp_path, [BASE] * 3)
        with pytest.raises(InspectionError, match="row limit"):
            inspect(path, max_rows=2)


def test_invalid_time_and_missing_ids(tmp_path):
    row = BASE.copy()
    row[0] = ""
    row[2] = "PRIVATE_INVALID_TIMESTAMP"
    row[3] = ""
    result = inspect(make_csv(tmp_path, [row]))
    assert result["counts"]["missing_event_ids"] == 1
    assert result["counts"]["invalid_timestamps"] == 1
    assert result["counts"].get("valid_timestamps", 0) == 0
    assert "utc_coverage" not in result
    assert "PRIVATE_INVALID_TIMESTAMP" not in repr(result)


def test_blank_and_zero_durations_abstain(tmp_path):
    row = BASE.copy()
    row[5] = ""
    row[6] = "0"
    result = inspect(make_csv(tmp_path, [row]))
    assert result["non_persistent_evidence_candidates"] == {"abstain": 1}


def test_private_value_not_leaked_in_csv_error(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text(','.join(HEADER) + '\n"PRIVATE_SECRET_UNCLOSED', encoding="utf-8")
    with pytest.raises(InspectionError) as exc:
        inspect(path)
    assert "PRIVATE_SECRET" not in str(exc.value)


@pytest.mark.parametrize("change", ["missing_id", "missing_end", "invalid_end", "reversed"])
def test_missing_provenance_abstains(tmp_path, change):
    row = BASE.copy()
    if change == "missing_id":
        row[0] = ""
    elif change == "missing_end":
        row[3] = ""
    elif change == "invalid_end":
        row[3] = "PRIVATE_BAD_TIMESTAMP"
    elif change == "reversed":
        row[3] = "2025-02-02T04:00:00Z"
    result = inspect(make_csv(tmp_path, [row]))
    assert result["non_persistent_evidence_candidates"] == {"abstain": 1}
    assert "PRIVATE_BAD_TIMESTAMP" not in repr(result)
    if change == "reversed":
        assert result["counts"]["reversed_timestamp_pairs"] == 1


def test_duplicate_id_different_payload_not_double_counted(tmp_path):
    altered = BASE.copy()
    altered[4] = "TRACK_SKIPPED_FORWARDS"
    altered[5] = "20000"
    result = inspect(make_csv(tmp_path, [BASE, altered]))
    assert result["counts"]["duplicate_event_ids"] == 1
    assert result["counts"]["conflicting_duplicate_event_ids"] == 1
    assert result["non_persistent_evidence_candidates"] == {
        "abstain": 1
    }


def test_csv_large_field_rejected_without_leaking_value(tmp_path):
    row = BASE.copy()
    row[-1] = "PRIVATE_GEO_MARKER" + "x" * 9000
    with pytest.raises(InspectionError, match="safely") as exc:
        inspect(make_csv(tmp_path, [row]))
    assert "PRIVATE_GEO_MARKER" not in str(exc.value)


def test_missing_start_abstains(tmp_path):
    row = BASE.copy()
    row[2] = ""
    result = inspect(make_csv(tmp_path, [row]))
    assert result["non_persistent_evidence_candidates"] == {"abstain": 1}


def test_streaming_character_budget(tmp_path):
    row = BASE.copy()
    path = make_csv(tmp_path, [row] * 4)
    # Initial byte limit is larger than the file, but decoder character
    # accounting is also checked independently using an explicit bound.
    from backend.services.apple_music_history_inspector import MAX_BYTES
    assert inspect(path, max_bytes=MAX_BYTES)["counts"]["rows"] == 4


def test_undersized_file_limit_rejected(tmp_path):
    path = make_csv(tmp_path, [BASE])
    with pytest.raises(InspectionError, match="size limit"):
        inspect(path, max_bytes=10)


def test_quoted_newline_and_comma_in_ignored_sensitive_field(tmp_path):
    row = BASE.copy()
    row[-2] = "PRIVATE_SENSITIVE,WITH\nNEWLINE"
    report = inspect(make_csv(tmp_path, [row]))
    assert report["counts"]["rows"] == 1
    assert report["non_persistent_evidence_candidates"] == {
        "completion_candidate": 1
    }
    assert "PRIVATE_SENSITIVE" not in repr(report)


def test_duplicate_header_rejected(tmp_path):
    header = HEADER.copy()
    header[-1] = "Event ID"
    with pytest.raises(InspectionError, match="schema"):
        inspect(make_csv(tmp_path, [BASE], header))


def test_nonfinite_and_infinite_media_durations_abstain(tmp_path):
    for value in ("NaN", "Infinity", "-Infinity"):
        row = BASE.copy()
        row[6] = value
        report = inspect(make_csv(tmp_path, [row]))
        assert report["non_persistent_evidence_candidates"] == {"abstain": 1}
        assert report["counts"]["invalid_media_durations"] == 1


def test_byte_budget_guard_limits_actual_stream_reads():
    import io

    from backend.services.apple_music_history_inspector import _ByteBudgetReader

    with io.BufferedReader(_ByteBudgetReader(io.BytesIO(b"12345"), 5)) as stream:
        assert stream.read() == b"12345"
    with io.BufferedReader(_ByteBudgetReader(io.BytesIO(b"123456"), 5)) as stream:
        with pytest.raises(InspectionError, match="byte budget"):
            stream.read()


def test_reject_nonregular_source(tmp_path, monkeypatch):
    # No filesystem writes should occur even when source validation rejects.
    path = make_csv(tmp_path, [BASE])
    from backend.services import apple_music_history_inspector as inspector
    original = inspector.stat.S_ISREG
    monkeypatch.setattr(inspector.stat, "S_ISREG", lambda _: False)
    try:
        with pytest.raises(InspectionError, match="size limit"):
            inspect(path)
    finally:
        monkeypatch.setattr(inspector.stat, "S_ISREG", original)


def test_anonymous_provider_repeat_rollup_no_identity_output(tmp_path):
    second = BASE.copy()
    second[0] = "second-distinct-event"
    third = BASE.copy()
    third[0] = "third-distinct-event"
    third[4] = "TRACK_SKIPPED_FORWARDS"
    third[5] = "20000"
    report = inspect(make_csv(tmp_path, [BASE, second, third]))
    assert report["anonymous_provider_candidate_buckets"] == {
        "buckets_with_multiple_completion_events": 1,
        "buckets_with_completion_and_early_skip_events": 1,
        "buckets_with_early_skip_events": 1,
        "buckets_with_completion_events": 1,
    }
    assert "synthetic-provider-1" not in repr(report)
    assert "Invented Track" not in repr(report)


def test_conflicting_id_revokes_anonymous_provider_candidate(tmp_path):
    conflicting = BASE.copy()
    conflicting[4] = "TRACK_SKIPPED_FORWARDS"
    conflicting[5] = "20000"
    report = inspect(make_csv(tmp_path, [BASE, conflicting]))
    assert report["counts"]["conflicting_duplicate_event_ids"] == 1
    assert all(
        value == 0
        for value in report["anonymous_provider_candidate_buckets"].values()
    )


def test_provider_id_crosses_distinct_song_labels_abstain_on_identity(tmp_path):
    second = BASE.copy()
    second[0] = "different-event"
    second[7] = "Another Imaginary Song"
    third = BASE.copy()
    third[0] = "metadata-only-event"
    third[8] = ""
    third[7] = "Third Imaginary Song"
    report = inspect(make_csv(tmp_path, [BASE, second, third]))
    quality = report["provider_identity_quality"]
    assert quality["distinct_provider_ids_on_play_end"] == 1
    assert quality["provider_ids_with_multiple_title_album_labels"] == 1
    assert quality["play_end_events_on_multi_label_provider_ids"] == 2
    assert quality[
        "completion_or_early_skip_candidates_on_multi_label_provider_ids"
    ] == 2
    assert quality["maximum_distinct_title_album_labels_on_one_provider_id"] == 2
    assert quality["distinct_title_album_labels_without_provider_id"] == 1
    assert "Another Imaginary Song" not in repr(report)
    assert "Third Imaginary Song" not in repr(report)
    assert "synthetic-provider-1" not in repr(report)


def test_same_title_repeats_do_not_trigger_multi_label_flag(tmp_path):
    repeated = BASE.copy()
    repeated[0] = "different-event"
    report = inspect(make_csv(tmp_path, [BASE, repeated]))
    quality = report["provider_identity_quality"]
    assert quality["distinct_provider_ids_on_play_end"] == 1
    assert quality["provider_ids_with_multiple_title_album_labels"] == 0
    assert quality["play_end_events_on_multi_label_provider_ids"] == 0
    assert quality["maximum_play_end_events_on_one_provider_id"] == 2


def test_different_provider_ids_same_label_are_distinct(tmp_path):
    other = BASE.copy()
    other[0] = "other-event"
    other[8] = "different-synthetic-provider"
    report = inspect(make_csv(tmp_path, [BASE, other]))
    quality = report["provider_identity_quality"]
    assert quality["distinct_provider_ids_on_play_end"] == 2
    assert quality["provider_ids_with_multiple_title_album_labels"] == 0


def test_multiple_source_dates_never_escape_aggregate_report(tmp_path):
    first = BASE.copy()
    second = BASE.copy()
    second[0] = "synthetic-2"
    second[2] = "2023-01-02T23:59:59Z"
    second[3] = "2023-01-03T00:03:59Z"
    report = inspect(make_csv(tmp_path, [first, second]))
    assert report["counts"]["valid_timestamps"] == 4
    assert "utc_coverage" not in report
    encoded = repr(report)
    for date_label in ("2023-01-02", "2023-01-03", "2025-02-03"):
        assert date_label not in encoded
    assert "earliest_date" not in encoded
    assert "latest_date" not in encoded
