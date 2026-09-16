from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class SemanticIntent:
    key: str
    concepts: tuple[tuple[str, float], ...]
    provenance: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "concepts": [{"name": name, "weight": weight} for name, weight in self.concepts],
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True)
class SemanticMusicMatch:
    available: bool
    score: float = 0.0
    source: str = "none"
    matched_concepts: tuple[str, ...] = ()
    unmatched_concepts: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MusicSemanticAnalyzer(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def analyze(
        self,
        *,
        artist_name: str,
        track_name: Optional[str],
        intent: SemanticIntent,
    ) -> SemanticMusicMatch: ...


class LastFmTagSource(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def get_semantic_tags(
        self,
        artist_name: str,
        *,
        track_name: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]: ...


INTENT_PRESETS: dict[str, tuple[tuple[str, float], ...]] = {
    "energetic": (("energetic", 1.0), ("upbeat", 0.9), ("powerful", 0.8), ("fast", 0.7), ("positive", 0.5)),
    "gameday": (("sport", 1.0), ("energetic", 1.0), ("powerful", 0.9), ("epic", 0.8), ("party", 0.6), ("upbeat", 0.6)),
    "gameday_big_stakes": (("sport", 1.0), ("powerful", 1.0), ("epic", 1.0), ("energetic", 0.9), ("upbeat", 0.5)),
    "gameday_clutch": (("powerful", 1.0), ("epic", 1.0), ("sport", 0.9), ("energetic", 0.8), ("upbeat", 0.4)),
    "gameday_victory_lap": (("fun", 1.0), ("upbeat", 0.9), ("party", 0.7), ("sport", 0.5), ("chill", 0.4)),
    "gameday_preseason": (("sport", 0.8), ("upbeat", 0.8), ("fun", 0.7), ("energetic", 0.5), ("chill", 0.4)),
    "social": (("party", 1.0), ("fun", 0.9), ("upbeat", 0.9), ("dance", 0.8), ("energetic", 0.7)),
    "gaming": (("energetic", 0.7), ("epic", 0.6), ("atmospheric", 0.5), ("focus", 0.4)),
    "valheim": (("norse", 1.0), ("viking", 1.0), ("folk", 0.9), ("epic", 0.8), ("atmospheric", 0.8), ("medieval", 0.6), ("metal", 0.5)),
    "working": (("focus", 1.0), ("instrumental", 0.7), ("calm", 0.5), ("upbeat", 0.3)),
    "relax": (("calm", 1.0), ("chill", 0.9), ("ambient", 0.8), ("acoustic", 0.5)),
}

INTENT_ALIASES = {
    "game day": "gameday",
    "party": "social",
    "work": "working",
    "relaxing": "relax",
    "viking": "valheim",
    "norse": "valheim",
}

_STOP_WORDS = {"a", "an", "and", "feel", "feeling", "for", "home", "hub", "i", "im", "in", "m", "me", "mood", "music", "of", "play", "please", "set", "some", "something", "the", "to", "want", "with"}


class DeterministicSemanticIntentResolver:
    """Converts known HomeHub contexts or simple mood text to one stable contract."""

    def resolve(self, *, mode: str, request: Optional[str] = None) -> SemanticIntent:
        raw = str(request or mode or "").strip().casefold()
        key = INTENT_ALIASES.get(raw, raw)
        if key in INTENT_PRESETS:
            return SemanticIntent(key=key, concepts=INTENT_PRESETS[key], provenance=("deterministic_preset",))

        words = [word for word in re.findall(r"[a-z0-9]+", raw) if word not in _STOP_WORDS]
        unique_words = list(dict.fromkeys(words))
        if len(unique_words) == 1:
            preset_key = INTENT_ALIASES.get(unique_words[0], unique_words[0])
            if preset_key in INTENT_PRESETS:
                return SemanticIntent(
                    key=preset_key,
                    concepts=INTENT_PRESETS[preset_key],
                    provenance=("deterministic_preset_from_phrase",),
                )
        seen: set[str] = set()
        concepts: list[tuple[str, float]] = []
        for word in words[:8]:
            if word not in seen:
                seen.add(word)
                concepts.append((word, 1.0))
        return SemanticIntent(
            key=key or "unspecified",
            concepts=tuple(concepts),
            provenance=("deterministic_text_tokens",),
        )


CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "energetic": ("energetic", "energy", "high energy", "workout"),
    "upbeat": ("upbeat", "uplifting", "feel good"),
    "powerful": ("powerful", "anthemic", "arena rock", "power metal"),
    "fast": ("fast", "uptempo", "speed metal"),
    "positive": ("positive", "happy", "uplifting", "feel good"),
    "sport": ("sport", "sports", "stadium", "workout"),
    "epic": ("epic", "cinematic", "symphonic", "orchestral", "soundtrack"),
    "party": ("party", "club", "dance"),
    "fun": ("fun", "feel good", "happy"),
    "dance": ("dance", "danceable", "club", "edm"),
    "atmospheric": ("atmospheric", "ambient", "ethereal", "dark ambient"),
    "focus": ("focus", "concentration", "study", "instrumental"),
    "norse": ("norse", "nordic", "scandinavian", "viking", "pagan"),
    "viking": ("viking", "norse", "nordic", "viking metal"),
    "folk": ("folk", "folk metal", "neofolk"),
    "medieval": ("medieval", "medieval folk"),
    "metal": ("metal", "folk metal", "viking metal", "heavy metal"),
    "instrumental": ("instrumental", "soundtrack", "classical"),
    "calm": ("calm", "relaxing", "mellow", "soft", "chill"),
    "chill": ("chill", "chillout", "mellow", "relaxing"),
    "ambient": ("ambient", "atmospheric", "downtempo"),
    "acoustic": ("acoustic", "singer songwriter", "unplugged"),
}


def _normalize_tag(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold())).strip()


