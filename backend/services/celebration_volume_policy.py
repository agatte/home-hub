"""
Celebration TTS volume policy — pure function, no I/O.

Computes a target Sonos volume (or `None` to suppress audio) for a given
PlayEvent + GameDayState, factoring in the play's win-probability swing,
late-game margin/clock context, and apartment-level signals (sleeping
mode, DND, late-night hour, camera presence).

Lights always fire. This gates only the TTS — the user's redirect after
the d9c1fcd live test was "make volume read the room": loud for big
plays, quiet for blowouts, silent when losing badly or apartment is
asleep.

Pure module by design — easy to unit-test, no service dependencies. The
orchestrator imports `compute_celebration_volume`, gathers context from
its injected automation_engine + camera_service, and passes everything
in.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — defensive only
    ZoneInfo = None  # type: ignore[misc,assignment]

from backend.services.gameday_service import GameDayState, PlayEvent

logger = logging.getLogger("home_hub.celebration_volume")

# Indianapolis-local hour determines the late-night cap.
_INDY_TZ = ZoneInfo("America/Indiana/Indianapolis") if ZoneInfo else None

# Volume bounds (Sonos volume range 0-100, but we don't go above 50 even
# for the biggest plays — Era 100 at 50 is already loud from the couch
# per Anthony's post-d9c1fcd verification).
_VOL_MIN = 5
_VOL_MAX = 50

# WPA bands (absolute value of WPA_colts).
_WPA_HUGE = 0.25     # +15 — game-changing swing
_WPA_BIG = 0.15      # +10 — big swing
_WPA_STANDARD = 0.05  # 0 — standard scoring play
# below 0.05 → -10 (decided game / polite golf clap)

# Late-night cap (10pm-6am local). Any louder and the apartment wakes.
_LATE_NIGHT_CAP = 18
_LATE_NIGHT_HOURS = set(range(22, 24)) | set(range(0, 6))

# Losing-blowout suppression: Q3+ and down by 21+.
_BLOWOUT_DEFICIT = 21
_BLOWOUT_QUARTER = 3


def compute_celebration_volume(
    play: PlayEvent,
    game_state: Optional[GameDayState],
    *,
    base_volume: int = 30,
    sleeping_mode: bool = False,
    dnd_active: bool = False,
    camera_absent: bool = False,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Return target Sonos volume in [5, 50] or `None` to suppress TTS.

    Args:
        play: The PlayEvent that triggered the celebration. ``play.wpa``
            is consulted first; if absent, falls back to margin+clock
            heuristics from ``game_state``.
        game_state: Current GameDayState, or None for synthetic test
            paths (the ``/api/gameday/test/{event}`` route emits a
            PlayEvent with no live state behind it).
        base_volume: Per-event baseline (touchdown=30, FG=28, etc).
            CelebrationSequence.base_volume drives this.
        sleeping_mode: True when automation_engine.current_mode ==
            "sleeping". Hard-suppresses TTS.
        dnd_active: True when automation_engine.is_dnd_active(). Hard-
            suppresses TTS.
        camera_absent: True when camera_service reports no presence in
            the last ~5 minutes. -10 modifier (no one's here to hear).
        now: For testing — UTC datetime to evaluate "late night" against.
            Production passes ``datetime.now(timezone.utc)``; tests pass
            a frozen value.

    Returns:
        int in [5, 50] for the TTS volume, or None to skip TTS entirely.
    """
    # Hard suppressions — these all return None, lights still fire.
    if sleeping_mode:
        logger.debug("celebration volume: suppressed (sleeping mode)")
        return None
    if dnd_active:
        logger.debug("celebration volume: suppressed (DND active)")
        return None
    if _is_losing_blowout(game_state):
        logger.debug(
            "celebration volume: suppressed (losing blowout — Q%s, margin=%s)",
            game_state.quarter if game_state else "?",
            (game_state.score_colts - game_state.score_opp) if game_state else "?",
        )
        return None

    volume = base_volume

    # Primary signal: WPA. Ignored entirely when None — fallback below.
    if play.wpa is not None:
        volume += _wpa_modifier(play.wpa)
    else:
        # Fallback only meaningful with state.
        if game_state is not None:
            volume += _margin_clock_modifier(game_state)

    # Apartment-context modifiers always layer on (independent of game state).
    if _is_late_night(now):
        volume = min(volume, _LATE_NIGHT_CAP)

    if camera_absent:
        # No one at the desk or in bed reclined — we don't need couch
        # volume. Floor at 5 so we never drop to 0 (which could behave
        # weirdly on Sonos).
        volume = max(_VOL_MIN, volume - 10)

    # Final clamp.
    volume = max(_VOL_MIN, min(_VOL_MAX, volume))
    return volume


