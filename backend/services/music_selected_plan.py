"""Revalidate one selected listening card; never grant playback authority.

Only a server-produced MusicRequestResult may enter this planner. A returned
plan is neither an approval nor a token; a future executor must revalidate
under its own runtime ownership and lifecycle guards.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.music_listening_choices import build_listening_choices
from backend.services.music_requests import MusicRequestResult
from backend.services.music_taste import MusicTasteProvider
from backend.services.music_trust import MusicApprovalService
from backend.services.playlist_catalog import MusicCatalog, VerifiedMusicCandidate

MAX_SELECTED_TRACKS = 5


@dataclass(frozen=True)
class SelectedListeningPlan:
    choice_id: str
    kind: str | None
    reason: str
    candidates: tuple[VerifiedMusicCandidate, ...] = ()
    actuation_allowed: bool = False

    @property
    def status(self) -> str:
        return "verified_preview" if self.candidates else "unavailable"


def _exact_song(candidate: VerifiedMusicCandidate, identity: str, title: str, artist: str) -> bool:
    return (
        candidate.provider == "itunes_search"
        and candidate.provider_id == identity
        and identity.isascii()
        and identity.isdigit()
        and candidate.media_type == "track"
        and candidate.title == title
        and candidate.metadata.get("artist_name") == artist
        and candidate.verified is True
        and candidate.catalog_verified is True
        and candidate.playback_capable
        and candidate.playback_adapter == "sonos_apple_music_share_link"
        and bool(candidate.uri.strip())
        and candidate.playback_reference == candidate.uri
        and candidate.metadata.get("apple_music_canonical") == f"song:{identity}"
        and candidate.metadata.get("playback_verification") == "live_verified"
    )


def _same_favorite(original: VerifiedMusicCandidate, current: VerifiedMusicCandidate) -> bool:
    return (
        original.provider == current.provider == "sonos_favorite"
        and original.provider_id == current.provider_id
        and original.media_type == current.media_type == "favorite"
        and original.title == current.title
        and original.uri == current.uri
        and bool(current.uri.strip())
        and original.source == current.source
        and current.verified is True
        and current.catalog_verified is True
        and current.playback_capable
        and current.playback_adapter == "sonos_favorite_title"
        and current.playback_reference == current.title
    )


class SelectedListeningPlanner:
    """Check a displayed choice without substituting other tracks or containers."""

    def __init__(
        self, *, catalog: MusicCatalog, taste_provider: MusicTasteProvider,
        approval_service: MusicApprovalService,
    ) -> None:
        self._catalog = catalog
        self._taste_provider = taste_provider
        self._approval_service = approval_service

    async def preview(
        self, request: MusicRequestResult, choice_id: str, *, limit: int = 6,
    ) -> SelectedListeningPlan:
        if not isinstance(request, MusicRequestResult):
            raise TypeError("server-generated MusicRequestResult required")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("invalid choice limit")
        if not isinstance(choice_id, str) or not choice_id or len(choice_id) > 256:
            raise ValueError("invalid choice identity")

        def unavailable(reason: str, kind: str | None = None) -> SelectedListeningPlan:
            return SelectedListeningPlan(choice_id, kind, reason)

        if (
            request.shadow is not True or request.actuation_allowed is not False
            or request.status != "shadow_ready"
            or (request.discovery is not None and (
                request.discovery.shadow is not True
                or request.discovery.actuation_allowed is not False
            ))
        ):
            return unavailable("invalid_preview")
        choices = build_listening_choices(request.to_dict(), limit=limit)["choices"]
        matches = [choice for choice in choices if choice["id"] == choice_id]
        if len(matches) != 1:
            return unavailable("choice_not_unique_or_visible")
        choice = matches[0]
        kind = choice["kind"]
        if kind == "album":
            return unavailable("album_contents_not_verified", kind)

        candidates = []
        try:
            if kind == "favorite":
                originals = [
                    item.candidate for item in request.familiar_suggestions
                    if item.candidate.provider == "sonos_favorite"
                    and "sonos_favorite:" + item.candidate.provider_id == choice_id
                ]
                if len(originals) != 1:
                    return unavailable("ambiguous_favorite", kind)
                original = originals[0]
                current = await self._catalog.get_by_identity(original.provider, original.provider_id)
                if current is None or not _same_favorite(original, current):
                    return unavailable("favorite_identity_changed", kind)
                candidates.append(current)
            elif kind == "artist_mix":
                tracks = choice["tracks"]
                identities = [track["provider_id"] for track in tracks]
                if not 2 <= len(tracks) <= MAX_SELECTED_TRACKS or len(set(identities)) != len(tracks):
                    return unavailable("invalid_mix_members", kind)
                for track in tracks:
                    identity = track["provider_id"]
                    current = await self._catalog.get_by_identity("itunes_search", identity)
                    if current is None or not _exact_song(
                        current, identity, track["title"], choice["artist"],
                    ):
                        return unavailable("mix_member_not_verified", kind)
                    candidates.append(current)
            else:
                return unavailable("unsupported_choice", kind)
        except Exception:
            return unavailable("catalog_unavailable", kind)

        try:
            snapshot = await self._taste_provider.snapshot()
            actions = await self._approval_service.latest_actions(candidates)
            mode = request.resolved_request.mode
            for candidate in candidates:
                action = actions.get((candidate.provider, candidate.provider_id))
                match = snapshot.classify_candidate(
                    candidate, mode=None if mode == "general" else mode,
                )
                allowed = {"familiar", "proven"} if kind == "favorite" else {
                    "familiar", "proven", "exploratory",
                }
                if (
                    action not in {None, "approve"}
                    or match.classification not in allowed
                    or not math.isfinite(match.preference) or match.preference < 0
                ):
                    return unavailable("current_taste_or_approval_veto", kind)
        except Exception:
            return unavailable("taste_or_approval_unavailable", kind)

        # Favorites still require an exact-identity execution seam; the existing
        # title-only Sonos route is NOT an exact executor. Mixes need session
        # ownership and continuation, not per-track approval mutation.
        return SelectedListeningPlan(choice_id, kind, "execution_not_connected", tuple(candidates))
