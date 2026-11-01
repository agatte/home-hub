"""Bound CSV column/record budgets *before* csv.reader builds row lists.

This is an offline-only, constant-memory prefilter for the default CSV dialect:
comma delimiter, double-quote quoting and doubled-quote escapes. It never
retains or reports input content. Strict csv.reader performs final validation.
"""
from __future__ import annotations

from typing import TextIO


class CsvRecordBudgetExceeded(ValueError):
    """Source-neutral failure without an input value or path."""


class BoundedCsvLines:
    """Yield bounded physical lines while accounting for logical CSV records.

    TextIOWrapper.readline(size) prevents materializing an unlimited physical
    line. The state machine tracks quoted line breaks and separators so the
    number of fields is rejected *before* csv.reader materializes the row.
    """

    def __init__(self, stream: TextIO, *, max_columns: int,
                 max_field: int) -> None:
        if max_columns < 1 or max_field < 1:
            raise ValueError("Invalid CSV limits")
        self.stream = stream
        self.max_columns = max_columns
        # Every decoded quote could be doubled in the raw CSV. Allow the
        # worst-case escaped field plus separators, enclosing quotes and CRLF.
        self.max_record_chars = max_columns * (2 * max_field + 3) + 2
        self.record_chars = 0
        self.columns = 1
        self.in_quotes = False
        self.pending_quote = False
        self.field_start = True

    def __iter__(self) -> BoundedCsvLines:
        return self

    def __next__(self) -> str:
        remaining = self.max_record_chars - self.record_chars
        if remaining < 1:
            raise CsvRecordBudgetExceeded("CSV record budget exceeded")
        line = self.stream.readline(remaining + 1)
        if not line:
            raise StopIteration
        if len(line) > remaining:
            raise CsvRecordBudgetExceeded("CSV record budget exceeded")

        for char in line:
            self.record_chars += 1
            if self.pending_quote:
                self.pending_quote = False
                if char == '"':
                    # A doubled quote stays inside the quoted field.
                    continue
                self.in_quotes = False
            if self.in_quotes:
                if char == '"':
                    self.pending_quote = True
                continue
            if char == ',':
                self.columns += 1
                if self.columns > self.max_columns:
                    raise CsvRecordBudgetExceeded("CSV column budget exceeded")
                self.field_start = True
            elif char == '"' and self.field_start:
                self.in_quotes = True
                self.field_start = False
            elif char in "\r\n":
                # Physical line break outside quotes ends the logical record.
                self.record_chars = 0
                self.columns = 1
                self.field_start = True
            else:
                self.field_start = False
        return line