def _wpa_modifier(wpa_colts: float) -> int:
    """Map |WPA| to a volume bump. WPA_colts is signed (+ for Colts-favoring
    swing, - for Colts-hurting). Magnitude alone drives the bump — a +0.30
    Colts TD and a -0.30 Colts pick-six are both "big moments"; the lights
    already encode which side it favors via the sequence variant. (Future
    note: a pick-six against the Colts wouldn't fire any of our SEQUENCES
    today — only Colts scoring plays come through. So in practice the WPA
    sign here is almost always positive when this fires.)"""
    mag = abs(wpa_colts)
    if mag >= _WPA_HUGE:
        return 15
    if mag >= _WPA_BIG:
        return 10
    if mag >= _WPA_STANDARD:
        return 0
    return -10


def _margin_clock_modifier(state: GameDayState) -> int:
    """Fallback when WPA is missing. Uses score margin + quarter + clock.

    Heuristic ordering matters — we score the most specific case first
    (clutch 2-minute drill in a one-score game) and fall through to
    looser bands.
    """
    margin = state.score_colts - state.score_opp
    abs_margin = abs(margin)
    quarter = state.quarter
    q4_or_ot = quarter >= 4
    time_left = _parse_clock_seconds(state.clock)

    # Q4/OT, one-score game, under 2 minutes — peak clutch.
    if q4_or_ot and abs_margin <= 7 and time_left is not None and time_left < 120:
        return 15
    # Q4/OT, one-score game (any time left in the quarter).
    if q4_or_ot and abs_margin <= 7:
        return 10
    # Any quarter, three-point game — meaningful at every point in the game.
    if abs_margin <= 3:
        return 5
    # Q4/OT, winning by 21+ — celebrating the lead but no need to shout.
    if q4_or_ot and margin >= _BLOWOUT_DEFICIT:
        return -10
    return 0


def _is_losing_blowout(state: Optional[GameDayState]) -> bool:
    """Q3+ and Colts down by 21 or more → suppress TTS entirely. Lights
    still play to acknowledge the (rare) Colts FG, but we don't punctuate
    a 38-3 Q4 with audio celebration."""
    if state is None:
        return False
    if state.quarter < _BLOWOUT_QUARTER:
        return False
    deficit = state.score_opp - state.score_colts
    return deficit >= _BLOWOUT_DEFICIT


def _is_late_night(now: Optional[datetime]) -> bool:
    """True when local Indianapolis hour is in 22..05 (10pm-5:59am).

    `now` is UTC; we convert to America/Indiana/Indianapolis. If
    zoneinfo isn't available (Python <3.9 or missing tzdata), we
    conservatively return False — better to not cap than to cap at the
    wrong time.
    """
    if now is None or _INDY_TZ is None:
        return False
    try:
        local = now.astimezone(_INDY_TZ)
    except Exception:
        return False
    return local.hour in _LATE_NIGHT_HOURS


def _parse_clock_seconds(clock: str) -> Optional[int]:
    """Parse "MM:SS" (or "M:SS") → total seconds remaining in the
    quarter. Returns None on garbage so callers can skip the clock-aware
    branches and fall through to broader bands."""
    if not clock or ":" not in clock:
        return None
    try:
        mins_s, secs_s = clock.split(":", 1)
        mins = int(mins_s)
        secs = int(secs_s)
        return mins * 60 + secs
    except (ValueError, TypeError):
        return None