def _concept_strength(concept: str, tag_strengths: dict[str, float]) -> float:
    aliases = CONCEPT_ALIASES.get(concept, (concept,))
    best = 0.0
    for alias in aliases:
        norm_alias = _normalize_tag(alias)
        for tag, strength in tag_strengths.items():
            if tag == norm_alias or norm_alias in tag or tag in norm_alias:
                best = max(best, strength)
    return best


class LastFmSemanticAnalyzer:
    """Metadata-only semantic analyzer backed by source-qualified Last.fm top tags."""

    def __init__(self, source: LastFmTagSource) -> None:
        self._source = source

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._source, "enabled", False))

    async def analyze(
        self,
        *,
        artist_name: str,
        track_name: Optional[str],
        intent: SemanticIntent,
    ) -> SemanticMusicMatch:
        if not self.enabled or not intent.concepts:
            return SemanticMusicMatch(available=False)
        artist_tags = await self._source.get_semantic_tags(artist_name, limit=20)
        track_tags: list[dict] = []
        if track_name:
            track_tags = await self._source.get_semantic_tags(
                artist_name, track_name=track_name, limit=15,
            )
        if not artist_tags and not track_tags:
            return SemanticMusicMatch(available=False)

        strengths: dict[str, float] = {}
        raw_tags: list[str] = []
        provenance: list[str] = []
        for source_name, rows, source_weight in (
            ("lastfm_artist_tags", artist_tags, 0.7),
            ("lastfm_track_tags", track_tags, 1.0),
        ):
            if not rows:
                continue
            provenance.append(source_name)
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                norm = _normalize_tag(name)
                if not norm:
                    continue
                rank_strength = source_weight / (1.0 + 0.18 * index)
                strengths[norm] = max(strengths.get(norm, 0.0), rank_strength)
                if name not in raw_tags:
                    raw_tags.append(name)

        total_weight = sum(max(0.0, weight) for _, weight in intent.concepts)
        if total_weight <= 0:
            return SemanticMusicMatch(available=False)
        matched: list[str] = []
        unmatched: list[str] = []
        weighted = 0.0
        for concept, weight in intent.concepts:
            strength = _concept_strength(_normalize_tag(concept), strengths)
            weighted += max(0.0, weight) * strength
            (matched if strength > 0 else unmatched).append(concept)
        score = max(0.0, min(1.0, weighted / total_weight))
        return SemanticMusicMatch(
            available=True,
            score=score,
            source="lastfm_top_tags",
            matched_concepts=tuple(matched),
            unmatched_concepts=tuple(unmatched),
            tags=tuple(raw_tags[:20]),
            provenance=tuple(provenance),
        )