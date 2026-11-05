"""Unregistered, in-process #431 one-artist review receiver REHEARSAL.

No FastAPI route, HTTP listener, credential discovery, filesystem, provider,
DB, telemetry, playback or network. This is not an approved real-data endpoint.

An eventual HTTP boundary MUST authenticate every peer, enforce encrypted
server-authenticated transport, reject CSRF/proxy tricks and guard body logging.
The ``transport_verified`` parameter is a synthetic test input, not proof of
TLS, and MUST NEVER be populated from an HTTP client-controlled field.
"""
from __future__ import annotations

import hmac
import json
import time
from threading import Lock
from dataclasses import dataclass
from typing import Callable
from unicodedata import category

MAX_JSON_BODY_BYTES = 1024
MAX_ARTIST_UTF8_BYTES = 512
SOURCE = "apple_daily_tracks"
EVIDENCE = "unverified_artist_label_day_exposure"
ERROR = "Artist review was not accepted."
_ALLOWED = frozenset({
    "artist_label", "source", "evidence", "identity_status",
    "preference_eligible", "session_proven", "cross_source_independent",
    "actuation_eligible",
})


class ReviewRefused(ValueError):
    def __init__(self) -> None:
        super().__init__(ERROR)


@dataclass(frozen=True, slots=True, repr=False)
class EphemeralReview:
    artist_label: str
    source: str = SOURCE
    evidence: str = EVIDENCE
    identity_status: str = "unverified"

    def __repr__(self) -> str:
        return "EphemeralReview(<redacted>)"


def _validate_body(body: object) -> str:
    if type(body) is not dict or set(body) != _ALLOWED:
        raise ReviewRefused()
    if any(type(value) is not str for value in body.values()):
        raise ReviewRefused()
    try:
        wire_size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, UnicodeError, ValueError):
        raise ReviewRefused() from None
    if wire_size > MAX_JSON_BODY_BYTES:
        raise ReviewRefused()
    artist = body["artist_label"]
    if (not artist or artist.strip() != artist or len(artist) > 256
            or any(category(ch).startswith("C") for ch in artist)):
        raise ReviewRefused()
    try:
        if len(artist.encode("utf-8")) > MAX_ARTIST_UTF8_BYTES:
            raise ReviewRefused()
    except UnicodeError:
        raise ReviewRefused() from None
    exact = {
        "source": SOURCE,
        "evidence": EVIDENCE,
        "identity_status": "unverified",
        "preference_eligible": "false",
        "session_proven": "false",
        "cross_source_independent": "false",
        "actuation_eligible": "false",
    }
    if any(body[k] != v for k, v in exact.items()):
        raise ReviewRefused()
    return artist


class OfflineSingleArtistReceiver:
    """One temporary in-memory slot and one successful admission per instance.

    - Dedicated high-entropy key passed in externally, never discovered here.
    - Requires *upstream*-verified secure transport on EVERY call.
    - The latter is intentionally not provided by this offline package.
    - No automatic retry, no concurrent second artist, no ACK content.
    """

    def __init__(self, *, expected_credential: bytes, ttl_seconds: int = 60,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if (type(expected_credential) is not bytes or len(expected_credential) < 32
                or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 120
                or not callable(clock)):
            raise ReviewRefused()
        self._expected = expected_credential
        self._lock = Lock()
        self._ttl = ttl_seconds
        self._clock = clock
        self._opened = float(clock())
        self._artist: str | None = None
        self._consumed = False
        self._closed = False

    def __repr__(self) -> str:
        return "OfflineSingleArtistReceiver(<redacted>)"

    def _require_authorized(self, credential: bytes, *, transport_verified: bool) -> None:
        if (transport_verified is not True or type(credential) is not bytes
                or not hmac.compare_digest(credential, self._expected)):
            raise ReviewRefused()
        if self._closed or self._clock() < self._opened or self._clock() - self._opened > self._ttl:
            self._clear()
            raise ReviewRefused()

    def receive(self, body: object, *, credential: bytes,
                transport_verified: bool = False) -> dict[str, str]:
        with self._lock:
            self._require_authorized(credential, transport_verified=transport_verified)
            if self._consumed or self._artist is not None:
                raise ReviewRefused()
            artist = _validate_body(body)
            # Single slot, only one successful submission for this receiver.
            self._consumed = True
            self._artist = artist
            return {"status": "received_for_temporary_review"}

    def take_once(self, *, credential: bytes,
                  transport_verified: bool = False) -> EphemeralReview:
        with self._lock:
            self._require_authorized(credential, transport_verified=transport_verified)
            if self._artist is None:
                raise ReviewRefused()
            artist = self._artist
            self._artist = None
            self._closed = True
            return EphemeralReview(artist)

    def discard(self) -> None:
        with self._lock:
            self._clear()

    def _clear(self) -> None:
        """Caller holds lock, except the constructor's unexposed state."""
        self._artist = None
        self._closed = True
        self._consumed = True
