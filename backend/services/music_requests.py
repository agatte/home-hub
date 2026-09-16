from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from backend.services.music_curator import MusicIntent
from backend.services.music_discovery import MusicDiscoveryResult, MusicDiscoveryService
from backend.services.music_semantics import DeterministicSemanticIntentResolver
from backend.services.music_taste import MusicTasteProvider
from backend.services.playlist_catalog import MusicCatalog, VerifiedMusicCandidate

REQUEST_KINDS = ("familiar", "discovery", "mood", "recommendation")
REQUEST_MODES = ("general", "gameday", "social", "gaming", "working", "relax")
_MODE_ALIASES = {"pregameday": "gameday"}

_FAMILIAR_PHRASES = (
    "something familiar", "play familiar", "familiar music", "music i know",
    "something i know", "my favorites", "one of my favorites",
)
_DISCOVERY_PHRASES = (
    "play new music", "new music", "something new", "discover music",
    "discover something", "new artist", "new artists",
)
_RECOMMEND_PHRASES = (
    "what do you recommend", "recommend music", "recommend something",
    "what should i listen to", "give me a recommendation",
)


@dataclass(frozen=True)
class MusicRequest:
    request_text: str = ""
    kind: Optional[str] = None
    mode: Optional[str] = None
    semantic_request: Optional[str] = None
    source: str = "dashboard:music_request"


@dataclass(frozen=True)
class ResolvedMusicRequest:
    request_text: str
    kind: str
    mode: str
    policy: str
    familiarity_target: float
    novelty_target: float
    semantic_request: Optional[str]
    semantic_key: Optional[str]
    semantic_concepts: tuple[str, ...]
    source: str
    rationale: str
    provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["semantic_concepts"] = list(self.semantic_concepts)
        data["provenance"] = list(self.provenance)
        return data


@dataclass(frozen=True)
class FamiliarMusicSuggestion:
    candidate: VerifiedMusicCandidate
    score: float
    taste_classification: str
    taste_preference: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "score": round(self.score, 4),
            "taste_classification": self.taste_classification,
            "taste_preference": round(self.taste_preference, 4),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MusicRequestResult:
    status: str
    resolved_request: ResolvedMusicRequest
    familiar_suggestions: tuple[FamiliarMusicSuggestion, ...]
    discovery: Optional[MusicDiscoveryResult]
    note: Optional[str] = None
    shadow: bool = True
    actuation_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "shadow": self.shadow,
            "actuation_allowed": self.actuation_allowed,
            "resolved_request": self.resolved_request.to_dict(),
            "familiar_suggestions": [item.to_dict() for item in self.familiar_suggestions],
            "discovery": self.discovery.to_dict() if self.discovery is not None else None,
            "note": self.note,
        }


