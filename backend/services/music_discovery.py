"""Explainable, non-actuating music discovery for shared Music Intelligence (#257)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from backend.services.music_semantics import (
    DeterministicSemanticIntentResolver,
    MusicSemanticAnalyzer,
    SemanticIntent,
    SemanticMusicMatch,
)
from backend.services.music_taste import CandidateTasteMatch, MusicTasteProvider

DISCOVERY_POLICIES = ("gentle", "explore")
DISCOVERY_SOURCE_CACHE_TTL = timedelta(hours=1)


class MusicDiscoverySource(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def discover_artist_candidates(
        self,
        mode: str,
        *,
        count: int = 8,
        tracks_per_artist: int = 3,
    ) -> list[dict]: ...


@dataclass(frozen=True)
class DiscoveryTrack:
    provider: str
    provider_id: str
    artist_name: str
    track_name: str
    album_name: Optional[str]
    preview_url: Optional[str]
    artwork_url: Optional[str]
    external_url: Optional[str]
    taste_classification: str
    taste_preference: float
    taste_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["taste_sources"] = list(self.taste_sources)
        return data


@dataclass(frozen=True)
class DiscoveryArtistCluster:
    artist_name: str
    seed_artist: str
    source: str
    source_match: float
    score: float
    artist_classification: str
    artist_preference: float
    artist_depth: int
    novelty_ratio: float
    semantic_score: Optional[float]
    semantic_intent: Optional[str]
    semantic_source: Optional[str]
    semantic_tags: tuple[str, ...]
    matched_semantics: tuple[str, ...]
    tracks: tuple[DiscoveryTrack, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artist_name": self.artist_name,
            "seed_artist": self.seed_artist,
            "source": self.source,
            "source_match": round(self.source_match, 4),
            "score": round(self.score, 4),
            "artist_classification": self.artist_classification,
            "artist_preference": round(self.artist_preference, 4),
            "artist_depth": self.artist_depth,
            "novelty_ratio": round(self.novelty_ratio, 4),
            "semantic_score": (
                round(self.semantic_score, 4) if self.semantic_score is not None else None
            ),
            "semantic_intent": self.semantic_intent,
            "semantic_source": self.semantic_source,
            "semantic_tags": list(self.semantic_tags),
            "matched_semantics": list(self.matched_semantics),
            "tracks": [track.to_dict() for track in self.tracks],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MusicDiscoveryResult:
    status: str
    mode: str
    policy: str
    generated_at: datetime
    clusters: tuple[DiscoveryArtistCluster, ...]
    source: str
    taste_available: bool
    shadow: bool = True
    actuation_allowed: bool = False
    source_cache_hit: bool = False
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "policy": self.policy,
            "generated_at": self.generated_at.isoformat(),
            "shadow": self.shadow,
            "actuation_allowed": self.actuation_allowed,
            "source": self.source,
            "taste_available": self.taste_available,
            "source_cache_hit": self.source_cache_hit,
            "note": self.note,
            "clusters": [cluster.to_dict() for cluster in self.clusters],
        }


@dataclass(frozen=True)
class _TasteCandidate:
    media_type: str
    title: str
    metadata: dict[str, Any]


def _empty_match() -> CandidateTasteMatch:
    return CandidateTasteMatch(
        classification="exploratory",
        familiarity=0.0,
        preference=0.0,
        artist_depth=0,
        positive_weight=0.0,
        negative_weight=0.0,
        sources=(),
    )


class MusicDiscoveryService:
    """Ranks external discovery candidates using canonical HomeHub taste evidence."""

    def __init__(
        self,
        *,
        source: MusicDiscoverySource,
        taste_provider: MusicTasteProvider,
        semantic_analyzer: Optional[MusicSemanticAnalyzer] = None,
        intent_resolver: Optional[DeterministicSemanticIntentResolver] = None,
    ) -> None:
        self._source = source
        self._taste_provider = taste_provider
        self._semantic_analyzer = semantic_analyzer
        self._intent_resolver = intent_resolver or DeterministicSemanticIntentResolver()
        self._source_cache: dict[
            tuple[str, int, int], tuple[datetime, list[dict]]
        ] = {}

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._source, "enabled", False))

    def status(self) -> dict[str, Any]:
        return {
            "shadow": True,
            "actuation_allowed": False,
            "source_enabled": self.enabled,
            "source": type(self._source).__name__,
            "policies": list(DISCOVERY_POLICIES),
            "source_cache_entries": len(self._source_cache),
            "semantic_enabled": bool(
                self._semantic_analyzer is not None
                and getattr(self._semantic_analyzer, "enabled", False)
            ),
            "semantic_analyzer": (
                type(self._semantic_analyzer).__name__
                if self._semantic_analyzer is not None else None
            ),
        }

    async def preview(
        self,
        mode: str,
        *,
        policy: str = "gentle",
        count: int = 6,
        tracks_per_artist: int = 3,
        intent: Optional[str] = None,
    ) -> MusicDiscoveryResult:
        if policy not in DISCOVERY_POLICIES:
            raise ValueError(f"unsupported discovery policy: {policy}")
        now = datetime.now(timezone.utc)
        source_name = type(self._source).__name__
        semantic_intent = self._intent_resolver.resolve(mode=mode, request=intent)
        if not self.enabled:
            return MusicDiscoveryResult(
                status="source_unavailable",
                mode=mode,
                policy=policy,
                generated_at=now,
                clusters=(),
                source=source_name,
                taste_available=False,
                note="discovery source is not configured",
            )

        cache_key = (mode, count, tracks_per_artist)
        source_cache_hit = False
        raw: list[dict]
        cached = self._source_cache.get(cache_key)
        if cached is not None and now - cached[0] <= DISCOVERY_SOURCE_CACHE_TTL:
            raw = list(cached[1])
            source_cache_hit = True
        else:
            raw = await self._source.discover_artist_candidates(
                mode,
                count=min(12, max(count + 3, count)),
                tracks_per_artist=tracks_per_artist,
            )
            if raw:
                self._source_cache[cache_key] = (now, list(raw))
        if not raw:
            return MusicDiscoveryResult(
                status="no_candidates",
                mode=mode,
                policy=policy,
                generated_at=now,
                clusters=(),
                source=source_name,
                taste_available=False,
                source_cache_hit=source_cache_hit,
            )

        snapshot = None
        taste_note = None
        try:
            snapshot = await self._taste_provider.snapshot()
        except Exception as exc:
            taste_note = f"taste snapshot unavailable: {type(exc).__name__}"

        clusters: list[DiscoveryArtistCluster] = []
        for candidate in raw:
            cluster = await self._build_cluster(
                candidate,
                mode=mode,
                policy=policy,
                snapshot=snapshot,
                semantic_intent=semantic_intent,
            )
            if cluster is not None:
                clusters.append(cluster)
        clusters.sort(key=lambda item: (-item.score, item.artist_name.casefold()))
        clusters = clusters[: max(1, count)]
        return MusicDiscoveryResult(
            status="shadow_ready" if clusters else "no_candidates",
            mode=mode,
            policy=policy,
            generated_at=now,
            clusters=tuple(clusters),
            source=source_name,
            taste_available=snapshot is not None,
            source_cache_hit=source_cache_hit,
            note=taste_note,
        )

    async def _build_cluster(
        self,
        candidate: dict[str, Any],
        *,
        mode: str,
        policy: str,
        snapshot: Any,
        semantic_intent: SemanticIntent,
    ) -> Optional[DiscoveryArtistCluster]:
        artist_name = str(candidate.get("artist_name") or "").strip()
        seed_artist = str(candidate.get("seed_artist") or "").strip()
        source = str(candidate.get("source") or "unknown").strip() or "unknown"
        if not artist_name or not seed_artist:
            return None
        try:
            source_match = max(0.0, min(1.0, float(candidate.get("source_match", 0.0))))
        except (TypeError, ValueError):
            source_match = 0.0

        artist_match = _empty_match()
        if snapshot is not None:
            artist_match = snapshot.classify_candidate(
                _TasteCandidate(
                    media_type="artist",
                    title=artist_name,
                    metadata={"artist_name": artist_name},
                ),
                mode=mode,
            )
            if artist_match.classification == "rejected":
                return None

        tracks: list[DiscoveryTrack] = []
        exploratory_count = 0
        track_preferences: list[float] = []
        for raw_track in candidate.get("tracks") or []:
            if not isinstance(raw_track, dict):
                continue
            track_name = str(raw_track.get("track_name") or "").strip()
            provider_id = str(raw_track.get("provider_id") or "").strip()
            provider = str(raw_track.get("provider") or "").strip()
            if not track_name or not provider_id or not provider:
                continue
            track_match = _empty_match()
            if snapshot is not None:
                track_match = snapshot.classify_candidate(
                    _TasteCandidate(
                        media_type="track",
                        title=track_name,
                        metadata={
                            "artist_name": artist_name,
                            "track_name": track_name,
                        },
                    ),
                    mode=mode,
                )
                if track_match.classification == "rejected":
                    continue
            if track_match.classification == "exploratory":
                exploratory_count += 1
            track_preferences.append(track_match.preference)
            tracks.append(DiscoveryTrack(
                provider=provider,
                provider_id=provider_id,
                artist_name=artist_name,
                track_name=track_name,
                album_name=raw_track.get("album_name"),
                preview_url=raw_track.get("preview_url"),
                artwork_url=raw_track.get("artwork_url"),
                external_url=raw_track.get("external_url"),
                taste_classification=track_match.classification,
                taste_preference=track_match.preference,
                taste_sources=track_match.sources,
            ))
        if not tracks:
            return None

        novelty_ratio = exploratory_count / len(tracks)
        avg_track_preference = (
            sum(track_preferences) / len(track_preferences)
            if track_preferences else 0.0
        )
        base_score = 0.68 * source_match
        base_score += 0.14 * artist_match.preference
        base_score += 0.08 * avg_track_preference
        base_score += min(0.06, 0.015 * artist_match.artist_depth)
        if policy == "gentle":
            base_score += 0.06 * (1.0 - novelty_ratio)
        else:
            base_score += 0.08 * novelty_ratio
        base_score = max(0.0, min(1.0, base_score))

        semantic_match = SemanticMusicMatch(available=False)
        analyzer = self._semantic_analyzer
        if analyzer is not None and getattr(analyzer, "enabled", False):
            try:
                semantic_match = await analyzer.analyze(
                    artist_name=artist_name,
                    track_name=tracks[0].track_name if tracks else None,
                    intent=semantic_intent,
                )
            except Exception:
                semantic_match = SemanticMusicMatch(available=False)
        score = base_score
        if semantic_match.available:
            score = 0.85 * base_score + 0.15 * semantic_match.score
        score = max(0.0, min(1.0, score))

        reasons = [
            f"Last.fm adjacency to {seed_artist} ({source_match:.2f})",
            f"{exploratory_count}/{len(tracks)} tracks new-to-HomeHub",
        ]
        if snapshot is not None:
            reasons.append(
                f"artist taste {artist_match.classification} ({artist_match.preference:+.2f})"
            )
            if artist_match.artist_depth:
                reasons.append(f"artist depth {artist_match.artist_depth}")
            explicit_actions = sorted({
                source.split(":", 2)[1]
                for source in artist_match.sources
                if source.startswith("explicit_feedback:") and ":" in source
            })
            if explicit_actions:
                labels = {
                    "fits_me": "Fits me",
                    "interesting": "Interesting",
                    "not_for_me": "Not for me",
                }
                reasons.append(
                    "explicit feedback: "
                    + ", ".join(labels.get(action, action) for action in explicit_actions)
                )
        if semantic_match.available:
            matched = ", ".join(semantic_match.matched_concepts) or "none"
            reasons.append(
                f"semantic {semantic_intent.key} match {semantic_match.score:.2f} "
                f"({matched})"
            )
        if policy == "explore":
            reasons.append("explicit exploration policy favors novel tracks")
        else:
            reasons.append("gentle policy favors established evidence when available")

        return DiscoveryArtistCluster(
            artist_name=artist_name,
            seed_artist=seed_artist,
            source=source,
            source_match=source_match,
            score=score,
            artist_classification=artist_match.classification,
            artist_preference=artist_match.preference,
            artist_depth=artist_match.artist_depth,
            novelty_ratio=novelty_ratio,
            semantic_score=semantic_match.score if semantic_match.available else None,
            semantic_intent=semantic_intent.key if semantic_match.available else None,
            semantic_source=semantic_match.source if semantic_match.available else None,
            semantic_tags=semantic_match.tags if semantic_match.available else (),
            matched_semantics=(
                semantic_match.matched_concepts if semantic_match.available else ()
            ),
            tracks=tuple(tracks),
            reasons=tuple(reasons),
        )
