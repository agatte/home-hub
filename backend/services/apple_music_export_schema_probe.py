"""#431 — read-only private CSV header classifier; outputs fixed labels only.

Reads a maximum of 32 KiB from ONE operator-selected CSV, without logging
the filename, path, header values, rows or any personal metadata.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_HEADER_BYTES = 32 * 1024
MAX_HEADER_FIELDS = 256
DAILY = frozenset({
    "Track Description", "Date Played", "Play Count",
    "Play Duration Milliseconds",
})
PLAY = frozenset({"Event Type", "Event End Timestamp", "Song Name"})
TRACK_HISTORY = frozenset({"Track Name", "Last Played Date", "Is User Initiated"})


class HeaderRejected(ValueError):
    """Fixed messages only; never include source text or a private path."""


def classify_header(header: list[str]) -> dict:
    if not 0 < len(header) <= MAX_HEADER_FIELDS:
        raise HeaderRejected("CSV column count outside allowed range")
    # Comparison is exact and strictly allowlisted; never echo unexpected names.
    fields = set(header)
    duplicate = len(fields) != len(header)
    daily_found = len(DAILY & fields)
    play_found = len(PLAY & fields)
    track_found = len(TRACK_HISTORY & fields)
    if duplicate:
        kind = "invalid_duplicate_column"
    elif DAILY <= fields:
        kind = "daily_tracks"
    elif PLAY <= fields:
        kind = "play_activity"
    elif TRACK_HISTORY <= fields:
        kind = "track_play_history"
    else:
        kind = "unknown_or_unsupported"
    return {
        "format": "apple_csv_schema_classification_v1",
        "classification": kind,
        "daily_tracks_required_columns_present": daily_found,
        "daily_tracks_required_columns_total": len(DAILY),
        "play_activity_required_columns_present": play_found,
        "play_activity_required_columns_total": len(PLAY),
        "track_play_history_required_columns_present": track_found,
        "track_play_history_required_columns_total": len(TRACK_HISTORY),
        "has_duplicate_column_names": duplicate,
        "total_header_columns": len(header),
    }


def inspect_header(path: Path) -> dict:
    try:
        # Only the first 32 KiB are ever loaded. It can include part of the
        # first data row; none of its content is used or disclosed.
        with path.open("rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise HeaderRejected("Unsupported CSV file type")
            if not 0 < metadata.st_size <= MAX_FILE_BYTES:
                raise HeaderRejected("CSV file size unsupported")
            fragment = source.read(MAX_HEADER_BYTES)
        # Do not attempt an unbounded/partially sampled quoted header.
        text = fragment.decode("utf-8-sig")
        csv.field_size_limit(8192)
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, [])
        if not header:
            raise HeaderRejected("CSV header is missing")
        return classify_header(header)
    except HeaderRejected:
        raise
    except (OSError, UnicodeError, csv.Error, ValueError, OverflowError):
        raise HeaderRejected("Unable to inspect CSV header safely") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only Apple CSV schema classifier")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_header(args.csv_path)
    except HeaderRejected as error:
        parser.exit(2, "Header check rejected: " + str(error) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
