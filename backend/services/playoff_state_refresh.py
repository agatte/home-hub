"""
Tuesday 06:00 ET refresh of the Colts' playoff-stakes state (GAMEDAY_SPEC §10.5).

Writes a structured dict to ``app_settings["gameday_playoff_state"]`` so the
pregameday→gameday audio policy (`pregame_audio_policy.compute_pregame_audio`)
has real stakes inputs to read at the T-30 flip.

Why this lives as a separate module + ScheduledTask:
  - The fetch is brittle (third-party HTML/JSON shapes change), so we isolate
    the parse logic for testability.
  - Once-a-week cadence keeps ESPN traffic low and matches the spec —
    playoff odds don't change mid-week meaningfully.
  - Pure parser is unit-tested against a fixture; the I/O wrapper handles
    HTTP + DB writes and is intentionally thin.

Phase 4 scope (this commit):
  - Pull team schedule from ESPN (the endpoint gameday_service already uses).
  - Derive record (wins/losses/ties from FINAL games), season_week, is_preseason.
  - Set playoff_probability=None + division_gap_games=None + is_eliminated=False
    until a robust source is wired (next iteration).
  - Write to app_settings; downstream policy gracefully falls back to "standard"
    tier when playoff_probability is None.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.playoff_state")

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
_SCHEDULE_URL = f"{_ESPN_BASE}/teams/11/schedule"  # COLTS = team id 11

_HTTP_TIMEOUT = 10.0

# Tuesday after NFL Monday Night Football final — playoff models recompute
# around this window. Spec §10.5.
REFRESH_HOUR_ET = 6
REFRESH_MINUTE_ET = 0
REFRESH_WEEKDAY = 1  # Tuesday (Mon=0..Sun=6)

# app_settings key written by this module — read by the pregameday audio
# dispatch handler in bootstrap.
PLAYOFF_STATE_KEY = "gameday_playoff_state"


def compute_playoff_state(
    schedule_events: list[dict[str, Any]],
    *,
    today: Optional[datetime] = None,
) -> dict[str, Any]:
    """Parse ESPN's team schedule payload into the playoff-state dict.

    Pure function — easy to unit-test with a fixture. The schedule payload
    is the ``events`` array from the ESPN team-schedule response (same
    shape gameday_service consumes).

    Args:
        schedule_events: List of ESPN event dicts with at minimum
            ``competitions[0].status.type.name`` ("STATUS_FINAL" /
            "STATUS_SCHEDULED" / "STATUS_IN_PROGRESS") and
            ``competitions[0].competitors`` with team scores.
        today: For testing — UTC datetime to evaluate the season-week
            against. Production passes ``datetime.now(timezone.utc)``.

    Returns:
        Dict with keys matching the spec §10.5 shape:
            playoff_probability, division_gap_games, is_eliminated,
            record (tuple of (w, l, t)), refreshed_at (iso8601),
            season_week, is_preseason.
    """
    today = today or datetime.now(timezone.utc)
    wins = losses = ties = 0
    games_played = 0

    for event in schedule_events:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        status_name = (
            comp.get("status", {}).get("type", {}).get("name", "")
        )
        if status_name != "STATUS_FINAL":
            continue

        season_type = (event.get("season") or {}).get("type")
        # ESPN season types: 1=preseason, 2=regular, 3=postseason.
        # Skip preseason for record (preseason wins/losses don't count).
        if season_type == 1:
            continue

        # Find the Colts among the competitors.
        competitors = comp.get("competitors") or []
        colts_score = opp_score = None
        for team in competitors:
            tid = (team.get("team") or {}).get("id")
            try:
                score = int(team.get("score") or 0)
            except (TypeError, ValueError):
                score = 0
            if tid == "11":
                colts_score = score
            else:
                opp_score = score
        if colts_score is None or opp_score is None:
            continue

        games_played += 1
        if colts_score > opp_score:
            wins += 1
        elif colts_score < opp_score:
            losses += 1
        else:
            ties += 1

    # Season week — NFL week 1 typically starts the first Thursday after
    # Labor Day. Approximation: any date in September-January counts as
    # regular season; August is preseason. Detailed week math could parse
    # ESPN's `week.number` from the schedule, but games_played + 1 is a
    # serviceable proxy when no ESPN week tag is available.
    is_preseason = _is_preseason(today)
    season_week = max(1, games_played + 1) if not is_preseason else 0

    return {
        "playoff_probability": None,  # backfill in next iteration
        "division_gap_games": None,
        "is_eliminated": False,
        "record": [wins, losses, ties],
        "refreshed_at": today.replace(microsecond=0).isoformat(),
        "season_week": season_week,
        "is_preseason": is_preseason,
    }


def _is_preseason(today: datetime) -> bool:
    """August or earlier in the calendar year → preseason.

    NFL preseason runs late July through early September; regular season
    starts the Thursday after Labor Day (early-mid September). A simpler
    month gate is plenty for v1.
    """
    return today.month in (7, 8)


async def refresh_playoff_state(save_setting_fn) -> dict[str, Any]:
    """Fetch ESPN, compute the state dict, persist to app_settings.

    Args:
        save_setting_fn: Async callable that takes (key, value_dict) and
            writes to app_settings. Injected so this module doesn't import
            the DB layer directly — keeps the parser testable.

    Returns:
        The computed state dict (also persisted).
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(_SCHEDULE_URL)
            resp.raise_for_status()
            payload = resp.json()
        events = payload.get("events") or []
    except Exception:
        logger.exception("playoff_state_refresh: ESPN fetch failed")
        return {}

    state = compute_playoff_state(events)
    try:
        await save_setting_fn(PLAYOFF_STATE_KEY, state)
        logger.info(
            "playoff_state_refresh: record=%s week=%s preseason=%s",
            state["record"], state["season_week"], state["is_preseason"],
        )
    except Exception:
        logger.exception("playoff_state_refresh: app_settings write failed")
    return state
