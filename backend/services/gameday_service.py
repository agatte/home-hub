"""
Game Day service — owns ESPN polling + Colts game state + automation hooks.

Polls ESPN's public site.api endpoint (no auth, no key) for the Colts'
schedule and live play-by-play. Auto-flips automation mode to `gameday`
30 min before kickoff and auto-clears 30 min after the final whistle
(unless the user manually overrode mid-game). Fires registered callbacks
on each new scoring play and on game state transitions; Slice B's
CelebrationOrchestrator subscribes here when it lands.

Spec: docs/GAMEDAY_SPEC.md §3.2, §4.1.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

import httpx

logger = logging.getLogger("home_hub.gameday")

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
SCHEDULE_URL = f"{ESPN_BASE}/teams/11/schedule"
SUMMARY_URL = f"{ESPN_BASE}/summary"
SCOREBOARD_URL = f"{ESPN_BASE}/scoreboard"

COLTS_TEAM_ID = "11"

SCHEDULE_CACHE_TTL = 900       # 15 min — spec §4.1 polling cadence
POLL_INTERVAL_LIVE = 10        # 10s during in-progress
POLL_INTERVAL_IDLE = 60        # 60s during pregame/final/no-game
PRE_KICKOFF_FLIP_MINUTES = 30
PRE_GAME_AMBIENT_FLIP_MINUTES = 60  # T-60 silent visual build (GAMEDAY_SPEC §10.1)
POST_GAME_CLEAR_MINUTES = 30

GAMEDAY_AUTO_SOURCE = "gameday:auto"
PREGAMEDAY_AUTO_SOURCE = "gameday:auto:pregame"

# WPA momentum lane (Plan §Phase 2): threshold for surfacing a non-scoring
# "big play" as a momentum PlayEvent. Matches `celebration_volume_policy._WPA_BIG`
# so the system is internally consistent: a play that triggers a momentum
# celebration is the same magnitude as a play that bumps celebration TTS
# volume by +10. Env-overridable for post-real-game tuning.
MOMENTUM_WPA_THRESHOLD = float(os.getenv("MOMENTUM_WPA_THRESHOLD", "0.15"))

HTTP_TIMEOUT = 10.0
HTTP_HEADERS = {"User-Agent": "HomeHub/1.0 (anthonygatte@gmail.com)"}

# ESPN's status names for `header.competitions[0].status.type.name`.
STATUS_SCHEDULED = "STATUS_SCHEDULED"
STATUS_IN_PROGRESS = "STATUS_IN_PROGRESS"
STATUS_FINAL = "STATUS_FINAL"

# Map ESPN status → our status string in GameDayState.
_STATUS_MAP = {
    STATUS_SCHEDULED: "pregame",
    STATUS_IN_PROGRESS: "in-progress",
    STATUS_FINAL: "final",
}

# Play text regexes. ESPN serves two formats depending on which array we're
# walking:
#   • `scoringPlays[]` (canonical) uses full names:
#       "Daniel Jones 1 Yd Rush (Spencer Shrader Kick)"
#       "Michael Pittman Jr. 27 Yd pass from Daniel Jones (Spencer Shrader Kick)"
#       "Spencer Shrader 24 Yd Field Goal"
#   • `drives.previous[].plays[]` uses initials:
#       "D.Jones left end for 20 yards, TOUCHDOWN."
#       "S.Shrader 24 yard field goal is GOOD, ..."
# We try canonical patterns first, then fall back to abbreviated. Verified
# against tests/fixtures/espn_colts_2025_summary.json (spec §7).
_TD_PASS_RE = re.compile(r"^(.+?)\s+\d+\s+Yd\s+pass\s+from\s+", re.IGNORECASE)
_TD_RUSH_RE = re.compile(r"^(.+?)\s+\d+\s+Yd\s+(?:Rush|Run)\b", re.IGNORECASE)
_TD_ABBREV_RE = re.compile(r"^([A-Z]\.[A-Za-z'\-]+)")
_FG_FULL_RE = re.compile(r"^(.+?)\s+(\d+)\s+Yd\s+Field\s+Goal", re.IGNORECASE)
_FG_ABBREV_RE = re.compile(
    r"^([A-Z]\.[A-Za-z'\-]+)\s+(\d+)\s+yard field goal", re.IGNORECASE
)


PlayType = Literal[
    "touchdown",
    "field_goal",
    "kickoff",
    # Slice C+ score-type coverage (2026-05-15): rare-but-real scoring events
    # that the original 4-event slice elided. Each maps to its own
    # CelebrationSequence in celebration_orchestrator.SEQUENCES.
    "safety",
    "extra_point_good",
    "two_point_conv",
    "defensive_td",  # Covers pick-six and fumble-return TD (turnover-going-for-points).
    # WPA momentum lane — emitted for non-scoring plays with |WPA| >= 0.15.
    "momentum",
    "other",
]


@dataclass
class PlayEvent:
    """A single scoring play (or kickoff) emitted to subscribers.

    ``wpa`` is the Colts-perspective Win Probability Added for this
    play, sampled from ESPN's ``summary.winprobability`` array. Present
    for scoring plays once ESPN's WP model has caught up (typically
    within 30-60s of the play); ``None`` when the WP model hasn't yet
    indexed this play OR for synthetic test events. Sign convention:
    positive = Colts WP went up (good for Colts), negative = down.
    Used by celebration_volume_policy to scale TTS volume by the size
    of the swing.
    """
    timestamp: datetime
    play_type: PlayType
    description: str
    player: Optional[str]
    kicker: Optional[str]
    yards: Optional[int]
    scoring_team: Optional[Literal["colts", "opp"]]
    wpa: Optional[float] = None


@dataclass
class GameDayState:
    """Snapshot of current Colts game state. Returned by current_state() and
    broadcast as `gameday_state` on each poll cycle."""
    status: Literal["pregame", "in-progress", "final", "no-game"]
    opponent: Optional[str]
    kickoff_utc: Optional[datetime]
    score_colts: int
    score_opp: int
    quarter: int
    clock: str
    possession: Optional[Literal["colts", "opp"]]
    last_play: Optional[PlayEvent]


@dataclass
class GameDayStateTransition:
    """Status transition event (e.g. pregame → in-progress)."""
    from_status: str
    to_status: str
    timestamp: datetime


PlayCallback = Callable[[PlayEvent], Awaitable[None]]
TransitionCallback = Callable[[GameDayStateTransition], Awaitable[None]]


class GameDayService:
    """Owns ESPN polling and Colts game state. Other modules subscribe via
    register_on_play_event / register_on_state_transition; they do NOT poll
    ESPN themselves.
    """

    def __init__(self, automation_engine: Any, ws_manager: Any) -> None:
        self._automation = automation_engine
        self._ws_manager = ws_manager

        self._connected = False
        self._closed = False

        # Schedule cache — list of normalized game dicts.
        self._schedule_cache: list[dict[str, Any]] = []
        self._schedule_cache_time: float = 0.0

        # Current game tracking.
        self._current_state: Optional[GameDayState] = None
        self._known_play_ids: set[str] = set()
        self._post_game_clear_task: Optional[asyncio.Task] = None

        # Subscribers.
        self._play_callbacks: list[PlayCallback] = []
        self._transition_callbacks: list[TransitionCallback] = []

        # Synthetic time injection for tests (GAMEDAY_SPEC §10.6). When set,
        # _now_utc() returns this instead of the real wall clock — lets tests
        # exercise the T-60 → T-30 → T+30 lifecycle without sleeping or
        # waiting for a real kickoff window. Always None in production.
        self._now_override: Optional[datetime] = None

    def _now_utc(self) -> datetime:
        """Real wall clock, or the test override when set."""
        return self._now_override or datetime.now(timezone.utc)

    # ------------------------------------------------------------------ Lifecycle

    @property
    def connected(self) -> bool:
        """True after the first successful schedule fetch."""
        return self._connected

    async def connect(self) -> None:
        """Warm the schedule cache. Tolerates failure — service still starts
        and the polling loop will retry on its own cadence."""
        try:
            await self._refresh_schedule()
            self._connected = True
            logger.info(
                "GameDayService connected — %d games cached",
                len(self._schedule_cache),
            )
        except Exception as exc:
            logger.warning("GameDayService initial schedule fetch failed: %s", exc)
            # Mark connected anyway so the rest of the app boots; the poll
            # loop will keep retrying. Match weather_service's resilience.
            self._connected = True

    async def close(self) -> None:
        """Cancel any pending tasks. Called from main.py shutdown."""
        self._closed = True
        if self._post_game_clear_task and not self._post_game_clear_task.done():
            self._post_game_clear_task.cancel()

    # ------------------------------------------------------------------ Public API

    def current_state(self) -> Optional[GameDayState]:
        """Synchronous snapshot — returns None if no game scheduled today."""
        return self._current_state

    def register_on_play_event(self, cb: PlayCallback) -> None:
        """Subscribe to scoring plays. Slice B's CelebrationOrchestrator
        attaches here."""
        self._play_callbacks.append(cb)

    def register_on_state_transition(self, cb: TransitionCallback) -> None:
        """Subscribe to status transitions (pregame→in-progress→final)."""
        self._transition_callbacks.append(cb)

    async def get_upcoming_schedule(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return the next `limit` scheduled / in-progress games. Refreshes
        cache if stale."""
        await self._refresh_schedule_if_stale()
        upcoming = [
            g for g in self._schedule_cache
            if g["status"] in (STATUS_SCHEDULED, STATUS_IN_PROGRESS)
        ]
        upcoming.sort(key=lambda g: g["kickoff_utc"])
        return upcoming[:limit]

    async def trigger_synthetic_pregame(
        self,
        opponent: str,
        stakes_tier: str,
        hold_seconds: int = 30,
    ) -> dict[str, Any]:
        """Synthetic T-60 pregameday fire for `POST /api/gameday/test/pregame`.

        Flips automation to pregameday, holds for `hold_seconds`, then clears.
        Phase 3 will extend this to also dispatch the audio policy with the
        supplied stakes_tier — for Phase 1 the tier is logged + returned but
        the audio path is not yet reachable.

        GAMEDAY_SPEC §10.6 specifies the live-synthetic-fire pattern.
        """
        logger.info(
            "synthetic pregameday fire: opponent=%s stakes_tier=%s hold=%ds",
            opponent, stakes_tier, hold_seconds,
        )
        await self._automation.set_manual_override(
            "pregameday", source=PREGAMEDAY_AUTO_SOURCE
        )

        async def _delayed_clear() -> None:
            try:
                await asyncio.sleep(hold_seconds)
                # Only clear if our synthetic-fire override is still the
                # active one (user may have manually changed mode mid-test).
                override_source = getattr(self._automation, "override_source", None)
                if override_source == PREGAMEDAY_AUTO_SOURCE:
                    await self._automation.clear_override(
                        source=PREGAMEDAY_AUTO_SOURCE
                    )
                    logger.info("synthetic pregameday cleared after %ds", hold_seconds)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("synthetic pregameday clear failed")

        asyncio.create_task(_delayed_clear())
        return {
            "status": "ok",
            "mode": "pregameday",
            "opponent": opponent,
            "stakes_tier": stakes_tier,
            "hold_seconds": hold_seconds,
        }

    async def trigger_synthetic_play(self, play_type: PlayType) -> PlayEvent:
        """Fire a synthetic PlayEvent through subscribers. Used by the test
        endpoint at POST /api/gameday/test/{event}. Until Slice B subscribes,
        no listeners — just logs and returns."""
        synthetic = PlayEvent(
            timestamp=datetime.now(timezone.utc),
            play_type=play_type,
            description=f"[TEST] Synthetic {play_type}",
            player="Test Player" if play_type == "touchdown" else None,
            kicker="Test Kicker" if play_type == "field_goal" else None,
            yards=42 if play_type == "field_goal" else None,
            scoring_team="colts",
        )
        await self._fire_play_event(synthetic)
        return synthetic

    # ------------------------------------------------------------------ Polling

    async def poll_state_loop(self) -> None:
        """Main polling loop. Variable cadence: 10s while a game is in
        progress, 60s otherwise. Run from main.py's lifespan task list."""
        while not self._closed:
            try:
                await self._tick()
            except Exception:
                logger.exception("GameDayService tick failed")

            interval = (
                POLL_INTERVAL_LIVE
                if (
                    self._current_state is not None
                    and self._current_state.status == "in-progress"
                )
                else POLL_INTERVAL_IDLE
            )
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        await self._refresh_schedule_if_stale()

        active = self._find_active_game()
        if active is None:
            await self._update_state(None)
            return

        now_utc = self._now_utc()

        # Pre-kickoff flips — only if game is still scheduled. Two windows:
        #   • T-60 → T-30 : pregameday (silent visual build, GAMEDAY_SPEC §10.1)
        #   • T-30 → T+0  : gameday (in-game baseline + audio policy at the flip)
        # _maybe_flip_gameday() takes priority — checked second so its
        # set_manual_override displaces the pregameday override within the
        # narrower window. Both are idempotent.
        if active["status"] == STATUS_SCHEDULED:
            minutes_to_kickoff = (
                active["kickoff_utc"] - now_utc
            ).total_seconds() / 60.0
            if 0 < minutes_to_kickoff <= PRE_GAME_AMBIENT_FLIP_MINUTES:
                if minutes_to_kickoff <= PRE_KICKOFF_FLIP_MINUTES:
                    await self._maybe_flip_gameday()
                else:
                    await self._maybe_flip_pregame_ambient()

            # Pregame state — no live data yet, just emit a snapshot.
            await self._update_state(self._pregame_state(active))
            return

        # In-progress or final — fetch live data.
        summary = await self._fetch_summary(active["id"])
        if summary is None:
            return

        new_state = self._build_state(summary, active)
        # IMPORTANT: scoring plays first — they call `self._known_play_ids.add(play_id)`
        # which makes the momentum walk below skip the same play_id (a TD with WPA=0.30
        # is already firing its full TD sequence; no generic momentum celebration on top).
        new_plays = self._extract_new_plays(summary)
        new_momentum_plays = self._extract_new_momentum_plays(summary)

        # Status transitions.
        old_status = (
            self._current_state.status if self._current_state else "no-game"
        )
        if new_state.status != old_status and old_status != "no-game":
            transition = GameDayStateTransition(
                from_status=old_status,
                to_status=new_state.status,
                timestamp=now_utc,
            )
            await self._fire_state_transition(transition)

        # Post-game auto-clear scheduling on final transition.
        if new_state.status == "final" and old_status != "final":
            self._schedule_post_game_clear()

        # Emit play events (oldest first). Scoring plays fire first so
        # their celebrations are not gated behind any momentum 8s cooldown.
        for play in new_plays:
            await self._fire_play_event(play)
            try:
                await self._ws_manager.broadcast("gameday_play", asdict(play))
            except Exception:
                logger.exception("ws broadcast gameday_play failed")

        # Momentum plays second. The orchestrator's 8s cooldown coalesces
        # bursts (consecutive big plays on a single drive) into one fire.
        for play in new_momentum_plays:
            await self._fire_play_event(play)
            try:
                await self._ws_manager.broadcast("gameday_play", asdict(play))
            except Exception:
                logger.exception("ws broadcast gameday_play failed")

        await self._update_state(new_state)

    async def _update_state(self, new_state: Optional[GameDayState]) -> None:
        self._current_state = new_state
        if new_state is None:
            return
        try:
            await self._ws_manager.broadcast("gameday_state", asdict(new_state))
        except Exception:
            logger.exception("ws broadcast gameday_state failed")

    # ------------------------------------------------------------------ Schedule

    async def _refresh_schedule_if_stale(self) -> None:
        if (time.time() - self._schedule_cache_time) >= SCHEDULE_CACHE_TTL:
            try:
                await self._refresh_schedule()
            except Exception as exc:
                logger.warning("schedule refresh failed: %s", exc)

    async def _refresh_schedule(self) -> None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS) as client:
            resp = await client.get(SCHEDULE_URL)
            resp.raise_for_status()
            data = resp.json()

        events = data.get("events", []) or []
        normalized: list[dict[str, Any]] = []
        for evt in events:
            game = self._normalize_schedule_event(evt)
            if game is not None:
                normalized.append(game)

        self._schedule_cache = normalized
        self._schedule_cache_time = time.time()
        logger.debug("schedule cache refreshed: %d games", len(normalized))

    @staticmethod
    def _normalize_schedule_event(evt: dict) -> Optional[dict[str, Any]]:
        """Flatten an ESPN schedule event into the fields we need."""
        try:
            game_id = str(evt.get("id"))
            date_str = evt.get("date")
            if not game_id or not date_str:
                return None

            kickoff_utc = _parse_espn_datetime(date_str)
            comps = evt.get("competitions") or []
            comp = comps[0] if comps else {}
            status = (
                comp.get("status", {}).get("type", {}).get("name")
                or evt.get("status", {}).get("type", {}).get("name")
                or STATUS_SCHEDULED
            )

            opponent = None
            colts_are_home = False
            for competitor in comp.get("competitors", []) or []:
                team = competitor.get("team") or {}
                team_id = str(team.get("id"))
                home_away = str(competitor.get("homeAway") or "").lower()
                if team_id == COLTS_TEAM_ID:
                    colts_are_home = (home_away == "home")
                else:
                    opponent = team.get("displayName") or team.get("name")

            return {
                "id": game_id,
                "kickoff_utc": kickoff_utc,
                "opponent": opponent,
                "colts_are_home": colts_are_home,
                "status": status,
                "name": evt.get("name"),
                "short_name": evt.get("shortName"),
            }
        except Exception:
            logger.exception("failed to normalize schedule event")
            return None

    def _find_active_game(self) -> Optional[dict[str, Any]]:
        """Return the most relevant Colts game right now: a live game if one
        exists, else the next scheduled game within 24h, else None."""
        now_utc = datetime.now(timezone.utc)

        # In-progress wins.
        for game in self._schedule_cache:
            if game["status"] == STATUS_IN_PROGRESS:
                return game

        # Next scheduled within 24h.
        upcoming = [
            g for g in self._schedule_cache
            if g["status"] == STATUS_SCHEDULED
            and 0 <= (g["kickoff_utc"] - now_utc).total_seconds() <= 86400
        ]
        if upcoming:
            upcoming.sort(key=lambda g: g["kickoff_utc"])
            return upcoming[0]

        # Recent final (within last 30 min) — still relevant for the post-game
        # clear scheduler to pick up.
        for game in self._schedule_cache:
            if game["status"] == STATUS_FINAL:
                age = (now_utc - game["kickoff_utc"]).total_seconds()
                if 0 <= age <= 4 * 3600:  # heuristic: games last <4h
                    return game

        return None

    # ------------------------------------------------------------------ Summary

    async def _fetch_summary(self, game_id: str) -> Optional[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS) as client:
                resp = await client.get(SUMMARY_URL, params={"event": game_id})
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("summary fetch %s failed: %s", game_id, exc)
            return None

    def _build_state(
        self, summary: dict, schedule_meta: dict
    ) -> GameDayState:
        """Assemble a GameDayState from a fresh summary response."""
        header = summary.get("header") or {}
        comps = header.get("competitions") or []
        comp = comps[0] if comps else {}
        status_type = (comp.get("status") or {}).get("type") or {}
        espn_status = status_type.get("name") or STATUS_IN_PROGRESS

        score_colts, score_opp = 0, 0
        possession: Optional[Literal["colts", "opp"]] = None
        for competitor in comp.get("competitors", []) or []:
            team = competitor.get("team") or {}
            try:
                points = int(competitor.get("score") or 0)
            except (TypeError, ValueError):
                points = 0
            if str(team.get("id")) == COLTS_TEAM_ID:
                score_colts = points
            else:
                score_opp = points

        # Possession at the competition level (live games only).
        sit = comp.get("situation") or {}
        poss_team = (sit.get("possession") or {})
        if isinstance(poss_team, dict):
            poss_team_id = str(poss_team.get("id") or "")
        else:
            poss_team_id = str(poss_team)
        if poss_team_id == COLTS_TEAM_ID:
            possession = "colts"
        elif poss_team_id:
            possession = "opp"

        # Quarter + clock from status (live games), fall back to 0/"" if final.
        status_obj = comp.get("status") or {}
        quarter = int(status_obj.get("period") or 0)
        clock_obj = status_obj.get("clock")
        if isinstance(clock_obj, dict):
            clock = str(clock_obj.get("displayValue") or "")
        elif isinstance(clock_obj, (int, float)):
            mins, secs = divmod(int(clock_obj), 60)
            clock = f"{mins}:{secs:02d}"
        else:
            clock = str(clock_obj or "")

        # Last play — pluck from drives (most recent first).
        last_play = self._extract_last_play(summary)

        return GameDayState(
            status=_STATUS_MAP.get(espn_status, "no-game"),
            opponent=schedule_meta.get("opponent"),
            kickoff_utc=schedule_meta.get("kickoff_utc"),
            score_colts=score_colts,
            score_opp=score_opp,
            quarter=quarter,
            clock=clock,
            possession=possession,
            last_play=last_play,
        )

    def _extract_last_play(self, summary: dict) -> Optional[PlayEvent]:
        drives = summary.get("drives") or {}
        # Try drives.current first (live), then last of drives.previous.
        current = drives.get("current") or {}
        plays = current.get("plays") or []
        if not plays:
            previous = drives.get("previous") or []
            if previous:
                plays = previous[-1].get("plays") or []
        if not plays:
            return None
        return self._parse_play(plays[-1])

    def _extract_new_plays(self, summary: dict) -> list[PlayEvent]:
        """Walk scoringPlays + drives, return only plays we haven't seen.

        Annotates each emitted play with ``wpa`` (Colts-perspective Win
        Probability Added) sampled from ``summary.winprobability``. WPA
        may be None when ESPN's WP model hasn't yet indexed the play
        (typical lag is 30-60s); the celebration volume policy degrades
        gracefully via the margin+clock fallback.
        """
        out: list[PlayEvent] = []
        active = self._find_active_game() or {}
        colts_are_home = bool(active.get("colts_are_home", False))

        # The top-level scoringPlays array is the canonical source of truth
        # for TDs/FGs. Walk in order; dedup against known ids.
        scoring_plays = summary.get("scoringPlays") or []
        for raw in scoring_plays:
            play_id = str(raw.get("id") or "")
            if not play_id or play_id in self._known_play_ids:
                continue
            play = self._parse_play(raw)
            # Slice C+: emit every recognized score subtype. Defensive_td
            # passes through even when scoring_team=="colts" (the Colts'
            # defense scored, which IS a Colts score). Opponent scores
            # land here too but are filtered downstream by the
            # CelebrationOrchestrator's on_play_event Colts-only gate.
            if play.play_type in (
                "touchdown", "field_goal", "safety",
                "extra_point_good", "two_point_conv", "defensive_td",
            ):
                play.wpa = self._compute_wpa(play_id, summary, colts_are_home)
                out.append(play)
                self._known_play_ids.add(play_id)

        return out

    def _extract_new_momentum_plays(self, summary: dict) -> list[PlayEvent]:
        """Phase 2 — surface non-scoring plays with |WPA| >= threshold.

        Walks ``drives.previous[].plays[]`` (and ``drives.current.plays[]``
        when present — in-progress drive's plays land there before the
        drive ends). For each play not already in ``_known_play_ids``:
          • Compute WPA via the shared ``_compute_wpa`` (reads from the
            same ``summary.winprobability`` array as scoring plays).
          • If a scoring play with the same id already passed through
            ``_extract_new_plays`` it was added to ``_known_play_ids``,
            so we skip it here — no double-emission.
          • If ``|wpa| >= MOMENTUM_WPA_THRESHOLD``, emit a momentum
            PlayEvent (``play_type="momentum"``, lights-only celebration).

        Latency caveat: ESPN's winprobability array lags 30-60s behind
        real time, same as scoring plays. Momentum celebrations will
        therefore fire ~1 minute after the actual play. Tolerable for
        v1; documented in the Plan as out-of-scope to fix.
        """
        out: list[PlayEvent] = []
        active = self._find_active_game() or {}
        colts_are_home = bool(active.get("colts_are_home", False))

        drives = summary.get("drives") or {}
        all_drives: list[dict] = []
        previous = drives.get("previous") or []
        all_drives.extend(previous)
        # `current` is the in-progress drive — its plays land in WP too.
        current = drives.get("current")
        if isinstance(current, dict):
            all_drives.append(current)

        for drive in all_drives:
            for raw in (drive.get("plays") or []):
                play_id = str(raw.get("id") or "")
                if not play_id or play_id in self._known_play_ids:
                    continue
                wpa = self._compute_wpa(play_id, summary, colts_are_home)
                if wpa is None or abs(wpa) < MOMENTUM_WPA_THRESHOLD:
                    continue
                # Build a minimal PlayEvent. We don't parse player/yards
                # for momentum — the sequence is lights-only, the TV is
                # carrying the play text. Description preserves the raw
                # ESPN text for postmortem digest readability.
                text = str(raw.get("text") or "")
                wallclock_str = raw.get("wallclock")
                if wallclock_str:
                    timestamp = (
                        _parse_espn_datetime(wallclock_str)
                        or datetime.now(timezone.utc)
                    )
                else:
                    timestamp = datetime.now(timezone.utc)
                out.append(PlayEvent(
                    timestamp=timestamp,
                    play_type="momentum",
                    description=text,
                    player=None,
                    kicker=None,
                    yards=None,
                    scoring_team=None,
                    wpa=wpa,
                ))
                self._known_play_ids.add(play_id)

        return out

    @staticmethod
    def _compute_wpa(
        scoring_play_id: str,
        summary: dict,
        colts_are_home: bool,
    ) -> Optional[float]:
        """Compute Colts-perspective WPA for a scoring play.

        ESPN's ``summary.winprobability`` is an ordered list of
        ``{playId, homeWinPercentage, tiePercentage}`` entries. WPA is
        the delta between this play's home WP and the prior play's home
        WP, then sign-flipped if Colts are away.

        Returns None when:
            • Play not yet in the WP array (ESPN's WP model lags
              30-60s — we cannot block the celebration on it).
            • WP array is empty/missing (e.g. final-only summary).
        """
        wp = summary.get("winprobability") or []
        if not wp:
            return None

        for idx, entry in enumerate(wp):
            if str(entry.get("playId") or "") == scoring_play_id:
                wp_after = entry.get("homeWinPercentage")
                if wp_after is None:
                    return None
                if idx == 0:
                    wp_before = 0.5  # season prior; rare — only true coin-flip openers
                else:
                    wp_before = wp[idx - 1].get("homeWinPercentage", 0.5)
                try:
                    wpa_home = float(wp_after) - float(wp_before)
                except (TypeError, ValueError):
                    return None
                return wpa_home if colts_are_home else -wpa_home

        # Play not (yet) in the WP array.
        return None

    def _parse_play(self, raw: dict) -> PlayEvent:
        """Convert an ESPN play dict to a PlayEvent. Best-effort regex
        extraction of player / kicker / yards from the abbreviated
        `text` field. Failure → None on those fields."""
        text = str(raw.get("text") or "")
        scoring_type = (raw.get("scoringType") or {}).get("abbreviation") or ""
        play_type_text = (raw.get("type") or {}).get("text") or ""

        # Determine play_type. Order matters — check more-specific subtypes
        # (defensive TD, safety, extra-point, 2pt-conv) BEFORE the broad
        # touchdown match, otherwise a pick-six lands as a plain "touchdown".
        text_upper = text.upper()
        scoring_upper = scoring_type.upper()
        play_type_upper = play_type_text.upper()
        is_td = "TD" in scoring_upper or "TOUCHDOWN" in play_type_upper

        if scoring_upper in ("SF", "SAFETY") or "SAFETY" in play_type_upper:
            play_type: PlayType = "safety"
        elif is_td and (
            "INTERCEPT" in text_upper
            or "FUMBLE" in text_upper
            or "DEFENSIVE TOUCHDOWN" in play_type_upper
        ):
            # Pick-six and fumble-return TD. ESPN keeps scoringType="TD" for
            # these, so the differentiator is the play text. If the offense
            # was the Colts (we recovered our own fumble into the EZ — vanishingly
            # rare on offense) the scoring_team logic below still resolves
            # correctly; the celebration sequence is about emotional category.
            play_type = "defensive_td"
        elif is_td:
            play_type = "touchdown"
        elif scoring_upper in ("PAT", "XP") or (
            "EXTRA POINT" in play_type_upper and ("GOOD" in text_upper or "MADE" in text_upper)
        ):
            play_type = "extra_point_good"
        elif scoring_upper in ("2PT", "2-PT") or (
            "TWO-POINT" in text_upper or "TWO POINT" in text_upper
        ) and ("GOOD" in text_upper or "SUCCESSFUL" in text_upper or "CONVERTED" in text_upper):
            play_type = "two_point_conv"
        elif scoring_upper == "FG" or "FIELD GOAL" in play_type_upper:
            play_type = "field_goal"
        elif "KICKOFF" in play_type_upper:
            play_type = "kickoff"
        else:
            play_type = "other"

        # Scoring team — Colts = team_id "11".
        team_id = str((raw.get("team") or {}).get("id") or "")
        scoring_team: Optional[Literal["colts", "opp"]]
        if team_id == COLTS_TEAM_ID:
            scoring_team = "colts"
        elif team_id:
            scoring_team = "opp"
        else:
            scoring_team = None

        # Player / kicker / yards extraction.
        player: Optional[str] = None
        kicker: Optional[str] = None
        yards: Optional[int] = None

        if play_type == "touchdown":
            # Try canonical "<Receiver> <yds> Yd pass from <Passer>"
            # then "<Runner> <yds> Yd Rush", finally abbreviated "<X.Lastname>".
            for rx in (_TD_PASS_RE, _TD_RUSH_RE, _TD_ABBREV_RE):
                m = rx.match(text)
                if m:
                    player = m.group(1).strip()
                    break
        elif play_type == "field_goal":
            for rx in (_FG_FULL_RE, _FG_ABBREV_RE):
                m = rx.match(text)
                if m:
                    kicker = m.group(1).strip()
                    try:
                        yards = int(m.group(2))
                    except ValueError:
                        yards = None
                    break

        # Wallclock if present, else now.
        wallclock_str = raw.get("wallclock")
        if wallclock_str:
            timestamp = _parse_espn_datetime(wallclock_str) or datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        return PlayEvent(
            timestamp=timestamp,
            play_type=play_type,
            description=text,
            player=player,
            kicker=kicker,
            yards=yards,
            scoring_team=scoring_team,
        )

    def _pregame_state(self, active: dict) -> GameDayState:
        return GameDayState(
            status="pregame",
            opponent=active.get("opponent"),
            kickoff_utc=active.get("kickoff_utc"),
            score_colts=0,
            score_opp=0,
            quarter=0,
            clock="",
            possession=None,
            last_play=None,
        )

    # ------------------------------------------------------------------ Mode flips

    async def _maybe_flip_pregame_ambient(self) -> None:
        """Set automation override to pregameday at T-60 (GAMEDAY_SPEC §10.1).
        Idempotent — re-flipping on every tick is harmless (set_manual_override
        no-ops if already set) but we gate on current mode to keep journalctl
        clean. Distinct override source so the post-game clear logic can tell
        a user-touched override apart from this and the T-30 flip."""
        try:
            current = self._automation.current_mode
        except Exception:
            current = None
        # If gameday is already up (e.g. user manually fired test/pregame
        # right at T-30) don't downgrade — gameday is the destination.
        if current in ("pregameday", "gameday"):
            return
        logger.info("T-60 reached — flipping automation to pregameday")
        await self._automation.set_manual_override(
            "pregameday", source=PREGAMEDAY_AUTO_SOURCE
        )

    async def _maybe_flip_gameday(self) -> None:
        """Set automation override to gameday at T-30. Idempotent — re-flipping
        on every tick is harmless (set_manual_override no-ops if already set)
        but we gate on current mode anyway to keep journalctl clean.

        Renamed from _maybe_flip_pregame on 2026-05-15 (pregameday added) —
        the old name implied 'flip at pregame', but the actual flip lands on
        gameday. _maybe_flip_pregame_ambient now owns the T-60 pre-game flip."""
        try:
            current = self._automation.current_mode
        except Exception:
            current = None
        if current == "gameday":
            return
        logger.info("T-30 reached — flipping automation to gameday")
        await self._automation.set_manual_override(
            "gameday", source=GAMEDAY_AUTO_SOURCE
        )

    def _schedule_post_game_clear(self) -> None:
        """Schedule a one-shot task that clears the override 30 min after
        the game went final. If the user manually overrode mid/post-game
        (override source != gameday:auto), the task no-ops — it doesn't
        clobber the user's intent."""
        if self._post_game_clear_task and not self._post_game_clear_task.done():
            return  # already scheduled

        async def _delayed_clear() -> None:
            try:
                await asyncio.sleep(POST_GAME_CLEAR_MINUTES * 60)
                await self._maybe_clear_postgame()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("post-game clear task failed")

        self._post_game_clear_task = asyncio.create_task(_delayed_clear())
        logger.info(
            "post-game auto-clear scheduled for T+%d min", POST_GAME_CLEAR_MINUTES
        )

    async def _maybe_clear_postgame(self) -> None:
        """Clear the override only if its source is still gameday:auto."""
        try:
            override_source = getattr(self._automation, "override_source", None)
        except Exception:
            override_source = None
        if override_source != GAMEDAY_AUTO_SOURCE:
            logger.info(
                "post-game clear skipped — override source=%s (user touched it)",
                override_source,
            )
            return
        logger.info("post-game clear firing — restoring auto mode")
        await self._automation.clear_override(source=GAMEDAY_AUTO_SOURCE)

    # ------------------------------------------------------------------ Subscribers

    async def _fire_play_event(self, play: PlayEvent) -> None:
        logger.info(
            "play_event: %s team=%s player=%s kicker=%s yards=%s",
            play.play_type, play.scoring_team, play.player, play.kicker, play.yards,
        )
        for cb in list(self._play_callbacks):
            try:
                await cb(play)
            except Exception:
                logger.exception("play callback failed")

    async def _fire_state_transition(self, transition: GameDayStateTransition) -> None:
        logger.info(
            "state_transition: %s → %s", transition.from_status, transition.to_status,
        )
        for cb in list(self._transition_callbacks):
            try:
                await cb(transition)
            except Exception:
                logger.exception("transition callback failed")


def _parse_espn_datetime(value: str) -> Optional[datetime]:
    """Parse ESPN's ISO-ish dates ('2025-09-07T17:00Z' or '...+00:00')."""
    if not value:
        return None
    try:
        # Z → +00:00 for fromisoformat.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
