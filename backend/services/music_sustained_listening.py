"""Strict append-only listening continuity. No transport or cleanup operation.

A selected session must supply original verified queue provenance. A coarse
Sonos track boundary is never sufficient by itself to grant authority.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from urllib.parse import unquote

from backend.services.music_continuation import MAX_CONTINUATION_TRACKS, QueuedSong
from backend.services.music_favorite_execution import _exact_queued_songs
from backend.services.music_selected_plan import _exact_song

MAX_SESSION_SECONDS = 4 * 3600
MAX_SESSION_TRACKS = 96
MAX_SAMPLE_GAP = 12.0
MAX_VALIDATION_AGE = 3.0
NEAR_END_SECONDS = 6.0
POSITION_TOLERANCE = 2.0
REFILL_AT_REMAINING = 2


def _seconds(value) -> float | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isascii() or not part.isdigit() for part in parts):
        return None
    hours, minutes, seconds = map(int, parts)
    if minutes >= 60 or seconds >= 60:
        return None
    return float(hours * 3600 + minutes * 60 + seconds)


@dataclass(frozen=True)
class QueueProof:
    uid: str
    revision: str
    first_hash: str
    volume: int
    songs: tuple[QueuedSong, ...]

    def valid(self) -> bool:
        return (
            bool(self.uid and self.revision and self.first_hash)
            and type(self.volume) is int and self.volume > 0
            and 1 <= len(self.songs) <= MAX_SESSION_TRACKS
            and all(
                song.provider_id.isascii() and song.provider_id.isdigit()
                and bool(song.artist and song.title) for song in self.songs
            )
        )


@dataclass(frozen=True)
class PlaybackCursor:
    observed_at: float
    track: int
    position: float
    duration: float


def sample_cursor(proof: QueueProof, evidence, *, now: float) -> PlaybackCursor | None:
    """Require exact queue/source, known track timing, and active unmuted playback."""
    if not proof.valid() or not isinstance(evidence, dict) or not math.isfinite(now):
        return None
    index = evidence.get("queue_track")
    if (
        evidence.get("queue_uid") != proof.uid
        or evidence.get("queue_update_id") != proof.revision
        or evidence.get("queue_first_item_hash") != proof.first_hash
        or evidence.get("queue_size") != len(proof.songs)
        or evidence.get("current_uri") != f"x-rincon-queue:{proof.uid}#0"
        or evidence.get("coordinator") is not True
        or evidence.get("transport_state") != "PLAYING"
        or evidence.get("play_mode") != "NORMAL"
        or evidence.get("mute") is not False
        or evidence.get("volume") != proof.volume
        or type(index) is not int or not 1 <= index <= len(proof.songs)
    ):
        return None
    song = proof.songs[index - 1]
    uri = evidence.get("queue_track_uri")
    if not isinstance(uri, str) or unquote(uri).split("?", 1)[0].casefold() != f"x-sonos-http:song:{song.provider_id}":
        return None
    position = _seconds(evidence.get("position"))
    duration = _seconds(evidence.get("duration"))
    if position is None or duration is None or duration <= 0 or not 0 <= position < duration:
        return None
    return PlaybackCursor(now, index, position, duration)


def continuous_progress(previous: PlaybackCursor, current: PlaybackCursor) -> bool:
    """Conservative continuity, not proof of a natural end.

    A manual Next at the exact expected boundary may be indistinguishable;
    append-only work never restarts playback or claims transport authority.
    """
    elapsed = current.observed_at - previous.observed_at
    if not 0 < elapsed <= MAX_SAMPLE_GAP:
        return False
    if current.track == previous.track:
        advance = current.position - previous.position
        return (
            current.duration == previous.duration and 0 < advance <= elapsed + POSITION_TOLERANCE
            and advance >= max(0, elapsed - POSITION_TOLERANCE)
        )
    if current.track != previous.track + 1:
        return False
    remaining = previous.duration - previous.position
    # Adjacent position and time must fit a single uninterrupted transition.
    return (
        0 < remaining <= NEAR_END_SECONDS
        and abs(remaining + current.position - elapsed) <= POSITION_TOLERANCE
    )


def should_refill(proof: QueueProof, cursor: PlaybackCursor, *, started_at: float) -> bool:
    """Bounded replenishment only near queue end while still playing."""
    return (
        proof.valid()
        and 0 <= cursor.observed_at - started_at < MAX_SESSION_SECONDS
        and len(proof.songs) < MAX_SESSION_TRACKS
        and 1 <= cursor.track <= len(proof.songs)
        and len(proof.songs) - cursor.track <= REFILL_AT_REMAINING
        and cursor.duration - cursor.position >= NEAR_END_SECONDS
    )

def _read_prefix_sync(device, size, revision):
    """Read the complete queue in bounded pages, with one exact revision."""
    if not 1 <= size <= MAX_SESSION_TRACKS:
        return None
    rows = []
    for offset in range(0, size, 32):
        count = min(32, size - offset)
        result = device.contentDirectory.Browse([
            ("ObjectID", "Q:0"), ("BrowseFlag", "BrowseDirectChildren"),
            ("Filter", "*"), ("StartingIndex", offset), ("RequestedCount", count),
            ("SortCriteria", ""),
        ], timeout=3.0)
        xml = result.get("Result")
        if (
            str(result.get("UpdateID") or "") != revision
            or int(result.get("TotalMatches") or 0) != size
            or int(result.get("NumberReturned") or 0) != count
            or not isinstance(xml, str) or len(xml) > 512000
        ):
            return None
        root = ET.fromstring(xml)
        if root.tag.rsplit("}", 1)[-1] != "DIDL-Lite":
            return None
        page = [ET.tostring(item, encoding="unicode") for item in root
                if item.tag.rsplit("}", 1)[-1] == "item"]
        if len(page) != count:
            return None
        rows.extend(page)
    return tuple(rows)


def started_queue_proof(snapshot, uid, volume, rows):
    """Construct only from the executor's pre-Play exact ordered snapshots."""
    try:
        if not rows or len(rows) != snapshot[1]:
            return None
        songs = _exact_queued_songs(rows)
        proof = QueueProof(uid, snapshot[0], hashlib.sha256(snapshot[2].encode()).hexdigest(),
                           volume, songs)
        return proof if proof.valid() and len(songs) == len(rows) else None
    except Exception:
        return None


