"""#431 offline rehearsal of a *local* one-artist consent boundary.

NO NETWORK, API ROUTE, AUTHENTICATION OR PERSISTENCE. This module does not
prove that an operator or server is authenticated. Do not wire to a real
transport without independent review of those separate components.
"""
from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe
from unicodedata import category

ERROR = "Artist handoff was not authorized. No data sent."
RECIPIENT = "HomeHub Latitude (private, temporary review only)"
SOURCE = "apple_daily_tracks"
EVIDENCE = "unverified_artist_label_day_exposure"
BANDS = frozenset({"1 day", "2-3 days", "4-9 days", "10+ days"})
MAX_ARTIST_UTF8_BYTES = 512  # Keep in sync with the closed receiver contract.


class HandoffRefused(ValueError):
    def __init__(self):
        super().__init__(ERROR)


@dataclass(frozen=True, slots=True, repr=False)
class ArtistPreview:
    """Transient information for local UI confirmation, never telemetry."""

    artist_label: str
    date_band: str
    recipient: str
    challenge: str

    def __repr__(self) -> str:
        return "ArtistPreview(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class PreparedSingleArtist:
    """One permitted artist; body returns a new dict on each access."""

    _artist_label: str

    @property
    def body(self) -> dict[str, str]:
        # No mutable request body is retained or aliased by this container.
        return {
            "artist_label": self._artist_label,
            "source": SOURCE,
            "evidence": EVIDENCE,
            "identity_status": "unverified",
            "preference_eligible": "false",
            "session_proven": "false",
            "cross_source_independent": "false",
            "actuation_eligible": "false",
        }

    def __repr__(self) -> str:
        return "PreparedSingleArtist(<redacted>)"


def _check_artist(label: object, band: object) -> None:
    # The PC consent step must refuse any label the server's wire contract
    # would reject, so an offline confirmation never promises a doomed send.
    if (type(label) is not str or not label or label != label.strip()
            or len(label) > 256 or type(band) is not str or band not in BANDS
            or any(category(ch).startswith("C") for ch in label)):
        raise HandoffRefused()
    try:
        if len(label.encode("utf-8")) > MAX_ARTIST_UTF8_BYTES:
            raise HandoffRefused()
    except UnicodeError:
        raise HandoffRefused() from None


class OneArtistConsentSession:
    """Single source snapshot, one explicit approval, one payload, no retries.

    The caller must be the existing local reviewer; source provenance here is
    descriptive and does *not* authenticate a file, person, or server.
    """

    def __init__(self, candidates: tuple[tuple[str, str], ...]):
        if (not isinstance(candidates, tuple) or len(candidates) > 5000
                or any(not isinstance(x, tuple) or len(x) != 2 for x in candidates)):
            raise HandoffRefused()
        self._candidates = candidates
        self._preview_index: int | None = None
        self._challenge: str | None = None
        self._used = False
        self._closed = False

    def __repr__(self) -> str:
        return "OneArtistConsentSession(<redacted>)"

    def preview(self, index: int) -> ArtistPreview:
        if self._closed or self._used or type(index) is not int or index < 0 or index >= len(self._candidates):
            raise HandoffRefused()
        label, band = self._candidates[index]
        _check_artist(label, band)
        self._preview_index = index
        self._challenge = token_urlsafe(32)
        return ArtistPreview(label, band, RECIPIENT, self._challenge)

    def approve_once(self, challenge: str, recipient: str, *, confirmed: bool) -> PreparedSingleArtist:
        if (self._closed or self._used or confirmed is not True or self._challenge is None
                or type(challenge) is not str or challenge != self._challenge
                or recipient != RECIPIENT or self._preview_index is None):
            raise HandoffRefused()
        # Burn the authorization *before* constructing the payload. A failed
        # request must require a fresh human review, never transparent replay.
        self._used = True
        index = self._preview_index
        self._preview_index = None
        self._challenge = None
        label, band = self._candidates[index]
        _check_artist(label, band)
        return PreparedSingleArtist(label)

    def discard(self) -> None:
        self._candidates = ()
        self._preview_index = None
        self._challenge = None
        self._closed = True
        self._used = True
