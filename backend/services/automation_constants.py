"""
Automation engine constants — mode priority, autonomous-source sets,
schedule dataclasses, and time-based fallback rules.

Step 1 of the automation_engine decomposition (GH#86): pure data, no
imports from any service module, so anything (routes, services, tests)
can import from here without circular-import risk. automation_engine
re-exports every name for back-compat — existing imports from it keep
working.
"""
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

# Indianapolis timezone (Indiana doesn't follow standard Eastern DST rules)
TZ = ZoneInfo("America/Indiana/Indianapolis")

# Modes during which screen sync colors should be applied. The receiver
# endpoint at POST /api/automation/screen-color drops colors silently when
# the current mode isn't in this set.
SCREEN_SYNC_MODES = frozenset(("gaming", "watching"))
# How recently screen sync must have pushed a color for the engine to treat
# its target lamps (L2/L5) as sync-owned and skip re-applying the mode's
# static state to them. Sync captures every ~2.5s; 8s ≈ 3 frames of grace.
# Past this with no push, the engine reclaims the lamps on the next tick.
SCREEN_SYNC_FRESH_SECONDS = 8.0

# Zone+posture → relax rule — first mode-changing sensor actuation. Auto-
# applies the "relax" manual override when the camera sees bed+reclined for
# a sustained window. Ships in shadow mode (settings.ZONE_POSTURE_RULE_APPLY
# defaults False) so the firing pattern can be observed via ml_decisions
# before flipping to live actuation. Full spec in docs/PROJECT_SPEC.md.
#
# Design notes:
# - Dwell (2 min idle/working, 3 min social) filters brief lean-backs.
# - Projector-from-bed carves itself out: sitting up against the headboard
#   keeps posture=upright, so the (bed, reclined) gate never trips.
# - Re-fire suppression reuses `_override_timeout_hours` so shadow and live
#   cadence match: once the rule logs/fires, it won't re-fire for 4h.
# - Eligible modes are idle/working/social. Social is included because the
#   override often outlives its context (guest left, Anthony stays in social
#   then goes to bed — observed 6× in 30 days). Gated by minimum
#   override age so actively-set social isn't instantly stomped.
# - Time gate: evening always; weekend afternoons (≥13:00) also eligible.
ZONE_POSTURE_RULE_DWELL_SECONDS = 120
ZONE_POSTURE_RULE_DWELL_SOCIAL_SECONDS = 180
# Minimum age of a social override before the rule may supersede it.
# Below this, treat the social setting as fresh user intent and stay out.
ZONE_POSTURE_RULE_SOCIAL_MIN_AGE_SECONDS = 30 * 60
ZONE_POSTURE_RULE_WEEKEND_AFTERNOON_HOUR = 13
ZONE_POSTURE_RULE_ELIGIBLE_MODES = frozenset(("idle", "working", "social"))


# ---------------------------------------------------------------------------
# Watching-sleep guard rule
# ---------------------------------------------------------------------------
# Catches the "fell asleep with YouTube on the projector" case the
# late_night_rescue can't reach (rescue is gated to working/idle and skips
# while a video player is foregrounded). Fires watching → sleeping after a
# sustained late-night dwell with the camera observing bed+reclined.
#
# Reference incident (2026-05-13 → 2026-05-14): manual `watching` set at
# 22:26 from the bed, YouTube ran on the projector all night, mode held
# `watching` for 7h 39m. Lights stayed on the bed-watching cycle the whole
# time. No existing rule could catch it because a real video player was
# foregrounded — process detector kept reporting watching, late_night_rescue
# correctly stayed out.
WATCHING_SLEEP_GUARD_DWELL_SECONDS = 90 * 60  # 90 minutes
# Minimum age of a manual `watching` override before the guard may supersede
# it. Mirrors the social-supersede pattern in zone_posture_rule — fresh user
# intent (just set watching, sat down) is protected; sustained watching that
# pre-dates the late-night window by >90min is fair game.
WATCHING_SLEEP_GUARD_OVERRIDE_MIN_AGE_SECONDS = 90 * 60

# Failsafe expiry for the "user is likely still asleep" stamp. After this
# many hours since the last bed+reclined observation (during watching mode),
# the stamp is treated as stale and `_is_likely_still_asleep` returns False
# even without an attendance signal. Catches the case where the user left
# for the day without the camera ever seeing them re-enter the desk zone
# (e.g., walked straight out the door). 12h covers a long night plus most
# of a morning; anyone still in bed past that is on their own.
ASLEEP_STAMP_FAILSAFE_HOURS = 12