class MusicRequestResolver:
    """Resolve manual music language into one stable, provider-neutral contract."""

    def __init__(self, semantic_resolver: Optional[DeterministicSemanticIntentResolver] = None) -> None:
        self._semantic_resolver = semantic_resolver or DeterministicSemanticIntentResolver()

    def resolve(self, request: MusicRequest, *, current_mode: Optional[str] = None) -> ResolvedMusicRequest:
        text = str(request.request_text or "").strip()
        normalized = self._normalize(text)
        mode = self._mode(request.mode or current_mode)
        explicit_kind = str(request.kind or "").strip().casefold() or None
        if explicit_kind is not None and explicit_kind not in REQUEST_KINDS:
            raise ValueError(f"unsupported music request kind: {explicit_kind}")

        familiar = self._contains(normalized, _FAMILIAR_PHRASES)
        discovery = self._contains(normalized, _DISCOVERY_PHRASES)
        if familiar and discovery:
            raise ValueError("music request cannot ask for both familiar and new music")
        if explicit_kind == "familiar" and discovery:
            raise ValueError("structured familiar request conflicts with new-music language")
        if explicit_kind == "discovery" and familiar:
            raise ValueError("structured discovery request conflicts with familiar-music language")
        kind = explicit_kind or self._infer_kind(normalized, familiar=familiar, discovery=discovery)
        semantic_request = self._semantic_request(request, normalized, kind)
        semantic = None
        if semantic_request:
            semantic = self._semantic_resolver.resolve(mode=mode, request=semantic_request)

        if kind == "familiar":
            policy, familiarity, novelty = "gentle", 1.0, 0.0
            rationale = "Strict familiarity request; only proven/familiar identities may satisfy it."
        elif kind == "discovery":
            policy, familiarity, novelty = "explore", 0.2, 0.8
            rationale = "Explicit discovery request; raise novelty while retaining taste adjacency."
        else:
            policy, familiarity, novelty = "gentle", 0.8, 0.2
            rationale = "Ordinary request; keep the result familiarity-heavy with bounded exploration."

        provenance = ["music_request_resolver", f"source:{request.source}"]
        provenance.append("explicit_kind" if explicit_kind else "deterministic_phrase")
        provenance.append(f"mode:{mode}")
        if semantic is not None:
            provenance.extend(semantic.provenance)
        return ResolvedMusicRequest(
            request_text=text,
            kind=kind,
            mode=mode,
            policy=policy,
            familiarity_target=familiarity,
            novelty_target=novelty,
            semantic_request=semantic_request,
            semantic_key=semantic.key if semantic is not None else None,
            semantic_concepts=tuple(name for name, _ in semantic.concepts) if semantic else (),
            source=request.source,
            rationale=rationale,
            provenance=tuple(dict.fromkeys(provenance)),
        )

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.casefold().replace("’", "'").replace("â€™", "'")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _contains(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _mode(value: Optional[str]) -> str:
        mode = str(value or "general").strip().casefold() or "general"
        mode = _MODE_ALIASES.get(mode, mode)
        return mode if mode in REQUEST_MODES else "general"

    @staticmethod
    def _infer_kind(text: str, *, familiar: bool, discovery: bool) -> str:
        if familiar:
            return "familiar"
        if discovery:
            return "discovery"
        if any(phrase in text for phrase in _RECOMMEND_PHRASES) or not text:
            return "recommendation"
        return "mood"

    def _semantic_request(self, request: MusicRequest, text: str, kind: str) -> Optional[str]:
        explicit = str(request.semantic_request or "").strip()
        if explicit:
            return explicit
        if kind in {"mood"}:
            return request.request_text.strip() or None
        if kind not in {"familiar", "discovery"} or not text:
            return None

        residual = text
        phrases = _FAMILIAR_PHRASES if kind == "familiar" else _DISCOVERY_PHRASES
        for phrase in sorted(phrases, key=len, reverse=True):
            residual = residual.replace(phrase, " ")
        tokens = re.findall(r"[a-z0-9]+", residual)
        ignored = {
            "a", "and", "for", "give", "home", "hub", "i", "me", "music",
            "my", "play", "please", "some", "something", "the", "to", "want",
        }
        meaningful = [token for token in tokens if token not in ignored]
        return " ".join(meaningful) or None


class MusicRequestService:
    """Suggestion-only manual request surface over familiar and discovery evidence."""

    def __init__(
        self,
        *,
        app_state: Any,
        catalog: MusicCatalog,
        taste_provider: MusicTasteProvider,
        discovery: MusicDiscoveryService,
        resolver: Optional[MusicRequestResolver] = None,
    ) -> None:
        self._app_state = app_state
        self._catalog = catalog
        self._taste_provider = taste_provider
        self._discovery = discovery
        self._resolver = resolver or MusicRequestResolver()

    def status(self) -> dict[str, Any]:
        return {
            "shadow": True,
            "actuation_allowed": False,
            "supported_kinds": list(REQUEST_KINDS),
            "supported_modes": list(REQUEST_MODES),
            "familiar_catalog_available": bool(getattr(self._catalog, "available", True)),
            "discovery_enabled": self._discovery.enabled,
        }

    async def preview(
        self,
        request: MusicRequest,
        *,
        count: int = 6,
        tracks_per_artist: int = 3,
    ) -> MusicRequestResult:
        if count < 1 or count > 10:
            raise ValueError("count must be between 1 and 10")
        if tracks_per_artist < 1 or tracks_per_artist > 5:
            raise ValueError("tracks_per_artist must be between 1 and 5")
        current_mode = self._current_mode()
        resolved = self._resolver.resolve(request, current_mode=current_mode)
        familiar_limit, discovery_limit = self._allocation(resolved.kind, count)

        familiar: tuple[FamiliarMusicSuggestion, ...] = ()
        familiar_note: Optional[str] = None
        if familiar_limit:
            familiar, familiar_note = await self._familiar_suggestions(
                resolved, limit=familiar_limit,
            )

        discovery_result: Optional[MusicDiscoveryResult] = None
        if discovery_limit:
            discovery_result = await self._discovery.preview(
                resolved.mode,
                policy=resolved.policy,
                count=discovery_limit,
                tracks_per_artist=tracks_per_artist,
                intent=resolved.semantic_request,
            )

        has_discovery = bool(discovery_result and discovery_result.clusters)
        if familiar or has_discovery:
            status = "shadow_ready"
        elif discovery_result is not None and discovery_result.status == "source_unavailable":
            status = "source_unavailable"
        else:
            status = "no_candidates"
        return MusicRequestResult(
            status=status,
            resolved_request=resolved,
            familiar_suggestions=familiar,
            discovery=discovery_result,
            note=familiar_note,
        )

    def _current_mode(self) -> Optional[str]:
        automation = getattr(self._app_state, "automation", None)
        return getattr(automation, "current_mode", None) if automation is not None else None

    @staticmethod
    def _allocation(kind: str, count: int) -> tuple[int, int]:
        if kind == "familiar":
            return count, 0
        if kind == "discovery":
            return 0, count
        discovery = max(1, count // 5) if count >= 4 else 0
        return count - discovery, discovery

    async def _familiar_suggestions(
        self,
        resolved: ResolvedMusicRequest,
        *,
        limit: int,
    ) -> tuple[tuple[FamiliarMusicSuggestion, ...], Optional[str]]:
        try:
            snapshot = await self._taste_provider.snapshot()
        except Exception as exc:
            return (), f"taste snapshot unavailable: {type(exc).__name__}"

        intent = self._catalog_intent(resolved)
        candidates = await self._catalog.search(intent, limit=max(30, limit * 6))
        ranked: list[FamiliarMusicSuggestion] = []
        taste_mode = None if resolved.mode == "general" else resolved.mode
        for candidate in candidates:
            if not candidate.verified or not candidate.title.strip() or not candidate.uri.strip():
                continue
            match = snapshot.classify_candidate(candidate, mode=taste_mode)
            if match.classification not in {"familiar", "proven"}:
                continue
            class_score = 1.0 if match.classification == "proven" else 0.8
            preference = max(-1.0, min(1.0, float(match.preference)))
            preference_score = (preference + 1.0) / 2.0
            catalog_score = max(
                0.0,
                min(1.0, float(candidate.metadata.get("catalog_match_score") or 0.0)),
            )
            score = min(1.0, 0.72 * class_score + 0.18 * preference_score + 0.10 * catalog_score)
            reasons = [
                "provider-verified Sonos favorite",
                f"taste {match.classification} ({match.preference:+.2f})",
            ]
            matched = candidate.metadata.get("matched_concepts") or []
            if matched:
                reasons.append("matched request: " + ", ".join(str(x) for x in matched[:4]))
            ranked.append(FamiliarMusicSuggestion(
                candidate=candidate,
                score=score,
                taste_classification=match.classification,
                taste_preference=match.preference,
                reasons=tuple(reasons),
            ))
        ranked.sort(key=lambda item: (-item.score, item.candidate.title.casefold()))
        note = None if ranked else "no favorite currently has enough evidence to call it familiar"
        return tuple(ranked[:limit]), note

    def _catalog_intent(self, resolved: ResolvedMusicRequest) -> MusicIntent:
        concepts = resolved.semantic_concepts
        return MusicIntent(
            energy=0.5,
            familiarity=resolved.familiarity_target,
            novelty=resolved.novelty_target,
            nostalgia=0.5,
            singalong=0.5,
            aggressiveness=0.3,
            background_focus=0.5,
            genres=(),
            themes=concepts,
            search_concepts=concepts,
            rationale=resolved.rationale,
            source="music_request_resolver",
        )
