"""#431: synthetic CSV fixtures only; private Apple archives never accessed."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.services.apple_music_artist_local_audit import (
    analyze_daily_csv, _safe_int,
)
from backend.services.apple_music_daily_join_audit import AuditRejected

HEADERS = [
    "Account Identifier", "Play Count", "Track Description",
    "Date Played", "Play Duration Milliseconds", "Private Location",
]
SCRIPT = (
    Path(__file__).parents[1]
    / "backend" / "services" / "apple_music_artist_local_audit.py"
)
SECRET = "PRIVATE_NEVER_ECHO_THIS_VALUE"


def csv_file(tmp_path, rows, *, headers=None):
    path = tmp_path / "synthetic_daily.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers if headers is not None else HEADERS)
        writer.writerows(rows)
    return path


def sample(
    artist="Madeup Artist", title="Imaginary Song", date="2026-10-01",
    plays="15", duration="120000",
):
    return [
        SECRET, plays, f"{artist} - {title}", date, duration, SECRET,
    ]


def test_aggregate_only_does_not_return_sensitive_source_columns(tmp_path):
    path = csv_file(tmp_path, [
        sample(), sample(), sample(title="Another Imaginary Song"),
        sample(date="2026-10-02"),
    ])
    report = analyze_daily_csv(path)
    assert report["format"] == "apple_artist_label_day_shadow_v1"
    assert report["counts"]["input_daily_rows"] == 4
    assert report["counts"]["candidate_artist_label_days"] == 2
    assert report["counts"]["collapsed_repeated_or_multiple_song_rows"] == 2
    assert report["artist_label_day_histogram"]["2_to_3_days"] == 1
    encoded = json.dumps(report)
    for private in [SECRET, "Madeup Artist", "Imaginary Song", "2026-10-01", str(path)]:
        assert private not in encoded


def test_single_source_file_cli_succeeds_without_exporting_title(tmp_path):
    path = csv_file(tmp_path, [sample()])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    output = json.loads(result.stdout)
    assert output["counts"]["candidate_artist_label_days"] == 1
    assert SECRET not in result.stdout
    assert "Madeup Artist" not in result.stdout
    assert str(path) not in result.stdout


def test_undecodable_utf8_fails_closed_with_no_value_or_path(tmp_path):
    path = tmp_path / "sensitive-name.csv"
    path.write_bytes(b"\xff\xfePRIVATE_NEVER_ECHO_THIS_VALUE")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Artist audit rejected:" in result.stderr
    assert SECRET not in result.stderr and str(path) not in result.stderr


@pytest.mark.parametrize("headers", [
    HEADERS[:-2],
    HEADERS + ["Play Count"],
    ["Track Description", "Date Played", "Play Count"],
])
def test_missing_or_duplicate_csv_schema_rejected(tmp_path, headers):
    path = csv_file(tmp_path, [sample()], headers=headers)
    with pytest.raises(AuditRejected, match="Required CSV fields"):
        analyze_daily_csv(path)


@pytest.mark.parametrize("count", [
    "", "0", "-1", "1.5", "1e9", "+1", "X" * 20,
    "１２３", "٤٢", "NaN",
])
def test_nonpositive_invalid_or_non_ascii_counts_abstain(tmp_path, count):
    path = csv_file(tmp_path, [sample(plays=count)])
    report = analyze_daily_csv(path)
    assert report["counts"]["candidate_artist_label_days"] == 0
    assert report["counts"]["abstain_invalid_or_ambiguous_description_or_metrics"] == 1


@pytest.mark.parametrize("duration", [
    "", "0", "-2", "12.3", "Infinity", "1E9", SECRET,
])
def test_invalid_duration_abstains(tmp_path, duration):
    path = csv_file(tmp_path, [sample(duration=duration)])
    report = analyze_daily_csv(path)
    assert report["counts"]["candidate_artist_label_days"] == 0


def test_ambiguous_artist_labels_abstain_not_inflate_counts(tmp_path):
    path = csv_file(tmp_path, [
        sample(), sample(artist="Other", title="Imaginary Song"),
        sample(artist="Third", title="Unique Song"),
    ])
    result = analyze_daily_csv(path)["counts"]
    assert result["ambiguous_title_day_groups"] == 1
    assert result["candidate_artist_label_days"] == 1


def test_oversized_excluded_source_field_rejected_safely(tmp_path):
    path = csv_file(tmp_path, [sample()[:-1] + ["5" * 9000]])
    with pytest.raises(AuditRejected):
        analyze_daily_csv(path)


def test_unterminated_quoted_csv_fails_closed(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "Track Description,Date Played,Play Count,Play Duration Milliseconds\n"
        '"PRIVATE_UNTERMINATED,2026-10-01,5,120000',
        encoding="utf-8",
    )
    with pytest.raises(AuditRejected):
        analyze_daily_csv(path)


def test_safe_int_numerics_only():
    assert _safe_int("001") == 1
    assert _safe_int("0") == 0
    assert _safe_int("15000") == 15_000
    assert _safe_int("1.5") is None


def test_nested_zip_or_unextracted_source_never_scanned(tmp_path):
    path = tmp_path / "synthetic.zip"
    path.write_bytes(b"PK\x03\x04garbage and no CSV header")
    with pytest.raises(AuditRejected):
        analyze_daily_csv(path)
    assert not any(x.name.endswith(".csv") for x in tmp_path.iterdir())


def test_no_network_or_new_file_creation_in_code(tmp_path):
    path = csv_file(tmp_path, [sample()])
    before = {x.name for x in tmp_path.iterdir()}
    analyze_daily_csv(path)
    after = {x.name for x in tmp_path.iterdir()}
    assert before == after


@pytest.mark.parametrize("date_label", [
    "2026-10-01TAIL", "2026-10-01T12:00:00ZTAIL", "2026-10-01 ",
    "2026/10/01", "2026-1-1", "2026-02-30", "２０２６-１０-０１",
    "", "1999-12-31", "2026-10-01T25:00:00Z",
    "2026-10-01T12:61:00Z", "2026-10-01T12:00:00+24:00",
    "2026-10-01T12:00Z", "2026-10-01T12:00:00.0000000000Z",
])
def test_nonexact_or_invalid_day_labels_abstain(tmp_path, date_label):
    path = csv_file(tmp_path, [sample(date=date_label)])
    report = analyze_daily_csv(path)
    assert report["counts"]["candidate_artist_label_days"] == 0
    assert report["counts"]["abstain_invalid_or_ambiguous_description_or_metrics"] == 1


def test_csv_extension_is_required_even_if_content_looks_valid(tmp_path):
    original = csv_file(tmp_path, [sample()])
    wrong_extension = tmp_path / "private-archive.zip"
    wrong_extension.write_bytes(original.read_bytes())
    with pytest.raises(AuditRejected, match="Only CSV"):
        analyze_daily_csv(wrong_extension)
    assert analyze_daily_csv(original)["counts"]["candidate_artist_label_days"] == 1


def test_case_insensitive_csv_extension_supported(tmp_path):
    original = csv_file(tmp_path, [sample()])
    upper = tmp_path / "ANONYMOUS.CSV"
    upper.write_bytes(original.read_bytes())
    assert analyze_daily_csv(upper)["counts"]["candidate_artist_label_days"] == 1


def test_error_does_not_include_selected_filename_on_non_csv(tmp_path):
    path = tmp_path / (SECRET + ".zip")
    path.write_bytes(b"synthetic")
    with pytest.raises(AuditRejected) as exc:
        analyze_daily_csv(path)
    assert SECRET not in str(exc.value)
    assert str(path) not in str(exc.value)


def test_date_quality_counts_are_aggregate_only(tmp_path):
    path = csv_file(tmp_path, [
        sample(date="2026-10-01"),
        sample(date="2026-10-01PRIVATE"),
        sample(date="2026-02-30"),
        sample(date="2026-10-02"),
    ])
    report = analyze_daily_csv(path)
    assert report["counts"]["input_daily_rows"] == 4
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 2
    assert report["source_quality"]["date_label_shapes"]["unsupported"] == 2
    assert report["counts"]["candidate_artist_label_days"] == 2
    encoded = json.dumps(report)
    assert "PRIVATE" not in encoded
    assert "Madeup Artist" not in encoded


def test_valid_source_day_quality_is_zero(tmp_path):
    report = analyze_daily_csv(csv_file(tmp_path, [sample()]))
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 0
    assert report["source_quality"]["date_label_shapes"]["date_only"] == 1


@pytest.mark.parametrize(("date_label", "shape"), [
    ("2026-10-01", "date_only"),
    ("2026-10-01T12:30:45Z", "iso_timestamp_utc"),
    ("2026-10-01T12:30:45.123Z", "iso_timestamp_utc"),
    ("2026-10-01T12:30:45.123456789Z", "iso_timestamp_utc"),
    ("2026-10-01T12:30:45+05:30", "iso_timestamp_offset"),
    ("2026-10-01 12:30:45-04:00", "iso_timestamp_offset"),
    ("2026-10-01 12:30:45", "iso_timestamp_no_zone"),
    ("2026-10-01T12:30:45.123", "iso_timestamp_no_zone"),
])
def test_fully_validated_iso_date_label_shapes_count_once(tmp_path, date_label, shape):
    path = csv_file(tmp_path, [sample(date=date_label)])
    report = analyze_daily_csv(path)
    assert report["source_quality"]["date_label_shapes"][shape] == 1
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 0
    assert report["counts"]["candidate_artist_label_days"] == 1


def test_source_calendar_day_not_shifted_across_timezones(tmp_path):
    # Date Played is a Daily Tracks export label, not proven UTC play time.
    path = csv_file(tmp_path, [
        sample(date="2026-10-01T00:01:00+14:00"),
        sample(date="2026-10-01T23:59:00-12:00"),
    ])
    report = analyze_daily_csv(path)
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["source_quality"]["date_label_shapes"]["iso_timestamp_offset"] == 2
    assert "2026-10-01" not in json.dumps(report)


def test_supported_and_unsupported_source_date_shapes_are_anonymous(tmp_path):
    path = csv_file(tmp_path, [
        sample(date="2026-10-01T09:00:00Z"),
        sample(date="2026-10-02T09:00:00+01:00"),
        sample(date="2026-10-03T09:00:00"),
        sample(date="2026-10-04USER_PRIVATE"),
    ])
    report = analyze_daily_csv(path)
    shapes = report["source_quality"]["date_label_shapes"]
    assert shapes == {
        "date_only": 0,
        "compact_calendar_date": 0,
        "iso_week_date": 0,
        "compact_iso_week_date": 0,
        "iso_timestamp_utc": 1,
        "iso_timestamp_offset": 1,
        "iso_timestamp_no_zone": 1,
        "unsupported": 1,
    }
    assert report["counts"]["candidate_artist_label_days"] == 3
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 1
    output = json.dumps(report)
    for text in ["2026-10-04USER_PRIVATE", "Madeup Artist", SECRET]:
        assert text not in output


def test_common_unsupported_date_format_returns_only_masked_pattern(tmp_path):
    # Invented UTC word suffix: a previously unsupported but date-prefixed
    # shape. The program must NOT accept it as an artist-day.
    pattern = "2026-10-01 12:30:45 UTC"
    path = csv_file(tmp_path, [sample(date=pattern)] * 21)
    report = analyze_daily_csv(path)
    quality = report["source_quality"]
    assert quality["rows_with_invalid_or_unsupported_day"] == 21
    assert quality["common_unsupported_masked_shapes"] == [{
        "shape": "9999-99-99_99:99:99_AAA", "count": 21,
    }]
    assert quality["rare_or_unclassified_unsupported_rows"] == 0
    assert report["counts"]["candidate_artist_label_days"] == 0
    encoded = json.dumps(report)
    for raw in ("2026", "UTC", "Imaginary Song", SECRET):
        assert raw not in encoded


def test_rare_date_shape_is_suppressed(tmp_path):
    path = csv_file(tmp_path, [sample(date="2026-10-01T12:30:45 PRIVATE")])
    quality = analyze_daily_csv(path)["source_quality"]
    assert quality["common_unsupported_masked_shapes"] == []
    assert quality["rare_or_unclassified_unsupported_rows"] == 1


def test_pattern_limit_keeps_five_common_shapes_without_source_values(
    tmp_path, monkeypatch,
):
    from backend.services import apple_music_artist_local_audit as audit

    monkeypatch.setattr(audit, "MIN_MASK_GROUP", 2)
    rows = []
    for suffix in (
        " T", " TT", " TTT", " TTTT", " TTTTT", " TTTTTT",
    ):
        rows.extend([sample(date="2026-10-01" + suffix)] * 2)
    report = analyze_daily_csv(csv_file(tmp_path, rows))
    quality = report["source_quality"]
    assert len(quality["common_unsupported_masked_shapes"]) == 5
    assert quality["rare_or_unclassified_unsupported_rows"] == 2
    assert "2026-10-01" not in json.dumps(report)


def test_unrecognized_prefix_still_has_only_masked_common_shape(tmp_path):
    rows = [sample(date="PRIVATE_USER_NAME_SENSITIVE") for _ in range(21)]
    quality = analyze_daily_csv(csv_file(tmp_path, rows))["source_quality"]
    assert quality["common_unsupported_masked_shapes"] == [{
        "shape": "AAAAAAA?AAAA?AAAA?AAAAAAAAA", "count": 21,
    }]
    assert quality["rare_or_unclassified_unsupported_rows"] == 0
    assert "PRIVATE" not in json.dumps(quality)


def test_mask_never_contains_source_letters_or_digits():
    from backend.services.apple_music_artist_local_audit import (
        _masked_date_pattern,
    )

    assert _masked_date_pattern("2026-10-01 11:22:33 PST") == (
        "9999-99-99_99:99:99_AAA"
    )
    assert _masked_date_pattern("2026-10-01 private@name.com") == (
        "9999-99-99_AAAAAAA?AAAA.AAA"
    )
    assert _masked_date_pattern("private@name.com") == "AAAAAAA?AAAA.AAA"


@pytest.mark.parametrize(("date_label", "bucket"), [
    ("20261001", "compact_calendar_date"),
    ("2026-W40-4", "iso_week_date"),
    ("2026W404", "compact_iso_week_date"),
])
def test_exact_iso_8601_basic_and_week_dates_supported(tmp_path, date_label, bucket):
    report = analyze_daily_csv(csv_file(tmp_path, [sample(date=date_label)]))
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["source_quality"]["date_label_shapes"][bucket] == 1
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 0


@pytest.mark.parametrize("invalid_week", [
    "2026-W54-3", "2026-W44-8", "2026-W00-1",
    "20261342", "2026W548",
])
def test_invalid_basic_and_week_dates_remain_rejected(tmp_path, invalid_week):
    report = analyze_daily_csv(csv_file(tmp_path, [sample(date=invalid_week)]))
    assert report["counts"]["candidate_artist_label_days"] == 0
    assert report["source_quality"]["rows_with_invalid_or_unsupported_day"] == 1


def test_unsupported_short_and_long_values_get_coarse_length_buckets(tmp_path):
    values = ["", "X", "ABCD" * 10, "P" * 70]
    report = analyze_daily_csv(csv_file(tmp_path, [
        sample(date=value) for value in values
    ]))
    q = report["source_quality"]
    assert q["unsupported_length_buckets"] == {
        "empty": 1, "1_to_10": 1, "11_to_32": 0,
        "33_to_64": 1, "65_plus": 1,
    }
    assert q["rare_or_unclassified_unsupported_rows"] == 4
    assert q["common_unsupported_masked_shapes"] == []
    assert "ABCD" not in json.dumps(report)


def test_common_compact_unrecognized_values_can_be_diagnosed_without_prefix(tmp_path):
    raw = "2026W993"
    report = analyze_daily_csv(csv_file(tmp_path, [
        sample(date=raw) for _ in range(21)
    ]))
    q = report["source_quality"]
    assert q["common_unsupported_masked_shapes"] == [{
        "shape": "9999A999", "count": 21,
    }]
    assert q["unsupported_length_buckets"]["1_to_10"] == 21
    assert raw not in json.dumps(report)
