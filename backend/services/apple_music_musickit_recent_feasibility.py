"""Fictional-only Apple Music *recent tracks* feasibility assessment (#431).

Pure, offline, aggregate-only classification of already-decoded hypothetical API
responses. No HTTP/credentials, file I/O, DB, HomeHub taste, Sonos or presence.
A resource ID is NOT a playback event, session, liked track, or recording proof.
"""
from __future__ import annotations

from dataclasses import dataclass

# Application test budget only. Apple documents at most 30 tracks per page.
MAX_PAGES = 4
MAX_PAGE_ITEMS = 30
MAX_PAGINATION_LENGTH = 2048
MAX_CATALOG_ID_LENGTH = 32
_ALLOWED_TYPES = frozenset({"songs", "library-songs", "music-videos",
                            "library-music-videos"})
_REFUSAL = "Offline recent-track feasibility refused"


class RecentTracksRefused(ValueError):
    """Never include submitted resource labels, IDs or pagination in errors."""

    def __init__(self) -> None:
        super().__init__(_REFUSAL)


@dataclass(frozen=True, repr=False)
class RecentTracksAssessment:
    """Only anonymous counters; all evidence/ingestion authority is withheld."""

    pages_examined: int
    resource_observations: int
    catalog_song_observations: int
    distinct_catalog_song_ids: int
    repeated_catalog_id_observations: int
    library_song_observations: int
    video_observations: int
    unusable_catalog_song_ids: int
    last_page_advertised_next: bool

    @property
    def verified_play_sessions(self) -> int:
        return 0

    @property
    def taste_updates_eligible(self) -> bool:
        return False

    @property
    def complete_history_proven(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "RecentTracksAssessment(<aggregate-only>)"


def _catalog_id_shape(value: object) -> bool:
    # Shape recognition is NOT evidence the ID resolves, represents the exact
    # recording, or corresponds to a distinct playback.
    return (type(value) is str and 0 < len(value) <= MAX_CATALOG_ID_LENGTH
            and value.isascii() and value.isdecimal() and value.strip("0") != "")


def assess_recent_track_pages(pages: list[dict] | tuple[dict, ...]
                              ) -> RecentTracksAssessment:
    """Summarize fictional /v1/me/recent/played/tracks resource pages.

    The caller supplies already-decoded pages. We do not fetch or follow
    pagination; a "next" field is treated as an opaque yes/no indicator only.
    This does not bound incoming JSON bytes or authenticate a response.

    Repeats are duplicate *resource IDs*, never proven plays. Ignores
    attributes (names, durations, artwork, user metadata, apparent timestamps)
    and returns counts only. No cross-source/session/consent evidence exists.
    """
    if type(pages) not in (list, tuple) or not 1 <= len(pages) <= MAX_PAGES:
        raise RecentTracksRefused()

    seen_catalog_ids: set[str] = set()
    resource_count = catalog_count = library_count = video_count = invalid_count = 0
    last_next = False
    for page in pages:
        if type(page) is not dict or "errors" in page:
            raise RecentTracksRefused()
        data = page.get("data")
        if type(data) is not list or len(data) > MAX_PAGE_ITEMS:
            raise RecentTracksRefused()

        next_value = page.get("next")
        if next_value is not None and (type(next_value) is not str
                                       or not 0 < len(next_value) <= MAX_PAGINATION_LENGTH):
            raise RecentTracksRefused()
        last_next = next_value is not None
        for resource in data:
            if type(resource) is not dict:
                raise RecentTracksRefused()
            kind = resource.get("type")
            if type(kind) is not str or kind not in _ALLOWED_TYPES:
                raise RecentTracksRefused()
            resource_count += 1
            if kind == "songs":
                identifier = resource.get("id")
                if _catalog_id_shape(identifier):
                    catalog_count += 1
                    seen_catalog_ids.add(identifier)
                else:
                    invalid_count += 1
            elif kind == "library-songs":
                # Library-local identifiers are not catalog identity proof.
                library_count += 1
            else:
                video_count += 1

    return RecentTracksAssessment(
        pages_examined=len(pages),
        resource_observations=resource_count,
        catalog_song_observations=catalog_count,
        distinct_catalog_song_ids=len(seen_catalog_ids),
        repeated_catalog_id_observations=catalog_count - len(seen_catalog_ids),
        library_song_observations=library_count,
        video_observations=video_count,
        unusable_catalog_song_ids=invalid_count,
        last_page_advertised_next=last_next,
    )