"""#431: privacy-limited, local-only Apple Daily Tracks join diagnostics.

No database, network, HomeHub imports, playback or file writes.
Returns aggregate counts only, not titles, artists, IDs or paths.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import stat
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

if __package__:
    from .apple_music_csv_record_budget import BoundedCsvLines
else:  # Direct operator-only Python invocation; no HomeHub app dependencies.
    from apple_music_csv_record_budget import BoundedCsvLines

MAX_BYTES = 100 * 1024 * 1024
MAX_ROWS = 250_000
MAX_COLUMNS = 256
MAX_FIELD = 8192
MAX_TEXT = 2048
DAILY = frozenset({
    "Track Description", "Date Played", "Play Count",
    "Play Duration Milliseconds",
})
PLAY = frozenset({"Event Type", "Event End Timestamp", "Song Name"})
SEPARATOR = " - "


class AuditRejected(ValueError):
    """Only fixed error messages, never source-field interpolation."""


class _LimitedBytes(io.RawIOBase):
    def __init__(self, source, limit: int) -> None:
        super().__init__()
        self.source = source
        self.remaining = limit

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:
        if self.remaining == 0:
            if self.source.read(1):
                raise AuditRejected("CSV exceeds byte limit")
            return 0
        count = self.source.readinto(memoryview(target)[:self.remaining])
        if count is None:
            return 0
        self.remaining -= count
        return count


@contextmanager
def _csv_rows(path: Path, required: frozenset[str]):
    """Yield known field positions and bounded row iterator from one open file."""
    try:
        with path.open("rb") as source:
            original = os.fstat(source.fileno())
            if (not stat.S_ISREG(original.st_mode)
                    or not 0 < original.st_size <= MAX_BYTES):
                raise AuditRejected("Unsupported CSV file size or type")
            with io.TextIOWrapper(
                io.BufferedReader(_LimitedBytes(source, MAX_BYTES)),
                encoding="utf-8-sig", newline="",
            ) as stream:
                csv.field_size_limit(MAX_FIELD)
                reader = csv.reader(
                    BoundedCsvLines(stream, max_columns=MAX_COLUMNS,
                                    max_field=MAX_FIELD),
                    strict=True,
                )
                header = next(reader, [])
                if (len(header) > MAX_COLUMNS
                        or len(header) != len(set(header))
                        or not required.issubset(header)):
                    raise AuditRejected("Required CSV fields missing or duplicated")
                positions = {key: header.index(key) for key in required}

                def rows():
                    for n, row in enumerate(reader, 1):
                        if n > MAX_ROWS:
                            raise AuditRejected("CSV row limit exceeded")
                        if len(row) != len(header):
                            raise AuditRejected("Malformed CSV row")
                        yield row

                yield positions, rows()
            final = os.fstat(source.fileno())
            if (final.st_size != original.st_size
                    or final.st_mtime_ns != original.st_mtime_ns):
                raise AuditRejected("CSV changed during inspection")
    except AuditRejected:
        raise
    except (OSError, UnicodeError, csv.Error, ValueError, OverflowError):
        raise AuditRejected("CSV could not be safely inspected") from None


def _text(value: str) -> str:
    if not value or len(value) > MAX_TEXT:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _date(value: str) -> date | None:
    if not value or len(value) > 40:
        return None
    try:
        result = date.fromisoformat(value[:10])
        return result if 2000 <= result.year <= 2100 else None
    except ValueError:
        return None


def _end_date(value: str) -> date | None:
    if not value or len(value) > 50:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc).date() if 2000 <= result.year <= 2100 else None
    except (ValueError, OverflowError):
        return None


def _numeric(value: str) -> bool:
    return bool(value) and len(value) <= 18 and value.isascii() and value.isdecimal()


def analyze(daily_path: Path, play_path: Path | None = None) -> dict:
    """Produce only fixed-schema aggregate quality/matching counts.

    Matches are provisional even if description/title and UTC date agree:
    neither uniquely identifies a recording or listening session.
    """
    counts: Counter[str] = Counter()
    play_events: list[tuple[str, date | None]] = []
    titles: set[str] = set()
    if play_path is not None:
        with _csv_rows(play_path, PLAY) as (pos, rows):
            for row in rows:
                counts["play_rows_scanned"] += 1
                if row[pos["Event Type"]] != "PLAY_END":
                    continue
                counts["play_end_rows"] += 1
                title = _text(row[pos["Song Name"]])
                end_day = _end_date(row[pos["Event End Timestamp"]])
                if not title:
                    counts["play_end_missing_title"] += 1
                    continue
                play_events.append((title, end_day))
                titles.add(title)
                if end_day is None:
                    counts["play_end_invalid_end_date"] += 1
        counts["distinct_play_end_titles"] = len(titles)

    # Keep only titles/artists/dates necessary for matching in volatile memory.
    # Values are not logged, serialized, retained or passed into HomeHub.
    candidate: dict[str, dict[str, set[date]]] = defaultdict(
        lambda: defaultdict(set)
    )
    ambiguous_titles: set[str] = set()
    with _csv_rows(daily_path, DAILY) as (pos, rows):
        for row in rows:
            counts["daily_rows"] += 1
            description = _text(row[pos["Track Description"]])
            day = _date(row[pos["Date Played"]])
            if description:
                counts["daily_rows_with_description"] += 1
            else:
                counts["daily_rows_missing_description"] += 1
            if day:
                counts["daily_rows_with_valid_date"] += 1
            else:
                counts["daily_rows_invalid_date"] += 1
            if _numeric(row[pos["Play Count"]]):
                counts["daily_rows_with_numeric_play_count"] += 1
            else:
                counts["daily_rows_invalid_play_count"] += 1
            if _numeric(row[pos["Play Duration Milliseconds"]]):
                counts["daily_rows_with_numeric_duration"] += 1
            else:
                counts["daily_rows_invalid_duration"] += 1
            if SEPARATOR in description:
                counts["daily_rows_with_artist_song_separator"] += 1
                if description.count(SEPARATOR) > 1:
                    counts["daily_rows_with_multiple_separators"] += 1
            if play_path is None or not description:
                continue
            possibilities: set[tuple[str, str]] = set()
            start = 0
            while True:
                at = description.find(SEPARATOR, start)
                if at < 0:
                    break
                artist = description[:at].strip()
                title = description[at + len(SEPARATOR):].strip()
                if artist and title in titles:
                    possibilities.add((title, artist))
                start = at + len(SEPARATOR)
            if possibilities and (len(possibilities) > 1 or description.count(SEPARATOR) > 1):
                ambiguous_titles.update(title for title, _ in possibilities)
                counts["daily_rows_with_ambiguous_title_split"] += 1
            elif possibilities:
                title, artist = next(iter(possibilities))
                if day:
                    candidate[title][artist].add(day)
                else:
                    counts["daily_rows_with_title_but_invalid_date"] += 1
            else:
                counts["daily_rows_without_exact_title_suffix"] += 1


    if play_path is not None:
        for title, event_day in play_events:
            if event_day is None:
                counts["play_end_undated_or_unmatched"] += 1
                continue
            artists = candidate.get(title, {})
            if title in ambiguous_titles or len(artists) > 1:
                counts["play_end_ambiguous_artist"] += 1
            elif len(artists) == 1:
                days = next(iter(artists.values()))
                if event_day in days:
                    counts["play_end_same_date_provisional"] += 1
                elif any(abs((event_day - day).days) == 1 for day in days):
                    counts["play_end_adjacent_date_provisional"] += 1
                else:
                    counts["play_end_title_only_no_near_date"] += 1
            else:
                counts["play_end_undated_or_unmatched"] += 1
        counts["provisional_results_are_not_verified_recordings"] = 1
    return {
        "format": "apple_daily_tracks_join_aggregate_v1",
        "summary": dict(sorted(counts.items())),
        "warnings": [
            "Aggregate only; no titles, artists, identifiers, dates or paths returned.",
            "Description suffix and date overlap do not verify recording identity.",
            "No HomeHub taste import, persistence, playback or network traffic.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only Apple history matching audit")
    parser.add_argument("daily_csv", type=Path)
    parser.add_argument("--play-csv", type=Path)
    args = parser.parse_args()
    try:
        report = analyze(args.daily_csv, args.play_csv)
    except AuditRejected as error:
        parser.exit(2, "Audit rejected: " + str(error) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