@dataclass(frozen=True)
class RetainedQueue:
    """Last verified queue identity; conveys no surviving write authority."""
    owner_scope: str
    sonos: object
    device: object
    proof: QueueProof
    rows: tuple[str, ...]
    expires: float


@dataclass
class _Active:
    authority: object
    token: object
    sonos: object
    device: object
    proof: QueueProof
    rows: tuple[str, ...]
    mode: str
    allowed: object
    started_at: float
    cursor: PlaybackCursor | None = None
    initial_track: int = 1


def _same_track(previous, current):
    if current is None or current.track != previous.track or current.duration != previous.duration:
        return False
    elapsed = current.observed_at - previous.observed_at
    delta = current.position - previous.position
    return (0 <= elapsed <= MAX_SAMPLE_GAP
            and 0 <= delta <= elapsed + POSITION_TOLERANCE
            and delta >= max(0, elapsed - POSITION_TOLERANCE))


class SustainedListening:
    """One process-local owner-selected queue; only append while PLAYING."""

    def __init__(self, planner, *, clock=time.monotonic):
        self._planner = planner
        self._clock = clock
        self._active: _Active | None = None
        self._retained: RetainedQueue | None = None

    def install(self, *, authority, token, sonos, device, proof, rows, mode, allowed,
                owner_scope=None, initial_track=1):
        if proof is None or len(rows) != len(proof.songs) or not 1 <= initial_track <= len(rows):
            return False
        self._active = _Active(
            authority, token, sonos, device, proof, rows, mode, allowed, self._clock(),
            initial_track=initial_track,
        )
        self._retained = RetainedQueue(
            owner_scope, sonos, device, proof, rows, self._clock() + MAX_SESSION_SECONDS,
        ) if owner_scope else None
        return True

    def retained(self, owner_scope, sonos):
        origin = self._retained
        if (
            origin is not None and origin.owner_scope == owner_scope
            and origin.sonos is sonos and origin.device is sonos.device
            and self._clock() < origin.expires
        ):
            return origin
        return None

    def consume_retained(self, origin):
        if self._retained is not origin or self._clock() >= origin.expires:
            return False
        self._retained = None
        return True

    def restore_unwritten_retained(self, origin):
        # Only the caller with unchanged fresh authority may restore a
        # consumed identity after a definitively non-mutating refusal.
        if self._retained is None and self._clock() < origin.expires:
            self._retained = origin

    def forget_retained(self):
        self._retained = None

    def stop(self):
        self._active = None

    def _current(self, session):
        try:
            return (
                self._active is session
                and 0 <= self._clock() - session.started_at < MAX_SESSION_SECONDS
                and session.allowed()
                and session.sonos.device is session.device
                and session.authority.listening_append_is_current(session.token)
            )
        except Exception:
            return False

    async def _sample(self, session, proof=None):
        if not self._current(session):
            return None
        evidence = await session.sonos.get_prepare_evidence()
        if not self._current(session):
            return None
        return sample_cursor(proof or session.proof, evidence, now=self._clock())

    async def _refill(self, session):
        tail = await self._planner.preview_container(session.proof.songs, mode=session.mode)
        if not tail or not self._current(session):
            return False
        if len(tail) > MAX_CONTINUATION_TRACKS:
            return False
        tail = tail[:MAX_SESSION_TRACKS - len(session.rows)]
        ids = {song.provider_id for song in session.proof.songs}
        names = {(song.artist.casefold(), song.title.casefold()) for song in session.proof.songs}
        for item in tail:
            artist = item.metadata.get("artist_name")
            if (
                not isinstance(artist, str) or not artist.strip()
                or not _exact_song(item, item.provider_id, item.title, artist)
                or item.provider_id in ids or (artist.casefold(), item.title.casefold()) in names
                or session.sonos._canonical_apple_music_share_link(item.uri) != f"song:{item.provider_id}"
            ):
                return False
            ids.add(item.provider_id)
            names.add((artist.casefold(), item.title.casefold()))

        # Catalog/provider reads must not occupy the shared audio writer lock.
        # A manual command can finish while this read-only refresh is pending.
        if not self._current(session) or not await self._planner.revalidate(tail, mode=session.mode):
            return False
        validated_at = self._clock()
        if not self._current(session):
            return False

        async def admitted():
            if (
                not self._current(session)
                or not 0 <= self._clock() - validated_at <= MAX_VALIDATION_AGE
            ):
                return False
            current = await self._sample(session)
            if not _same_track(session.cursor, current) or not should_refill(
                session.proof, current, started_at=session.started_at,
            ):
                return False
            session.cursor = current
            for item in tail:
                if not self._current(session):
                    return False
                size = len(session.rows)
                proof = session.proof
                previous = session.cursor

                def append_one():
                    if not self._current(session):
                        return None
                    if _read_prefix_sync(session.device, size, proof.revision) != session.rows:
                        return None
                    evidence = session.sonos._prepare_evidence_sync()
                    fresh = sample_cursor(proof, evidence, now=self._clock())
                    if (
                        not _same_track(previous, fresh)
                        or fresh.duration - fresh.position < NEAR_END_SECONDS
                        or not self._current(session)
                    ):
                        return None
                    return session.sonos._add_apple_music_share_link_sync(item.uri)

                position = await session.sonos._safe_mutation_call(append_one)
                if type(position) is not int or position != size + 1 or not self._current(session):
                    return False
                first = await session.sonos._safe_call(
                    session.sonos._queue_item_snapshot_sync, 0, 1.0,
                )
                if (
                    not first or len(first) != 3 or first[1] != size + 1
                    or not first[0] or first[0] == proof.revision
                    or hashlib.sha256(first[2].encode()).hexdigest() != proof.first_hash
                ):
                    return False
                updated = await session.sonos._safe_call(
                    _read_prefix_sync, session.device, size + 1, first[0],
                )
                if updated is None or updated[:-1] != session.rows:
                    return False
                next_proof = started_queue_proof(first, proof.uid, proof.volume, updated)
                expected = QueuedSong(item.provider_id, item.title, item.metadata["artist_name"])
                if next_proof is None or next_proof.songs != proof.songs + (expected,):
                    return False
                fresh = await self._sample(session, next_proof)
                if not _same_track(previous, fresh):
                    return False
                if self._retained is not None and self._retained.proof is proof:
                    self._retained = replace(self._retained, proof=next_proof, rows=updated)
                session.proof, session.rows, session.cursor = next_proof, updated, fresh
            return True

        executed, result = await session.authority.run_listening_append(session.token, admitted)
        return executed and result is True

    async def tick(self):
        session = self._active
        if session is None:
            return
        try:
            cursor = await self._sample(session)
            if cursor is None:
                raise ValueError("playing evidence unavailable")
            if session.cursor is None:
                # Start proof was advancing the selected item. Never adopt an already
                # changed source/track, or a session whose first sample is late.
                if cursor.track != session.initial_track or self._clock() - session.started_at > MAX_SAMPLE_GAP:
                    raise ValueError("initial cursor unavailable")
                session.cursor = cursor
                return
            if not continuous_progress(session.cursor, cursor):
                raise ValueError("playback continuity lost")
            session.cursor = cursor
            if should_refill(session.proof, cursor, started_at=session.started_at):
                if not await self._refill(session):
                    raise ValueError("refill unavailable or uncertain")
        except Exception:
            # Never retry uncertain writes, restart playback, or remove any
            # accepted appends. A newer session must not be cleared by this one.
            if self._active is session:
                self.stop()

    async def run_loop(self):
        try:
            while True:
                await asyncio.sleep(4)
                await self.tick()
        finally:
            self.stop()
            self.forget_retained()
