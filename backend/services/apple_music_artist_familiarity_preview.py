"""#431 — synthetic-only Apple Daily Tracks artist-label familiarity preview.

This is a pure in-memory *feasibility* calculator, not an importer, catalog
identity resolver, proof issuer, preference model or source reader.

A Daily Tracks description is an unverified artist label. An "artist day" is
a distinct DATE LABEL with one or more unambiguous descriptions, not evidence
of separate playback sessions. It cannot become a MusicTasteSnapshot weight.
No per-artist result, date, song, key, hash or source row leaves this module.
"""
from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

MAX_ROWS = 250_000
MAX_TEXT = 2048
MAX_TOTAL_DURATION_MS = 7 * 24 * 60 * 60 * 1000
MAX_PLAY_COUNT = 100_000
SEPARATOR = " - "
SOURCE = "apple_daily_tracks"
FORMAT = "apple_artist_label_day_shadow_v1"


@dataclass(frozen=True)
class DailyArtistObservation:
    """Only four allowlisted Daily Tracks columns; never serialize the object."""

    description: str
    day: date
    play_count: int
    duration_ms: int
    source: str = SOURCE


class ArtistPreviewRejected(ValueError):
    """Fixed error messages only; never interpolate input data."""


def _normalized(text: object) -> str | None:
    if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
        return None
    value = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    return value if 0 < len(value) <= MAX_TEXT else None


def _valid_day(value: object) -> bool:
    return type(value) is date and 2000 <= value.year <= 2100


def _parse(row: DailyArtistObservation) -> tuple[date, str, str, int, int] | None:
    if (row.source != SOURCE or not _valid_day(row.day)
            or type(row.play_count) is not int
            or not 1 <= row.play_count <= MAX_PLAY_COUNT
            or type(row.duration_ms) is not int
            or not 0 < row.duration_ms <= MAX_TOTAL_DURATION_MS):
        return None
    description = row.description
    if not isinstance(description, str) or not 0 < len(description) <= MAX_TEXT:
        return None
    if description.count(SEPARATOR) != 1:
        return None
    raw_artist, raw_title = description.split(SEPARATOR)
    artist, title = _normalized(raw_artist), _normalized(raw_title)
    if artist is None or title is None:
        return None
    return row.day, artist, title, row.play_count, row.duration_ms


def preview_artist_label_days(rows: Iterable[DailyArtistObservation]) -> dict:
    """Return anonymous aggregate buckets; all raw strings stay in memory.

    Same (day, song title) attributed to multiple artists -> *all* such
    descriptions abstain. Conflicting play-count/duration aggregates for
    one (day, artist label, title label) also abstain. Duplicated rows and
    multiple songs by the same label/day never increase the day count.
    No tie to Apple Event ID, artist catalog identity or Sonos is claimed.
    """
    counts: Counter[str] = Counter({"input_daily_rows": 0})
    title_day_artists: dict[tuple[date, str], set[str]] = defaultdict(set)
    signature_values: dict[tuple[date, str, str], set[tuple[int, int]]] = defaultdict(set)
    title_day_rows: Counter[tuple[date, str]] = Counter()

    for row in rows:
        counts["input_daily_rows"] += 1
        if counts["input_daily_rows"] > MAX_ROWS:
            raise ArtistPreviewRejected("Artist preview row limit exceeded")
        if not isinstance(row, DailyArtistObservation):
            counts["abstain_invalid_row"] += 1
            continue
        parsed = _parse(row)
        if parsed is None:
            counts["abstain_invalid_or_ambiguous_description_or_metrics"] += 1
            continue
        day, artist, title, plays, duration = parsed
        title_day = (day, title)
        title_day_artists[title_day].add(artist)
        signature_values[(day, artist, title)].add((plays, duration))
        title_day_rows[title_day] += 1
        counts["parsed_description_rows"] += 1

    conflicted_keys = {
        (day, title)
        for (day, artist, title), values in signature_values.items()
        if len(values) != 1
    }
    ambiguous_title_days = {
        key for key, artists in title_day_artists.items() if len(artists) != 1
    }
    excluded = conflicted_keys | ambiguous_title_days
    counts["ambiguous_title_day_groups"] = len(ambiguous_title_days)
    counts["conflicting_aggregate_title_day_groups"] = len(conflicted_keys)
    counts["abstain_ambiguous_or_conflicting_rows"] = sum(
        title_day_rows[key] for key in excluded
    )

    unique_title_days: set[tuple[date, str, str]] = set()
    artist_days: set[tuple[str, date]] = set()
    for day, artist, title in signature_values:
        if (day, title) in excluded:
            continue
        unique_title_days.add((day, artist, title))
        artist_days.add((artist, day))
    counts["unambiguous_title_day_labels"] = len(unique_title_days)
    counts["collapsed_repeated_or_multiple_song_rows"] = (
        counts["parsed_description_rows"]
        - counts["abstain_ambiguous_or_conflicting_rows"]
        - len(artist_days)
    )
    counts["candidate_artist_label_days"] = len(artist_days)

    frequencies: Counter[str] = Counter()
    days_per_artist: Counter[str] = Counter(label for label, _ in artist_days)
    for n in days_per_artist.values():
        band = "1_day" if n == 1 else "2_to_3_days" if n <= 3 else (
            "4_to_9_days" if n <= 9 else "10_plus_days"
        )
        frequencies[band] += 1
    counts["distinct_provisional_artist_labels"] = len(days_per_artist)
    return {
        "format": FORMAT,
        "counts": dict(sorted(counts.items())),
        "artist_label_day_histogram": {
            key: frequencies[key] for key in (
                "1_day", "2_to_3_days", "4_to_9_days", "10_plus_days"
            )
        },
        "warnings": [
            "Calendar-day label presence only; no independent playback sessions proven.",
            "Artist names parsed from descriptions are not catalog identities.",
            "No per-artist names, titles, dates, IDs, hashes or individual rows returned.",
            "Familiarity candidates are not liking, ratings, or positive/negative weights.",
            "No Sonos dedup, physical presence, playback, ranking or HomeHub persistence.",
        ],
    }
