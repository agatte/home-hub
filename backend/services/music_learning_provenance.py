"""Session-scoped provenance for passive music learning.

The shared audio lease is the authority. For ordinary MusicMapper auto-play,
its lease id is also the durable learning-session id recorded in
sonos_playback_events. Historical rows intentionally remain unscoped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.audio_ownership import QUEUE_SOURCE, TRANSPORT

MODE_AUTOPLAY_OWNER = "music_mapper"
MODE_AUTOPLAY_PURPOSE = "mode_auto_play"
LEARNING_ELIGIBLE_METADATA_KEY = "learning_eligible"
OWNED_RETENTION_EVENT = "owned_retained"
PASSIVE_REWARD_THRESHOLD_SECONDS = 60.0

_SESSION_PROOF_KEYS = (
    "queue_uid",
    "queue_update_id",
    "queue_size",
    "queue_first_item_hash",
    "play_mode",
    "transport_state",
    "current_uri",
    "queue_track",
    "queue_track_uri",
)


@dataclass(frozen=True)
class OwnedPlaybackLearningOrigin:
    session_id: str
    ownership_lease_id: str
    favorite_title: str
    mode: str
    weather_class: str | None
    timestamp: Any


@dataclass(frozen=True)
class OwnedMusicLearningSession:
    session_id: str
    ownership_lease_id: str
    favorite_title: str
    mode: str
    weather_class: str | None
    sonos_evidence: dict[str, Any]


def session_from_lease(
    lease: dict[str, Any] | None,
) -> OwnedMusicLearningSession | None:
    """Project one established MusicMapper lease into learning provenance."""
    if not lease:
        return None
    if lease.get("owner") != MODE_AUTOPLAY_OWNER:
        return None
    if lease.get("purpose") != MODE_AUTOPLAY_PURPOSE:
        return None

    held = frozenset(lease.get("dimensions") or ())
    if not {QUEUE_SOURCE, TRANSPORT} <= held:
        return None

    evidence = lease.get("evidence") or {}
    if evidence.get("phase") != "owned":
        return None
    sonos_evidence = evidence.get("sonos")
    if not isinstance(sonos_evidence, dict):
        return None

    metadata = lease.get("metadata") or {}
    if metadata.get(LEARNING_ELIGIBLE_METADATA_KEY) is not True:
        return None
    title = str(metadata.get("favorite_title") or "").strip()
    mode = str(metadata.get("mode") or "").strip()
    lease_id = str(lease.get("lease_id") or "").strip()
    if not lease_id or not title or not mode:
        return None

    weather = str(metadata.get("weather_class") or "").strip() or None
    return OwnedMusicLearningSession(
        session_id=lease_id,
        ownership_lease_id=lease_id,
        favorite_title=title,
        mode=mode,
        weather_class=weather,
        sonos_evidence=dict(sonos_evidence),
    )


async def capture_owned_music_session(
    audio_ownership,
) -> OwnedMusicLearningSession | None:
    """Capture the current eligible MusicMapper session before invalidation."""
    if audio_ownership is None:
        return None
    finder = getattr(audio_ownership, "find_lease", None)
    if finder is None:
        return None
    lease = await finder(
        owner=MODE_AUTOPLAY_OWNER,
        purpose=MODE_AUTOPLAY_PURPOSE,
    )
    return session_from_lease(lease)


def playback_still_matches_session(
    session: OwnedMusicLearningSession,
    current: dict[str, Any] | None,
) -> bool:
    """Require the same exact queue/source/track and active PLAYING transport."""
    if not current:
        return False
    if str(current.get("transport_state") or "").upper() != "PLAYING":
        return False
    return all(
        current.get(key) == session.sonos_evidence.get(key)
        for key in _SESSION_PROOF_KEYS
    )


def _event_session_identity(event: Any) -> tuple[str, str] | None:
    session_id = str(getattr(event, "session_id", "") or "").strip()
    lease_id = str(getattr(event, "ownership_lease_id", "") or "").strip()
    if not session_id or not lease_id or session_id != lease_id:
        return None
    return session_id, lease_id


def index_owned_playback_origins(
    events: list[Any],
) -> dict[str, OwnedPlaybackLearningOrigin]:
    """Index only explicitly scoped HomeHub auto-play session starts."""
    origins: dict[str, OwnedPlaybackLearningOrigin] = {}
    for event in events:
        if str(getattr(event, "event_type", "") or "").casefold() != "auto_play":
            continue
        if str(getattr(event, "triggered_by", "") or "").casefold() != "auto":
            continue
        identity = _event_session_identity(event)
        if identity is None:
            continue
        session_id, lease_id = identity
        title = str(getattr(event, "favorite_title", "") or "").strip()
        mode = str(getattr(event, "mode_at_time", "") or "").strip()
        if not title or not mode:
            continue
        # First durable origin wins. Duplicate start rows must not silently
        # redefine a session's candidate/container.
        origins.setdefault(
            session_id,
            OwnedPlaybackLearningOrigin(
                session_id=session_id,
                ownership_lease_id=lease_id,
                favorite_title=title,
                mode=mode,
                weather_class=(
                    str(getattr(event, "weather_class", "") or "").strip() or None
                ),
                timestamp=getattr(event, "timestamp", None),
            ),
        )
    return origins


def matching_owned_playback_origin(
    event: Any,
    origins: dict[str, OwnedPlaybackLearningOrigin],
) -> OwnedPlaybackLearningOrigin | None:
    """Resolve a passive event only when it belongs to the exact origin."""
    identity = _event_session_identity(event)
    if identity is None:
        return None
    session_id, lease_id = identity
    origin = origins.get(session_id)
    if origin is None or origin.ownership_lease_id != lease_id:
        return None

    title = str(getattr(event, "favorite_title", "") or "").strip()
    mode = str(getattr(event, "mode_at_time", "") or "").strip()
    if title and title != origin.favorite_title:
        return None
    if mode and mode != origin.mode:
        return None
    return origin
