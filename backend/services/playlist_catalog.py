"""Provider-neutral music catalog boundary for the Music Curator.

The curator may describe music intent, but only candidates returned by a
catalog adapter are eligible to leave the discovery layer.  The initial
adapter is intentionally conservative: it exposes Sonos favorites that are
already real and queueable in Anthony's system.  Future provider adapters can
implement the same protocol without teaching the curator how Sonos works.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


_TOKEN_RE = re.compile(r"[a-z0-9]+")
APPLE_MUSIC_SHARELINK_CAPABILITY_KEY = "music_apple_sharelink_capability"


@dataclass(frozen=True)
class VerifiedMusicCandidate:
    """A provider-returned identity with explicit verification/capability facts.

    ``verified`` is retained for compatibility with existing callers. New code
    must distinguish catalog existence from HomeHub playback capability.
    """

    provider: str
    provider_id: str
    media_type: str
    title: str
    uri: str
    source: str
    verified: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    catalog_verified: bool = True
    playback_capability: str = "unknown"
    playback_adapter: str | None = None
    playback_reference: str | None = None

    @property
    def playback_capable(self) -> bool:
        return (
            self.catalog_verified
            and self.playback_capability == "supported"
            and bool(self.playback_adapter)
            and bool(self.playback_reference)
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["playback_capable"] = self.playback_capable
        return data


class MusicCatalog(Protocol):
    """Provider-neutral catalog contract used by Music Intelligence."""

    async def search(self, intent: Any, *, limit: int = 12) -> list[VerifiedMusicCandidate]:
        """Return provider-verified candidates with explicit playback capability."""

    async def get_by_identity(
        self, provider: str, provider_id: str,
    ) -> VerifiedMusicCandidate | None:
        """Re-verify one exact provider identity without rediscovery guessing."""

    async def resolve_tracks(
        self, artist_name: str, tracks: list[dict[str, Any]],
    ) -> dict[tuple[str, str], VerifiedMusicCandidate]:
        """Resolve exact provider identities without title-only guessing."""


class SonosFavoritesCatalog:
    """Read-only catalog adapter over the favorites currently exposed by Sonos."""

    provider_name = "sonos_favorite"

    def __init__(self, sonos_service, *, timeout_seconds: float = 5.0) -> None:
        self._sonos = sonos_service
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return bool(getattr(self._sonos, "connected", False))

    async def search(self, intent: Any, *, limit: int = 12) -> list[VerifiedMusicCandidate]:
        if not self.available:
            return []
        try:
            favorites = await asyncio.wait_for(
                self._sonos.get_favorites(), timeout=self._timeout_seconds,
            )
        except Exception:
            return []

        concept_tokens = self._intent_tokens(intent)
        candidates: list[tuple[float, VerifiedMusicCandidate]] = []
        seen: set[tuple[str, str]] = set()
        for favorite in favorites or []:
            if not isinstance(favorite, dict):
                continue
            title = str(favorite.get("title") or "").strip()
            uri = str(favorite.get("uri") or "").strip()
            source = str(favorite.get("source") or "favorite").strip() or "favorite"
            playback_supported = favorite.get("playback_supported")
            if playback_supported is False:
                continue
            if not title or not uri:
                # Empty-URI favorites are visible in Sonos but are not queueable.
                continue
            dedupe_key = (title.casefold(), uri)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            match_score, matched = self._match_score(title, concept_tokens)
            provider_id = str(favorite.get("id") or "").strip()
            if not provider_id:
                provider_id = hashlib.sha256(f"{source}|{uri}".encode()).hexdigest()[:16]
            candidate = VerifiedMusicCandidate(
                provider=self.provider_name,
                provider_id=provider_id,
                media_type="favorite",
                title=title,
                uri=uri,
                source=source,
                verified=True,
                catalog_verified=True,
                playback_capability="supported",
                playback_adapter="sonos_favorite_title",
                playback_reference=title,
                metadata={
                    "catalog_match_score": round(match_score, 4),
                    "matched_concepts": matched,
                },
            )
            candidates.append((match_score, candidate))

        candidates.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
        return [candidate for _, candidate in candidates[: max(1, limit)]]

    async def get_by_identity(
        self, provider: str, provider_id: str,
    ) -> VerifiedMusicCandidate | None:
        if provider != self.provider_name or not provider_id:
            return None
        candidates = await self.search(object(), limit=10000)
        return next((item for item in candidates if item.provider_id == provider_id), None)

    async def resolve_tracks(
        self, artist_name: str, tracks: list[dict[str, Any]],
    ) -> dict[tuple[str, str], VerifiedMusicCandidate]:
        # Favorites are containers/playlists, not exact track identities.
        return {}

    @staticmethod
    def _intent_tokens(intent: Any) -> set[str]:
        values: list[str] = []
        for attr in ("search_concepts", "themes", "genres"):
            raw = getattr(intent, attr, None) or []
            if isinstance(raw, (list, tuple, set)):
                values.extend(str(item) for item in raw if item)
        tokens: set[str] = set()
        for value in values:
            tokens.update(token for token in _TOKEN_RE.findall(value.casefold()) if len(token) >= 3)
        return tokens

    @staticmethod
    def _match_score(title: str, concept_tokens: set[str]) -> tuple[float, list[str]]:
        title_tokens = set(_TOKEN_RE.findall(title.casefold()))
        matched = sorted(title_tokens & concept_tokens)
        if not concept_tokens:
            return 0.0, []
        overlap = len(matched) / max(1, len(concept_tokens))
        phrase_bonus = 0.0
        lowered = title.casefold()
        for token in concept_tokens:
            if token in lowered:
                phrase_bonus += 0.05
        return min(1.0, overlap + phrase_bonus), matched

class CompositeMusicCatalog:
    """Compose provider catalogs without weakening exact identity boundaries."""

    def __init__(self, *catalogs: MusicCatalog) -> None:
        self._catalogs = tuple(catalogs)

    @property
    def available(self) -> bool:
        return any(bool(getattr(catalog, "available", True)) for catalog in self._catalogs)

    async def search(self, intent: Any, *, limit: int = 12) -> list[VerifiedMusicCandidate]:
        results: list[VerifiedMusicCandidate] = []
        seen: set[tuple[str, str]] = set()
        for catalog in self._catalogs:
            try:
                candidates = await catalog.search(intent, limit=limit)
            except Exception:
                continue
            for candidate in candidates:
                key = (candidate.provider, candidate.provider_id)
                if key in seen:
                    continue
                seen.add(key)
                results.append(candidate)
        return results[: max(1, limit)]

    async def get_by_identity(
        self, provider: str, provider_id: str,
    ) -> VerifiedMusicCandidate | None:
        for catalog in self._catalogs:
            resolver = getattr(catalog, "get_by_identity", None)
            if resolver is None:
                continue
            try:
                candidate = await resolver(provider, provider_id)
            except Exception:
                continue
            if candidate is not None:
                return candidate
        return None

    async def resolve_tracks(
        self, artist_name: str, tracks: list[dict[str, Any]],
    ) -> dict[tuple[str, str], VerifiedMusicCandidate]:
        unresolved = [dict(track) for track in tracks if isinstance(track, dict)]
        resolved: dict[tuple[str, str], VerifiedMusicCandidate] = {}
        for catalog in self._catalogs:
            resolver = getattr(catalog, "resolve_tracks", None)
            if resolver is None or not unresolved:
                continue
            try:
                found = await resolver(artist_name, unresolved)
            except Exception:
                continue
            for key, candidate in found.items():
                if key not in resolved and candidate.playback_capable:
                    resolved[key] = candidate
            unresolved = [
                track for track in unresolved
                if (
                    str(track.get("provider") or ""),
                    str(track.get("provider_id") or ""),
                ) not in resolved
            ]
        return resolved


class AppleMusicShareCatalog:
    """Upgrade Apple/iTunes identities through Sonos' Apple Music ShareLink path.

    The public iTunes Search API already returns Apple Music track IDs and
    ``music.apple.com`` share URLs. SoCo's ShareLink adapter can translate those
    exact URLs into Sonos queue metadata using the Apple Music account already
    linked to the Sonos household. No second Apple credential is required.
    """

    provider_name = "itunes_search"
    service_name = "Apple Music"
    playback_adapter_name = "sonos_apple_music_share_link"

    def __init__(
        self,
        sonos_service,
        *,
        lookup_source,
        verified_household_id: str | None = None,
    ) -> None:
        self._sonos = sonos_service
        self._lookup_source = lookup_source
        self._verified_household_id = str(verified_household_id or "").strip() or None

    @property
    def playback_verified(self) -> bool:
        device = getattr(self._sonos, "device", None)
        household_id = str(getattr(device, "household_id", "") or "").strip()
        return bool(
            self._verified_household_id
            and household_id
            and household_id == self._verified_household_id
        )

    @property
    def available(self) -> bool:
        return bool(getattr(self._sonos, "connected", False))

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "service": self.service_name,
            "sonos_available": self.available,
            "credentials_required": False,
            "playback_adapter": self.playback_adapter_name,
            "playback_verified": self.playback_verified,
            "verification_state": (
                "live_verified" if self.playback_verified else "queue_test_required"
            ),
            "actuation_allowed": False,
        }

    async def search(self, intent: Any, *, limit: int = 12) -> list[VerifiedMusicCandidate]:
        # Discovery remains the search authority; this adapter upgrades exact
        # Apple identities and re-verifies them later for trust/playback.
        return []

    async def resolve_tracks(
        self, artist_name: str, tracks: list[dict[str, Any]],
    ) -> dict[tuple[str, str], VerifiedMusicCandidate]:
        if not self.available:
            return {}
        resolved: dict[tuple[str, str], VerifiedMusicCandidate] = {}
        for track in tracks:
            candidate = self._candidate_from_track(track, expected_artist=artist_name)
            if candidate is None:
                continue
            resolved[(candidate.provider, candidate.provider_id)] = candidate
        return resolved

    async def get_by_identity(
        self, provider: str, provider_id: str,
    ) -> VerifiedMusicCandidate | None:
        if provider != self.provider_name or not provider_id or not self.available:
            return None
        try:
            track = await self._lookup_source.lookup_itunes_track(provider_id)
        except Exception:
            return None
        if not track:
            return None
        return self._candidate_from_track(track)

    def _candidate_from_track(
        self, track: dict[str, Any], *, expected_artist: str | None = None,
    ) -> VerifiedMusicCandidate | None:
        provider = str(track.get("provider") or "").strip()
        provider_id = str(track.get("provider_id") or "").strip()
        title = str(track.get("track_name") or "").strip()
        artist = str(track.get("artist_name") or "").strip()
        share_url = str(track.get("external_url") or "").strip()
        if provider != self.provider_name or not provider_id or not provider_id.isdigit():
            return None
        if not title or not artist or not share_url:
            return None
        if expected_artist and artist.casefold() != expected_artist.strip().casefold():
            return None
        try:
            from soco.plugins.sharelink import AppleMusicShare
            canonical = AppleMusicShare().canonical_uri(share_url)
        except Exception:
            return None
        if canonical != f"song:{provider_id}":
            return None
        playback_verified = self.playback_verified
        return VerifiedMusicCandidate(
            provider=self.provider_name,
            provider_id=provider_id,
            media_type="track",
            title=title,
            uri=share_url,
            source="itunes_search+sonos_share_link",
            verified=True,
            catalog_verified=True,
            playback_capability=(
                "supported" if playback_verified else "pending_verification"
            ),
            playback_adapter=(self.playback_adapter_name if playback_verified else None),
            playback_reference=(share_url if playback_verified else None),
            metadata={
                "artist_name": artist,
                "track_name": title,
                "album_name": track.get("album_name"),
                "apple_music_canonical": canonical,
                "playback_verification": (
                    "live_verified" if playback_verified else "queue_test_required"
                ),
            },
        )
