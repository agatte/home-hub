"""#431 synthetic-only identity and cross-source evidence feasibility.

No source files, HomeHub runtime, database, network, playback or persistence.
These are *review decisions* about independently supplied evidence, not a
trustworthy proof issuer. Real data adapters and coverage authority do not exist.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

MAX_RECORDS = 250_000
MAX_TEXT = 2048
MAX_ID = 256
DURATION_TOLERANCE_MS = 1_000
CLOCK_SKEW = timedelta(minutes=2)
MAX_PLAYBACK_WINDOW = timedelta(hours=24)
TRUSTED_CATALOG_SOURCES = frozenset({"apple_catalog_verified", "library_id_verified"})
TRUSTED_COVERAGE_SOURCE = "verified_continuous_sonos_capture"


@dataclass(frozen=True)
class HistoricalTrack:
    """An Apple listening record *with* a separate, independent catalog ID."""
    catalog_id: str = field(repr=False)
    title: str = field(repr=False)
    artist: str = field(repr=False)
    album: str = field(repr=False)
    duration_ms: int | None = None
    id_origin: str = "unverified"


@dataclass(frozen=True)
class CatalogRecord:
    """Metadata from an independently verified authoritative catalog lookup."""
    catalog_id: str = field(repr=False)
    title: str = field(repr=False)
    artist: str = field(repr=False)
    album: str = field(repr=False)
    duration_ms: int | None = None
    source: str = "unverified"


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CoverageReceipt:
    """A hypothetical authority receipt; *not* issued from Sonos DB events.

    'complete' requires continuous playback telemetry proving *all* Sonos
    playback intervals were observed. Action logs do NOT satisfy this.
    """
    interval: Interval
    source: str = "unverified"
    complete: bool = False


class ReconciliationRejected(ValueError):
    """Fixed non-sensitive error messages only."""


def _normalize(value: object, cap: int = MAX_TEXT) -> str | None:
    if not isinstance(value, str) or not 0 < len(value) <= cap:
        return None
    text = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return text or None


def _id(value: object) -> str | None:
    """Opaque catalog identifiers are case sensitive; never fold them."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_ID:
        return None
    return value if value.strip() == value else None


def _duration(value: object) -> bool:
    return type(value) is int and 0 < value <= 24 * 60 * 60 * 1000


def _metadata_match(track: HistoricalTrack, ref: CatalogRecord) -> bool:
    return all(
        _normalize(getattr(track, attr)) is not None
        and _normalize(getattr(track, attr)) == _normalize(getattr(ref, attr))
        for attr in ("title", "artist", "album")
    ) and (
        _duration(track.duration_ms)
        and _duration(ref.duration_ms)
        and abs(track.duration_ms - ref.duration_ms) <= DURATION_TOLERANCE_MS
    )


