"""Synthetic CSV pre-parser resource limits. No user data or network."""
import csv
import io

import pytest

from backend.services.apple_music_csv_record_budget import (
    BoundedCsvLines,
    CsvRecordBudgetExceeded,
)


def _read(source, *, columns=4, field=16):
    return list(csv.reader(
        BoundedCsvLines(io.StringIO(source, newline=""),
                        max_columns=columns, max_field=field),
        strict=True,
    ))


def test_reject_million_empty_cells_before_csv_builds_large_row():
    with pytest.raises(CsvRecordBudgetExceeded, match="budget exceeded"):
        _read("first,second\n" + "," * 1_000_000)


def test_header_is_also_rejected_before_materialization():
    with pytest.raises(CsvRecordBudgetExceeded, match="budget exceeded"):
        _read("," * 3000)


def test_quoted_separators_and_multiline_fields_are_supported():
    rows = _read('artist,title,notes\r\n'
                 '"A, B","C""D","line one\nline two"\r\n',
                 columns=3, field=32)
    assert rows == [
        ["artist", "title", "notes"],
        ["A, B", 'C"D', "line one\nline two"],
    ]


def test_quoted_multiline_record_is_capped_across_physical_lines():
    with pytest.raises(CsvRecordBudgetExceeded, match="record budget"):
        _read('a,b\n"'+ ("small\n" * 300) + '",c\n',
              columns=2, field=8)


def test_many_valid_columns_are_not_counted_as_too_many():
    data = ",".join("a" for _ in range(256)) + "\n"
    assert len(_read(data, columns=256, field=8)[0]) == 256


def test_multibyte_source_and_no_final_newline_are_supported():
    assert _read("title,value\nCafé,okay", columns=2, field=16)[1] == [
        "Café", "okay",
    ]


def test_excess_columns_rejected_below_record_byte_budget():
    with pytest.raises(CsvRecordBudgetExceeded, match="column budget"):
        _read("a,b,c,d," + "e," * 40, columns=4, field=8192)


def test_maximum_valid_doubled_quote_field_is_not_preemptively_rejected():
    encoded = '"' + '""' * 8192 + '"\n'
    assert _read(encoded, columns=1, field=8192)[0][0] == '"' * 8192
