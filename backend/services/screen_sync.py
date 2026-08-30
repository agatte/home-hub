"""
Screen sync service — color receiver for bedroom lamps.

The capture loop lives in a desktop pc_agent (`screen_sync_agent.py`). This
service receives RGB colors via `POST /api/automation/screen-color`, smooths
them with an exponential moving average, and applies them to one or more
Hue lights. The mode gate (gaming / watching only) lives in the route
handler — by the time `apply_color` is called, the gate has already passed.

Multi-light support: generic gaming resolves each target from the canonical
period-specific gaming state and bounds it with the existing fixture cap;
screen samples only refresh ownership. Watching keeps independent per-light
EMA state and mirror dispatch (currently L2 + L5); per-light caps, sat boost,
and luma compensation differentiate its on-bridge state so the clear-housing
L5 doesn't blow out next to the diffused-shade L2. (Dual-region — L2 ← left
half, L5 ← right —
was tried and abandoned 2026-05-12 night for eye strain at close viewing
distance; see lighting-curator INDEX for the documented anti-pattern.)

`LaptopLoopbackCapture` is an opt-in escape hatch for the rare case of
plugging the laptop into a TV. It runs the same screen capture loop but
in-process on the laptop and POSTs to its own localhost endpoint, so it
goes through the same wire format as the desktop agent. Disabled by default.
"""
import asyncio
import colorsys
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.services.automation_constants import SCREEN_SYNC_FRESH_SECONDS
from backend.services.color_utils import (
    DEFAULT_LUMA_COMP,
    DEFAULT_SAT_BOOST,
    PER_LIGHT_LUMA_COMP,
    PER_LIGHT_SAT_BOOST,
    rgb_to_hue_hsb,
)
from backend.services.light_state_calculator import (
    get_functional_weather_multiplier,
    lux_to_multiplier,
    resolve_activity_state,
)

logger = logging.getLogger("home_hub.screen_sync")

# Throttle for screen_sync → event_logger writes (closes audit syncfight-3:
# synced colors otherwise bypass the logger and never reach light_adjustments /
# analytics). One row per light per interval so the ~2.5s capture cadence
# doesn't flood the table — ~720 rows/hr/light at 5s, negligible vs retention.
SCREEN_SYNC_LOG_INTERVAL_S = 5.0


# Per-(mode, light_id) max brightness clamps for the synced lamps.
# Gaming caps bound the canonical base for fixture safety; watching stays
# subtle so mirrored projected content doesn't wash the image.
# L5's clear housing reads ~1.3× brighter than L2's fabric shade, so its
# caps are stepped down to keep it in a peripheral role.
MODE_MAX_BRIGHTNESS: dict[tuple[str, str], int] = {
    ("gaming",   "2"): 240,
    ("watching", "2"):  80,
    ("gaming",   "5"):  75,   # Clear seeded-glass housing reads ~2× brighter
                              # than L2's fabric shade at the same numeric bri.
                              # Cap is now backed up by per-light luma
                              # compensation (see PER_LIGHT_LUMA_COMP below) —
                              # the cap handles peak amplitude, luma comp handles
                              # the hue-perception punch that cap alone can't fix.
                              # 60→75 2026-06-02 (curator): headroom for vivid
                              # blue frames to lift the accent in a blinds-closed
                              # day; 90 is the hard glare ceiling — do NOT exceed.
    ("watching", "5"):  50,
}
DEFAULT_MAX_BRIGHTNESS = 80
MIN_BRIGHTNESS = 15

# Time-period-specific overrides of MODE_MAX_BRIGHTNESS. When a `(mode, period,
# light_id)` key is present, it wins over the flat `(mode, light_id)` lookup.
# Day values fall through to the flat table (the caps above are tuned against
# bright daylight ambient). Evening/night/late_night drop progressively to
# stay proportional to the dimming room — see the
# gamingEveningBothLamps.JPEG anti-pattern photo in the curator INDEX for
# what time-period-unaware caps look like in practice.
MODE_MAX_BRIGHTNESS_PERIOD: dict[tuple[str, str, str], int] = {
    # L2 (fabric shade) — curator-proposed ratios ~1.2× the per-period static
    # baseline (150/140/110) give the sync headroom to pop on bright content
    # without becoming the room's dominant visual element.
    ("gaming", "evening",    "2"): 170,
    ("gaming", "night",      "2"): 125,
    ("gaming", "late_night", "2"):  95,
    # L5 (clear seeded glass) — Stage-2 2026-05-31 (curator agent a976374):
    # caps RAISED above the lowered static resting floor (90/75/65/50) so
    # screen-sync can LIFT L5 on vivid frames instead of dragging it below its
    # resting state (the prior 50/35/25 caps sat 2-3x UNDER the static base =
    # the "dim colors" complaint, audit syncfight-2). Rec.601 luma comp still
    # scales warm/green frames down, so the lift mainly benefits low-luma blue
    # gaming content. Evening cap (95) intentionally exceeds day (flat 60): an
    # accent should read MORE present in a dark room than in daylight.
    ("gaming", "evening",    "5"):  80,
    ("gaming", "night",      "5"):  55,
    ("gaming", "late_night", "5"):  35,
}

# Per-(mode, light_id) minimum brightness. Gaming stays visible even on
# dark scenes; watching allows dim bias lighting.
MODE_MIN_BRIGHTNESS: dict[tuple[str, str], int] = {
    # L2 (fabric shade) carries the ROOM-brightness load — it throws diffuse
    # light, unlike L5's clear point-source. 130→150 2026-06-02 (curator): the
    # single highest-value lever for the "bedroom dim while gaming" complaint.
    ("gaming", "2"): 150,
    ("gaming", "5"):  40,    # Lower than L5's static baseline so dark scenes
                             # can actually dim L5's visible bulb instead of
                             # holding it bright on a black frame. Paired with
                             # the perceptual luma compensation, this widens
                             # L5's usable dynamic range without raising the cap.
                             # 25→40 2026-06-02 (curator): lift the clear-pendant
                             # accent off "dim spark"; modest because raising a
                             # point source adds glare, not room light.
}

# Time-period overrides for floors — same pattern as the cap override table.
# Only late_night L2 is shipped today: the L2 cap collapses to 130 at
# late_night (matching the existing floor), so without a matching floor drop
# the dynamic range becomes a single point. 110 lets late-night dark scenes
# actually dim L2 toward its late_night static baseline.
# Desk-watching needs a small dark-frame floor so videos remain comfortable
# at the monitor without turning projector/bed watching into working mode.
MODE_ZONE_MIN_BRIGHTNESS: dict[tuple[str, str, str, str], int] = {
    ("watching", "desk", "night",      "2"): 30,
    ("watching", "desk", "late_night", "2"): 25,
    ("watching", "desk", "night",      "5"): 18,
    ("watching", "desk", "late_night", "5"): 14,
}