def assess_catalog_identity(
    track: HistoricalTrack, references: Iterable[CatalogRecord],
) -> str:
    """Fail closed unless one externally verified, metadata-consistent catalog ID.

    Neither a Provider ID nor a title/date join is independently verified.
    Duplicate conflicting entries for one ID always abstain.
    """
    if _id(track.catalog_id) is None:
        return "missing_independent_catalog_id"
    if track.id_origin != "independent_catalog_lookup":
        return "catalog_id_origin_unverified"
    same_id: list[CatalogRecord] = []
    for n, item in enumerate(references, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Catalog reference limit exceeded")
        if _id(item.catalog_id) == _id(track.catalog_id):
            same_id.append(item)
    if not same_id:
        return "catalog_id_not_found"
    if any(item.source not in TRUSTED_CATALOG_SOURCES for item in same_id):
        return "catalog_source_unverified"
    signature = {
        (
            _normalize(item.title), _normalize(item.artist),
            _normalize(item.album), item.duration_ms,
        ) for item in same_id
    }
    if len(signature) != 1:
        return "conflicting_catalog_metadata"
    if not _metadata_match(track, same_id[0]):
        return "catalog_metadata_mismatch"
    return "corroborated_catalog_candidate_only"


def _interval(value: Interval) -> tuple[datetime, datetime] | None:
    if not isinstance(value, Interval):
        return None
    a, b = value.start, value.end
    if not all(isinstance(t, datetime) and t.tzinfo is not None for t in (a, b)):
        return None
    try:
        a, b = a.astimezone(timezone.utc), b.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None
    if a.year < 2000 or b.year > 2100 or not a <= b <= a + MAX_PLAYBACK_WINDOW:
        return None
    return a, b

def assess_sonos_overlap(
    apple_session: Interval,
    sonos_playback_intervals: Iterable[Interval],
    coverage: Iterable[CoverageReceipt],
) -> str:
    """Only a genuinely complete telemetry interval can prove non-overlap.

    SonosPlaybackEvent's timestamped *actions* cannot produce that receipt.
    If an independently known Sonos playback window intersects (including
    two-minute clock uncertainty), mark possible overlap regardless of title.
    """
    bounds = _interval(apple_session)
    if bounds is None:
        return "unknown_invalid_apple_session"
    start, end = bounds
    padded_start, padded_end = start - CLOCK_SKEW, end + CLOCK_SKEW
    for n, sonos in enumerate(sonos_playback_intervals, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Sonos playback interval limit exceeded")
        window = _interval(sonos)
        if window is None:
            return "unknown_invalid_sonos_interval"
        if window[0] <= padded_end and window[1] >= padded_start:
            return "possible_cross_source_overlap"

    receipts: list[tuple[datetime, datetime]] = []
    for n, proof in enumerate(coverage, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Coverage receipt limit exceeded")
        window = _interval(proof.interval)
        if window is None:
            return "unknown_invalid_coverage"
        if proof.complete and proof.source == TRUSTED_COVERAGE_SOURCE:
            receipts.append(window)
    # A complete receipt must cover the entire padded Apple window.
    # Combine only contiguous or overlapping complete telemetry segments.
    cursor = padded_start
    for lower, upper in sorted(receipts):
        if lower <= cursor < upper:
            cursor = upper
        if cursor >= padded_end:
            return "no_overlap_with_complete_telemetry"
    return "unknown_incomplete_sonos_coverage"


def assess_sonos_action_log(
    apple_session: Interval, sonos_events: Iterable[object],
) -> str:
    """Bounded read-only projection of SonosPlaybackEvent-like action rows.

    These are timestamps, not continuous playback windows. Even a fully empty
    query of SonosPlaybackEvent can *never* prove that nothing played.
    """
    bounds = _interval(apple_session)
    if bounds is None:
        return "unknown_invalid_apple_session"
    start, end = bounds
    start -= CLOCK_SKEW
    end += CLOCK_SKEW
    observed = False
    for n, row in enumerate(sonos_events, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Sonos action event limit exceeded")
        when = getattr(row, "timestamp", None)
        if not isinstance(when, datetime) or when.tzinfo is None:
            return "unknown_invalid_action_timestamp"
        when = when.astimezone(timezone.utc)
        if start <= when <= end and str(getattr(row, "event_type", "")).lower() in {
            "play", "auto_play", "owned_retained", "skip", "pause",
        }:
            observed = True
    if observed:
        return "possible_overlap_from_sonos_action"
    return "unknown_action_log_cannot_prove_nonoverlap"


def summarize_proof_decisions(
    catalog_statuses: Iterable[str], overlap_statuses: Iterable[str],
) -> dict:
    """Aggregate-only report; never return per-record identifying details."""
    results: Counter[str] = Counter()
    for n, state in enumerate(catalog_statuses, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Identity decision limit exceeded")
        if state not in {
            "missing_independent_catalog_id", "catalog_id_origin_unverified",
            "catalog_id_not_found",
            "catalog_source_unverified", "conflicting_catalog_metadata",
            "catalog_metadata_mismatch", "corroborated_catalog_candidate_only",
        }:
            raise ReconciliationRejected("Unsupported catalog decision")
        results["catalog_" + state] += 1
    for n, state in enumerate(overlap_statuses, 1):
        if n > MAX_RECORDS:
            raise ReconciliationRejected("Overlap decision limit exceeded")
        if state not in {
            "unknown_invalid_apple_session", "unknown_invalid_sonos_interval",
            "possible_cross_source_overlap", "unknown_invalid_coverage",
            "no_overlap_with_complete_telemetry",
            "unknown_incomplete_sonos_coverage",
            "unknown_invalid_action_timestamp",
            "possible_overlap_from_sonos_action",
            "unknown_action_log_cannot_prove_nonoverlap",
        }:
            raise ReconciliationRejected("Unsupported overlap decision")
        results["overlap_" + state] += 1
    return {
        "format": "apple_identity_overlap_proof_gap_v1",
        "counts": dict(sorted(results.items())),
        "warnings": [
            "Catalog matches are candidates, not proof of an actual played recording.",
            "Sonos action logs cannot prove a negative or establish full coverage.",
            "No input identifiers, timestamps, titles, artists or source rows exported.",
            "No preference weights, HomeHub writes, queue actions or house-state effects.",
        ],
    }
