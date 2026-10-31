"""#431: operator-local read-only Daily Tracks artist-label/day histogram.

Opens one explicitly chosen local CSV; never searches folders/ZIP archives,
writes data, accesses HomeHub runtime, uses a network connection or persists
artist/song/date values. Public JSON contains only fixed anonymous aggregates.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

if __package__:
    from .apple_music_artist_familiarity_preview import (
        ArtistPreviewRejected, DailyArtistObservation, preview_artist_label_days,
    )
    from .apple_music_daily_join_audit import (
        AuditRejected, DAILY, _csv_rows, _date, _numeric,
    )
else:
    from apple_music_artist_familiarity_preview import (
        ArtistPreviewRejected, DailyArtistObservation, preview_artist_label_days,
    )
    from apple_music_daily_join_audit import (
        AuditRejected, DAILY, _csv_rows, _date, _numeric,
    )


def _safe_int(value: str) -> int | None:
    """Reject non-ASCII, signed, decimal, scientific and huge source numbers."""
    if not _numeric(value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_BASIC_DAY = re.compile(r"[0-9]{8}", re.ASCII)
_WEEK_DAY = re.compile(r"[0-9]{4}-W[0-9]{2}-[1-7]", re.ASCII)
_BASIC_WEEK_DAY = re.compile(r"[0-9]{4}W[0-9]{2}[1-7]", re.ASCII)
# A fully validated datetime is still only a *source date label*, never an
# independently proven session or a trustworthy time-zone conversion.
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})?",
    re.ASCII,
)
_SHAPES = (
    "date_only", "compact_calendar_date", "iso_week_date",
    "compact_iso_week_date", "iso_timestamp_utc", "iso_timestamp_offset",
    "iso_timestamp_no_zone", "unsupported",
)
_LENGTH_BUCKETS = ("empty", "1_to_10", "11_to_32", "33_to_64", "65_plus")


def _length_bucket(value: object) -> str:
    if not isinstance(value, str):
        return "empty"
    n = len(value)
    return (
        "empty" if n == 0 else
        "1_to_10" if n <= 10 else
        "11_to_32" if n <= 32 else
        "33_to_64" if n <= 64 else "65_plus"
    )
# Only structurally similar patterns repeated >= 20 times can leave the
# process. No original character, timestamp value or private text is emitted.
MIN_MASK_GROUP = 20
MAX_MASK_GROUPS = 5
MAX_MASK_LENGTH = 64
_MASK_PUNCTUATION = frozenset("-:+./,()")


def _masked_date_pattern(value: object) -> str | None:
    """Return character CLASSES for an unsupported prefixed date, not data.

    No date prefix is required: the diagnostic must be useful precisely
    when the parser cannot identify the input. All digits become 9,
    letters become A, whitespace becomes _, and only a small punctuation
    allowlist remains unchanged. Rare patterns are never returned.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_MASK_LENGTH:
        return None
    result = []
    for char in value:
        if "0" <= char <= "9":
            result.append("9")
        elif ("A" <= char <= "Z") or ("a" <= char <= "z"):
            result.append("A")
        elif char.isspace():
            result.append("_")
        elif char in _MASK_PUNCTUATION:
            result.append(char)
        else:
            result.append("?")
    return "".join(result)


def _source_day(value: str) -> tuple[object, str]:
    """Parse complete ISO-like date labels; never accept a date prefix alone."""
    if not isinstance(value, str) or not 0 < len(value) <= 40:
        return None, "unsupported"
    for regex, label in (
        (_DAY, "date_only"),
        (_BASIC_DAY, "compact_calendar_date"),
        (_WEEK_DAY, "iso_week_date"),
        (_BASIC_WEEK_DAY, "compact_iso_week_date"),
    ):
        if regex.fullmatch(value):
            day = _date(value)
            return (day, label) if day is not None else (None, "unsupported")
    if not _TIMESTAMP.fullmatch(value):
        return None, "unsupported"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None, "unsupported"
    if not 2000 <= parsed.year <= 2100:
        return None, "unsupported"
    # Do not convert to UTC: Apple's Daily Tracks labels are not unique
    # playback sessions, and a timezone conversion would invent a new day.
    shape = (
        "iso_timestamp_utc" if value.endswith("Z") else
        "iso_timestamp_offset" if parsed.tzinfo is not None else
        "iso_timestamp_no_zone"
    )
    return parsed.date(), shape


def analyze_daily_csv(daily_csv: Path) -> dict:
    """Reuse the existing bounded streaming parser, not a second CSV reader.

    Even when CSV has extra private columns, only the four allowlisted
    positions are inspected. csv.reader transiently parses full bounded rows;
    excluded columns are never retained, logged, returned or analyzed.
    """
    if daily_csv.suffix.casefold() != ".csv":
        raise AuditRejected("Only CSV file selection is supported")
    source_shapes: Counter[str] = Counter()
    unsupported_masks: Counter[str] = Counter()
    unsupported_lengths: Counter[str] = Counter()
    with _csv_rows(daily_csv, DAILY) as (position, csv_rows):
        def observations():
            for cells in csv_rows:
                raw_date = cells[position["Date Played"]]
                day, shape = _source_day(raw_date)
                source_shapes[shape] += 1
                if shape == "unsupported":
                    unsupported_lengths[_length_bucket(raw_date)] += 1
                    masked = _masked_date_pattern(raw_date)
                    if masked is not None:
                        unsupported_masks[masked] += 1
                yield DailyArtistObservation(
                    description=cells[position["Track Description"]],
                    day=day,
                    play_count=_safe_int(cells[position["Play Count"]]),
                    duration_ms=_safe_int(cells[position["Play Duration Milliseconds"]]),
                )

        result = preview_artist_label_days(observations())
    reportable_masks = sorted(
        (
            (masked, count) for masked, count in unsupported_masks.items()
            if count >= MIN_MASK_GROUP
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )[:MAX_MASK_GROUPS]
    reported_total = sum(count for _, count in reportable_masks)
    result["source_quality"] = {
        "rows_with_invalid_or_unsupported_day": source_shapes["unsupported"],
        "date_label_shapes": {key: source_shapes[key] for key in _SHAPES},
        "common_unsupported_masked_shapes": [
            {"shape": masked, "count": count}
            for masked, count in reportable_masks
        ],
        "unsupported_length_buckets": {
            key: unsupported_lengths[key] for key in _LENGTH_BUCKETS
        },
        "rare_or_unclassified_unsupported_rows": (
            source_shapes["unsupported"] - reported_total
        ),
    }
    result["warnings"].append(
        "Exact dates and fully validated ISO datetime labels are supported; "
        "unrecognized values abstain. Common unsupported date shapes are "
        "fully masked and rare patterns suppressed. Date labels are not sessions."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Private, local-only Daily Tracks artist-label histogram."
    )
    parser.add_argument("daily_csv", type=Path)
    args = parser.parse_args()
    try:
        report = analyze_daily_csv(args.daily_csv)
    except (AuditRejected, ArtistPreviewRejected) as error:
        parser.exit(2, "Artist audit rejected: " + str(error) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
