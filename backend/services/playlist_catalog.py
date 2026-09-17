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
