"""
Per-light target state calculator — pure functions over lookup tables.

Given a mode, time period, schedule, environment readings (lux,
zone, posture, weather), this module produces the per-light target
dict that ``AutomationEngine`` then dedupes, filters for overrides,
and ships to the Hue bridge.

Extracted from ``automation_engine.py`` so the engine itself can stay
focused on orchestration (mode resolution, override timeouts, fusion
voting, callback dispatch, effect lifecycle, bridge I/O). Every
function here is pure — no ``self``, no I/O, no service objects.
The engine reads state off services and threads primitives in.

The four most-grepped constants (``ACTIVITY_LIGHT_STATES``,
``EFFECT_AUTO_MAP``, ``DEFAULT_MODE_BRIGHTNESS``,
``MODE_TRANSITION_TIME``) are re-exported from
``backend.services.automation_engine`` for back-compat with callers
that imported them from there.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

# Indianapolis timezone — Indiana doesn't follow standard Eastern DST.
# Re-declared here (rather than imported from automation_engine) so
# this module has no engine dependency.
TZ = ZoneInfo("America/Indiana/Indianapolis")


# ---------------------------------------------------------------------------
# Fixture inventory — single source of truth for "every light in the apartment"
# ---------------------------------------------------------------------------

# Light ID → human-readable room mapping. Adding a new fixture is a
# single-edit change here; both this module and automation_engine.py
# derive their iteration tuples from this dict.
LIGHT_IDS: dict[str, str] = {
    "living_room": "1",
    "bedroom_lamp_left": "2",
    "kitchen_front": "3",
    "kitchen_back": "4",
    "bedroom_lamp_right": "5",
}

# Canonical tuple of every fixture ID. Use this anywhere operational
# code needs to iterate over "all lights" so a 5→6 expansion is a
# single LIGHT_IDS edit rather than a tree-wide audit of hardcoded
# tuples.
ALL_LIGHT_IDS: tuple[str, ...] = tuple(LIGHT_IDS.values())


# ---------------------------------------------------------------------------
# Mode brightness multipliers
# ---------------------------------------------------------------------------

# Default per-mode brightness multiplier (1.0 = unchanged). Settings UI
# exposes these as 0.3..1.5 sliders persisted in mode_brightness_config.
DEFAULT_MODE_BRIGHTNESS: dict[str, float] = {
    "gaming": 1.0,
    "working": 1.0,
    "watching": 1.0,
    "relax": 1.0,
    "cooking": 1.0,
    "social": 1.0,
    "gameday": 1.0,
    "pregameday": 1.0,
}


# ---------------------------------------------------------------------------
# Mode transition speeds (deciseconds: 10 = 1 second)
# ---------------------------------------------------------------------------

MODE_TRANSITION_TIME: dict[str, int] = {
    "working":  20,   # 2s smooth
    "gaming":    5,   # 0.5s snappy
    "watching": 30,   # 3s cinematic fade
    "relax":    50,   # 5s gentle
    "social":   10,   # 1s
    "sleeping": 50,   # 5s gradual
    "cooking":  10,   # 1s — kitchen lights up the moment you tap the tile
    "idle":     20,   # 2s
    "gameday":  10,   # 1s snap — celebration windows are time-sensitive
    "pregameday": 40, # 4s slow build — anticipation, not a snap (GAMEDAY_SPEC §10.4)
}


# ---------------------------------------------------------------------------
# Ambient lux adaptive brightness
# ---------------------------------------------------------------------------

# Modes where ambient adaptation is desirable. +30%/-15% range is small
# enough that gaming/watching's intentional spatial palettes stay recognizable
# while still compensating when the room is significantly darker (or brighter)
# than the calibrated baseline. Cooking + social keep their intentional
# bright/medium palettes — explicit user-mode choices that shouldn't drift.
LUX_MODES = frozenset(("working", "relax", "gaming", "watching"))

# Piecewise-linear curve mapping camera-derived ambient brightness
# (gray.mean, 0–255) to a brightness multiplier. Dark rooms (low lux)
# lift brightness; bright rooms dim. Low-end anchor (20.0, 1.30) gives
# overcast-day rooms more headroom than the original (40, 1.15) ceiling
# — needed for the heavy-rain case where the lamp at +15% still felt
# dim against a darker-than-baseline room.
LUX_CURVE: list[tuple[float, float]] = [
    (20.0, 1.30), (40.0, 1.20), (90.0, 1.00), (180.0, 0.85),
]
# The neutral anchor — lux value where multiplier = 1.00. Used by the
# baseline-shift in lux_to_multiplier so an uncalibrated room (default
# baseline=90) lands neutral here, and a calibrated room shifts the
# whole curve so its baseline_lux maps onto this point.
LUX_NEUTRAL_LUX = 90.0
LUX_MULT_EPSILON = 0.03      # Skip re-apply if multiplier change < 3%
LUX_STALE_SECONDS = 30       # Ignore readings older than this


def lux_to_multiplier(lux: float, baseline: float = 90.0) -> float:
    """Piecewise-linear interpolation across LUX_CURVE anchors.

    The ``baseline`` argument shifts the curve so the user's calibrated
    "normal room" reading lands at the neutral anchor (multiplier = 1.00).
    Default baseline of 90 matches the raw LUX_CURVE anchors — used when
    no calibration baseline is available yet.

    Clamps to the first/last anchor's multiplier when lux is outside the
    anchor range. Dark rooms (low lux) lift brightness; bright rooms dim.
    """
    effective = lux - baseline + LUX_NEUTRAL_LUX
    if effective <= LUX_CURVE[0][0]:
        return LUX_CURVE[0][1]
    if effective >= LUX_CURVE[-1][0]:
        return LUX_CURVE[-1][1]
    for (x0, y0), (x1, y1) in zip(LUX_CURVE, LUX_CURVE[1:]):
        if x0 <= effective <= x1:
            frac = (effective - x0) / (x1 - x0) if x1 != x0 else 0.0
            return y0 + frac * (y1 - y0)
    return 1.0  # Unreachable


# ---------------------------------------------------------------------------
# Time-period rollover for fades + activity_light_states lookup
# ---------------------------------------------------------------------------

WINDDOWN_RAMP_MINUTES = 30  # Duration of evening → night fade (minutes)


# ---------------------------------------------------------------------------
# Activity light states — time-aware per-light states
# ---------------------------------------------------------------------------
# Structure: mode → time_period → per-light state dict
# Time periods: "day", "evening", "night", "late_night"
# Social mode is flat (no time keys) — routed through party sub-modes.

_LIGHT_OFF = {"on": False}

# Auto-activate effects based on mode + time period.
# Each cell is either:
#   None           — no effect
#   {"effect": name, "lights": None}          — apply to all mapped lights
#   {"effect": name, "lights": ["1", "2"]}    — apply to specific v1 light IDs only
# Relax uses per-light targeting so the moss-shadow kitchen pendants
# (L3/L4) don't get masked by flame-colored candle/fire flicker.
# Social is static (no cycling) so it has no entry and the engine's
# _get_desired_effect returns None for it.
EFFECT_AUTO_MAP: dict[str, dict[str, dict[str, Any] | None]] = {
    "relax": {
        "day":        {"effect": "opal",   "lights": None},
        # Evening previously fired candle on L1+L2; removed 2026-05-09 because
        # the effect locked color values and persisted through mode changes,
        # masking other lighting decisions. Static palette is enough.
        "evening":    None,
        # L5 added 2026-05-11 (clear-housing desk lamp). Bulb-visible
        # fixture is a natural fire-flicker host; mirror L2's fire scope.
        "night":      {"effect": "fire",   "lights": ["1", "2", "5"]},
        "late_night": {"effect": "fire",   "lights": ["1", "2", "5"]},
    },
    "working":  {"day": None, "evening": None, "night": None},
    "gaming":   {"day": None, "evening": None, "night": None},
    "cooking":  {"day": None, "evening": None, "night": None},
    "watching": {
        "day":     None,
        "evening": {"effect": "glisten", "lights": None},
        "night":   {"effect": "glisten", "lights": None},
    },
    # Gameday — fully custom CelebrationOrchestrator sequences own all
    # visual effects during plays (Decision 1.3a in docs/GAMEDAY_SPEC.md).
    # Auto-effect map stays None across periods.
    "gameday":  {"day": None, "evening": None, "night": None, "late_night": None},
    # Pregameday — silent visual build (T-60 to T-30). No animated effects;
    # static palette only. Weather can still overlay if the period defaults
    # to None (e.g. thunderstorm→sparkle) — that's a feature, not a bug,
    # since lightning-and-Colts-blue is on-brand.
    "pregameday": {"day": None, "evening": None, "night": None, "late_night": None},
}


ACTIVITY_LIGHT_STATES: dict[str, dict[str, Any]] = {
    # L5 ("Bedroom Lamp Right", clear housing, desk-side) added 2026-05-11.
    # Phase A landed L5 = L2 mirror placeholder; Phase C (curator design pass,
    # 2026-05-11) ships distinct L5 values across gaming/watching/relax to
    # exploit the clear-housing aesthetic — bulb visible, sat reads sharper,
    # warm-whites more "candle-y." Modes where L5 still mirrors L2 (working,
    # cooking, gameday, social, watching-day) are either curator-approved
    # mirror (matched task pair) or out-of-scope for Phase C.
    # ── Gaming ────────────────────────────────────────────────────────
    # Retuned 2026-05-05: blue palette (hue 46920–50000) is intentional and
    # maps onto the room's existing teal accents, but saturation 220–240
    # was overcooked — the warm-wood + cream textile palette can't absorb
    # that much pure blue. Sat dropped to 180; same hue band, less visual
    # weight. Added an explicit late_night state that warms toward relax-
    # adjacent values for past-23:00 sessions.
    "gaming": {
        # L5 Phase C 2026-05-11: hue shifts toward room's teal accent (~48000)
        # vs L2's Colts-blue (46920) — L1 lamp base + monstera pot teal benefit
        # when L5 echoes them. Bri stepped back (peripheral vs L2 screen-adjacent
        # primary). Sat lowered because seeded glass pops sat more than fabric —
        # sat=200 produced aggressive bleed in bedroomLampRightGamingDay.jpeg.
        "day": {
            "1": {"on": True, "bri": 130, "hue": 47000, "sat": 180},
            "2": {"on": True, "bri": 240, "hue": 46920, "sat": 180},
            "3": {"on": True, "bri": 30,  "hue": 50000, "sat": 180},
            "4": {"on": True, "bri": 30,  "hue": 50000, "sat": 180},
            "5": {"on": True, "bri": 180, "hue": 48500, "sat": 160},
        },
        "evening": {
            "1": {"on": True, "bri": 45,  "hue": 47000, "sat": 190},
            "2": {"on": True, "bri": 150, "hue": 46920, "sat": 190},
            "3": {"on": True, "bri": 22,  "hue": 50000, "sat": 190},
            "4": {"on": True, "bri": 22,  "hue": 50000, "sat": 190},
            "5": {"on": True, "bri": 120, "hue": 48000, "sat": 170},
        },
        "night": {
            "1": {"on": True, "bri": 55,  "hue": 47000, "sat": 200},
            "2": {"on": True, "bri": 140, "hue": 46920, "sat": 200},
            "3": {"on": True, "bri": 28,  "hue": 50000, "sat": 200},
            "4": {"on": True, "bri": 28,  "hue": 50000, "sat": 200},
            "5": {"on": True, "bri": 110, "hue": 48000, "sat": 175},
        },
        # Late-night gaming — warmer accent, less saturation, dimmed overall.
        # L1 shifts toward muted teal, L2 (desk dominant) keeps the blue but
        # at lower bri to ease eye strain. Kitchen drops further into accent.
        "late_night": {
            "1": {"on": True, "bri": 40,  "hue": 47000, "sat": 160},
            "2": {"on": True, "bri": 110, "hue": 46920, "sat": 170},
            "3": {"on": True, "bri": 18,  "hue": 50000, "sat": 180},
            "4": {"on": True, "bri": 18,  "hue": 50000, "sat": 180},
            "5": {"on": True, "bri": 80,  "hue": 47500, "sat": 150},
        },
    },
    # ── Working ───────────────────────────────────────────────────────
    # L5 Phase C pass-3 (2026-05-12) — workingBothLampsLateNight.JPEG showed
    # that at L5=L2 mirror values, L5's clear housing reads COOLER and
    # BRIGHTER than L2's fabric shade despite identical bri/ct (transparent
    # enclosure emits raw bulb output; fabric diffuses + holds it). Net
    # effect was "two different temperature sources fighting" not "flat-lit
    # twin." Gradient corrects by warming + dimming L5 to pull it toward L2's
    # apparent warmth — creates a deliberate ambient step-back instead of
    # accidental brightness incoherence. Pattern: L1 fill ≈ L5 ambient
    # step-back < L2 dominant.
    "working": {
        "day": {
            "1": {"on": True, "bri": 180, "ct": 233},
            "2": {"on": True, "bri": 254, "ct": 210},
            "3": {"on": True, "bri": 140, "ct": 250},
            "4": {"on": True, "bri": 140, "ct": 250},
            # L5 day: bri step-back from 254, ct=233 matches L1 to avoid a
            # dual-CT fight in the desk zone (L2 at ct=210 is the daytime
            # exception; L1+L5 anchor at 233 for coherence).
            "5": {"on": True, "bri": 220, "ct": 233},
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},
            "2": {"on": True, "bri": 180, "ct": 333},
            "3": {"on": True, "bri": 60,  "ct": 400},
            "4": {"on": True, "bri": 60,  "ct": 400},
            # L5 evening: dim + warm step-back (fixture physics already
            # push L5 cooler at mirror values; correction reverses it).
            "5": {"on": True, "bri": 140, "ct": 370},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 440},
            "2": {"on": True, "bri": 130, "ct": 370},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
            # L5 night: depth gradient — L2 stays dominant desk read,
            # L5 sits in ambient layer alongside L1.
            "5": {"on": True, "bri": 100, "ct": 400},
        },
        # Distinct from night: warmer and slightly brighter so 1am+ desk
        # work stays readable without falling back to relax-dim. Kitchen
        # stays off; this is desk-only late-night functional lighting.
        "late_night": {
            "1": {"on": True, "bri": 90,  "ct": 454},
            "2": {"on": True, "bri": 160, "ct": 400},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
            # L5 late_night: iterative tune-by-feel after Phase C pass-3.
            # 120/440 → 100/454 (first tune, still bright) → 70/470 (this).
            # Clear housing's visible filament reads as ambient warmth even
            # at very low bri, so we can drop further than fabric-shade L2
            # without losing presence. Lands clearly below L1's 90-anchor
            # so L5 reads as "on but soft" rather than "second functional
            # source." L2 at bri=160 carries the actual desk-task read.
            "5": {"on": True, "bri": 70, "ct": 470},
        },
    },
    # ── Watching ──────────────────────────────────────────────────────
    "watching": {
        # Day CT bumped 320→286 (3500K) to match cooking — projector food
        # scenes read more accurate at 286 mirek; 320K was slightly cool
        # for daytime color rendition.
        "day": {
            "1": {"on": True, "bri": 80,  "ct": 286},
            "2": {"on": True, "bri": 70,  "ct": 333},
            "3": {"on": True, "bri": 30,  "ct": 333},
            "4": {"on": True, "bri": 30,  "ct": 333},
            "5": {"on": True, "bri": 70,  "ct": 333},
        },
        # L5 Phase C 2026-05-11: dimmer + warmer than L2 in watching evening/
        # night. Seated user-perspective photo shows L5 in line-of-sight peripheral
        # vision when projector is on — at L2-matched bri the visible bulb would
        # glare. Pulled bri below the projector-safe floor, ct pushed warmer to
        # blend into ambient darkness without competing with the screen.
        "evening": {
            "1": {"on": True, "bri": 65,  "ct": 400},
            "2": {"on": True, "bri": 40,  "ct": 400},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
            "5": {"on": True, "bri": 20,  "ct": 454},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 454},
            "2": {"on": True, "bri": 30,  "ct": 454},
            "3": _LIGHT_OFF,
            "4": _LIGHT_OFF,
            "5": {"on": True, "bri": 15,  "ct": 500},
        },
    },
    # ── Social ────────────────────────────────────────────────────────
    # "Velvet Speakeasy" — retuned 2026-05-05. L3/L4 burnt-orange dropped
    # from sat254/bri70 to sat210/bri55: max saturation overpowered the
    # sage accent palette and pulled the kitchen into a too-loud focal
    # point. Lower sat lets olive breathe; lower bri keeps it ambient,
    # not center-stage. L1 (dusty rose) and L2 (cognac amber) unchanged.
    # NOTE 2026-05-12: L1 social `bri=140, hue=58500, sat=160` reads as violet
    # wall-flood from the hallway angle (curator pass 2 surfaced this from
    # socialBothLampsLookingIntoBedroom.jpeg — analogous to weirdOldMode.JPEG
    # anti-pattern). L1 retune is queued as a separate follow-up; L5 change
    # below is the only social edit shipped now.
    "social": {
        "1": {"on": True, "bri": 140, "hue": 58500, "sat": 160},
        "2": {"on": True, "bri": 120, "hue": 6500,  "sat": 200},
        "3": {"on": True, "bri": 55,  "hue": 4000,  "sat": 210},
        "4": {"on": True, "bri": 55,  "hue": 4000,  "sat": 210},
        # L5 Phase C pass-2 2026-05-12: lighter cognac (hue 7500 vs L2's 6500)
        # and lower sat (185 vs L2's 200) — seeded glass amplifies sat, so
        # stepping back gives same perceived warmth without overpowering L2's
        # soft fabric wash. Bri 140 > L2's 120 compensates for fixture
        # perceived-output gap; the seated photo already showed L5 reading
        # slightly brighter at equal bri, so 140 there exaggerates that
        # deliberately into a foreground-vs-background pair.
        "5": {"on": True, "bri": 140, "hue": 7500,  "sat": 185},
    },
    # ── Gameday ──────────────────────────────────────────────────────
    # PLACEHOLDER values — slice B's CelebrationOrchestrator authoring
    # finalizes these alongside per-event sequences. Baseline applies
    # between plays / at halftime; CelebrationOrchestrator overrides
    # during TD / FG / kickoff / end-of-game.
    #
    # Design intent: Colts royal blue accent on L1 (hue ~47000) +
    # warm-amber fill on L2 + matched warm pendants on L3/L4 (kitchen
    # pair, Rule 1). HSB throughout (Rule 4). Saturation moderated to
    # coexist with the warm-earthy room (Rule 5). Lighting curator
    # review owed before slice B commits real values.
    "gameday": {
        "day": {
            "1": {"on": True, "bri": 150, "hue": 47000, "sat": 185},
            "2": {"on": True, "bri": 200, "hue": 8000,  "sat": 130},
            "3": {"on": True, "bri": 140, "hue": 8000,  "sat": 130},
            "4": {"on": True, "bri": 140, "hue": 8000,  "sat": 130},
            "5": {"on": True, "bri": 200, "hue": 8000,  "sat": 130},
        },
        "evening": {
            "1": {"on": True, "bri": 110, "hue": 47000, "sat": 200},
            "2": {"on": True, "bri": 150, "hue": 7000,  "sat": 160},
            "3": {"on": True, "bri": 60,  "hue": 7000,  "sat": 160},
            "4": {"on": True, "bri": 60,  "hue": 7000,  "sat": 160},
            "5": {"on": True, "bri": 150, "hue": 7000,  "sat": 160},
        },
        "night": {
            "1": {"on": True, "bri": 70,  "hue": 47000, "sat": 200},
            "2": {"on": True, "bri": 100, "hue": 6500,  "sat": 200},
            "3": {"on": True, "bri": 30,  "hue": 6500,  "sat": 200},
            "4": {"on": True, "bri": 30,  "hue": 6500,  "sat": 200},
            "5": {"on": True, "bri": 100, "hue": 6500,  "sat": 200},
        },
        "late_night": {
            "1": {"on": True, "bri": 50,  "hue": 47000, "sat": 200},
            "2": {"on": True, "bri": 70,  "hue": 6000,  "sat": 200},
            "3": {"on": True, "bri": 18,  "hue": 6000,  "sat": 180},
            "4": {"on": True, "bri": 18,  "hue": 6000,  "sat": 180},
            "5": {"on": True, "bri": 70,  "hue": 6000,  "sat": 200},
        },
    },
    # ── Pregameday ────────────────────────────────────────────────────
    # T-60 to T-30 silent visual build (GAMEDAY_SPEC §10.2). Sister
    # palette to gameday, dialed back ~15-20% on saturation: Colts blue
    # clearly present on L1 (hue 47000) but a notch less committed than
    # gameday's _COLTS_BLUE_SAT=215 commitment; warm-amber fill on L2 +
    # kitchen pair L3≡L4 a hair softer than gameday so the room reads as
    # "building toward" rather than "fully arrived." Curator iteration
    # on real values pre-preseason tracked at GH #8.
    "pregameday": {
        "day": {
            "1": {"on": True, "bri": 140, "hue": 47000, "sat": 170},
            "2": {"on": True, "bri": 180, "hue": 8500,  "sat": 105},
            "3": {"on": True, "bri": 120, "hue": 8500,  "sat": 105},
            "4": {"on": True, "bri": 120, "hue": 8500,  "sat": 105},
            "5": {"on": True, "bri": 180, "hue": 8500,  "sat": 105},
        },
        "evening": {
            "1": {"on": True, "bri": 100, "hue": 47000, "sat": 175},
            "2": {"on": True, "bri": 130, "hue": 7500,  "sat": 135},
            "3": {"on": True, "bri": 50,  "hue": 7500,  "sat": 135},
            "4": {"on": True, "bri": 50,  "hue": 7500,  "sat": 135},
            "5": {"on": True, "bri": 130, "hue": 7500,  "sat": 135},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "hue": 47000, "sat": 175},
            "2": {"on": True, "bri": 85,  "hue": 6800,  "sat": 170},
            "3": {"on": True, "bri": 25,  "hue": 6800,  "sat": 170},
            "4": {"on": True, "bri": 25,  "hue": 6800,  "sat": 170},
            "5": {"on": True, "bri": 85,  "hue": 6800,  "sat": 170},
        },
        # Late-night L5 bumped to bri=75 (vs L2's 60) per lighting-curator
        # advisory 2026-05-15: L5 clear-housing fixture amplifies saturation
        # at low brightness; matching L2's 60 lands in the "cave amber"
        # caution zone. 75 is L2's night value — keeps the sister-pair feel
        # without the seeded-glass pop becoming oppressive. Real-room photo
        # verification pre-preseason owed (GH #8).
        "late_night": {
            "1": {"on": True, "bri": 42,  "hue": 47000, "sat": 175},
            "2": {"on": True, "bri": 60,  "hue": 6300,  "sat": 170},
            "3": {"on": True, "bri": 15,  "hue": 6300,  "sat": 150},
            "4": {"on": True, "bri": 15,  "hue": 6300,  "sat": 150},
            "5": {"on": True, "bri": 75,  "hue": 6300,  "sat": 170},
        },
    },
    # ── Relax ─────────────────────────────────────────────────────────
    # The "Moss & Candlelight" / "Moss & Ember" palette names below survive
    # as colour descriptions, not capability promises. Candle flicker was
    # removed from the relax-evening EFFECT_AUTO_MAP entry on 2026-05-09;
    # fire on night/late_night remains the only animated candle analog.
    "relax": {
        "day": {
            "1": {"on": True, "bri": 95, "hue": 7500,  "sat": 200},
            "2": {"on": True, "bri": 85, "hue": 8000,  "sat": 190},
            "3": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 30, "hue": 20000, "sat": 100},
            "5": {"on": True, "bri": 85, "hue": 8000,  "sat": 190},
        },
        # L5 Phase C 2026-05-11: raised above L2 mirror so it registers as a
        # genuine second accent — bedroomL2andL5TogetherSittingAtDesk.jpeg
        # showed L5 at bri=55 as a "barely-perceptible spark" while L2
        # dominated. Hue 6000 (deeper amber) vs L2's 6500 creates variation
        # without clash. Sat 210 < L2's 220 because seeded glass pops sat.
        "evening": {
            "1": {"on": True, "bri": 70, "hue": 6000,  "sat": 230},
            "2": {"on": True, "bri": 55, "hue": 6500,  "sat": 220},
            "3": {"on": True, "bri": 15, "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 15, "hue": 20000, "sat": 100},
            "5": {"on": True, "bri": 75, "hue": 6000,  "sat": 210},
        },
        # L5 Phase C 2026-05-11: brighter seed for the fire-effect host. Fire is
        # scoped to L1+L2+L5 (per EFFECT_AUTO_MAP), so L5 at higher bri makes
        # it the left-anchor of a two-point flicker that frames the monitor.
        # Hue 4000 (deeper than L2's 4500) and sat 240 < L2's 254 — distinct
        # left ember vs L2's right ember without identical-twin clone effect.
        "night": {
            "1": {"on": True, "bri": 38, "hue": 5000,  "sat": 254},
            "2": {"on": True, "bri": 28, "hue": 4500,  "sat": 254},
            "3": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 8,  "hue": 20000, "sat": 100},
            "5": {"on": True, "bri": 38, "hue": 4000,  "sat": 240},
        },
        # Late-night relax — retuned 2026-05-05. L1/L2 sat254 at bri 28/22
        # produced oppressive cave-burgundy. Sat dropped to 240 (still
        # deep amber) and bri lifted to 34/26 for readable softness.
        "late_night": {
            "1": {"on": True, "bri": 34, "hue": 3000,  "sat": 240},
            "2": {"on": True, "bri": 26, "hue": 2500,  "sat": 240},
            "3": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},
            "4": {"on": True, "bri": 5,  "hue": 20000, "sat": 100},
            "5": {"on": True, "bri": 26, "hue": 2500,  "sat": 240},
        },
    },
    # ── Cooking ───────────────────────────────────────────────────────
    "cooking": {
        "day": {
            "1": {"on": True, "bri": 150, "ct": 320},
            "2": {"on": True, "bri": 80,  "ct": 333},
            "3": {"on": True, "bri": 254, "ct": 286},
            "4": {"on": True, "bri": 254, "ct": 286},
            "5": {"on": True, "bri": 80,  "ct": 333},
        },
        "evening": {
            "1": {"on": True, "bri": 100, "ct": 370},
            "2": {"on": True, "bri": 50,  "ct": 400},
            "3": {"on": True, "bri": 230, "ct": 333},
            "4": {"on": True, "bri": 230, "ct": 333},
            "5": {"on": True, "bri": 50,  "ct": 400},
        },
        "night": {
            "1": {"on": True, "bri": 60,  "ct": 420},
            "2": {"on": True, "bri": 25,  "ct": 454},
            "3": {"on": True, "bri": 180, "ct": 370},
            "4": {"on": True, "bri": 180, "ct": 370},
            "5": {"on": True, "bri": 25,  "ct": 454},
        },
    },
}


# ---------------------------------------------------------------------------
# Bed+reclined zone-posture overlay tunables
# ---------------------------------------------------------------------------

# Watching + zone=bed + posture=reclined target brightness per period.
# LOWER than the baseline watching state — projector + lying back means
# bright lamps compete with the screen and hit eyes more directly than
# when sitting upright. Day is unset (napping in daylight needs no rule).
#
# L1-night is the user-facing knob (settings page slider); evening and
# late_night L1 scale proportionally to the ratios in the original
# tuning. L2 is held at these tuned values — sits out of line of sight
# when reclined and is already near-off.
BED_RECLINED_L1_NIGHT_DEFAULT = 25
BED_RECLINED_L2_WATCHING_BRI = {
    "evening":    18,
    "night":      8,
    "late_night": 5,
}
# Working in bed reclined needs a higher floor than watching: the user
# is actively reading terminal text, not letting the projector do all
# the visual work. Still well below the working baseline (160 at
# late_night) to stop blinding bedside-lamp glare. Mirrors
# BED_ZONE_ONLY_L2_BRI levels — "sitting up reading on phone" and
# "lying down with terminal" want similar dim-but-readable L2.
BED_RECLINED_L2_WORKING_BRI = {
    "evening":    50,
    "night":      35,
    "late_night": 25,
}
BED_RECLINED_L1_RATIO = {
    "evening":    1.8,   # default 45 when night=25
    "night":      1.0,
    "late_night": 0.6,   # default 15 when night=25
}

# Bed-zone-only target brightness per period (posture None or upright).
# Used by apply_zone_overlay's third branch when zone=bed and posture is
# not "reclined" — i.e. face-only detection (laptop blocks pose
# landmarks) or pose committed "upright". Higher than BED_RECLINED_*
# because the user might be sitting up against the headboard, scrolling
# a phone, or actively working on a laptop in bed: bedside-reading
# levels rather than lying-down levels.
BED_ZONE_ONLY_L1_BRI = {"evening": 60, "night": 40, "late_night": 30}
BED_ZONE_ONLY_L2_BRI = {"evening": 50, "night": 35, "late_night": 25}

# Maximum age (in seconds) for a committed zone/posture to be honored
# by the overlay. Older than this and the value is treated as missing —
# mirrors ConfidenceFusion's SOURCE_STALE_SECONDS so stale camera state
# can't drive the lights when the user has been gone for a while.
ZONE_POSTURE_FRESHNESS_SECONDS = 300


# ---------------------------------------------------------------------------
# Pure helpers — used by engine and exposed for tests
# ---------------------------------------------------------------------------


def morning_ramp(
    minute_in_window: int,
    window_minutes: int = 120,
) -> dict[str, Any]:
    """Calculate gradual morning light ramp from warm/dim to daylight/bright.

    Args:
        minute_in_window: Minutes elapsed since the ramp start.
        window_minutes: Total ramp duration in minutes.

    Returns:
        Light state dict interpolated between warm/dim and daylight/bright.
    """
    progress = min(1.0, max(0.0, minute_in_window / window_minutes))

    bri = int(80 + (254 - 80) * progress)
    hue = int(8000 + (34000 - 8000) * progress)
    sat = int(180 + (50 - 180) * progress)

    return {"on": True, "bri": bri, "hue": hue, "sat": sat}


def lerp_light_state(
    state_a: dict[str, Any],
    state_b: dict[str, Any],
    progress: float,
) -> dict[str, Any]:
    """Interpolate between two light states.

    Handles both uniform {bri, hue, sat} and per-light {"1": {...}, ...} formats.
    progress=0.0 returns state_a, progress=1.0 returns state_b.
    """
    progress = min(1.0, max(0.0, progress))

    def _lerp_val(a: int, b: int) -> int:
        return int(a + (b - a) * progress)

    def _lerp_single(sa: dict, sb: dict) -> dict:
        result: dict[str, Any] = {"on": sa.get("on", True) or sb.get("on", True)}
        for key in ("bri", "hue", "sat", "ct"):
            if key in sa and key in sb:
                result[key] = _lerp_val(sa[key], sb[key])
            elif key in sa:
                result[key] = sa[key]
            elif key in sb:
                result[key] = sb[key]
        return result

    is_per_light_a = any(k in ALL_LIGHT_IDS for k in state_a)
    is_per_light_b = any(k in ALL_LIGHT_IDS for k in state_b)

    if is_per_light_a and is_per_light_b:
        return {
            lid: _lerp_single(state_a[lid], state_b[lid])
            for lid in state_a
            if lid in state_b
        }

    return _lerp_single(state_a, state_b)


def get_time_period_static() -> str:
    """Determine the current time period using fixed defaults.

    Used as a fallback when no schedule config is available
    (e.g. by ``resolve_activity_state`` when called without
    a precomputed period).
    """
    hour = datetime.now(tz=TZ).hour
    if 8 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"


def get_time_period(schedule, now: Optional[datetime] = None) -> str:
    """Determine the current time period using the schedule config.

    Returns one of: "day", "evening", "night", "late_night". The
    late_night slot runs from schedule.late_night_start_hour until
    the next day's wake_hour — modes without a late_night state
    fall back to night via ``resolve_activity_state``.

    Args:
        schedule: A ``ScheduleConfig`` (with .weekday and .weekend
            ``DaySchedule`` children).
        now: Override for the current time (used by tests). Defaults
            to ``datetime.now(tz=TZ)``.

    The morning ramp window (ramp_start_hour..ramp_start_hour+duration)
    counts as "day" — the ramp's brightness curve comes from
    ``_build_time_rules``' morning_ramp handling, not this bucket; the
    user is awake and active, so day-mode states are the right baseline.
    """
    if now is None:
        now = datetime.now(tz=TZ)
    hour = now.hour
    day = schedule.weekday if now.weekday() < 5 else schedule.weekend

    if day.ramp_start_hour <= hour < day.evening_start_hour:
        return "day"
    if day.evening_start_hour <= hour < day.winddown_start_hour:
        return "evening"
    # late_night wraps midnight: [late_night_start_hour, 24) ∪ [0, wake_hour)
    if hour >= day.late_night_start_hour or hour < day.wake_hour:
        return "late_night"
    return "night"


def resolve_activity_state(
    mode: str,
    time_period: Optional[str] = None,
) -> dict[str, Any]:
    """Look up the time-appropriate light state for an activity mode.

    Time-aware entries have "day"/"evening"/"night" (and optionally
    "late_night") keys. Flat entries (social) are returned as-is.

    Args:
        mode: Activity mode name.
        time_period: Override time period. Uses the static default
            when None.
    """
    entry = ACTIVITY_LIGHT_STATES.get(mode)
    if entry is None:
        return {}
    if "day" in entry:
        period = time_period or get_time_period_static()
        # late_night falls back to night for modes that don't define it
        if period == "late_night" and "late_night" not in entry:
            period = "night"
        return entry.get(period, entry.get("night", {}))
    return entry


# ---------------------------------------------------------------------------
# Per-light state transformations — pure
# ---------------------------------------------------------------------------


def _is_per_light_dict(state: dict[str, Any]) -> bool:
    """True if ``state`` is the per-light shape (keys are light IDs)."""
    return all(isinstance(v, dict) for v in state.values()) and any(
        k in ALL_LIGHT_IDS for k in state.keys()
    )


def apply_brightness_multiplier(
    state: dict[str, Any],
    mode: str,
    multipliers: dict[str, float],
) -> dict[str, Any]:
    """Apply per-mode brightness multiplier to a light state.

    Pure: returns a new state dict, never mutates the input.
    """
    multiplier = multipliers.get(mode, 1.0)
    if multiplier == 1.0:
        return state

    if _is_per_light_dict(state):
        result: dict[str, Any] = {}
        for lid, ls in state.items():
            ls_copy = ls.copy()
            if ls_copy.get("on", True) and "bri" in ls_copy:
                ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * multiplier)))
            result[lid] = ls_copy
        return result

    result = state.copy()
    if result.get("on", True) and "bri" in result:
        result["bri"] = max(1, min(254, int(result["bri"] * multiplier)))
    return result


def apply_lux_multiplier(
    state: dict[str, Any],
    mode: str,
    lux_reading: Optional[float],
    last_multiplier: float,
    baseline_lux: Optional[float] = None,
) -> tuple[dict[str, Any], float]:
    """Adjust per-light brightness by camera-derived ambient lux.

    Pure: caller owns the hysteresis state and gets the new value
    back. ``last_multiplier`` is what was applied last tick; this
    function returns the multiplier that should be remembered for
    next tick (which may be the same ``last_multiplier`` if the new
    raw reading is within ``LUX_MULT_EPSILON``, or a fresh value).

    Returns ``(new_state, new_last_multiplier)``. Engine stores the
    second element back into ``self._last_lux_multiplier``.

    No-op (returns state unchanged + ``last_multiplier`` unchanged) when:
      - mode is not in LUX_MODES (only working / relax adapt)
      - ``lux_reading`` is None (camera not wired, paused, stale, etc;
        engine resolves freshness before calling)
    """
    if mode not in LUX_MODES or lux_reading is None:
        return state, last_multiplier

    raw_mult = lux_to_multiplier(
        float(lux_reading),
        float(baseline_lux) if baseline_lux else 90.0,
    )
    # Hysteresis: stay on the last multiplier if the new raw value is
    # within epsilon — keeps the resulting state dict bit-identical so
    # the per-light dedupe downstream skips bridge writes.
    if abs(raw_mult - last_multiplier) < LUX_MULT_EPSILON:
        multiplier = last_multiplier
    else:
        multiplier = raw_mult

    if multiplier == 1.0:
        return state, multiplier

    if _is_per_light_dict(state):
        result: dict[str, Any] = {}
        for lid, ls in state.items():
            ls_copy = ls.copy()
            if ls_copy.get("on", True) and "bri" in ls_copy:
                ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * multiplier)))
            result[lid] = ls_copy
        return result, multiplier

    result = state.copy()
    if result.get("on", True) and "bri" in result:
        result["bri"] = max(1, min(254, int(result["bri"] * multiplier)))
    return result, multiplier


def apply_zone_overlay(
    state: dict[str, Any],
    mode: str,
    period: str,
    zone: Optional[str],
    posture: Optional[str],
    bed_reclined_l1_night: int = BED_RECLINED_L1_NIGHT_DEFAULT,
) -> dict[str, Any]:
    """Zone- and posture-aware per-light adjustments as the final overlay.

    Two branches:

    1. ``zone=desk`` + watching: LIFT L2 above the projector-safe dim —
       watching at the desk is YouTube / a monitor stream and the
       projector is off, so the default dim L2 reads as too dark.
    2. ``zone=bed + posture=reclined`` (any mode except sleeping):
       LOWER L1 and L2 below the baseline. ``bed + reclined`` is a
       physical fact about the user's body, not a mode label — when
       you're lying down with the projector on, bright bedside lamps
       compete with the screen and hit eyes directly regardless of
       what the activity detector thinks you're doing.

    Only ever moves brightness in one direction per branch (lift-only
    for desk, lower-only for reclined) so a learned override stays
    preserved if it already moved the same way.

    ``zone`` and ``posture`` are passed in pre-resolved — the engine
    handles freshness-gating via the camera service. ``None`` for
    either means "no fresh reading" and the overlay is a no-op.
    """
    is_per_light = all(isinstance(v, dict) for v in state.values()) and "2" in state
    if not is_per_light:
        return state

    # Branch 1 — watching at desk: lift L2 (and L5 if present).
    # L5 ("Bedroom Lamp Right", desk-side clear housing) joins the lift
    # so both desk lamps brighten when watching is happening at the
    # monitor instead of the projector. Lift-only — preserves any
    # learned override that already lifted them.
    if zone == "desk" and mode == "watching":
        zone_bri_by_period = {
            "day": 160,
            "evening": 110,
            "night": 70,
            "late_night": 50,
        }
        target_bri = zone_bri_by_period.get(period)
        if target_bri is None:
            return state
        new_state = {lid: dict(ls) for lid, ls in state.items()}
        changed = False
        for light_id in ("2", "5"):
            if light_id not in new_state:
                continue
            current = int(new_state[light_id].get("bri", 0))
            if current >= target_bri:
                continue
            new_state[light_id]["bri"] = target_bri
            changed = True
        if not changed:
            return state
        return new_state

    # Branch 2 — reclined in bed: lower L1 and L2. Mode-agnostic
    # except for sleeping (already at ember-dim, no-op anyway).
    # Working mode picks a higher L2 floor (terminal needs to be
    # readable); every other mode (watching, relax, gaming, social,
    # cooking, idle, gameday) takes the watching-projector floor.
    if zone == "bed" and posture == "reclined" and mode != "sleeping":
        ratio = BED_RECLINED_L1_RATIO.get(period)
        l2_table = (
            BED_RECLINED_L2_WORKING_BRI
            if mode == "working"
            else BED_RECLINED_L2_WATCHING_BRI
        )
        l2_target = l2_table.get(period)
        if ratio is None or l2_target is None:
            return state
        l1_target = max(1, min(254, int(bed_reclined_l1_night * ratio)))
        targets = {"1": l1_target, "2": l2_target}
        new_state = {lid: dict(ls) for lid, ls in state.items()}
        changed = False
        for light_id, target in targets.items():
            if light_id not in new_state:
                continue
            current = int(new_state[light_id].get("bri", 0))
            if current <= target:
                continue  # Already at or below target — don't raise.
            new_state[light_id]["bri"] = target
            changed = True
        if not changed:
            return state
        return new_state

    # Branch 3 — bed zone, posture not committed as "reclined". Triggers
    # when posture is None (face-only detection — laptop blocks hip /
    # shoulder landmarks) or "upright" (sitting up in bed). Scoped to
    # working/idle during evening/night/late_night so brief bed visits
    # in active modes (gaming/watching/social/cooking) keep their
    # baselines. Targets are bedside-reading levels — between the
    # working baseline and the full reclined dim.
    if (
        zone == "bed"
        and posture in (None, "upright")
        and mode in ("working", "idle")
        and period in ("evening", "night", "late_night")
    ):
        l1_target = BED_ZONE_ONLY_L1_BRI.get(period)
        l2_target = BED_ZONE_ONLY_L2_BRI.get(period)
        if l1_target is None or l2_target is None:
            return state
        targets = {"1": l1_target, "2": l2_target}
        new_state = {lid: dict(ls) for lid, ls in state.items()}
        changed = False
        for light_id, target in targets.items():
            if light_id not in new_state:
                continue
            current = int(new_state[light_id].get("bri", 0))
            if current <= target:
                continue
            new_state[light_id]["bri"] = target
            changed = True
        if not changed:
            return state
        return new_state

    return state


def is_zone_posture_freshness_ok(
    committed_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """True if a zone/posture commit timestamp is fresh enough to honor.

    Matches the staleness threshold ConfidenceFusion uses, so a stale
    camera commit (e.g. from before the last sleep cycle) can't leak
    into the lighting decision.

    A ``None`` ``committed_at`` returns False (no fresh commit).
    """
    if committed_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    age = (now - committed_at).total_seconds()
    return age <= ZONE_POSTURE_FRESHNESS_SECONDS


# ---------------------------------------------------------------------------
# Weather adjustment — pure (caller resolves the condition string)
# ---------------------------------------------------------------------------


def classify_weather(desc: str, weather: dict[str, Any]) -> Optional[str]:
    """Map a weather description string + payload to a condition category.

    Returns one of "thunderstorm", "rain", "snow", "clouds",
    "golden_hour", or None. The golden-hour case reads the sunset
    timestamp from ``weather`` to decide if we're within the ±30
    minute window.
    """
    if "thunderstorm" in desc:
        return "thunderstorm"
    if "rain" in desc or "drizzle" in desc:
        return "rain"
    if "snow" in desc:
        return "snow"
    if "overcast" in desc or "clouds" in desc:
        return "clouds"
    if "clear" in desc:
        now = datetime.now(tz=TZ)
        sunset_ts = weather.get("sunset")
        if sunset_ts:
            sunset_utc = datetime.fromtimestamp(sunset_ts, tz=timezone.utc)
            sunset_local = sunset_utc.astimezone(TZ)
            minutes_to_sunset = (sunset_local - now).total_seconds() / 60
            if -30 <= minutes_to_sunset <= 30:
                return "golden_hour"
    return None


def adjust_single_light(
    light: dict[str, Any], condition: str,
) -> dict[str, Any]:
    """Apply weather adjustment to a single light's state dict.

    Respects CT vs HSB: if the light uses ``ct``, adjustments shift
    color temperature. If it uses ``hue``/``sat``, adjustments shift
    those values instead. Never mixes the two color spaces.
    """
    adj = {**light}
    uses_ct = "ct" in adj

    if condition == "thunderstorm":
        adj["bri"] = max(1, adj.get("bri", 200) - 30)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 80)
        else:
            adj["hue"] = min(65535, adj.get("hue", 8000) + 12000)
            adj["sat"] = min(254, adj.get("sat", 100) + 60)

    elif condition == "rain":
        adj["bri"] = max(1, adj.get("bri", 200) - 15)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 50)
        else:
            adj["hue"] = max(0, adj.get("hue", 8000) + 4000)
            adj["sat"] = min(254, adj.get("sat", 100) + 30)

    elif condition == "snow":
        adj["bri"] = min(254, adj.get("bri", 200) + 25)
        if uses_ct:
            adj["ct"] = max(153, adj["ct"] - 60)

    elif condition == "clouds":
        adj["bri"] = max(1, int(adj.get("bri", 200) * 0.85))
        if uses_ct:
            adj["ct"] = min(500, adj["ct"] + 25)

    elif condition == "golden_hour":
        if uses_ct:
            adj["ct"] = min(500, adj["ct"] + 50)
        else:
            adj["hue"] = min(65535, adj.get("hue", 8000) + 3000)
            adj["sat"] = min(254, adj.get("sat", 100) + 40)

    return adj


def apply_weather_adjust(
    state: dict[str, Any],
    condition: Optional[str],
) -> dict[str, Any]:
    """Apply subtle weather-based adjustments to light states.

    Caller resolves the condition (via ``classify_weather`` or by
    pulling it off the cached weather payload). ``None`` means
    "no condition matched" — function is a no-op.

    Works with both flat and per-light formats. Lights that are off
    pass through untouched.
    """
    if condition is None:
        return state

    if _is_per_light_dict(state):
        return {
            lid: adjust_single_light(ls, condition) if ls.get("on", True) else ls
            for lid, ls in state.items()
        }
    return adjust_single_light(state, condition)


# ---------------------------------------------------------------------------
# Functional-mode weather brightness — opposite sign from apply_weather_adjust
# ---------------------------------------------------------------------------
# Mood-mode weather_adjust DIMS lights on rain/clouds (gloomy mood). For
# functional modes (gaming) the ambient daylight drop is the problem, not
# the mood — desk lamps need MORE output when natural light fades. Day-only
# because evening/night ambient is artificial and weather is irrelevant.
# Composes multiplicatively on top of apply_lux_multiplier so the two
# compensations stack mildly (rain near-baseline lux: ~1.03 × 1.15 ≈ 1.18).

FUNCTIONAL_WEATHER_BRIGHTNESS_MODES = frozenset(("gaming",))

FUNCTIONAL_WEATHER_BRIGHTNESS: dict[str, float] = {
    "thunderstorm": 1.20,
    "rain":         1.15,
    "clouds":       1.10,
    "snow":         1.05,
}


def apply_functional_weather_brightness(
    state: dict[str, Any],
    mode: str,
    period: str,
    condition: Optional[str],
) -> dict[str, Any]:
    """Brighten functional-mode lights on dim-ambient weather.

    No-op outside ``FUNCTIONAL_WEATHER_BRIGHTNESS_MODES``, outside
    ``period == "day"``, or when ``condition`` is None / unmapped.
    """
    if mode not in FUNCTIONAL_WEATHER_BRIGHTNESS_MODES:
        return state
    if period != "day":
        return state
    if condition is None:
        return state
    mult = FUNCTIONAL_WEATHER_BRIGHTNESS.get(condition)
    if mult is None or mult == 1.0:
        return state

    if _is_per_light_dict(state):
        result: dict[str, Any] = {}
        for lid, ls in state.items():
            ls_copy = ls.copy()
            if ls_copy.get("on", True) and "bri" in ls_copy:
                ls_copy["bri"] = max(1, min(254, int(ls_copy["bri"] * mult)))
            result[lid] = ls_copy
        return result

    result = state.copy()
    if result.get("on", True) and "bri" in result:
        result["bri"] = max(1, min(254, int(result["bri"] * mult)))
    return result