MODE_MIN_BRIGHTNESS_PERIOD: dict[tuple[str, str, str], int] = {
    ("gaming", "evening", "2"): 125,
    ("gaming", "night", "2"): 85,
    ("gaming", "late_night", "2"): 65,
    ("gaming", "evening", "5"): 35,
    ("gaming", "night", "5"): 28,
    ("gaming", "late_night", "5"): 20,
    # Day-specific floors 2026-06-02 (curator): blinds-closed "day" is the dim
    # complaint case the day-only caps wrongly assume is bright. L2 carries the
    # room light; L5 gets a slightly-more-present accent than a bright-sun day.
    ("gaming", "day", "2"): 150,
    ("gaming", "day", "5"): 45,
}

# PER_LIGHT_SAT_BOOST, PER_LIGHT_LUMA_COMP, and the underlying conversion
# now live in ``color_utils`` so the LoL champion color service shares the
# same tuning. The imports at the top of this module pull them in.

# Zone- and posture-aware brightness overrides, keyed by light_id so each
# lamp can have its own projector-safe cap when reclining in bed.
# Lookup prefers the most specific match: (mode, zone, posture, light_id) →
# (mode, zone, light_id) → MODE_MAX_BRIGHTNESS[(mode, light_id)] → default.
#
# DORMANT NOTE (2026-05-27 Latitude→living-room move): the bed-zone entries
# below (("watching","bed","reclined",…) and ("watching","bed","upright",…))
# are unreachable now — no camera produces zone="bed". The watching-at-desk
# entry (("watching","desk","2")) still fires via the desktop pc_agent's
# zone="desk" emission (Phase 1). The bed entries are kept (not deleted) for
# revival if bed-zone detection is later added via the desktop's wide FoV.
MODE_ZONE_MAX_BRIGHTNESS: dict[tuple[str, ...], int] = {
    ("watching", "desk", "day",        "2"): 180,
    ("watching", "desk", "evening",    "2"): 140,
    ("watching", "desk", "night",      "2"): 110,
    ("watching", "desk", "late_night", "2"):  80,
    ("watching", "desk",            "2"): 120,
    ("watching", "bed", "reclined", "2"):  25,
    ("watching", "bed", "upright",  "2"):  60,
    ("watching", "bed", "reclined", "5"):  20,
    ("watching", "bed", "upright",  "5"):  50,
}


# ---------------------------------------------------------------------------
# Rust profile — luma-driven brightness on a fixed ember color
# ---------------------------------------------------------------------------
# The Rust gaming profile holds a fixed warm ember on L2 and drives its
# BRIGHTNESS from the screen's whole-frame luminance, so the room dims when
# Rust goes dark (deliberately pitch-black nights) and lifts on bright day
# scenes. Color is intentionally NOT screen-driven — Rust has no coherent
# ambient color, so the dominant-color picker latched onto on-screen noise.
#
# Ember hue/sat are kept in lock-step with GAME_LIGHT_PROFILES["rust"] L2 in
# light_state_calculator.py so the resting engine base and the synced color
# match (no hue jump when sync starts/stops).
RUST_EMBER_HUE = 6000
RUST_EMBER_SAT = 200

# Per-light, per-period (floor, cap) brightness envelope under the Rust profile.
# "Dim hard at night" (user choice 2026-06-08): pitch-black Rust drops the lamp
# to its floor; a bright daytime scene lifts it toward the cap. Floors step down
# through the evening so a dark scene at midnight is genuinely dim.
#
# BOTH bedroom lamps are luma-driven (2026-06-08 live fix): L5 was originally a
# *static* ember spark, but live it towered over an L2 that dims with the screen
# (the curator-predicted glare-pop). Making L5 track luma at a subordinate
# envelope (~50-55% of L2) keeps the two proportional — L5 dims alongside L2 and
# never becomes the brightest desk element. L5's clear seeded-glass housing
# reads sharper than L2's fabric shade, so its caps stay well below L2's.
RUST_BRI_ENVELOPE: dict[str, dict[str, tuple[int, int]]] = {
    # evening/night/late_night lifted ~10-15% on 2026-06-08 ("a tad dim" at
    # 9:45pm live feedback) — eases the floor+cap without abandoning the
    # dim-hard-at-night intent. Day untouched (already bright).
    "2": {  # L2 — diffuse fabric shade, the room-light primary
        "day":        (60, 200),
        "evening":    (50, 182),
        "night":      (43, 162),
        "late_night": (27, 120),
    },
    "5": {  # L5 — clear-housing accent, subordinate, dims with L2
        "day":        (32, 105),
        "evening":    (29, 97),
        "night":      (23, 84),
        "late_night": (16, 58),
    },
}
# Screen-luma input window mapped onto the envelope. Rust daytime scenes read
# ~100-150; the pitch-black night floor is ~5-15. Below RUST_LUMA_DARK → floor,
# above RUST_LUMA_BRIGHT → cap, linear between.
RUST_LUMA_DARK = 12
RUST_LUMA_BRIGHT = 135


