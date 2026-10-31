"""Offline, aggregate-only Apple Music Play Activity CSV inspector (#431).

No database, HomeHub runtime, network or playback imports. No source-field values
are returned, printed or logged. Synthetic-first; operator-local CSV only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024
MAX_ROWS = 250_000
MAX_FIELD = 8192
MAX_FIELDS = 256
MAX_DURATION_MS = 24 * 60 * 60 * 1000
MAX_DISTINCT_EVENT_IDS = 250_000
REQUIRED = frozenset({
    "Event ID", "Event Type", "Event Start Timestamp",
    "Event End Timestamp", "End Reason Type", "Play Duration Milliseconds",
    "Media Duration In Milliseconds", "Song Name", "Provider ID",
})
READ_FIELDS = REQUIRED | frozenset({"Album Name"})
EVENT_TYPES = {"PLAY_END", "PLAY_START", "LYRIC_DISPLAY"}
NATURAL = {"NATURAL_END_OF_TRACK"}
SKIP = {"TRACK_SKIPPED_FORWARDS", "TRACK_SKIPPED_BACKWARDS"}
NEUTRAL = {
    "PLAYBACK_MANUALLY_PAUSED", "PLAYBACK_SUSPENDED", "EXITED_APPLICATION",
    "TRACK_SELECTED_FOR_PLAYBACK", "OTHER", "SCRUB_BEGIN", "SCRUB_END",
    "FAILED_TO_LOAD",
}


class InspectionError(ValueError):
    """Deliberately fixed, non-sensitive diagnostic."""


class _ByteBudgetReader(io.RawIOBase):
    """Bound actual input bytes read, including ignored CSV columns and escapes."""

    def __init__(self, source, limit: int) -> None:
        super().__init__()
        self._source = source
        self._limit = limit
        self.bytes_read = 0

    def readable(self) -> bool:
        return True

    def readinto(self, destination) -> int:
        remaining = self._limit - self.bytes_read
        if remaining <= 0:
            # Only a one-byte probe distinguishes exact-size EOF from growth.
            if self._source.read(1):
                raise InspectionError("Input exceeds byte budget")
            return 0
        read = self._source.readinto(memoryview(destination)[:remaining])
        if read is None:
            return 0
        self.bytes_read += read
        return read


def _timestamp(value: str) -> datetime | None:
    if not value or len(value) > 50:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or not (2000 <= dt.year <= 2100):
            return None
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _duration(value: str) -> int | None:
    if not value or len(value) > 30:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            return None
        milliseconds = int(number)
        if 0 <= milliseconds <= MAX_DURATION_MS:
            return milliseconds
    except (ValueError, OverflowError):
        pass
    return None


def _reason(value: str) -> str:
    if value in NATURAL:
        return "natural"
    if value in SKIP:
        return "skip"
    if not value:
        return "missing"
    if value in NEUTRAL:
        return "neutral"
    return "unknown"


def _evidence(event: str, reason: str, played: int | None,
              total: int | None, identity: str, *,
              has_event_id: bool, has_timestamp: bool) -> str:
    if (event != "PLAY_END" or identity != "provider_id"
            or not has_event_id or not has_timestamp):
        return "abstain"
    if played is None or total is None or total <= 0 or played > total * 1.25:
        return "abstain"
    ratio = played / total
    if reason == "natural" and ratio >= 0.8:
        return "completion_candidate"
    if reason == "skip" and ratio < 0.3:
        return "early_skip_candidate"
    if reason == "skip" and ratio >= 0.8:
        return "late_skip_neutral"
    return "abstain"


def inspect(path: Path, *, max_bytes: int = MAX_BYTES,
            max_rows: int = MAX_ROWS) -> dict:
    """Stream at most a bounded file; return counts only, never source data."""
    byte_limit = min(max_bytes, MAX_BYTES)
    if byte_limit <= 0 or max_rows <= 0:
        raise InspectionError("Invalid inspection limits")
    counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    play_end_reason_counts: Counter[str] = Counter()
    identity_counts: Counter[str] = Counter()
    play_end_identity_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    # Provider-ID buckets are ephemeral digests, never raw catalog identifiers.
    provider_candidate_buckets: dict[bytes, Counter[str]] = {}
    # Diagnostics retain only in-memory, one-way fingerprints. These help
    # distinguish a possible catalog-track ID from a reused source/provider ID.
    provider_play_end_counts: Counter[bytes] = Counter()
    provider_title_album_labels: dict[bytes, set[bytes]] = {}
    metadata_only_labels: set[bytes] = set()
    # A conflicting duplicate revokes earlier diagnostic evidence.
    seen_ids: dict[bytes, tuple[bytes | None, str, bytes | None]] = {}
    min_time: datetime | None = None
    max_time: datetime | None = None
    scanned_characters = 0

    try:
        with ExitStack() as stack:
            raw = stack.enter_context(path.open("rb"))
            original = os.fstat(raw.fileno())
            if (not stat.S_ISREG(original.st_mode)
                    or not 0 < original.st_size <= byte_limit):
                raise InspectionError("Input outside permitted size limit")
            guarded = _ByteBudgetReader(raw, byte_limit)
            stream = stack.enter_context(io.TextIOWrapper(
                io.BufferedReader(guarded), encoding="utf-8-sig", newline=""
            ))
            # Prevent an unbounded CSV field from consuming arbitrary memory.
            csv.field_size_limit(MAX_FIELD)
            reader = csv.reader(stream, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise InspectionError("Missing CSV header") from None
            if (len(header) > MAX_FIELDS or len(header) != len(set(header))
                    or not REQUIRED.issubset(header)):
                raise InspectionError("Invalid or incomplete CSV schema")
            positions = {name: header.index(name) for name in READ_FIELDS if name in header}
            for row in reader:
                scanned_characters += sum(len(value) for value in row)
                if scanned_characters > min(max_bytes, MAX_BYTES):
                    raise InspectionError("Input exceeds streaming budget")
                counts["rows"] += 1
                if counts["rows"] > min(max_rows, MAX_ROWS):
                    raise InspectionError("Input exceeds row limit")
                if len(row) != len(header):
                    counts["malformed_rows"] += 1
                    continue
                # Only extract allowlisted fields; all other columns are ignored.
                def get(name: str) -> str:
                    return row[positions[name]].strip() if name in positions else ""
                event_id = get("Event ID")
                event_digest: bytes | None = None
                payload_fingerprint: bytes | None = None
                if event_id:
                    counts["event_ids_present"] += 1
                    event_digest = hashlib.blake2s(
                        event_id.encode("utf-8"), digest_size=16
                    ).digest()
                    # Hash only explicitly allowed fields (never account, IP,
                    # location or device columns). Store digests, not titles.
                    payload = hashlib.blake2s(digest_size=16)
                    for field_name in sorted(READ_FIELDS - {"Event ID"}):
                        value = get(field_name).encode("utf-8")
                        payload.update(len(value).to_bytes(4, "big"))
                        payload.update(value)
                    payload_fingerprint = payload.digest()
                    if event_digest in seen_ids:
                        counts["duplicate_event_ids"] += 1
                        old_fingerprint, old_evidence, old_provider = seen_ids[event_digest]
                        if (old_fingerprint is not None
                                and old_fingerprint != payload_fingerprint):
                            counts["conflicting_duplicate_event_ids"] += 1
                            if old_evidence != "abstain":
                                evidence_counts[old_evidence] -= 1
                                if evidence_counts[old_evidence] == 0:
                                    del evidence_counts[old_evidence]
                                evidence_counts["abstain"] += 1
                            if old_provider is not None and old_evidence in {
                                "completion_candidate", "early_skip_candidate"
                            }:
                                bucket = provider_candidate_buckets[old_provider]
                                bucket[old_evidence] -= 1
                                if bucket[old_evidence] == 0:
                                    del bucket[old_evidence]
                                if not bucket:
                                    del provider_candidate_buckets[old_provider]
                            # Conflict is sticky; later duplicates cannot
                            # re-establish the original candidate as trusted.
                            seen_ids[event_digest] = (None, "abstain", None)
                        continue
                    if len(seen_ids) >= MAX_DISTINCT_EVENT_IDS:
                        raise InspectionError("Event identity budget exceeded")
                else:
                    counts["missing_event_ids"] += 1

                event = get("Event Type")
                category = event if event in EVENT_TYPES else "missing" if not event else "unknown"
                event_counts[category] += 1
                reason = _reason(get("End Reason Type"))
                reason_counts[reason] += 1
                played = _duration(get("Play Duration Milliseconds"))
                duration = _duration(get("Media Duration In Milliseconds"))
                if played is not None:
                    counts["valid_play_durations"] += 1
                elif get("Play Duration Milliseconds"):
                    counts["invalid_play_durations"] += 1
                if duration is not None and duration > 0:
                    counts["valid_media_durations"] += 1
                elif get("Media Duration In Milliseconds"):
                    counts["invalid_media_durations"] += 1
                provider = get("Provider ID")
                title = get("Song Name")
                album = get("Album Name")
                identity = ("provider_id" if provider else
                            "ambiguous_metadata" if title or album else "missing")
                identity_counts[identity] += 1
                start_time = _timestamp(get("Event Start Timestamp"))
                end_time = _timestamp(get("Event End Timestamp"))
                if start_time and end_time and end_time < start_time:
                    counts["reversed_timestamp_pairs"] += 1
                eligible_time = bool(
                    start_time and end_time and start_time <= end_time
                )
                evidence = _evidence(
                    event, reason, played, duration, identity,
                    has_event_id=bool(event_id), has_timestamp=eligible_time,
                )
                evidence_counts[evidence] += 1
                provider_digest = None
                if provider and event == "PLAY_END" and evidence in {
                    "completion_candidate", "early_skip_candidate"
                }:
                    provider_digest = hashlib.blake2s(
                        provider.encode("utf-8"), digest_size=16
                    ).digest()
                    provider_candidate_buckets.setdefault(
                        provider_digest, Counter()
                    )[evidence] += 1
                if event_digest is not None and payload_fingerprint is not None:
                    seen_ids[event_digest] = (
                        payload_fingerprint, evidence, provider_digest
                    )
                if event == "PLAY_END":
                    counts["play_end_rows"] += 1
                    if provider:
                        identity_digest = hashlib.blake2s(
                            provider.encode("utf-8"), digest_size=16
                        ).digest()
                        provider_play_end_counts[identity_digest] += 1
                        if title or album:
                            label_hash = hashlib.blake2s(digest_size=16)
                            for part in (title, album):
                                normalized = part.strip().casefold().encode("utf-8")
                                label_hash.update(len(normalized).to_bytes(4, "big"))
                                label_hash.update(normalized)
                            provider_title_album_labels.setdefault(
                                identity_digest, set()
                            ).add(label_hash.digest())
                        else:
                            counts["play_end_provider_without_title_album"] += 1
                    elif title or album:
                        label_hash = hashlib.blake2s(digest_size=16)
                        for part in (title, album):
                            normalized = part.strip().casefold().encode("utf-8")
                            label_hash.update(len(normalized).to_bytes(4, "big"))
                            label_hash.update(normalized)
                        metadata_only_labels.add(label_hash.digest())
                    play_end_reason_counts[reason] += 1
                    play_end_identity_counts[identity] += 1
                    if event_id:
                        counts["play_end_event_ids_present"] += 1
                    if eligible_time:
                        counts["play_end_valid_timestamp_pairs"] += 1
                    if played is not None and duration is not None and duration > 0:
                        counts["play_end_valid_duration_pairs"] += 1
                    if provider:
                        counts["play_end_provider_ids"] += 1
                for name, parsed in (
                    ("Event Start Timestamp", start_time),
                    ("Event End Timestamp", end_time),
                ):
                    raw_time = get(name)
                    if parsed:
                        counts["valid_timestamps"] += 1
                        if min_time is None or parsed < min_time:
                            min_time = parsed
                        if max_time is None or parsed > max_time:
                            max_time = parsed
                    elif raw_time:
                        counts["invalid_timestamps"] += 1
            counts["distinct_event_ids"] = len(seen_ids)
            multi_label_providers = {
                key for key, labels in provider_title_album_labels.items()
                if len(labels) > 1
            }
            identity_quality = {
                "distinct_provider_ids_on_play_end": len(provider_play_end_counts),
                "provider_ids_with_multiple_title_album_labels": len(
                    multi_label_providers
                ),
                "play_end_events_on_multi_label_provider_ids": sum(
                    provider_play_end_counts[key] for key in multi_label_providers
                ),
                "completion_or_early_skip_candidates_on_multi_label_provider_ids": sum(
                    provider_candidate_buckets.get(key, Counter())[
                        "completion_candidate"
                    ] + provider_candidate_buckets.get(key, Counter())[
                        "early_skip_candidate"
                    ]
                    for key in multi_label_providers
                ),
                "maximum_play_end_events_on_one_provider_id": max(
                    provider_play_end_counts.values(), default=0
                ),
                "maximum_distinct_title_album_labels_on_one_provider_id": max(
                    (len(labels) for labels in provider_title_album_labels.values()),
                    default=0,
                ),
                "distinct_title_album_labels_without_provider_id": len(
                    metadata_only_labels
                ),
            }
            provider_rollup = {
                "buckets_with_multiple_completion_events": sum(
                    bucket["completion_candidate"] >= 2
                    for bucket in provider_candidate_buckets.values()
                ),
                "buckets_with_completion_and_early_skip_events": sum(
                    bucket["completion_candidate"] >= 1
                    and bucket["early_skip_candidate"] >= 1
                    for bucket in provider_candidate_buckets.values()
                ),
                "buckets_with_early_skip_events": sum(
                    bucket["early_skip_candidate"] >= 1
                    for bucket in provider_candidate_buckets.values()
                ),
                "buckets_with_completion_events": sum(
                    bucket["completion_candidate"] >= 1
                    for bucket in provider_candidate_buckets.values()
                ),
            }
            final = os.fstat(raw.fileno())
            if (final.st_size != original.st_size
                    or final.st_mtime_ns != original.st_mtime_ns):
                raise InspectionError("Input changed during inspection")
        return {
            "format": "apple_music_play_activity_aggregate_v1",
            "counts": dict(sorted(counts.items())),
            "event_types": dict(sorted(event_counts.items())),
            "end_reason_categories": dict(sorted(reason_counts.items())),
            "play_end_reason_categories": dict(sorted(play_end_reason_counts.items())),
            "identity_confidence": dict(sorted(identity_counts.items())),
            "play_end_identity_confidence": dict(sorted(play_end_identity_counts.items())),
            "non_persistent_evidence_candidates": dict(sorted(evidence_counts.items())),
            "anonymous_provider_candidate_buckets": provider_rollup,
            "provider_identity_quality": identity_quality,
            "utc_coverage": {
                "earliest_date": min_time.date().isoformat() if min_time else None,
                "latest_date": max_time.date().isoformat() if max_time else None,
            },
            "warnings": [
                "Counts are events, not independent plays or confirmed preferences.",
                "Candidate evidence is not identity/session-deduplicated against Apple or Sonos.",
                "No track/artist inference from metadata-only identity.",
                "Multiple provider-bucket events may still be one listening session.",
                "Provider ID is unverified as a track identifier; multi-label IDs are ambiguous.",
                "No data was imported into HomeHub or transmitted.",
            ],
        }
    except InspectionError:
        raise
    except (OSError, UnicodeError, csv.Error, ValueError, OverflowError):
        raise InspectionError("Unable to parse CSV safely") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only aggregate Apple Music CSV inspection")
    parser.add_argument("csv_path", type=Path)
    arguments = parser.parse_args()
    try:
        result = inspect(arguments.csv_path)
    except InspectionError as error:
        parser.exit(2, f"Inspection rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
