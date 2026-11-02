"""#431 fictional-only artist-label exposure preview; no private inputs.

Portable developer demo. This module has no CSV reader, file selection,
persistence, account access, network, HomeHub state, or playback integration.
All named rows are literal invented fixtures, never results from a user export.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from backend.services.apple_music_artist_familiarity_preview import (
    DailyArtistObservation,
    preview_artist_label_days,
)

FIXTURES = (
    ("Imaginary Aurora", 10),
    ("Fictional Harbor", 5),
    ("Made-Up Midnight", 3),
    ("Invented Echo", 1),
    ("Placeholder Ensemble", 1),
)
BANDS = ("1_day", "2_to_3_days", "4_to_9_days", "10_plus_days")


class SyntheticPreviewRejected(RuntimeError):
    """Only fixed source-neutral errors; no source values in diagnostics."""


@dataclass(frozen=True, repr=False)
class SyntheticArtistSummary:
    """Only known synthetic aggregate counts and fictional presentation data."""

    preview_format: str
    artist_label_days: int
    provisional_labels: int
    excluded_ambiguous_rows: int
    histogram: tuple[tuple[str, int], ...]
    fictional_labels: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        return "SyntheticArtistSummary(<redacted>)"


def _band(days: int) -> str:
    if days == 1:
        return "1_day"
    if days <= 3:
        return "2_to_3_days"
    if days <= 9:
        return "4_to_9_days"
    return "10_plus_days"


def build_synthetic_preview() -> SyntheticArtistSummary:
    """Run the merged aggregate-only engine on 23 fictional observations."""
    start = date(2026, 1, 1)
    observations = [
        DailyArtistObservation(
            description=f"{label} - Fictional Track {label}",
            day=start + timedelta(days=offset),
            play_count=1,
            duration_ms=180_000,
        )
        for label, days in FIXTURES
        for offset in range(days)
    ]
    for label in ("Invented Ambiguous One", "Invented Ambiguous Two"):
        observations.append(
            DailyArtistObservation(
                description=f"{label} - Shared Fictional Song",
                day=start + timedelta(days=17),
                play_count=1,
                duration_ms=180_000,
            )
        )
    observations.append(observations[0])  # duplicate; not another artist-day
    try:
        result = preview_artist_label_days(observations)
        counts = result["counts"]
        histogram = result["artist_label_day_histogram"]
        expected_bands = {
            band: sum(_band(days) == band for _, days in FIXTURES)
            for band in BANDS
        }
        expected_counts = {
            "input_daily_rows": 23,
            "candidate_artist_label_days": 20,
            "distinct_provisional_artist_labels": 5,
            "abstain_ambiguous_or_conflicting_rows": 2,
            "collapsed_repeated_or_multiple_song_rows": 1,
        }
        if (
            result["format"] != "apple_artist_label_day_shadow_v1"
            or any(
                type(counts.get(key)) is not int or counts[key] != value
                for key, value in expected_counts.items()
            )
            or set(histogram) != set(BANDS)
            or any(
                type(histogram[key]) is not int or histogram[key] != value
                for key, value in expected_bands.items()
            )
        ):
            raise SyntheticPreviewRejected("Synthetic preview invariants failed")
    except Exception:
        raise SyntheticPreviewRejected("Synthetic preview invariants failed") from None

    # The aggregate engine intentionally emits no artist identities. These
    # displayed labels are *only* from this explicitly fictional fixture.
    return SyntheticArtistSummary(
        preview_format="apple_artist_label_day_shadow_v1",
        artist_label_days=expected_counts["candidate_artist_label_days"],
        provisional_labels=expected_counts["distinct_provisional_artist_labels"],
        excluded_ambiguous_rows=expected_counts["abstain_ambiguous_or_conflicting_rows"],
        histogram=tuple((key, expected_bands[key]) for key in BANDS),
        fictional_labels=tuple((label, _band(days)) for label, days in FIXTURES),
    )
