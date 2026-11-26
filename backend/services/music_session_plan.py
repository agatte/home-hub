"""Read-only listening session planning; no playback or approval authority."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.services.music_requests import MusicRequestResult
from backend.services.music_taste import MusicTasteProvider
from backend.services.music_trust import MusicApprovalService
from backend.services.playlist_catalog import MusicCatalog, VerifiedMusicCandidate

MAX_TRACKS = 6
MAX_LOOKUPS = 30
_PROVIDER = "itunes_search"
_ADAPTER = "sonos_apple_music_share_link"


@dataclass(frozen=True)
class SessionTrack:
    candidate: VerifiedMusicCandidate
    familiarity: str


@dataclass(frozen=True)
class MusicSessionPlan:
    kind: str
    requested_tracks: int
    tracks: tuple[SessionTrack, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": (
                "unavailable" if not self.tracks else
                "preview_ready" if len(self.tracks) == self.requested_tracks else
                "partial_preview"
            ),
            "kind": self.kind,
            "requested_tracks": self.requested_tracks,
            "tracks": [
                {"candidate": item.candidate.to_dict(), "familiarity": item.familiarity}
                for item in self.tracks
            ],
            "reason": self.reason,
            "shadow": True,
            "actuation_allowed": False,
        }


def _exact_track(candidate: VerifiedMusicCandidate, key: tuple[str, str]) -> bool:
    return (
        (candidate.provider, candidate.provider_id) == key
        and candidate.provider == _PROVIDER
        and candidate.provider_id.isascii()
        and candidate.provider_id.isdigit()
        and candidate.media_type == "track"
        and candidate.verified is True
        and candidate.catalog_verified is True
        and candidate.playback_capable
        and candidate.playback_adapter == _ADAPTER
        and candidate.playback_reference == candidate.uri
        and bool(candidate.uri.strip())
        and bool(candidate.title.strip())
        and candidate.metadata.get("apple_music_canonical") == f"song:{candidate.provider_id}"
        and candidate.metadata.get("playback_verification") == "live_verified"
        and bool(str(candidate.metadata.get("artist_name") or "").strip())
    )


class MusicSessionPlanner:
    """Plan from a trusted server-generated preview, never raw client candidates.

    Recheck exact catalog identities and current taste/approval vetoes. A plan
    cannot be used as a playback token or as persistent track approval. A later
    executor must revalidate identities, authorization and runtime ownership.
    """

    def __init__(
        self, *, catalog: MusicCatalog, taste_provider: MusicTasteProvider,
        approval_service: MusicApprovalService,
    ) -> None:
        self._catalog = catalog
        self._taste_provider = taste_provider
        self._approval_service = approval_service

    async def preview(
        self, request: MusicRequestResult, *, count: int = MAX_TRACKS,
    ) -> MusicSessionPlan:
        if type(count) is not int or not 1 <= count <= MAX_TRACKS:
            raise ValueError("count must be an integer between 1 and 6")
        kind = request.resolved_request.kind

        def unavailable(reason: str) -> MusicSessionPlan:
            return MusicSessionPlan(kind, count, (), reason)

        if kind not in {"familiar", "discovery", "mood", "recommendation"}:
            raise ValueError("unsupported session request kind")
        if request.shadow is not True or request.actuation_allowed is not False:
            return unavailable("invalid_preview")
        if request.status != "shadow_ready":
            return unavailable("request_unavailable")

        keys: dict[tuple[str, str], None] = {}
        for suggestion in request.familiar_suggestions:
            item = suggestion.candidate
            key = (item.provider, item.provider_id)
            if _exact_track(item, key):
                keys[key] = None
        if request.discovery is not None:
            discovery = request.discovery
            if discovery.shadow is not True or discovery.actuation_allowed is not False:
                return unavailable("invalid_preview")
            for cluster in discovery.clusters:
                for track in cluster.tracks:
                    if (
                        track.provider == _PROVIDER and track.catalog_verified is True
                        and track.provider_id.isascii() and track.provider_id.isdigit()
                        and track.playback_capability == "supported"
                        and track.playback_adapter == _ADAPTER
                        and track.playback_reason == "provider_exact_match"
                        and track.playback_reference
                    ):
                        keys[(track.provider, track.provider_id)] = None
        resolved: list[VerifiedMusicCandidate] = []
        for key in list(keys)[:MAX_LOOKUPS]:
            try:
                candidate = await self._catalog.get_by_identity(*key)
            except Exception:
                continue
            if candidate is not None and _exact_track(candidate, key):
                resolved.append(candidate)
        if not resolved:
            return unavailable("no_exact_supported_tracks")

        try:
            snapshot = await self._taste_provider.snapshot()
            actions = await self._approval_service.latest_actions(resolved)
            familiar: list[SessionTrack] = []
            exploratory: list[SessionTrack] = []
            mode = request.resolved_request.mode
            for candidate in resolved:
                action = actions.get((candidate.provider, candidate.provider_id))
                if action not in {None, "approve"}:
                    continue
                match = snapshot.classify_candidate(
                    candidate, mode=None if mode == "general" else mode,
                )
                if not math.isfinite(match.preference) or match.preference < 0:
                    continue
                if match.classification in {"proven", "familiar"}:
                    familiar.append(SessionTrack(candidate, match.classification))
                elif match.classification == "exploratory":
                    exploratory.append(SessionTrack(candidate, match.classification))
        except Exception:
            return unavailable("taste_or_approval_unavailable")

        # Respect requested familiarity. Don't disguise a shortfall as success.
        if kind == "familiar":
            selected = familiar[:count]
        elif kind == "discovery":
            novelty_count = max(1, math.ceil(count * 0.8))
            selected = exploratory[:novelty_count] + familiar[:count - novelty_count]
            if not any(item.familiarity == "exploratory" for item in selected):
                return unavailable("no_discovery_tracks")
        else:
            novelty_count = count // 5
            selected = familiar[:count - novelty_count] + exploratory[:novelty_count]
        return MusicSessionPlan(
            kind, count, tuple(selected),
            None if len(selected) == count else "eligible_track_shortfall",
        )
