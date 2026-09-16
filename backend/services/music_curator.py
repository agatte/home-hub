"""Shadow-only, provider-verified Music Curator.

The model translates trusted HomeHub facts into a structured music intent.  It
never names a playable provider object and cannot actuate Sonos.  A separate
``MusicCatalog`` verifies real candidates, then this service ranks those
verified candidates using only bounded intent + existing preference evidence.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol
from zoneinfo import ZoneInfo


from backend.services.music_mapper import DEFAULT_PREGAME_HYPE_FAVORITE, _time_period
from backend.services.music_taste import MusicTasteProvider, MusicTasteSnapshot
from backend.services.playlist_catalog import MusicCatalog, VerifiedMusicCandidate
from backend.services.playoff_state_refresh import PLAYOFF_STATE_KEY, TEAM_FORM_KEY

logger = logging.getLogger("home_hub.music.curator")
TZ = ZoneInfo("America/Indiana/Indianapolis")
MAX_CONTEXT_AGE = timedelta(minutes=15)
SETTING_FACT_MAX_AGE = timedelta(days=8)
CURATOR_CACHE_TTL = timedelta(hours=1)


class MusicCuratorError(RuntimeError):
    pass


class MusicCuratorUnavailable(MusicCuratorError):
    pass


@dataclass(frozen=True)
class CuratorFact:
    value: Any
    source: str
    observed_at: Optional[str] = None
    usable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MusicCuratorContext:
    mode: str
    generated_at: datetime
    facts: dict[str, CuratorFact] = field(default_factory=dict)
    suppression_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "generated_at": self.generated_at.isoformat(),
            "suppression_reason": self.suppression_reason,
            "facts": {key: fact.to_dict() for key, fact in self.facts.items()},
        }

    def prompt_payload(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class MusicIntent:
    energy: float
    familiarity: float
    novelty: float
    nostalgia: float
    singalong: float
    aggressiveness: float
    background_focus: float
    genres: tuple[str, ...]
    themes: tuple[str, ...]
    search_concepts: tuple[str, ...]
    rationale: str
    source: str = "intent_provider"

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], *, source: str = "intent_provider") -> "MusicIntent":
        def bounded(name: str, default: float = 0.5) -> float:
            try:
                value = float(raw.get(name, default))
            except (TypeError, ValueError):
                value = default
            return max(0.0, min(1.0, value))

        def strings(name: str, limit: int) -> tuple[str, ...]:
            values = raw.get(name) or []
            if not isinstance(values, list):
                values = []
            cleaned: list[str] = []
            for value in values:
                text = str(value).strip()
                if text and text.casefold() not in {x.casefold() for x in cleaned}:
                    cleaned.append(text[:80])
                if len(cleaned) >= limit:
                    break
            return tuple(cleaned)

        return cls(
            energy=bounded("energy"),
            familiarity=bounded("familiarity", 0.75),
            novelty=bounded("novelty", 0.25),
            nostalgia=bounded("nostalgia"),
            singalong=bounded("singalong"),
            aggressiveness=bounded("aggressiveness"),
            background_focus=bounded("background_focus"),
            genres=strings("genres", 6),
            themes=strings("themes", 6),
            search_concepts=strings("search_concepts", 10),
            rationale=str(raw.get("rationale") or "Context-shaped music intent.").strip()[:500],
            source=source,
        )

    @classmethod
    def fallback(cls) -> "MusicIntent":
        return cls(
            energy=0.5,
            familiarity=1.0,
            novelty=0.0,
            nostalgia=0.5,
            singalong=0.5,
            aggressiveness=0.3,
            background_focus=0.5,
            genres=(), themes=(), search_concepts=(),
            rationale="Intent provider unavailable; preserve the existing verified candidate pool.",
            source="deterministic_fallback",
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("genres", "themes", "search_concepts"):
            data[key] = list(data[key])
        return data


class MusicIntentProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    async def generate(self, context: MusicCuratorContext) -> MusicIntent: ...


class UnavailableMusicIntentProvider:
    """Deliberate placeholder until a reasoning provider is selected.

    Keeping this as a provider implementation makes the curator runtime-safe
    without embedding any LLM vendor in the shared Music Intelligence contract.
    The curator will fall back to verified/proven candidates only.
    """

    def __init__(self, reason: str = "no intent provider configured") -> None:
        self._reason = reason

    @property
    def configured(self) -> bool:
        return False

    async def generate(self, context: MusicCuratorContext) -> MusicIntent:
        del context
        raise MusicCuratorUnavailable(self._reason)


@dataclass(frozen=True)
class CuratorSuggestion:
    candidate: VerifiedMusicCandidate
    score: float
    reason: str
    bandit_mean: Optional[float] = None
    taste_classification: Optional[str] = None
    taste_preference: Optional[float] = None
    artist_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "score": round(self.score, 4),
            "reason": self.reason,
            "bandit_mean": self.bandit_mean,
            "taste_classification": self.taste_classification,
            "taste_preference": self.taste_preference,
            "artist_depth": self.artist_depth,
        }


@dataclass(frozen=True)
class CuratorResult:
    status: str
    context: MusicCuratorContext
    intent: Optional[MusicIntent]
    suggestions: tuple[CuratorSuggestion, ...]
    shadow: bool = True
    actuation_allowed: bool = False
    cache_hit: bool = False
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "shadow": self.shadow,
            "actuation_allowed": self.actuation_allowed,
            "cache_hit": self.cache_hit,
            "note": self.note,
            "context": self.context.to_dict(),
            "intent": self.intent.to_dict() if self.intent else None,
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
        }


class MusicContextAdapter(Protocol):
    """Mode-specific factual context source for the shared curator."""

    mode: str
    mapping_mode: str
    fallback_titles: tuple[str, ...]

    async def augment(
        self,
        facts: dict[str, CuratorFact],
        now: datetime,
    ) -> Optional[str]: ...


class GameDayContextAdapter:
    """Source-qualified Colts/Game Day facts; never computes sports truth."""

    mode = "gameday"
    mapping_mode = "pregameday"
    fallback_titles = (DEFAULT_PREGAME_HYPE_FAVORITE,)

    def __init__(
        self,
        app_state: Any,
        *,
        setting_loader: Optional[Callable[[str], Awaitable[Any]]] = None,
    ) -> None:
        self._app_state = app_state
        self._setting_loader = setting_loader

    async def augment(
        self,
        facts: dict[str, CuratorFact],
        now: datetime,
    ) -> Optional[str]:
        gameday = getattr(self._app_state, "gameday", None)
        state = None
        if gameday is not None:
            try:
                state = gameday.current_state()
            except Exception:
                state = None
        if state is not None:
            facts["opponent"] = CuratorFact(state.opponent, "gameday_state")
            facts["game_status"] = CuratorFact(state.status, "gameday_state")
            facts["kickoff_utc"] = CuratorFact(
                state.kickoff_utc.isoformat() if state.kickoff_utc else None,
                "gameday_state",
            )
        elif gameday is not None:
            try:
                peek = getattr(gameday, "peek_upcoming_schedule", None)
                if callable(peek):
                    upcoming = peek(limit=1)
                    schedule_source = "gameday_schedule_cache"
                else:
                    upcoming = await gameday.get_upcoming_schedule(limit=1)
                    schedule_source = "gameday_schedule"
            except Exception:
                upcoming = []
            if upcoming:
                game = upcoming[0]
                facts["opponent"] = CuratorFact(
                    game.get("opponent"), schedule_source,
                )
                facts["home_away"] = CuratorFact(
                    "home" if game.get("colts_are_home") else "away",
                    schedule_source,
                )
                kickoff = game.get("kickoff_utc")
                facts["kickoff_utc"] = CuratorFact(
                    kickoff.isoformat() if isinstance(kickoff, datetime) else kickoff,
                    schedule_source,
                )

        if self._setting_loader is None:
            return None
        stakes = await self._load_setting(PLAYOFF_STATE_KEY)
        if isinstance(stakes, dict):
            observed = stakes.get("refreshed_at")
            usable = _setting_snapshot_usable(stakes, now)
            for key in (
                "season_week", "playoff_probability", "division_gap_games",
                "is_eliminated", "is_preseason", "record",
            ):
                if key in stakes:
                    facts[key] = CuratorFact(
                        stakes.get(key), PLAYOFF_STATE_KEY, observed, usable=usable,
                    )

        form = await self._load_setting(TEAM_FORM_KEY)
        if isinstance(form, dict):
            observed = form.get("refreshed_at")
            usable = _setting_snapshot_usable(form, now)
            for key in (
                "last4_record", "win_streak", "last_game_result",
                "last_game_margin", "season_record",
            ):
                if key in form:
                    facts[key] = CuratorFact(
                        form.get(key), TEAM_FORM_KEY, observed, usable=usable,
                    )

        # Elimination/preseason remain factual curator inputs, not shared-core
        # hard suppressions.  The existing deterministic Game Day audio policy
        # continues to own whether those states silence current production
        # playback; #254 must not invent a parallel no-music rule.
        return None

    async def _load_setting(self, key: str) -> Any:
        try:
            return await self._setting_loader(key) or {}
        except Exception:
            return {}


class SocialContextAdapter:
    """Current Sonos/session facts for Social without choosing music."""

    mode = "social"
    mapping_mode = "social"
    fallback_titles: tuple[str, ...] = ()

    def __init__(self, app_state: Any) -> None:
        self._app_state = app_state

    async def augment(
        self,
        facts: dict[str, CuratorFact],
        now: datetime,
    ) -> Optional[str]:
        automation = getattr(self._app_state, "automation", None)
        if automation is not None:
            active = getattr(automation, "current_mode", None) == "social"
            facts["social_active"] = CuratorFact(active, "automation_engine")
            changed = getattr(automation, "last_activity_change", None)
            if active and isinstance(changed, datetime):
                if changed.tzinfo is None:
                    changed = changed.replace(tzinfo=now.tzinfo or timezone.utc)
                age = max(0.0, (now - changed).total_seconds())
                phase = "arrival" if age < 30 * 60 else "steady" if age < 2 * 60 * 60 else "long_session"
                facts["social_session_phase"] = CuratorFact(
                    phase, "automation_engine", changed.isoformat(),
                )

        sonos = getattr(self._app_state, "sonos", None)
        if sonos is None or not getattr(sonos, "connected", False):
            facts["sonos_connected"] = CuratorFact(False, "sonos")
            return None
        facts["sonos_connected"] = CuratorFact(True, "sonos")
        try:
            status = await sonos.get_status()
        except Exception:
            return None
        if isinstance(status, dict):
            facts["sonos_state"] = CuratorFact(status.get("state"), "sonos")
            current = status.get("title") or status.get("track")
            if current:
                facts["current_track"] = CuratorFact(current, "sonos")
        return None


class GamingContextAdapter:
    """Trusted Gaming facts; a running background game is never game identity."""

    mode = "gaming"
    mapping_mode = "gaming"
    fallback_titles: tuple[str, ...] = ()
    _MAX_PROCESS_AGE_SECONDS = 30.0
    _FOREGROUND_QUALIFICATIONS = {"foreground_game", "foreground_runelite_java"}

    def __init__(self, app_state: Any) -> None:
        self._app_state = app_state

    async def augment(
        self,
        facts: dict[str, CuratorFact],
        now: datetime,
    ) -> Optional[str]:
        del now
        automation = getattr(self._app_state, "automation", None)
        if automation is None:
            facts["gaming_active"] = CuratorFact(False, "automation_engine")
            return None
        try:
            context = automation.get_activity_context()
        except Exception:
            context = {}
        active = context.get("current_activity") == "gaming"
        facts["gaming_active"] = CuratorFact(active, "automation_engine")
        facts["gaming_activity_source"] = CuratorFact(
            context.get("current_activity_source"), "automation_engine",
        )
        desktop = (context.get("process_observations_by_device") or {}).get("desktop") or {}
        qualification = desktop.get("gaming_qualification")
        observed_at = desktop.get("received_at")
        try:
            age = float(desktop.get("age_seconds"))
        except (TypeError, ValueError):
            age = float("inf")
        foreground = bool(
            active
            and 0.0 <= age <= self._MAX_PROCESS_AGE_SECONDS
            and desktop.get("candidate_mode") == "gaming"
            and qualification in self._FOREGROUND_QUALIFICATIONS
        )
        facts["gaming_qualification"] = CuratorFact(
            qualification, "automation_engine:desktop_process", observed_at,
            usable=(0.0 <= age <= self._MAX_PROCESS_AGE_SECONDS),
        )
        facts["gaming_identity_trusted"] = CuratorFact(
            foreground, "automation_engine:desktop_process", observed_at,
        )
        game = getattr(automation, "current_game", None)
        if game:
            facts["game"] = CuratorFact(
                game,
                "automation_engine:desktop_foreground_game" if foreground
                else "automation_engine:untrusted_game_context",
                observed_at,
                usable=foreground,
            )
        return None


def _setting_snapshot_usable(payload: dict[str, Any], now: datetime) -> bool:
    refreshed = payload.get("refreshed_at")
    if not refreshed:
        return False
    try:
        observed = datetime.fromisoformat(str(refreshed).replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)
    return timedelta(0) <= age <= SETTING_FACT_MAX_AGE


class MusicCuratorContextBuilder:
    """Compose common facts with registered mode-specific context adapters."""

    def __init__(
        self,
        app_state: Any,
        *,
        setting_loader: Optional[Callable[[str], Awaitable[Any]]] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        adapters: Optional[list[MusicContextAdapter]] = None,
    ) -> None:
        self._app_state = app_state
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        if adapters is None:
            adapters = [
                GameDayContextAdapter(app_state, setting_loader=setting_loader),
                SocialContextAdapter(app_state),
                GamingContextAdapter(app_state),
            ]
        self._adapters = {adapter.mode: adapter for adapter in adapters}
        if len(self._adapters) != len(adapters):
            raise ValueError("duplicate music context adapter mode")

    @property
    def supported_modes(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    async def build(self, mode: str) -> MusicCuratorContext:
        adapter = self._adapters.get(mode)
        if adapter is None:
            raise ValueError(f"unsupported curator mode: {mode}")
        now = self._now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local = now.astimezone(TZ)
        facts: dict[str, CuratorFact] = {
            "local_period": CuratorFact(_time_period(local.hour), "home_clock", local.isoformat()),
            "local_weekday": CuratorFact(local.strftime("%A"), "home_clock", local.isoformat()),
            "local_hour": CuratorFact(local.hour, "home_clock", local.isoformat()),
        }

        suppression = self._automation_facts(facts)
        self._weather_fact(facts)
        self._mapping_facts(adapter, facts)
        adapter_suppression = await adapter.augment(facts, now)
        suppression = suppression or adapter_suppression

        return MusicCuratorContext(
            mode=mode,
            generated_at=now.astimezone(timezone.utc),
            facts=facts,
            suppression_reason=suppression,
        )

    def _automation_facts(self, facts: dict[str, CuratorFact]) -> Optional[str]:
        automation = getattr(self._app_state, "automation", None)
        if automation is None:
            return None
        house_state = getattr(automation, "house_state", None)
        current_mode = getattr(automation, "current_mode", None)
        try:
            dnd = bool(automation.is_dnd_active())
        except Exception:
            dnd = False
        facts["house_state"] = CuratorFact(house_state, "automation_engine")
        facts["current_mode"] = CuratorFact(current_mode, "automation_engine")
        facts["dnd_active"] = CuratorFact(dnd, "automation_engine")
        if dnd:
            return "dnd_active"
        if current_mode == "sleeping":
            return "sleeping"
        if house_state not in (None, "home"):
            return f"house_state_{house_state}"
        return None

    def _weather_fact(self, facts: dict[str, CuratorFact]) -> None:
        weather = getattr(self._app_state, "weather_service", None)
        if weather is None:
            return
        try:
            snapshot = weather.get_cache_snapshot()
        except Exception:
            return
        condition = snapshot.get("condition_family")
        if condition:
            facts["weather"] = CuratorFact(
                condition,
                f"weather:{snapshot.get('provenance') or 'unknown'}",
                snapshot.get("observed_at"),
                usable=bool(snapshot.get("fresh")),
            )

    def _mapping_facts(
        self,
        adapter: MusicContextAdapter,
        facts: dict[str, CuratorFact],
    ) -> None:
        mapper = getattr(self._app_state, "music_mapper", None)
        if mapper is not None:
            entries = (mapper.mapping or {}).get(adapter.mapping_mode, [])
            mapped = [
                {"title": entry.get("favorite_title"), "vibe": entry.get("vibe")}
                for entry in entries if entry.get("favorite_title")
            ]
            facts["mapped_playlists"] = CuratorFact(
                mapped, f"music_mapper:{adapter.mapping_mode}",
            )
        if adapter.fallback_titles:
            facts["deterministic_fallback_titles"] = CuratorFact(
                list(adapter.fallback_titles), f"{adapter.mode}_deterministic_policy",
            )

class MusicCurator:
    """Non-actuating curator that ranks only provider-verified candidates."""

    def __init__(
        self,
        *,
        context_builder: MusicCuratorContextBuilder,
        intent_provider: MusicIntentProvider,
        catalog: MusicCatalog,
        bandit: Any = None,
        taste_provider: Optional[MusicTasteProvider] = None,
    ) -> None:
        self._context_builder = context_builder
        self._intent_provider = intent_provider
        self._catalog = catalog
        self._bandit = bandit
        self._taste_provider = taste_provider
        self._preview_cache: dict[str, tuple[str, datetime, CuratorResult]] = {}

    @property
    def configured(self) -> bool:
        return bool(getattr(self._intent_provider, "configured", False))

    @property
    def supported_modes(self) -> tuple[str, ...]:
        return self._context_builder.supported_modes

    def supports_mode(self, mode: str) -> bool:
        return mode in self.supported_modes

    def status(self) -> dict[str, Any]:
        return {
            "shadow": True,
            "actuation_allowed": False,
            "supported_modes": list(self.supported_modes),
            "intent_provider_configured": self.configured,
            "catalog": type(self._catalog).__name__,
            "taste_provider": (
                type(self._taste_provider).__name__ if self._taste_provider is not None else None
            ),
            "cache_entries": len(self._preview_cache),
        }

    async def preview(self, mode: str, *, limit: int = 6) -> CuratorResult:
        context = await self._context_builder.build(mode)
        signature = self._context_signature(context, limit)
        cached = self._preview_cache.get(mode)
        now = datetime.now(timezone.utc)
        if cached is not None:
            cached_signature, cached_at, cached_result = cached
            if cached_signature == signature and now - cached_at <= CURATOR_CACHE_TTL:
                return CuratorResult(
                    status=cached_result.status,
                    context=context,
                    intent=cached_result.intent,
                    suggestions=cached_result.suggestions,
                    cache_hit=True,
                    note=cached_result.note,
                )
        result = await self.curate(context, limit=limit)
        self._preview_cache[mode] = (signature, now, result)
        return result

    @staticmethod
    def _context_signature(context: MusicCuratorContext, limit: int) -> str:
        payload = {
            "mode": context.mode,
            "suppression_reason": context.suppression_reason,
            "limit": limit,
            "facts": {key: fact.to_dict() for key, fact in context.facts.items()},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def curate(self, context: MusicCuratorContext, *, limit: int = 6) -> CuratorResult:
        if not self.supports_mode(context.mode):
            raise ValueError(f"unsupported curator mode: {context.mode}")
        now = datetime.now(timezone.utc)
        generated = context.generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        if now - generated.astimezone(timezone.utc) > MAX_CONTEXT_AGE:
            raise MusicCuratorError("curator context is stale")
        if context.suppression_reason:
            return CuratorResult(
                status="suppressed", context=context, intent=None, suggestions=(),
                note=context.suppression_reason,
            )

        fallback_reason: Optional[str] = None
        try:
            intent = await self._intent_provider.generate(context)
        except MusicCuratorUnavailable as exc:
            logger.info("Music curator intent provider unavailable; using verified deterministic pool: %s", exc)
            intent = MusicIntent.fallback()
            fallback_reason = str(exc)

        taste_snapshot: Optional[MusicTasteSnapshot] = None
        if self._taste_provider is not None:
            try:
                taste_snapshot = await self._taste_provider.snapshot()
            except Exception:
                logger.exception("Music curator taste snapshot unavailable; continuing without it")

        candidates = await self._catalog.search(intent, limit=max(12, limit * 3))
        verified = [
            candidate for candidate in candidates
            if candidate.verified and candidate.title.strip() and candidate.uri.strip()
        ]
        if fallback_reason:
            verified = self._fallback_candidates(context, verified)
        suggestions = self._rank(context, intent, verified, taste_snapshot)[: max(1, limit)]
        if suggestions:
            status = "fallback" if fallback_reason else "shadow_ready"
        else:
            status = "no_verified_candidates"
        return CuratorResult(
            status=status,
            context=context,
            intent=intent,
            suggestions=tuple(suggestions),
            note=fallback_reason,
        )

    @staticmethod
    def _fallback_candidates(
        context: MusicCuratorContext,
        candidates: list[VerifiedMusicCandidate],
    ) -> list[VerifiedMusicCandidate]:
        allowed: set[str] = set()
        mapped = context.facts.get("mapped_playlists")
        if mapped and isinstance(mapped.value, list):
            for item in mapped.value:
                if isinstance(item, dict) and item.get("title"):
                    allowed.add(str(item["title"]).casefold())
        fallback = context.facts.get("deterministic_fallback_titles")
        if fallback and isinstance(fallback.value, list):
            allowed.update(str(title).casefold() for title in fallback.value if title)
        if not allowed:
            return []
        return [candidate for candidate in candidates if candidate.title.casefold() in allowed]

    def _rank(
        self,
        context: MusicCuratorContext,
        intent: MusicIntent,
        candidates: list[VerifiedMusicCandidate],
        taste_snapshot: Optional[MusicTasteSnapshot] = None,
    ) -> list[CuratorSuggestion]:
        mapped_titles: set[str] = set()
        mapped = context.facts.get("mapped_playlists")
        if mapped and isinstance(mapped.value, list):
            mapped_titles = {
                str(item.get("title")).casefold()
                for item in mapped.value if isinstance(item, dict) and item.get("title")
            }
        fallback_titles: set[str] = set()
        fallback = context.facts.get("deterministic_fallback_titles")
        if fallback and isinstance(fallback.value, list):
            fallback_titles = {str(title).casefold() for title in fallback.value if title}
        bandit_means = {} if taste_snapshot is not None else self._bandit_means(context.mode)

        ranked: list[CuratorSuggestion] = []
        for candidate in candidates:
            catalog_score = float(candidate.metadata.get("catalog_match_score") or 0.0)
            title_key = candidate.title.casefold()
            familiar = title_key in mapped_titles
            deterministic_fallback = title_key in fallback_titles
            score = 0.55 * catalog_score
            score += (0.25 * intent.familiarity) if familiar else (0.20 * intent.novelty)
            if deterministic_fallback:
                score += 0.35
            bandit_mean = bandit_means.get(candidate.title.casefold())
            if bandit_mean is not None:
                score += 0.25 * bandit_mean

            taste_match = (
                taste_snapshot.classify_candidate(candidate, mode=context.mode)
                if taste_snapshot is not None else None
            )
            if taste_match is not None:
                if taste_match.classification == "proven":
                    score += 0.18
                elif taste_match.classification == "familiar":
                    score += 0.08 * intent.familiarity
                elif taste_match.classification == "exploratory":
                    score += 0.08 * intent.novelty
                elif taste_match.classification == "rejected":
                    score -= 0.35
                score += 0.12 * taste_match.preference
            score = max(0.0, min(1.0, score))

            reasons = ["provider-verified queueable favorite"]
            matched = candidate.metadata.get("matched_concepts") or []
            if matched:
                reasons.append("matched intent: " + ", ".join(matched[:4]))
            if familiar:
                reasons.append("already mapped for this context")
            if deterministic_fallback:
                reasons.append("current deterministic fallback")
            if bandit_mean is not None:
                reasons.append(f"bandit mean {bandit_mean:.2f}")
            if taste_match is not None:
                reasons.append(
                    f"taste {taste_match.classification} ({taste_match.preference:+.2f})"
                )
                if taste_match.artist_depth:
                    reasons.append(f"artist depth {taste_match.artist_depth}")
            ranked.append(CuratorSuggestion(
                candidate=candidate,
                score=score,
                reason="; ".join(reasons),
                bandit_mean=bandit_mean,
                taste_classification=(
                    taste_match.classification if taste_match is not None else None
                ),
                taste_preference=(
                    taste_match.preference if taste_match is not None else None
                ),
                artist_depth=taste_match.artist_depth if taste_match is not None else 0,
            ))
        ranked.sort(key=lambda item: (-item.score, item.candidate.title.casefold()))
        return ranked

    def _bandit_means(self, mode: str) -> dict[str, float]:
        bandit = self._bandit
        if bandit is None:
            return {}
        try:
            buckets = bandit.get_status().get("top_arms", {}).get(mode, {})
        except Exception:
            return {}
        means: dict[str, float] = {}
        if not isinstance(buckets, dict):
            return means
        for entries in buckets.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("title"):
                    continue
                try:
                    mean = float(entry.get("mean"))
                except (TypeError, ValueError):
                    continue
                key = str(entry["title"]).casefold()
                means[key] = max(means.get(key, 0.0), max(0.0, min(1.0, mean)))
        return means