# User-respect cooldown — when the user clears an override via the dashboard
# (api:* source), suppress autonomous mode-pushes for this window so "auto"
# actually means auto. Explicit user actions (api:*, rule_suggestion_accept:*)
# bypass.
USER_CLEAR_AUTO_PUSH_COOLDOWN_SECONDS = 30 * 60  # 30 minutes

# Process-attendance veto window for autonomous relax pushes (late-night
# rescue). Camera-zone freshness is the primary "user is here"
# signal, but the camera blips in dark rooms / pose-only conditions and the
# 5-min freshness window can lapse. The PC agent reporting `working` is an
# independent attendance signal — if it's been < this window, treat the user
# as attended and skip the relax push. 10 minutes tolerates idle thinking
# gaps while staying conservative against "user left for the night."
# (2026-05-07: late-night rescue fired during a dev session because camera
# zone went stale; PC agent had reported working 1.4s before the fire.)
RECENT_PROCESS_WORKING_SECONDS = 10 * 60  # 10 minutes

# Desk-attendance veto window for autonomous idle/relax pushes. Unlike
# is_at_desk_fresh(), this can use PresenceFusion's high-water mark so a
# single no-face/head-down desktop frame does not make the system treat an
# active desk session as empty.
RECENT_DESK_ATTENDANCE_SECONDS = 10 * 60  # 10 minutes

# Ambient-relax dwell — how long the apartment must sit in `idle` (no manual
# override, no Sonos, both attendance vetoes negative, not away) before the
# soft-default kicks in and pushes to `relax`. Slower than the original 180s
# so brief thinking gaps or camera flicker do not make the apartment feel
# eager to drift away from functional modes.
IDLE_AMBIENT_RELAX_DWELL_SECONDS = 10 * 60  # 10 minutes

# Physical-context relax fallback. The existing couch commit supplies the
# 15-second entry hysteresis; the engine accepts a fresh confirming face.
# Process intent has a tighter freshness window than global source ownership,
# and presence loss is debounced so brief camera gaps do not churn the mode.
PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS = 8
PHYSICAL_CONTEXT_PROCESS_VETO_SECONDS = 30
PHYSICAL_CONTEXT_DESK_ABSENCE_SECONDS = 30
PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS = 30
PHYSICAL_CONTEXT_PROCESS_DEVICE_LIMIT = 8

# Sleeping wake authority: a process semantic can prove a human wake only when
# the trusted Desktop lane also shows very recent real keyboard/mouse input.
# Keep this aligned with the existing 15s recent-desktop-interaction boundary.
SLEEPING_WAKE_DESKTOP_MAX_IDLE_SECONDS = 15
SLEEPING_WAKE_INTERACTIVE_MODES = frozenset({"working", "gaming", "watching"})

# Source labels that get blocked by the cooldown above. These are the
# sensor-driven autonomous pushes — they should defer to a recent user
# choice. User-API actions (api:*) and rule-suggestion accepts
# (rule_suggestion_accept:*) are deliberately absent: those represent
# direct user intent, not sensor reactivity.
AUTONOMOUS_PUSH_SOURCES = frozenset({
    "late_night_rescue",
    "ambient_relax",
    "physical_context_relax",
    "zone_posture_rule",
    "watching_sleep_guard",
    "behavioral_predictor",
    "fusion_can_override",
    "fusion_auto_apply",
    "internal",
})

# Autonomous sources whose target modes are typically manual-only (relax,
# sleeping, cooking, social) and thus carry a default `MODE_PRIORITY=0`.
# Without a floor, an `idle` sensor report (p=1) silently displaces these
# rescue overrides — observed bug night of 2026-05-15: ambient `idle`
# reports churned `late_night_rescue → relax` every 60s for 47 minutes
# until the user manually changed modes. Members of this set get their
# override's effective priority floored at `MODE_PRIORITY["idle"]` in the
# displacement guard, so idle/sleeping sensor reports can no longer
# undo the rescue; real-activity signals (working+) still displace.
RESCUE_OVERRIDE_SOURCES = frozenset({
    "late_night_rescue",
    "ambient_relax",
    "physical_context_relax",
    "zone_posture_rule",
    "watching_sleep_guard",
})


