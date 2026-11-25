"""Bounded, non-actuating similar-track planning for an explicit session.

The continuation is a tail of the initial queue, not a new playback command
after an inferred end. Only the current owner selection may authorize it.
"""
from __future__ import annotations

import asyncio
import math

from backend.services.music_selected_plan import SelectedListeningPlan, _exact_song
from backend.services.playlist_catalog import VerifiedMusicCandidate

MAX_CONTINUATION_TRACKS = 3
MAX_LOOKUPS = 6
PLAN_TIMEOUT = 15.0
RECHECK_TIMEOUT = 10.0


class ContinuationPlanner:
    def __init__(self, *, source, catalog, taste_provider, approval_service):
        self._source = source
        self._catalog = catalog
        self._taste_provider = taste_provider
        self._approval_service = approval_service

    async def _allowed(self, candidates, mode):
        snapshot = await self._taste_provider.snapshot()
        actions = await self._approval_service.latest_actions(candidates)
        allowed = []
        for item in candidates:
            match = snapshot.classify_candidate(item, mode=None if mode == "general" else mode)
            if (
                actions.get((item.provider, item.provider_id)) in {None, "approve"}
                and match.classification in {"familiar", "proven", "exploratory"}
                and math.isfinite(match.preference) and match.preference >= 0
            ):
                allowed.append(item)
        return tuple(allowed)

    async def preview(self, selected: SelectedListeningPlan, *, mode: str):
        """Return an optional exact tail, excluding selected tracks and duplicates."""
        if (
            selected.status != "verified_preview" or selected.kind != "artist_mix"
            or selected.actuation_allowed is not False or not selected.candidates
        ):
            return ()
        artist = selected.candidates[-1].metadata.get("artist_name")
        if not isinstance(artist, str) or not artist.strip():
            return ()
        try:
            async with asyncio.timeout(PLAN_TIMEOUT):
                raw = await self._source.similar_tracks_for_artist(artist)
                ids = {item.provider_id for item in selected.candidates}
                names = {
                    (str(item.metadata.get("artist_name") or "").casefold(), item.title.casefold())
                    for item in selected.candidates
                }
                candidates = []
                for row in raw[:MAX_LOOKUPS]:
                    identity = row.get("provider_id")
                    title = row.get("track_name")
                    related = row.get("artist_name")
                    score = row.get("source_match")
                    if (
                        row.get("provider") != "itunes_search"
                        or row.get("catalog_verified") is not True
                        or row.get("seed_artist") != artist
                        or not isinstance(score, (float, int)) or isinstance(score, bool)
                        or not math.isfinite(score) or not 0.5 <= score <= 1.0
                        or not isinstance(identity, str) or not identity.isascii() or not identity.isdigit()
                        or not isinstance(title, str) or not title.strip()
                        or not isinstance(related, str) or not related.strip()
                        or related.casefold() == artist.casefold()
                        or identity in ids or (related.casefold(), title.casefold()) in names
                    ):
                        continue
                    current = await self._catalog.get_by_identity("itunes_search", identity)
                    if current is None or not _exact_song(current, identity, title, related):
                        continue
                    ids.add(identity)
                    names.add((related.casefold(), title.casefold()))
                    candidates.append(current)
                return (await self._allowed(candidates, mode))[:MAX_CONTINUATION_TRACKS]
        except Exception:
            return ()

    async def revalidate(self, tail: tuple[VerifiedMusicCandidate, ...], *, mode: str) -> bool:
        if not tail:
            return True
        if len(tail) > MAX_CONTINUATION_TRACKS:
            return False
        try:
            async with asyncio.timeout(RECHECK_TIMEOUT):
                for item in tail:
                    current = await self._catalog.get_by_identity(item.provider, item.provider_id)
                    if current != item or not _exact_song(
                        current, item.provider_id, item.title, item.metadata.get("artist_name"),
                    ):
                        return False
                return await self._allowed(tail, mode) == tail
        except Exception:
            return False
