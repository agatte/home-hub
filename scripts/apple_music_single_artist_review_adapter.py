"""Offline bridge from the existing volatile local Tk reviewer to #431 consent.

No UI hooks, network or production integration. The caller must display the
explicit per-artist confirmation and must never silently invoke approve_once.
"""
from __future__ import annotations

from typing import Any

from backend.services.apple_music_single_artist_handoff import (
    ArtistPreview, HandoffRefused, OneArtistConsentSession, PreparedSingleArtist,
    RECIPIENT,
)


class LocalReviewerAdapter:
    """Guard an existing reviewer's in-memory candidate snapshot and selection.

    A source reload, mutation, or discard invalidates the challenge and burns
    the bridge. The local reviewer remains authoritative for its own data.
    """

    def __init__(self, reviewer: Any) -> None:
        candidates = getattr(reviewer, "candidates", None)
        if not isinstance(candidates, list):
            raise HandoffRefused()
        self._reviewer = reviewer
        self._source_list = candidates
        self._snapshot = tuple(candidates)
        self._consent = OneArtistConsentSession(self._snapshot)
        self._last_preview: ArtistPreview | None = None
        self._closed = False

    def __repr__(self) -> str:
        return "LocalReviewerAdapter(<redacted>)"

    def _assert_same_session(self) -> None:
        if (self._closed or getattr(self._reviewer, "candidates", None) is not self._source_list
                or tuple(self._source_list) != self._snapshot):
            self.discard()
            raise HandoffRefused()

    def preview_selected(self, selected_ids: tuple[str, ...]) -> ArtistPreview:
        self._assert_same_session()
        if (type(selected_ids) is not tuple or len(selected_ids) != 1
                or type(selected_ids[0]) is not str
                or not selected_ids[0].isascii()
                or not selected_ids[0].isdecimal()
                or len(selected_ids[0]) > 4
                or selected_ids[0] != str(int(selected_ids[0]))):
            self.discard()
            raise HandoffRefused()
        try:
            self._last_preview = self._consent.preview(int(selected_ids[0]))
        except HandoffRefused:
            self.discard()
            raise
        return self._last_preview

    def confirm(self, preview: ArtistPreview, *, confirmed: bool) -> PreparedSingleArtist:
        self._assert_same_session()
        if (type(preview) is not ArtistPreview or preview is not self._last_preview
                or preview.recipient != RECIPIENT):
            self.discard()
            raise HandoffRefused()
        self._last_preview = None
        return self._consent.approve_once(preview.challenge, RECIPIENT, confirmed=confirmed)

    def discard(self) -> None:
        self._consent.discard()
        self._snapshot = ()
        self._source_list = None
        self._last_preview = None
        self._closed = True
