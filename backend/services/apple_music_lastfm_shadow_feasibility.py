"""Fictional-only Last.fm recent scrobble exposure assessment for HomeHub #431.

No HTTP, credentials, file reads, persistence, Apple account, HomeHub runtime,
taste, presence, or Sonos activity. Never treat a scrobble as a verified play.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_PAGES = 3  # Local fixture budget, NOT Last.fm's pagination limit.
MAX_ITEMS_PER_PAGE = 200  # Documented Last.fm user.getRecentTracks limit.
MIN_UNIX_SECOND = 946684800  # 2000-01-01 UTC inclusive.
MAX_UNIX_SECOND = 4102444800  # 2100-01-01 UTC exclusive.
_REFUSAL = "Offline Last.fm feasibility refused"


class LastFmShadowRefused(ValueError):
    """Fixed error only: never reveal track, artist, username, or API data."""

    def __init__(self) -> None:
        super().__init__(_REFUSAL)


@dataclass(frozen=True, repr=False)
class LastFmShadowAssessment:
    """Anonymous exposure metrics, with no playback or taste authority."""

    pages_examined: int
    resource_observations: int
    now_playing_observations: int
    timestamped_scrobble_observations: int
    missing_date_observations: int
    invalid_timestamp_observations: int
    repeated_timestamp_observations: int

    @property
    def verified_play_sessions(self) -> int:
        return 0

    @property
    def recording_identity_verified(self) -> bool:
        return False

    @property
    def taste_updates_eligible(self) -> bool:
        return False

    @property
    def complete_history_proven(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "LastFmShadowAssessment(<aggregate-only>)"


def _unix_second(value: object) -> int | None:
    # Last.fm supplies UTC seconds as an ASCII decimal string. Shape validation
    # is not evidence that the reported scrobble is a real distinct listening
    # session, or that a timestamp identifies the moment a track was played.
    if (type(value) is not str or not 9 <= len(value) <= 10
            or not value.isascii() or not value.isdecimal()):
        return None
    second = int(value)
    return second if MIN_UNIX_SECOND <= second < MAX_UNIX_SECOND else None


def assess_lastfm_recent_pages(
    pages: list[dict] | tuple[dict, ...],
) -> LastFmShadowAssessment:
    """Inspect already-decoded, fictional user.getRecentTracks response pages.

    This function performs no fetch, authorization, file read, or JSON parse.
    Incoming raw JSON byte size and third-party provenance are NOT verified.
    Names, artist/album text, usernames, URLs, IDs, and account metadata are
    deliberately not read, returned, logged, stored, or echoed in exceptions.
    'nowplaying' entries are not completed scrobbles. Equal UTC timestamps
    represent a collision, not duplicate-proof or a verified replay count.
    """
    if type(pages) not in (list, tuple) or not 1 <= len(pages) <= MAX_PAGES:
        raise LastFmShadowRefused()

    observations = nowplaying = dated = missing = invalid = 0
    seen_seconds: set[int] = set()
    for page in pages:
        if type(page) is not dict or "error" in page:
            raise LastFmShadowRefused()
        envelope = page.get("recenttracks")
        if type(envelope) is not dict:
            raise LastFmShadowRefused()
        tracks = envelope.get("track")
        if type(tracks) is not list or len(tracks) > MAX_ITEMS_PER_PAGE:
            raise LastFmShadowRefused()
        for track in tracks:
            if type(track) is not dict:
                raise LastFmShadowRefused()
            observations += 1
            marker = track.get("@attr")
            if marker is not None and type(marker) is not dict:
                raise LastFmShadowRefused()
            status = marker.get("nowplaying") if marker is not None else None
            if status not in (None, "true", "false"):
                raise LastFmShadowRefused()
            if status == "true":
                nowplaying += 1
                continue
            date = track.get("date")
            if date is None:
                missing += 1
                continue
            if type(date) is not dict:
                invalid += 1
                continue
            second = _unix_second(date.get("uts"))
            if second is None:
                invalid += 1
                continue
            dated += 1
            seen_seconds.add(second)

    return LastFmShadowAssessment(
        pages_examined=len(pages),
        resource_observations=observations,
        now_playing_observations=nowplaying,
        timestamped_scrobble_observations=dated,
        missing_date_observations=missing,
        invalid_timestamp_observations=invalid,
        repeated_timestamp_observations=dated - len(seen_seconds),
    )
