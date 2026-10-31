"""Synthetic-only, aggregate preview of possible Apple Music taste evidence.

This is NOT an importer. No HomeHub runtime/database, file, playback, network,
or persistent state. A catalog-verified recording AND independently validated
session and cross-source nonoverlap are all required to emit even a candidate.
The existing Apple Play Activity/Daily Tracks join establishes NONE of these.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_INPUT_EVENTS = 250_000
MAX_KEY_LENGTH = 256
MAX_DURATION_MS = 24 * 60 * 60 * 1000
SOURCE = "apple_play_activity"
TRACK_PROOFS = frozenset({"catalog_exact", "library_exact"})
SESSION_PROOF = "independent_playback_session"
CROSS_SOURCE_PROOF = "no_overlap_verified"
NATURAL = "NATURAL_END_OF_TRACK"
SKIPS = frozenset({"TRACK_SKIPPED_FORWARDS", "TRACK_SKIPPED_BACKWARDS"})
FAMILIARITY_NEUTRAL = frozenset({
    "PLAYBACK_MANUALLY_PAUSED", "PLAYBACK_SUSPENDED",
    "EXITED_APPLICATION", "TRACK_SELECTED_FOR_PLAYBACK", "OTHER",
})


@dataclass(frozen=True)
class ApplePreviewEvent:
    """In-memory normalized input. Never serialize this object or log it.

    recording_key must come from separately verified recording identity, NOT
    Provider ID, title-only matching or the aggregate Daily Tracks join.
    session_key must be an independently evidenced playback session, NOT Event ID.
    cross_source_proof requires an independent Sonos/other-source reconciliation.
    """

    event_id: str
    session_key: str
    recording_key: str
    ended_at: datetime | None
    play_duration_ms: int | None
    media_duration_ms: int | None
    end_reason: str
    track_proof: str = "unverified"
    session_proof: str = "unverified"
    cross_source_proof: str = "unknown"
    source: str = SOURCE
    event_type: str = "PLAY_END"


class PreviewRejected(ValueError):
    """Fixed, non-sensitive rejection only."""


def _key(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_KEY_LENGTH and bool(value.strip())


def _duration(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_DURATION_MS


def _signature(event: ApplePreviewEvent) -> tuple:
    """Ignore Event ID: two IDs may still describe one session."""
    return (
        event.source, event.event_type, event.session_key, event.recording_key,
        event.track_proof, event.session_proof, event.cross_source_proof,
        event.ended_at, event.play_duration_ms, event.media_duration_ms,
        event.end_reason,
    )


def _classify(event: ApplePreviewEvent) -> str:
    if event.source != SOURCE or event.event_type != "PLAY_END":
        return "abstain_unsupported_source_or_event"
    if event.track_proof not in TRACK_PROOFS or not _key(event.recording_key):
        return "abstain_unverified_recording"
    if event.session_proof != SESSION_PROOF:
        return "abstain_unverified_session"
    if event.cross_source_proof != CROSS_SOURCE_PROOF:
        return "abstain_cross_source_overlap_unknown"
    at = event.ended_at
    if not isinstance(at, datetime) or at.tzinfo is None:
        return "abstain_invalid_timestamp"
    try:
        utc = at.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return "abstain_invalid_timestamp"
    if not 2000 <= utc.year <= 2100:
        return "abstain_invalid_timestamp"
    played, duration = event.play_duration_ms, event.media_duration_ms
    if (not _duration(played) or not _duration(duration)
            or duration <= 0 or played > duration * 1.25):
        return "abstain_invalid_durations"
    ratio = played / duration
    if event.end_reason == NATURAL and ratio >= 0.8:
        return "preview_completion_only"
    if event.end_reason in SKIPS and ratio < 0.3:
        return "preview_early_skip_only"
    if event.end_reason in ({NATURAL} | SKIPS | FAMILIARITY_NEUTRAL):
        if played >= 60_000:
            return "preview_familiarity_only"
        return "preview_neutral_no_preference"
    return "abstain_unknown_or_nonplay_end_reason"


def preview_apple_taste(events: Iterable[ApplePreviewEvent]) -> dict:
    """Return anonymous preview counters, *never* weights or identities.

    Duplicate event IDs and conflicting records for the same session are
    conservatively revoked. Multiple Event IDs for one proven session count
    at most once, regardless of input order. No session can be inferred from
    an Apple Event ID or day+title coincidence.
    """
    counts: Counter[str] = Counter()
    first_sessions: dict[str, ApplePreviewEvent] = {}
    first_event_ids: dict[str, tuple[str, tuple]] = {}
    conflicting_sessions: set[str] = set()
    for event in events:
        counts["input_rows"] += 1
        if counts["input_rows"] > MAX_INPUT_EVENTS:
            raise PreviewRejected("Preview input exceeds event limit")
        if not isinstance(event, ApplePreviewEvent):
            counts["abstain_invalid_input"] += 1
            continue
        if (not _key(event.event_id) or not _key(event.session_key)
                or any(
                    not isinstance(value, str) or len(value) > MAX_KEY_LENGTH
                    for value in (
                        event.recording_key, event.track_proof, event.session_proof,
                        event.cross_source_proof, event.source, event.event_type,
                        event.end_reason,
                    )
                )):
            counts["abstain_invalid_input"] += 1
            continue

        signature = _signature(event)
        original = first_event_ids.get(event.event_id)
        if original is None:
            first_event_ids[event.event_id] = (event.session_key, signature)
        else:
            prior_session, prior_signature = original
            if prior_session != event.session_key or prior_signature != signature:
                conflicting_sessions.add(prior_session)
                conflicting_sessions.add(event.session_key)
                counts["conflicting_event_id_rows"] += 1
            else:
                counts["duplicate_event_id_rows"] += 1

        previous = first_sessions.get(event.session_key)
        if previous is None:
            first_sessions[event.session_key] = event
        elif _signature(previous) != signature:
            conflicting_sessions.add(event.session_key)
            counts["conflicting_session_rows"] += 1
        else:
            counts["duplicate_session_rows"] += 1

    counts["distinct_session_keys_seen"] = len(first_sessions)
    for session_key, event in first_sessions.items():
        if session_key in conflicting_sessions:
            counts["abstain_conflicting_identity_or_session"] += 1
        else:
            counts[_classify(event)] += 1
    counts["preview_only_not_imported"] = 1

    return {
        "format": "apple_taste_shadow_preview_v1",
        "counts": dict(sorted(counts.items())),
        "warnings": [
            "No user file or HomeHub database is read or written.",
            "Candidate classifications are not familiarity or preference weights.",
            "Apple Provider ID and provisional title/date joins cannot supply recording proof.",
            "Apple Event ID does not supply playback-session proof.",
            "Unknown Sonos/other-source overlap forces abstention.",
            "No presence, context, playback, recommendation or ranking effect.",
        ],
    }