class ScreenSyncService:
    """
    Receives RGB colors from any source and applies them to one or more Hue lights.

    The class holds per-light smoothing state in dicts keyed by light id, so
    successive `apply_color` calls for a given light produce smooth
    transitions without sharing EMA state across lamps. Status fields
    (`last_color_at`, `last_source`) report the most recent write across all
    targets and back the `/api/automation/screen-sync/status` endpoint.
    """

    def __init__(
        self,
        hue_service,
        target_light_ids: Optional[list[str]] = None,
        transition_boundary=None,
    ) -> None:
        self._hue = hue_service
        self._transition_boundary = transition_boundary
        targets = list(target_light_ids) if target_light_ids else ["2"]
        if not targets:
            targets = ["2"]
        self._targets: list[str] = targets
        # First target is the legacy "primary" — exposed for callers
        # (automation_engine, telemetry) that still read a single id.
        self._target_light = self._targets[0]

        # Smoothing — per-light EMA state. α=0.4 absorbs 40% of each new
        # target per frame; with 2.5s captures, ~75% convergence after 5s
        # (3 frames). Higher reacts faster to scene cuts but lets per-frame
        # picker noise through more.
        self._smoothing_alpha: float = 0.4
        self._last_hue: dict[str, float] = {lid: 0.0 for lid in self._targets}
        self._last_sat: dict[str, float] = {lid: 0.0 for lid in self._targets}
        self._last_bri: dict[str, float] = {lid: 0.0 for lid in self._targets}
        self._last_sent_state: dict[str, dict[str, int]] = {}

        # Status tracking — retain the legacy global most-recent write plus
        # per-source and per-light timestamps. The target list is a capability
        # set (desktop uses L2/L5; laptop can use L1/L3/L4), so bridge ownership
        # must be derived from the lights that actually received fresh frames.
        self._last_color_at: Optional[datetime] = None
        self._last_source: Optional[str] = None
        self._last_color_at_by_source: dict[str, datetime] = {}
        self._last_color_at_by_light: dict[str, datetime] = {}
        # Rejected non-media foreground frames refresh a short ownership hold.
        # This lets sticky Watching preserve the last valid media color without
        # pretending a rejected webpage frame was an accepted screen color.
        # Source+light keys keep desktop bedroom ownership isolated from laptop
        # living-room sync. The same freshness window provides agent-failure
        # recovery: if hold refreshes stop, normal automation reclaims the lamp.
        self._hold_refreshed_at: dict[tuple[str, str], datetime] = {}

        # Runtime overrides for specific (mode, zone, posture, light_id) caps —
        # settings page writes through this dict, persisted in app_settings.
        self._cap_overrides: dict[tuple[str, str, str, str], int] = {}

        # Event logger for throttled screen_sync write logging (syncfight-3).
        # Wired post-construction via set_event_logger (the EventLogger is
        # built later in bootstrap). None => no logging. _last_log_at throttles
        # to one row per light per SCREEN_SYNC_LOG_INTERVAL_S.
        self._event_logger = None
        self._last_log_at: dict[str, datetime] = {}

        # Runtime-tunable Rust profile knobs (seeded from the module defaults).
        # Live-adjustable via PUT /api/automation/rust-lighting + persisted in
        # app_settings, so "a tad dimmer/brighter" tweaks apply instantly with
        # no redeploy. apply_rust_brightness reads these, not the constants.
        self._rust_envelope: dict[str, dict[str, list[int]]] = {
            lid: {period: list(fc) for period, fc in periods.items()}
            for lid, periods in RUST_BRI_ENVELOPE.items()
        }
        self._rust_ember_hue: int = RUST_EMBER_HUE
        self._rust_ember_sat: int = RUST_EMBER_SAT
        self._rust_luma_dark: int = RUST_LUMA_DARK
        self._rust_luma_bright: int = RUST_LUMA_BRIGHT

    def set_cap_override(
        self,
        mode: str,
        zone: str,
        posture: str,
        cap: int,
        light_id: str = "2",
    ) -> None:
        """Set a runtime override for a (mode, zone, posture, light_id) cap.

        light_id defaults to "2" so existing watching-posture slider call
        sites (which target the projector-safe L2 cap) keep working unchanged.
        """
        self._cap_overrides[(mode, zone, posture, light_id)] = int(cap)

    def get_cap(
        self,
        mode: str,
        light_id: str,
        zone: Optional[str],
        posture: Optional[str],
        period: Optional[str] = None,
        lux_multiplier: float = 1.0,
        weather_condition: Optional[str] = None,
    ) -> int:
        """Resolve the screen-sync cap for the given context.

        Lookup order: runtime override 4-tuple → MODE_ZONE_MAX_BRIGHTNESS
        4-tuple (mode, zone, posture, light_id) → MODE_ZONE_MAX_BRIGHTNESS
        4-tuple (mode, zone, period, light_id) → MODE_ZONE_MAX_BRIGHTNESS
        3-tuple (mode, zone, light_id) → MODE_MAX_BRIGHTNESS_PERIOD
        (mode, period, light_id) → MODE_MAX_BRIGHTNESS[(mode, light_id)]
        → default.

        Zone/posture overrides take precedence over the time-period table
        because they reflect specific physical setups (projector-in-bed) that
        should hard-cap regardless of time of day.

        Ambient envelope lift: for ``mode`` in ``_AMBIENT_LIFT_MODES``
        (gaming + watching) during day/evening, the resolved cap is scaled by
        ``lux_multiplier * get_functional_weather_multiplier(mode, period,
        weather_condition)`` (cloudy 1.10×, rain 1.15×, etc.) — see
        ``_scale_for_ambient``. L5 is excluded from the lift (glare-prone clear
        housing keeps its static per-period caps); only L2's fabric shade,
        the room-light lever, tracks ambient.
        """
        if zone is not None and posture is not None:
            override = self._cap_overrides.get((mode, zone, posture, light_id))
            if override is not None:
                return self._scale_for_ambient(
                    override, mode, period, lux_multiplier, weather_condition, light_id,
                )
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, posture, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition, light_id,
                )
        if zone is not None and period is not None:
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, period, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition, light_id,
                )
        if zone is not None:
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition, light_id,
                )
        if period is not None:
            cap = MODE_MAX_BRIGHTNESS_PERIOD.get((mode, period, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition, light_id,
                )
        base = MODE_MAX_BRIGHTNESS.get((mode, light_id), DEFAULT_MAX_BRIGHTNESS)
        return self._scale_for_ambient(
            base, mode, period, lux_multiplier, weather_condition, light_id,
        )

    def get_floor(
        self,
        mode: str,
        light_id: str,
        zone: Optional[str] = None,
        posture: Optional[str] = None,
        period: Optional[str] = None,
        lux_multiplier: float = 1.0,
        weather_condition: Optional[str] = None,
    ) -> int:
        """Resolve the brightness floor for the given context.

        Lookup order: MODE_MIN_BRIGHTNESS_PERIOD (mode, period, light_id) →
        MODE_MIN_BRIGHTNESS (mode, light_id) → MIN_BRIGHTNESS default.

        Subject to the same ambient lift as ``get_cap`` (gaming + watching,
        day/evening, L2 only) — the floor lifting is the main eye-comfort
        payoff: dark content no longer drags L2 down to fabric-shade dimness
        when the bedroom itself is dark.
        """
        if zone is not None and period is not None:
            floor = MODE_ZONE_MIN_BRIGHTNESS.get((mode, zone, period, light_id))
            if floor is not None:
                return self._scale_for_ambient(
                    floor, mode, period, lux_multiplier, weather_condition,
                    light_id,
                )
        if period is not None:
            floor = MODE_MIN_BRIGHTNESS_PERIOD.get((mode, period, light_id))
            if floor is not None:
                return self._scale_for_ambient(
                    floor, mode, period, lux_multiplier, weather_condition,
                    light_id,
                )
        base = MODE_MIN_BRIGHTNESS.get((mode, light_id), MIN_BRIGHTNESS)
        return self._scale_for_ambient(
            base, mode, period, lux_multiplier, weather_condition, light_id,
        )

    # Modes whose screen-sync envelope tracks ambient lux + weather. Both
    # gaming and watching run in the dim bedroom and the user's stated intent
    # is "brighter when the room is dark" during day/evening gloom. Night and
    # late_night deliberately stay on their darker envelopes even when the
    # bedroom lux sensor reports a dark room.
    _AMBIENT_LIFT_MODES: frozenset[str] = frozenset({"gaming", "watching"})

    # Lights EXCLUDED from the ambient lift. L5 (clear seeded-glass pendant) is
    # a glare-prone point source, NOT a room-light lever — that's L2's job (the
    # diffuse fabric shade). Lifting L5 adds glare, not room light, so it keeps
    # its deliberate per-period caps (evening 95 / night 80) untouched. This
    # also closes a latent day-path gap: the L5 day cap was raised 60→75 on
    # 2026-06-02, so the old 75 × 1.40 = 105 lift exceeded L5's 90 glare ceiling
    # (build 4adce9f). See [[feedback_clear_housing_perceptual_luma]] + this
    # session's "L2 carries the room light" curator reframe.
    _AMBIENT_LIFT_EXCLUDE_LIGHTS: frozenset[str] = frozenset({"5"})
    _AMBIENT_LIFT_PERIODS: frozenset[str] = frozenset({"day", "evening"})

    # Worst-case stacked multiplier ceiling: LUX_CURVE peaks at 1.30 (20 lux
    # baseline-shifted) and FUNCTIONAL_WEATHER_BRIGHTNESS peaks at 1.20
    # (thunderstorm), so naive stacking allows 1.56×. 1.40 bounds the combined
    # lift. NOTE: 1.40 was originally derived from L5's clear-housing glare
    # threshold, but L5 is now excluded from the lift entirely (above), so this
    # ceiling is retained purely as a conservative over-bright-room bound on L2
    # (fabric shade, no point-source glare) — it is no longer a glare guard.
    _AMBIENT_LIFT_CEILING: float = 1.40

    @staticmethod
    def _scale_for_ambient(
        value: int,
        mode: str,
        period: Optional[str],
        lux_multiplier: float,
        weather_condition: Optional[str],
        light_id: str = "2",
    ) -> int:
        """Apply ambient lux × functional-weather scaling to a cap/floor.

        Gated to ``_AMBIENT_LIFT_MODES`` (gaming + watching) and to lamps NOT
        in ``_AMBIENT_LIFT_EXCLUDE_LIGHTS`` (L5 rides its static per-period
        caps to avoid point-source glare). Only day/evening are eligible: at night
        the mode-specific darker envelope wins even when the bedroom sensor
        reads dark. The combined multiplier is capped at
        ``_AMBIENT_LIFT_CEILING``; final value clamped
        to [1, 254].
        """
        if mode not in ScreenSyncService._AMBIENT_LIFT_MODES:
            return value
        if light_id in ScreenSyncService._AMBIENT_LIFT_EXCLUDE_LIGHTS:
            return value
        if period not in ScreenSyncService._AMBIENT_LIFT_PERIODS:
            return value
        weather_mult = get_functional_weather_multiplier(
            mode, period, weather_condition,
        )
        combined = min(
            ScreenSyncService._AMBIENT_LIFT_CEILING,
            lux_multiplier * weather_mult,
        )
        scaled = int(value * combined)
        return max(1, min(254, scaled))

    @property
    def last_color_at(self) -> Optional[datetime]:
        return self._last_color_at

    @property
    def last_source(self) -> Optional[str]:
        return self._last_source

    @property
    def last_color_at_by_source(self) -> dict[str, datetime]:
        """Most recent accepted screen-sync frame for each reporting source."""
        return dict(self._last_color_at_by_source)

    @property
    def last_color_at_by_light(self) -> dict[str, datetime]:
        """Most recent accepted screen-sync frame for each managed light."""
        return dict(self._last_color_at_by_light)

    def _record_source_write(self, source: str, light_id: str) -> None:
        observed_at = datetime.now(timezone.utc)
        self._last_color_at = observed_at
        self._last_source = source
        self._last_color_at_by_source[source] = observed_at
        self._last_color_at_by_light[light_id] = observed_at

    @property
    def target_light(self) -> str:
        """The primary (first) Hue light id this service writes to.

        Kept for back-compat with single-light callers; new code should use
        `target_lights` to iterate over the full target list.
        """
        return self._target_light

    @property
    def target_lights(self) -> list[str]:
        """All Hue light ids this service can write to."""
        return list(self._targets)

    def refresh_watching_hold(self, source: str, light_ids: list[str]) -> None:
        """Keep last valid media targets authoritative during sticky Watching.

        Only lights with an acknowledged screen-sync target can be held. The
        caller refreshes this stamp on each rejected non-media foreground frame;
        if the desktop agent disappears, the ordinary freshness timeout releases
        ownership automatically.
        """
        now = datetime.now(timezone.utc)
        for light_id in light_ids:
            if light_id in self._targets and light_id in self._last_sent_state:
                self._hold_refreshed_at[(source, light_id)] = now

    def clear_watching_hold(
        self, source: str, light_ids: Optional[list[str]] = None,
    ) -> None:
        """Release source-scoped sticky-Watching ownership holds."""
        selected = set(light_ids) if light_ids is not None else None
        for key in list(self._hold_refreshed_at):
            held_source, light_id = key
            if held_source == source and (selected is None or light_id in selected):
                self._hold_refreshed_at.pop(key, None)

    def held_owned_light_ids(self) -> set[str]:
        """Lights whose non-media hold has been refreshed recently."""
        now = datetime.now(timezone.utc)
        owned: set[str] = set()
        for key, refreshed_at in list(self._hold_refreshed_at.items()):
            age = (now - refreshed_at).total_seconds()
            if age < -2.0 or age >= SCREEN_SYNC_FRESH_SECONDS:
                self._hold_refreshed_at.pop(key, None)
                continue
            _source, light_id = key
            if light_id in self._last_sent_state:
                owned.add(light_id)
        return owned

    def fresh_owned_light_ids(self) -> set[str]:
        """Lights actively owned by fresh frames or refreshed media holds."""
        now = datetime.now(timezone.utc)
        fresh: set[str] = set()

        # Preserve per-light freshness without letting a desktop L2/L5 frame
        # refresh laptop-capable L1/L3/L4 ownership.
        last_global = self._last_color_at
        if last_global is not None:
            global_age = (now - last_global).total_seconds()
            if -2.0 <= global_age < SCREEN_SYNC_FRESH_SECONDS:
                fresh = {
                    light_id
                    for light_id, observed_at in self._last_color_at_by_light.items()
                    if -2.0 <= (now - observed_at).total_seconds() < SCREEN_SYNC_FRESH_SECONDS
                }

        return fresh | self.held_owned_light_ids()

    def invalidate_sent_state(self, light_ids: list[str]) -> None:
        """Forget cached bridge state for the selected managed lights.

        Normal automation and screen sync write the Hue bridge through
        separate paths. When automation changes a sync-capable lamp, the
        cached screen-sync target no longer proves what is physically on the
        bridge. Dropping only those cache entries makes the next valid frame
        reconcile each changed lamp once; later identical frames deduplicate
        normally. EMA state and ownership timestamps are intentionally left
        untouched.
        """
        for light_id in light_ids:
            if light_id in self._targets:
                self._last_sent_state.pop(light_id, None)

    def authoritative_state(self, light_id: str) -> Optional[dict[str, Any]]:
        """Return the last screen-sync target currently owning a lamp."""
        state = self._last_sent_state.get(light_id)
        return {"on": True, **state} if state is not None else None

    def fresh_authoritative_state(self, light_id: str) -> Optional[dict[str, Any]]:
        """Return a fresh acknowledged target without applying a mode gate.

        This is for transition safety only: a mode change may close the route
        gate before an old, still-fresh screen-sync target has been safely
        re-established and its effect released.
        """
        if light_id not in self.fresh_owned_light_ids():
            return None
        return self.authoritative_state(light_id)

    async def _set_light_serialized(self, light_id: str, state: dict) -> bool:
        """Serialize screen writes only while an effect transition is active."""
        if (
            self._transition_boundary is None
            or self._transition_boundary.held_by_current_task
        ):
            return await self._hue.set_light(light_id, state)
        async with self._transition_boundary.serialized():
            return await self._hue.set_light(light_id, state)

    def prime_from_mode_state(
        self,
        mode: str,
        period: Optional[str],
        states: dict[str, dict[str, Any]],
    ) -> None:
        """Seed EMA state from the mode target before screen frames resume.

        Mode changes already put the intended night/evening baseline on the
        bridge. Seeding the sync EMA from that baseline prevents the next
        screen frame from easing out of stale prior-mode values, which reads as
        a random brightness jump before settling back.
        """
        if mode not in {"gaming", "watching"}:
            return
        if period not in {"evening", "night", "late_night"}:
            return
        for light_id in self._targets:
            target = states.get(light_id)
            if not isinstance(target, dict):
                continue
            if target.get("on") is False:
                self._last_bri[light_id] = 0.0
                continue
            if "bri" in target:
                self._last_bri[light_id] = float(target["bri"])
            if "hue" in target:
                self._last_hue[light_id] = float(target["hue"])
            if "sat" in target:
                self._last_sat[light_id] = float(target["sat"])

    @staticmethod
    def _smoothing_alpha_for(mode: str, period: Optional[str]) -> float:
        if mode == "watching" and period in {"night", "late_night"}:
            return 0.35
        if mode == "gaming" and period == "late_night":
            return 0.25
        return 0.4

    @staticmethod
    def _transitiontime_for(mode: str, period: Optional[str]) -> int:
        if mode == "watching" and period in {"night", "late_night"}:
            return 15
        if mode == "gaming" and period == "late_night":
            return 30
        return 20

    @staticmethod
    def _max_brightness_step(mode: str, period: Optional[str]) -> Optional[int]:
        if mode == "watching" and period in {"night", "late_night"}:
            return 14
        if mode == "gaming" and period == "late_night":
            return 22
        return None

    @staticmethod
    def _within_deadband(
        previous: Optional[dict[str, int]],
        hue: int,
        sat: int,
        bri: int,
        mode: str,
        period: Optional[str],
    ) -> bool:
        if previous is None:
            return False
        if mode != "watching" or period not in {"night", "late_night"}:
            return False
        hue_delta = abs(hue - previous.get("hue", hue))
        hue_delta = min(hue_delta, 65535 - hue_delta)
        return (
            hue_delta < 700
            and abs(sat - previous.get("sat", sat)) < 4
            and abs(bri - previous.get("bri", bri)) < 2
        )

    async def apply_color(
        self,
        light_id: str,
        r: int,
        g: int,
        b: int,
        mode: str,
        source: str = "desktop",
        zone: Optional[str] = None,
        posture: Optional[str] = None,
        period: Optional[str] = None,
        lux_multiplier: float = 1.0,
        weather_condition: Optional[str] = None,
    ) -> None:
        """
        Apply a screen sample to one of the managed bedroom lamps.

        Args:
            light_id: Target Hue light id (e.g. "2" or "5"). Must be in
                ``target_lights`` or the call is a no-op.
            r, g, b: 0-255 RGB values from a screen capture. Generic gaming
                ignores them; watching retains dynamic RGB translation.
            mode: Current automation mode — used to look up the brightness clamp.
            source: "desktop" or "laptop" — recorded for status reporting only.
            zone: Optional camera-detected zone ("desk" | "bed").
            posture: Optional camera-detected posture ("upright" | "reclined").
            period: Optional time period ("day" | "evening" | "night" |
                "late_night"). When provided, ``MODE_MAX_BRIGHTNESS_PERIOD``
                and ``MODE_MIN_BRIGHTNESS_PERIOD`` are checked before the
                time-agnostic fallbacks so the lamp's bri envelope tracks
                the room's ambient.
            lux_multiplier: Camera-derived brightness multiplier (from
                ``lux_to_multiplier``). Consumed for gaming + watching across
                day/evening (L2 only — L5 is excluded); lifts the cap+floor
                envelope on dim ambient. Defaults to 1.0 (no lift).
            weather_condition: Classified weather string ("clouds" / "rain"
                / "thunderstorm" / "snow" / None). Same gate as
                ``lux_multiplier``; stacks multiplicatively with it to lift
                the envelope on overcast conditions.
        """
        if light_id not in self._targets:
            return
        if mode == "gaming":
            await self._apply_generic_gaming_state(
                light_id,
                source=source,
                zone=zone,
                posture=posture,
                period=period,
            )
            return
        max_bri = self.get_cap(
            mode, light_id, zone, posture, period,
            lux_multiplier, weather_condition,
        )
        min_bri = self.get_floor(
            mode, light_id, zone=zone, posture=posture, period=period,
            lux_multiplier=lux_multiplier, weather_condition=weather_condition,
        )
        sat_boost = PER_LIGHT_SAT_BOOST.get(light_id, DEFAULT_SAT_BOOST)
        luma_comp = PER_LIGHT_LUMA_COMP.get(light_id, DEFAULT_LUMA_COMP)
        h, s, br = rgb_to_hue_hsb(
            (r, g, b), max_bri, min_bri, sat_boost, luma_comp
        )
        max_step = self._max_brightness_step(mode, period)
        last_bri = self._last_bri.get(light_id, 0.0)
        if max_step is not None and last_bri > 0.0:
            br = max(last_bri - max_step, min(last_bri + max_step, br))
        sh, ss, sb = self._smooth(
            light_id, h, s, br, alpha=self._smoothing_alpha_for(mode, period),
        )
        ih, isat, ibri = int(sh), int(ss), int(sb)
        last_sent = self._last_sent_state.get(light_id)
        if (
            abs(ibri - int(br)) < 2
            and last_sent is not None
            and abs(last_sent.get("bri", ibri) - int(br)) < 2
            and self._within_deadband(last_sent, ih, isat, ibri, mode, period)
        ):
            self._record_source_write(source, light_id)
            return
        success = await self._set_light_serialized(light_id, {
            "on": True,
            "hue": ih,
            "sat": isat,
            "bri": ibri,
            "transitiontime": self._transitiontime_for(mode, period),
        })
        if success is not True:
            return
        self._last_sent_state[light_id] = {"hue": ih, "sat": isat, "bri": ibri}
        self._record_source_write(source, light_id)
        await self._maybe_log_adjustment(light_id, ih, isat, ibri, mode)

    async def _apply_generic_gaming_state(
        self,
        light_id: str,
        *,
        source: str,
        zone: Optional[str],
        posture: Optional[str],
        period: Optional[str],
    ) -> None:
        """Hold generic gaming on its canonical CT/HSB state and safe cap."""
        mode_state = resolve_activity_state("gaming", period)
        base = mode_state.get(light_id)
        if not isinstance(base, dict):
            return

        hue = base.get("hue")
        sat = base.get("sat")
        ct = base.get("ct")
        bri = base.get("bri")
        if bri is None:
            return

        cap = self.get_cap(
            "gaming",
            light_id,
            zone,
            posture,
            period,
            1.0,
            None,
        )
        if ct is not None:
            # Generic Gaming/day uses neutral CT. Keep the bridge payload
            # in one color space; evening/night remain canonical HSB.
            stable = {
                "ct": int(ct),
                "bri": min(int(bri), cap),
            }
        elif hue is not None and sat is not None:
            stable = {
                "hue": int(hue),
                "sat": int(sat),
                "bri": min(int(bri), cap),
            }
        else:
            return

        if "hue" in stable:
            self._last_hue[light_id] = float(stable["hue"])
        if "sat" in stable:
            self._last_sat[light_id] = float(stable["sat"])
        self._last_bri[light_id] = float(stable["bri"])
        if self._last_sent_state.get(light_id) == stable:
            self._record_source_write(source, light_id)
            return

        success = await self._set_light_serialized(
            light_id,
            {
                "on": True,
                **stable,
                "transitiontime": self._transitiontime_for("gaming", period),
            },
        )
        if success is not True:
            return
        self._last_sent_state[light_id] = stable
        self._record_source_write(source, light_id)
        await self._maybe_log_adjustment(
            light_id,
            stable.get("hue"),
            stable.get("sat"),
            stable["bri"],
            "gaming",
            ct=stable.get("ct"),
        )

    def _smooth(
        self, light_id: str, h: float, s: float, b: float,
        alpha: Optional[float] = None,
    ) -> tuple[float, float, float]:
        """Apply EMA smoothing with hue-wrap handling for the given light."""
        if alpha is None:
            alpha = self._smoothing_alpha
        last_h = self._last_hue.get(light_id, 0.0)
        last_s = self._last_sat.get(light_id, 0.0)
        last_b = self._last_bri.get(light_id, 0.0)

        # Hue wraps at 65535 → 0; pick the shorter path
        hue_diff = h - last_h
        if abs(hue_diff) > 32767:
            if hue_diff > 0:
                hue_diff -= 65535
            else:
                hue_diff += 65535
        smoothed_h = (last_h + alpha * hue_diff) % 65535

        smoothed_s = last_s + alpha * (s - last_s)
        smoothed_b = last_b + alpha * (b - last_b)

        self._last_hue[light_id] = smoothed_h
        self._last_sat[light_id] = smoothed_s
        self._last_bri[light_id] = smoothed_b

        return (smoothed_h, smoothed_s, smoothed_b)

    def set_event_logger(self, event_logger) -> None:
        """Wire the EventLogger so synced writes get recorded (throttled) to
        light_adjustments with trigger='screen_sync'. Called post-construction
        in bootstrap because the EventLogger is built after this service.
        ``None`` (the default) disables logging — keeps unit tests and the
        laptop-loopback path working without an event logger."""
        self._event_logger = event_logger

    async def _maybe_log_adjustment(
        self,
        light_id: str,
        hue: Optional[int],
        sat: Optional[int],
        bri: int,
        mode: str,
        trigger: str = "screen_sync",
        *,
        ct: Optional[int] = None,
    ) -> None:
        """Throttled event-log of a synced bridge write (closes syncfight-3).

        ``apply_color`` writes the bridge directly, bypassing the engine's
        event logger, so without this the synced targets never reach
        ``light_adjustments`` / analytics. Throttled to one row per light per
        ``SCREEN_SYNC_LOG_INTERVAL_S`` so the ~2.5s capture cadence doesn't
        flood the table. HSB writes record hue/sat; canonical CT writes record
        ct instead. ``trigger`` distinguishes the color path (``screen_sync``)
        from the Rust luma-brightness path (``rust_brightness_sync``) in
        analytics. No-op when no event logger is wired."""
        if self._event_logger is None:
            return
        now = datetime.now(timezone.utc)
        last = self._last_log_at.get(light_id)
        if last is not None and (now - last).total_seconds() < SCREEN_SYNC_LOG_INTERVAL_S:
            return
        self._last_log_at[light_id] = now
        await self._event_logger.log_light_adjustment(
            light_id=light_id,
            hue_after=hue,
            sat_after=sat,
            ct_after=ct,
            bri_after=bri,
            mode_at_time=mode,
            trigger=trigger,
        )

    def last_applied_bri(self, light_id: str) -> float:
        """Last smoothed brightness applied to ``light_id`` (RustEventService's
        flinch borrows this as its dip baseline). Mid-value before first frame."""
        return self._last_bri.get(light_id, 100.0)

    async def apply_rust_brightness(
        self,
        light_id: str,
        luma: int,
        period: Optional[str] = None,
        source: str = "desktop",
        tint: Optional[tuple[int, int, float]] = None,
    ) -> None:
        """Drive a lamp's BRIGHTNESS from screen luma, holding a fixed ember color.

        The Rust profile's L2 path. Instead of mirroring the (chaotic)
        on-screen color, hold the ember color and map the whole-frame luminance
        onto the period's (floor, cap) envelope so the lamp dims when Rust goes
        dark and lifts on bright scenes. Reads the runtime-tunable instance
        knobs (``_rust_envelope`` / ``_rust_ember_*`` / ``_rust_luma_*``),
        seeded from the module defaults and live-adjustable via
        ``PUT /api/automation/rust-lighting``. EMA smoothing reuses the per-light
        state — hue/sat are constant, so only ``bri`` moves. Deliberately NO
        ambient lux lift: brightness is screen-driven, and the lux feedback loop
        (lamp brightens room → webcam reads brighter → lifts the cap) would
        fight the luma signal.

        Args:
            light_id: Target lamp; no-op if not in ``target_lights``.
            luma: Whole-frame brightness 0-255 (Rec.601) from the capture agent.
            period: Time period for the envelope lookup; falls back to night.
            source: Reporting source, recorded for status only.
            tint: Optional ``(hue, sat, bri_factor)`` for the Rust under-fire
                danger glow — replaces the ember hue/sat and scales the target
                brightness, while the lamp still rides the luma envelope (so the
                glow tracks scene brightness, just red-shifted). None = ember.
        """
        if light_id not in self._targets:
            return
        light_env = self._rust_envelope.get(light_id, self._rust_envelope["2"])
        floor, cap = light_env.get(period or "night", light_env["night"])
        span = max(1, self._rust_luma_bright - self._rust_luma_dark)
        frac = max(0.0, min(1.0, (luma - self._rust_luma_dark) / span))
        target_bri = floor + (cap - floor) * frac
        if tint is not None:
            hue, sat, bri_factor = tint
            target_bri *= bri_factor
        else:
            hue, sat = self._rust_ember_hue, self._rust_ember_sat
        sh, ss, sb = self._smooth(light_id, float(hue), float(sat), target_bri)
        sent = {
            "on": True,
            "hue": int(sh),
            "sat": int(ss),
            "bri": int(sb),
            "transitiontime": 20,  # 2s — smooth brightness glide, no flicker
        }
        success = await self._set_light_serialized(light_id, sent)
        if success is not True:
            return
        self._last_sent_state[light_id] = {
            "hue": int(sh), "sat": int(ss), "bri": int(sb),
        }
        self._record_source_write(source, light_id)
        await self._maybe_log_adjustment(
            light_id, int(sh), int(ss), int(sb), "gaming",
            trigger="rust_brightness_sync",
        )

    # ------------------------------------------------------------------
    # Runtime Rust-profile tuning (no-redeploy knob)
    # ------------------------------------------------------------------

    def get_rust_config(self) -> dict:
        """Return the live Rust luma-brightness config as a JSON-safe dict.

        Shape: ``{"envelope": {light: {period: [floor, cap]}}, "ember":
        {"hue", "sat"}, "luma": {"dark", "bright"}}``. Backs
        ``GET /api/automation/rust-lighting`` and is the exact shape
        ``apply_rust_config`` accepts (full or partial)."""
        return {
            "envelope": {
                lid: {period: list(fc) for period, fc in periods.items()}
                for lid, periods in self._rust_envelope.items()
            },
            "ember": {"hue": self._rust_ember_hue, "sat": self._rust_ember_sat},
            "luma": {"dark": self._rust_luma_dark, "bright": self._rust_luma_bright},
        }

    def apply_rust_config(self, cfg: dict) -> dict:
        """Merge a (possibly partial) Rust config into the live knobs.

        Only the keys present in ``cfg`` are touched — e.g. PUT just
        ``{"envelope": {"2": {"night": [50, 170]}}}`` to bump L2's night
        range, leaving everything else. Values are validated/clamped:
        bri floor/cap to [1, 254] with floor ≤ cap, hue to [0, 65535], sat
        to [0, 254], luma dark/bright to [0, 255] with dark < bright. Unknown
        light ids / periods are ignored. Returns the full resolved config
        (``get_rust_config()``)."""
        if not isinstance(cfg, dict):
            return self.get_rust_config()

        env = cfg.get("envelope")
        if isinstance(env, dict):
            for lid, periods in env.items():
                if lid not in self._rust_envelope or not isinstance(periods, dict):
                    continue
                for period, fc in periods.items():
                    if period not in self._rust_envelope[lid]:
                        continue
                    if not isinstance(fc, (list, tuple)) or len(fc) != 2:
                        continue
                    floor = max(1, min(254, int(fc[0])))
                    cap = max(1, min(254, int(fc[1])))
                    if floor > cap:
                        floor, cap = cap, floor
                    self._rust_envelope[lid][period] = [floor, cap]

        ember = cfg.get("ember")
        if isinstance(ember, dict):
            if ember.get("hue") is not None:
                self._rust_ember_hue = max(0, min(65535, int(ember["hue"])))
            if ember.get("sat") is not None:
                self._rust_ember_sat = max(0, min(254, int(ember["sat"])))

        luma = cfg.get("luma")
        if isinstance(luma, dict):
            if luma.get("dark") is not None:
                self._rust_luma_dark = max(0, min(255, int(luma["dark"])))
            if luma.get("bright") is not None:
                self._rust_luma_bright = max(0, min(255, int(luma["bright"])))
            # Keep dark < bright so the span never collapses/inverts.
            if self._rust_luma_dark >= self._rust_luma_bright:
                self._rust_luma_bright = self._rust_luma_dark + 1

        return self.get_rust_config()


class LaptopLoopbackCapture:
    """
    Opt-in laptop screen capture for the TV-on-laptop escape hatch.

    Runs a screen capture loop in-process on the laptop and POSTs colors to
    `localhost:8000/api/automation/screen-color` — same wire format as the
    desktop pc_agent. Disabled by default; toggled via
    `PUT /api/automation/screen-sync/laptop-enabled`.
    """

    def __init__(self, server_port: int = 8000) -> None:
        self._url = f"http://localhost:{server_port}/api/automation/screen-color"
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._capture_interval: float = 2.5

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Laptop screen sync loopback started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Laptop screen sync loopback stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                regions = await asyncio.to_thread(_capture_dominant_colors)
                if regions:
                    body: dict[str, object] = {"source": "laptop"}
                    region_payload: dict[str, dict[str, int]] = {}
                    for name, rgb in regions.items():
                        region_payload[name] = {"r": rgb[0], "g": rgb[1], "b": rgb[2]}
                    body["regions"] = region_payload
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(self._url, json=body)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Laptop loopback error: {e}")
            await asyncio.sleep(self._capture_interval)


try:
    import numpy as np
    from sklearn.cluster import MiniBatchKMeans
    _HAS_KMEANS = True
except ImportError:
    _HAS_KMEANS = False


# Sticky-cluster state for the laptop-loopback picker — per region, so left
# and right halves bias toward their own previous winners independently.
# Same rationale as the desktop agent.
_STICKY_DISTANCE: float = 60.0
_STICKY_SCORE_MARGIN: float = 0.08
_STICKY_STALENESS_SEC: float = 10.0  # dropped from 30s — fresher resets after scene cuts


class _LoopbackPicker:
    """Per-region sticky-cluster state for the laptop loopback."""

    def __init__(self) -> None:
        # np.ndarray when populated; None before the first frame. Typed Any
        # because numpy is optional at import time.
        self.last_center: Any = None
        self.last_picked_at: float = 0.0


_LOOPBACK_PICKERS: dict[str, _LoopbackPicker] = {}


def _pick_dominant(pixels, picker: "_LoopbackPicker") -> Optional[tuple[int, int, int]]:
    """K-means dominant-color pick with per-region sticky bias.

    `picker` holds the prior winner so each region (left/right) keeps its
    own temporal stability instead of contending for one global slot.
    """
    if not _HAS_KMEANS or len(pixels) < 5:
        if not pixels:
            return None
        # Simple average fallback
        r_total = sum(p[0] for p in pixels)
        g_total = sum(p[1] for p in pixels)
        b_total = sum(p[2] for p in pixels)
        count = len(pixels)
        return (r_total // count, g_total // count, b_total // count)

    import time as _time

    pixel_array = np.array(pixels, dtype=np.float32)
    kmeans = MiniBatchKMeans(n_clusters=5, batch_size=100, n_init=1)  # type: ignore[arg-type]
    kmeans.fit(pixel_array)

    now = _time.time()
    prior = picker.last_center
    if prior is not None and now - picker.last_picked_at > _STICKY_STALENESS_SEC:
        prior = None

    scored = []
    for center in kmeans.cluster_centers_:
        r, g, b = center / 255.0
        _h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.2 and 0.15 < v < 0.85:
            score = s * 0.7 + (1.0 - abs(v - 0.5)) * 0.3
            scored.append((score, center))

    chosen = None
    if scored:
        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_center = scored[0]
        if prior is not None:
            prior_score, prior_center = min(
                scored, key=lambda t: float(np.linalg.norm(t[1] - prior))
            )
            if (
                float(np.linalg.norm(prior_center - prior)) < _STICKY_DISTANCE
                and best_score - prior_score < _STICKY_SCORE_MARGIN
            ):
                chosen = prior_center
        if chosen is None:
            chosen = best_center

    if chosen is None and prior is not None:
        distances = [float(np.linalg.norm(c - prior)) for c in kmeans.cluster_centers_]
        nearest_idx = int(np.argmin(distances))
        # Tightened from `* 2` (120 RGB units) to bare distance (60) — wider
        # window held stale warm colors when scenes dropped to gray.
        if distances[nearest_idx] < _STICKY_DISTANCE:
            chosen = kmeans.cluster_centers_[nearest_idx]

    if chosen is None:
        largest = int(np.argmax(np.bincount(kmeans.labels_)))
        chosen = kmeans.cluster_centers_[largest]

    picker.last_center = chosen
    picker.last_picked_at = now

    return (int(chosen[0]), int(chosen[1]), int(chosen[2]))


def _capture_dominant_colors() -> dict[str, tuple[int, int, int]]:
    """
    Capture the primary screen and extract dominant colors for left and right halves.

    Used by `LaptopLoopbackCapture`. The desktop agent has its own copy of
    this logic in `pc_agent/screen_sync_agent.py` — they're intentionally
    duplicated so the agent has zero backend dependencies.

    Returns a dict with "left" and "right" RGB triples. Skips entries where
    sampling failed (empty region).
    """
    try:
        import mss
    except ImportError:
        logger.error("mss not installed — cannot run laptop loopback")
        return {}

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)

            width = screenshot.width
            height = screenshot.height
            raw = screenshot.rgb

            # Downsample to ~50x30 grid per region — enough for K-means.
            step_x = max(1, width // 50)
            step_y = max(1, height // 30)

            # 4% dead zone down the middle so centered UI chrome (taskbars,
            # HUDs) doesn't pull both lamps to the same color.
            x_left_start  = int(width * 0.20)
            x_left_end    = int(width * 0.48)
            x_right_start = int(width * 0.52)
            x_right_end   = int(width * 0.80)
            y_start = int(height * 0.20)
            y_end   = int(height * 0.80)

            def _collect(x_start: int, x_end: int) -> list[tuple[int, int, int]]:
                out: list[tuple[int, int, int]] = []
                for y in range(y_start, y_end, step_y):
                    for x in range(x_start, x_end, step_x):
                        idx = (y * width + x) * 3
                        if idx + 2 < len(raw):
                            out.append((raw[idx], raw[idx + 1], raw[idx + 2]))
                return out

            left_pixels  = _collect(x_left_start,  x_left_end)
            right_pixels = _collect(x_right_start, x_right_end)

            regions: dict[str, tuple[int, int, int]] = {}
            for name, pixels in (("left", left_pixels), ("right", right_pixels)):
                picker = _LOOPBACK_PICKERS.setdefault(name, _LoopbackPicker())
                pick = _pick_dominant(pixels, picker)
                if pick is not None:
                    regions[name] = pick
            return regions

    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return {}