# Sources that should preserve per-light manual overrides across mode changes.
# When the user manually drags a brightness slider, mark_light_manual stamps
# that light so automation reconcile skips it. Picking a new mode normally
# wipes those stamps so the user gets the new mode's full default state — but
# only when the user themselves chose the new mode. Autonomous mode-setters
# (late-night rescue, fusion, predictor, zone+posture rule) should respect
# manual brightness; the user's stated rule is "manual sticks until I change
# it." Plus timeout_4h on clear_override: the override expiring isn't a user
# action, so per-light stamps shouldn't get wiped along with it (their own
# 4h expiry runs independently in run_loop).
PRESERVE_PER_LIGHT_OVERRIDE_SOURCES = frozenset({
    "late_night_rescue",
    "ambient_relax",
    "physical_context_relax",
    "behavioral_predictor",
    "fusion_can_override",
    "fusion_auto_apply",
    "zone_posture_rule",
    "watching_sleep_guard",
    "timeout_4h",
    "desk_exit_kitchen",
    "corridor",
    # Bounded auto-remediation clearing a *wedged mode override* is autonomous —
    # it must not also nuke the user's independent per-light slider stamps.
    "remediator:clear_stuck_override",
})


# app_settings key for the persisted DND state. Lives here (not in
# api/routes/automation.py) so the engine doesn't need a function-local
# import from the routes layer — that direction is a latent circular
# import. routes/automation.py re-imports it from here.
DND_STATE_KEY = "dnd_state"


# ---------------------------------------------------------------------------
# Configurable schedule dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DaySchedule:
    """Time-based lighting schedule for one day type (weekday or weekend)."""

    wake_hour: int = 5
    wake_brightness: int = 40
    ramp_start_hour: int = 6
    ramp_duration_minutes: int = 60
    evening_start_hour: int = 18
    winddown_start_hour: int = 21
    # Late-night period (relax-only override). From this hour until wake_hour
    # the relax palette switches to "Moss & Ember" — deeper, mossier, cave/den.
    # Modes that don't define a late_night state fall back to their night state.
    late_night_start_hour: int = 23


@dataclass
class ScheduleConfig:
    """Combined weekday + weekend schedule configuration."""

    weekday: DaySchedule = field(default_factory=DaySchedule)
    weekend: DaySchedule = field(default_factory=lambda: DaySchedule(
        wake_hour=8,
        ramp_start_hour=8,
        ramp_duration_minutes=120,
    ))


# Mode priority — higher index wins when multiple sources report.
# Enforced universally by the priority guard in report_activity().
MODE_PRIORITY = {
    "sleeping": 0,
    "idle": 1,
    "working": 2,
    "watching": 3,
    "cooking": 3,
    "social": 4,
    "gaming": 5,
    "gameday": 6,
    # Pregameday shares priority 6 with gameday by design (GAMEDAY_SPEC §10.1).
    # gameday_service flips pregameday→gameday at T-30 from the same source —
    # same-source updates always pass the priority guard, so the flip lands
    # without priority gymnastics. Any other source trying to displace
    # pregameday must outrank 6 (impossible — pregameday/gameday is the top).
    "pregameday": 6,
}

# Source-staleness cutoff for the priority guard. A current-mode source that
# hasn't reported in this many seconds is considered dead, and a lower-priority
# report from a different source may take over. Prevents an abandoned
# high-priority signal (e.g. stale social) from permanently locking out fresh
# lower-priority reports. 300s matches the confidence-fusion stale window.
SOURCE_STALE_SECONDS = 300


# ---------------------------------------------------------------------------
# Time-based rules — weekday vs weekend
# ---------------------------------------------------------------------------

WEEKDAY_TIME_RULES = [
    # (start_hour, end_hour, light_state_or_ramp)
    (0, 5, {"on": False}),                                          # Overnight — off
    (5, 6, {"on": True, "bri": 40, "hue": 6000, "sat": 200}),     # Early sniping — very dim warm
    (6, 7, ("morning_ramp", 6, 60)),                                # Getting ready (60 min ramp)
    (7, 18, {"on": False}),                                         # At work — off
    (18, 21, {"on": True, "bri": 180, "hue": 8000, "sat": 160}),  # Warm evening
    (21, 24, {"on": True, "bri": 60, "hue": 5500, "sat": 220}),   # Dim wind-down
]

WEEKEND_TIME_RULES = [
    (0, 8, {"on": False}),                                          # Sleeping in — off
    (8, 10, ("morning_ramp", 8, 120)),                              # Gentle weekend ramp (120 min)
    (10, 18, {"on": True, "bri": 220, "hue": 20000, "sat": 80}),  # Daytime neutral bright
    (18, 21, {"on": True, "bri": 180, "hue": 8000, "sat": 160}),  # Warm evening
    (21, 24, {"on": True, "bri": 60, "hue": 5500, "sat": 220}),   # Dim wind-down
]
