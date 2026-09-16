"""Canonical read-only taste/familiarity evidence for Music Intelligence (#255).

This layer aggregates existing HomeHub evidence without creating a second taste
database.  It keeps artist, track, and favorite familiarity separate and exposes
raw/derived provenance so future recommendation and autonomy policy can reason
about what is known versus merely adjacent.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import select

from backend.database import async_session
from backend.models import (
    MusicArtist,
    MusicFeedbackEvent,
    Recommendation,
    SonosPlaybackEvent,
    TasteProfile,
)

PLAYBACK_LOOKBACK = timedelta(days=180)
EXPLICIT_FEEDBACK_WEIGHTS = {
    "fits_me": (3.0, 0.0),
    "interesting": (0.5, 0.0),
    "not_for_me": (0.0, 3.0),
}


def _key(value: str) -> str:
    return value.strip().casefold()


def _track_key(track: str, artist: str = "") -> str:
    track_part = _key(track)
    artist_part = _key(artist)
    return f"{artist_part}|{track_part}" if artist_part else track_part


def _utc_iso(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _preference(positive: float, negative: float) -> float:
    total = positive + negative
    if total <= 0:
        return 0.0
    return max(-1.0, min(1.0, (positive - negative) / (total + 1.0)))


@dataclass(frozen=True)
class ContextTasteEvidence:
    positive_weight: float = 0.0
    negative_weight: float = 0.0
    preference: float = 0.0
    bandit_mean: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TasteEntityEvidence:
    kind: str
    identity: str
    familiarity: float
    preference: float
    positive_weight: float
    negative_weight: float
    depth: int
    sources: tuple[str, ...]
    last_observed_at: Optional[str]
    contexts: dict[str, ContextTasteEvidence] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = list(self.sources)
        data["contexts"] = {key: value.to_dict() for key, value in self.contexts.items()}
        return data


@dataclass(frozen=True)
class CandidateTasteMatch:
    classification: str
    familiarity: float
    preference: float
    artist_depth: int
    positive_weight: float
    negative_weight: float
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = list(self.sources)
        return data


@dataclass(frozen=True)
class MusicTasteSnapshot:
    generated_at: datetime
    profile_imported_at: Optional[str]
    genre_distribution: dict[str, float]
    mode_genre_map: dict[str, list[str]]
    artists: dict[str, TasteEntityEvidence]
    tracks: dict[str, TasteEntityEvidence]
    favorites: dict[str, TasteEntityEvidence]

    def classify_candidate(self, candidate: Any, *, mode: Optional[str] = None) -> CandidateTasteMatch:
        title = str(getattr(candidate, "title", "") or "").strip()
        media_type = str(getattr(candidate, "media_type", "") or "").strip().casefold()
        metadata = getattr(candidate, "metadata", {}) or {}
        artist_name = str(
            metadata.get("artist_name") or metadata.get("artist") or ""
        ).strip()
        track_name = str(
            metadata.get("track_name") or metadata.get("track") or ""
        ).strip()

        primary: Optional[TasteEntityEvidence] = None
        if media_type in {"favorite", "playlist", "station"} and title:
            primary = self.favorites.get(_key(title))
        elif media_type in {"track", "song"}:
            track_identity = track_name or title
            if track_identity:
                primary = self.tracks.get(_track_key(track_identity, artist_name))
                if primary is None:
                    primary = self.tracks.get(_track_key(track_identity))
        elif media_type == "artist":
            artist_identity = artist_name or title
            if artist_identity:
                primary = self.artists.get(_key(artist_identity))

        artist = self.artists.get(_key(artist_name)) if artist_name else None
        related = artist if artist is not primary else None
        entities = [entity for entity in (primary, related) if entity is not None]
        if not entities:
            return CandidateTasteMatch(
                classification="exploratory", familiarity=0.0, preference=0.0,
                artist_depth=0, positive_weight=0.0, negative_weight=0.0, sources=(),
            )

        # Familiarity belongs to the candidate identity itself.  A known artist
        # may make a new track adjacent/promising, but never makes that track
        # familiar by implication.
        familiarity = primary.familiarity if primary is not None else 0.0
        positive = primary.positive_weight if primary is not None else 0.0
        negative = primary.negative_weight if primary is not None else 0.0
        sources = tuple(sorted({source for entity in entities for source in entity.sources}))
        artist_depth = artist.depth if artist is not None else 0

        def entity_preference(entity: TasteEntityEvidence) -> float:
            if mode and mode in entity.contexts:
                return entity.contexts[mode].preference
            return entity.preference

        if primary is not None:
            preference = entity_preference(primary)
            if related is not None:
                # Artist affinity is adjacency evidence, not identity evidence.
                preference = (0.75 * preference) + (0.25 * entity_preference(related))
        elif related is not None:
            preference = 0.5 * entity_preference(related)
        else:
            preference = 0.0

        if primary is not None and preference <= -0.35 and negative >= 2.0:
            classification = "rejected"
        elif (
            primary is not None
            and familiarity >= 0.75
            and preference >= 0.25
            and positive >= 2.0
        ):
            classification = "proven"
        elif primary is not None and familiarity >= 0.75:
            classification = "familiar"
        else:
            classification = "exploratory"

        return CandidateTasteMatch(
            classification=classification,
            familiarity=round(familiarity, 4),
            preference=round(preference, 4),
            artist_depth=artist_depth,
            positive_weight=round(positive, 4),
            negative_weight=round(negative, 4),
            sources=sources,
        )

    def summary(self, *, limit: int = 10) -> dict[str, Any]:
        def top(items: dict[str, TasteEntityEvidence]) -> list[dict[str, Any]]:
            ranked = sorted(
                items.values(),
                key=lambda item: (-item.preference, -item.positive_weight, item.identity.casefold()),
            )[:limit]
            return [item.to_dict() for item in ranked]

        return {
            "generated_at": self.generated_at.isoformat(),
            "profile_imported_at": self.profile_imported_at,
            "entity_counts": {
                "artists": len(self.artists),
                "tracks": len(self.tracks),
                "favorites": len(self.favorites),
            },
            "top_artists": top(self.artists),
            "top_favorites": top(self.favorites),
            "genre_distribution": self.genre_distribution,
            "mode_genre_map": self.mode_genre_map,
        }


class MusicTasteProvider(Protocol):
    async def snapshot(self) -> MusicTasteSnapshot: ...


@dataclass
class _ContextAccumulator:
    positive: float = 0.0
    negative: float = 0.0
    bandit_mean: Optional[float] = None


@dataclass
class _Accumulator:
    kind: str
    identity: str
    familiarity: float = 0.0
    positive: float = 0.0
    negative: float = 0.0
    depth: int = 0
    sources: set[str] = field(default_factory=set)
    last_observed_at: Optional[datetime] = None
    contexts: dict[str, _ContextAccumulator] = field(default_factory=dict)
    positive_tracks: set[str] = field(default_factory=set)

    def observe(
        self,
        *,
        source: str,
        familiarity: float = 0.0,
        positive: float = 0.0,
        negative: float = 0.0,
        depth: int = 0,
        observed_at: Optional[datetime] = None,
        mode: Optional[str] = None,
    ) -> None:
        self.sources.add(source)
        self.familiarity = max(self.familiarity, max(0.0, min(1.0, familiarity)))
        self.positive += max(0.0, positive)
        self.negative += max(0.0, negative)
        self.depth = max(self.depth, max(0, int(depth)))
        if observed_at is not None:
            normalized = observed_at
            if normalized.tzinfo is None:
                normalized = normalized.replace(tzinfo=timezone.utc)
            normalized = normalized.astimezone(timezone.utc)
            if self.last_observed_at is None or normalized > self.last_observed_at:
                self.last_observed_at = normalized
        if mode:
            context = self.contexts.setdefault(mode, _ContextAccumulator())
            context.positive += max(0.0, positive)
            context.negative += max(0.0, negative)

    def finalize(self) -> TasteEntityEvidence:
        contexts: dict[str, ContextTasteEvidence] = {}
        for mode, context in self.contexts.items():
            base = _preference(context.positive, context.negative)
            if context.bandit_mean is None:
                preference = base
            else:
                bandit_pref = (2.0 * context.bandit_mean) - 1.0
                if context.positive + context.negative > 0:
                    preference = (0.6 * base) + (0.4 * bandit_pref)
                else:
                    preference = bandit_pref
            contexts[mode] = ContextTasteEvidence(
                positive_weight=round(context.positive, 4),
                negative_weight=round(context.negative, 4),
                preference=round(max(-1.0, min(1.0, preference)), 4),
                bandit_mean=(
                    round(context.bandit_mean, 4)
                    if context.bandit_mean is not None else None
                ),
            )
        return TasteEntityEvidence(
            kind=self.kind,
            identity=self.identity,
            familiarity=round(self.familiarity, 4),
            preference=round(_preference(self.positive, self.negative), 4),
            positive_weight=round(self.positive, 4),
            negative_weight=round(self.negative, 4),
            depth=max(self.depth, len(self.positive_tracks)),
            sources=tuple(sorted(self.sources)),
            last_observed_at=_utc_iso(self.last_observed_at),
            contexts=contexts,
        )


def build_music_taste_snapshot(
    *,
    artists: list[Any],
    recommendations: list[Any],
    playback_events: list[Any],
    explicit_feedback: Optional[list[Any]] = None,
    profile: Any = None,
    bandit_status: Optional[dict[str, Any]] = None,
    generated_at: Optional[datetime] = None,
) -> MusicTasteSnapshot:
    generated_at = generated_at or datetime.now(timezone.utc)
    artist_acc: dict[str, _Accumulator] = {}
    track_acc: dict[str, _Accumulator] = {}
    favorite_acc: dict[str, _Accumulator] = {}

    def entity(store: dict[str, _Accumulator], kind: str, identity: str) -> _Accumulator:
        key = _key(identity)
        current = store.get(key)
        if current is None:
            current = _Accumulator(kind=kind, identity=identity.strip())
            store[key] = current
        return current

    for row in artists:
        name = str(getattr(row, "name", "") or "").strip()
        if not name or str(getattr(row, "source", "import") or "") != "import":
            continue
        play_count = max(0, int(getattr(row, "play_count", 0) or 0))
        bounded_plays = min(2.0, math.log1p(play_count) / math.log(51) * 2.0) if play_count else 0.0
        rating = getattr(row, "rating_avg", None)
        positive = bounded_plays
        negative = 0.0
        if isinstance(rating, (int, float)):
            if rating > 3:
                positive += min(1.5, (float(rating) - 3.0) * 0.75)
            elif rating < 3:
                negative += min(1.5, (3.0 - float(rating)) * 0.75)
        entity(artist_acc, "artist", name).observe(
            source="library_import",
            familiarity=1.0,
            positive=positive,
            negative=negative,
            depth=max(0, int(getattr(row, "track_count", 0) or 0)),
            observed_at=getattr(row, "created_at", None),
        )

    for rec in recommendations:
        status = str(getattr(rec, "status", "") or "").casefold()
        if status not in {"liked", "dismissed"}:
            continue
        positive = 3.0 if status == "liked" else 0.0
        negative = 3.0 if status == "dismissed" else 0.0
        source = f"recommendation_{status}"
        artist_name = str(getattr(rec, "artist_name", "") or "").strip()
        track_name = str(getattr(rec, "track_name", "") or "").strip()
        observed_at = getattr(rec, "created_at", None)
        mode = str(getattr(rec, "source_mode", "") or "").strip() or None
        if artist_name:
            acc = entity(artist_acc, "artist", artist_name)
            acc.observe(
                source=source, familiarity=1.0, positive=positive, negative=negative,
                observed_at=observed_at, mode=mode,
            )
            if status == "liked" and track_name:
                acc.positive_tracks.add(_key(track_name))
        if track_name:
            track_key = _track_key(track_name, artist_name)
            acc = track_acc.get(track_key)
            if acc is None:
                acc = _Accumulator(kind="track", identity=track_name)
                track_acc[track_key] = acc
            acc.observe(
                source=source,
                familiarity=0.8 if status == "liked" else 0.5,
                positive=positive,
                negative=negative,
                observed_at=observed_at,
                mode=mode,
            )

    for feedback in explicit_feedback or []:
        action = str(getattr(feedback, "action", "") or "").casefold()
        weights = EXPLICIT_FEEDBACK_WEIGHTS.get(action)
        if weights is None:
            continue
        positive, negative = weights
        target_kind = str(getattr(feedback, "target_kind", "artist") or "artist").casefold()
        artist_name = str(getattr(feedback, "artist_name", "") or "").strip()
        track_name = str(getattr(feedback, "target_track_name", "") or "").strip()
        provider = str(getattr(feedback, "provider", "") or "unknown").strip().casefold()
        source = f"explicit_feedback:{action}:{provider}"
        observed_at = getattr(feedback, "created_at", None)
        mode = str(getattr(feedback, "mode", "") or "").strip() or None
        if not artist_name:
            continue
        if target_kind == "artist":
            entity(artist_acc, "artist", artist_name).observe(
                source=source,
                positive=positive,
                negative=negative,
                observed_at=observed_at,
                mode=mode,
            )
            continue
        if target_kind != "track" or not track_name:
            continue
        track_key = _track_key(track_name, artist_name)
        track = track_acc.get(track_key)
        if track is None:
            track = _Accumulator(kind="track", identity=track_name)
            track_acc[track_key] = track
        track.observe(
            source=source,
            positive=positive,
            negative=negative,
            observed_at=observed_at,
            mode=mode,
        )
        artist = entity(artist_acc, "artist", artist_name)
        artist.observe(
            source=source,
            positive=positive * 0.25,
            negative=negative * 0.25,
            observed_at=observed_at,
            mode=mode,
        )
        if action == "fits_me":
            artist.positive_tracks.add(_key(track_name))

    for event in playback_events:
        title = str(getattr(event, "favorite_title", "") or "").strip()
        if not title:
            continue
        event_type = str(getattr(event, "event_type", "") or "").casefold()
        triggered_by = str(getattr(event, "triggered_by", "") or "").casefold()
        positive = negative = 0.0
        if event_type == "play" and triggered_by == "manual":
            positive = 1.5
        elif event_type == "auto_play":
            positive = 0.25
        elif event_type == "suggestion" and triggered_by == "suggestion_accepted":
            positive = 2.0
        elif event_type == "skip":
            negative = 1.5
        entity(favorite_acc, "favorite", title).observe(
            source="sonos_playback",
            familiarity=1.0,
            positive=positive,
            negative=negative,
            observed_at=getattr(event, "timestamp", None),
            mode=str(getattr(event, "mode_at_time", "") or "").strip() or None,
        )

    if isinstance(bandit_status, dict):
        top_arms = bandit_status.get("top_arms") or {}
        if isinstance(top_arms, dict):
            for mode, by_weather in top_arms.items():
                if not isinstance(by_weather, dict):
                    continue
                per_title: dict[str, list[float]] = {}
                display: dict[str, str] = {}
                for entries in by_weather.values():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict) or not entry.get("title"):
                            continue
                        try:
                            mean = float(entry.get("mean"))
                        except (TypeError, ValueError):
                            continue
                        title = str(entry["title"]).strip()
                        if not title:
                            continue
                        key = _key(title)
                        display.setdefault(key, title)
                        per_title.setdefault(key, []).append(max(0.0, min(1.0, mean)))
                for key, means in per_title.items():
                    acc = entity(favorite_acc, "favorite", display[key])
                    acc.sources.add("music_bandit")
                    acc.familiarity = max(acc.familiarity, 1.0)
                    context = acc.contexts.setdefault(str(mode), _ContextAccumulator())
                    context.bandit_mean = sum(means) / len(means)

    profile_imported_at = _utc_iso(getattr(profile, "last_import_at", None)) if profile else None
    genre_distribution = dict(getattr(profile, "genre_distribution", {}) or {}) if profile else {}
    mode_genre_map = dict(getattr(profile, "mode_genre_map", {}) or {}) if profile else {}

    return MusicTasteSnapshot(
        generated_at=generated_at.astimezone(timezone.utc),
        profile_imported_at=profile_imported_at,
        genre_distribution=genre_distribution,
        mode_genre_map=mode_genre_map,
        artists={key: value.finalize() for key, value in artist_acc.items()},
        tracks={key: value.finalize() for key, value in track_acc.items()},
        favorites={key: value.finalize() for key, value in favorite_acc.items()},
    )


class MusicTasteService:
    """Build snapshots from current durable evidence; performs no writes."""

    def __init__(self, *, bandit: Any = None, session_factory=async_session) -> None:
        self._bandit = bandit
        self._session_factory = session_factory

    async def snapshot(self) -> MusicTasteSnapshot:
        cutoff = datetime.now(timezone.utc) - PLAYBACK_LOOKBACK
        async with self._session_factory() as session:
            profile_result = await session.execute(select(TasteProfile).limit(1))
            profile = profile_result.scalar_one_or_none()
            artists_result = await session.execute(
                select(MusicArtist).where(MusicArtist.source == "import")
            )
            recommendations_result = await session.execute(
                select(Recommendation).where(
                    Recommendation.status.in_(["liked", "dismissed"])
                )
            )
            playback_result = await session.execute(
                select(SonosPlaybackEvent).where(
                    SonosPlaybackEvent.timestamp >= cutoff,
                    SonosPlaybackEvent.favorite_title.is_not(None),
                )
            )
            feedback_result = await session.execute(
                select(MusicFeedbackEvent).order_by(MusicFeedbackEvent.created_at.asc())
            )
            artists = list(artists_result.scalars().all())
            recommendations = list(recommendations_result.scalars().all())
            playback_events = list(playback_result.scalars().all())
            explicit_feedback = list(feedback_result.scalars().all())

        bandit_status = None
        if self._bandit is not None:
            try:
                bandit_status = self._bandit.get_status()
            except Exception:
                bandit_status = None
        return build_music_taste_snapshot(
            artists=artists,
            recommendations=recommendations,
            playback_events=playback_events,
            explicit_feedback=explicit_feedback,
            profile=profile,
            bandit_status=bandit_status,
        )
