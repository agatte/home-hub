"""
Screen sync service — color receiver for bedroom lamps.

The capture loop lives in a desktop pc_agent (`screen_sync_agent.py`). This
service receives RGB colors via `POST /api/automation/screen-color`, smooths
them with an exponential moving average, and applies them to one or more
Hue lights. The mode gate (gaming / watching only) lives in the route
handler — by the time `apply_color` is called, the gate has already passed.

Multi-light support: the service manages N target lights with independent
per-light EMA state and per-light brightness caps. Mirror dispatch (route
handler) sends the same RGB to every target lamp (currently L2 + L5); per-
light caps, sat boost, and luma compensation differentiate the on-bridge
state so the clear-housing L5 doesn't blow out next to the diffused-shade
L2 even with identical input. (Dual-region — L2 ← left half, L5 ← right —
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
)

logger = logging.getLogger("home_hub.screen_sync")


# Per-(mode, light_id) max brightness clamps for the synced lamps.
# Gaming gets a higher cap so the lamp can pop on bright moments; watching
# stays subtle so the mirrored projected content doesn't wash the image.
# L5's clear housing reads ~1.3× brighter than L2's fabric shade, so its
# caps are stepped down to keep it in a peripheral role.
MODE_MAX_BRIGHTNESS: dict[tuple[str, str], int] = {
    ("gaming",   "2"): 240,
    ("watching", "2"):  80,
    ("gaming",   "5"):  60,   # Clear seeded-glass housing reads ~2× brighter
                              # than L2's fabric shade at the same numeric bri.
                              # Cap is now backed up by per-light luma
                              # compensation (see PER_LIGHT_LUMA_COMP below) —
                              # the cap handles peak amplitude, luma comp handles
                              # the hue-perception punch that cap alone can't fix.
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
    ("gaming", "evening",    "2"): 185,
    ("gaming", "night",      "2"): 170,
    ("gaming", "late_night", "2"): 130,
    # L5 (clear seeded glass) — Stage-2 2026-05-31 (curator agent a976374):
    # caps RAISED above the lowered static resting floor (90/75/65/50) so
    # screen-sync can LIFT L5 on vivid frames instead of dragging it below its
    # resting state (the prior 50/35/25 caps sat 2-3x UNDER the static base =
    # the "dim colors" complaint, audit syncfight-2). Rec.601 luma comp still
    # scales warm/green frames down, so the lift mainly benefits low-luma blue
    # gaming content. Evening cap (95) intentionally exceeds day (flat 60): an
    # accent should read MORE present in a dark room than in daylight.
    ("gaming", "evening",    "5"):  95,
    ("gaming", "night",      "5"):  80,
    ("gaming", "late_night", "5"):  50,
}

# Per-(mode, light_id) minimum brightness. Gaming stays visible even on
# dark scenes; watching allows dim bias lighting.
MODE_MIN_BRIGHTNESS: dict[tuple[str, str], int] = {
    ("gaming", "2"): 130,    # Sits at L2's gaming evening/night baseline (140/150).
    ("gaming", "5"):  25,    # Lower than L5's static baseline so dark scenes
                             # can actually dim L5's visible bulb instead of
                             # holding it bright on a black frame. Paired with
                             # the perceptual luma compensation, this widens
                             # L5's usable dynamic range without raising the cap.
}

# Time-period overrides for floors — same pattern as the cap override table.
# Only late_night L2 is shipped today: the L2 cap collapses to 130 at
# late_night (matching the existing floor), so without a matching floor drop
# the dynamic range becomes a single point. 110 lets late-night dark scenes
# actually dim L2 toward its late_night static baseline.
MODE_MIN_BRIGHTNESS_PERIOD: dict[tuple[str, str, str], int] = {
    ("gaming", "late_night", "2"): 110,
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
    ("watching", "desk",            "2"): 180,
    ("watching", "bed", "reclined", "2"):  25,
    ("watching", "bed", "upright",  "2"):  60,
    ("watching", "bed", "reclined", "5"):  20,
    ("watching", "bed", "upright",  "5"):  50,
}


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
    ) -> None:
        self._hue = hue_service
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

        # Status tracking — global "most recent write" across all lamps.
        self._last_color_at: Optional[datetime] = None
        self._last_source: Optional[str] = None

        # Runtime overrides for specific (mode, zone, posture, light_id) caps —
        # settings page writes through this dict, persisted in app_settings.
        self._cap_overrides: dict[tuple[str, str, str, str], int] = {}

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
        3-tuple (mode, zone, light_id) → MODE_MAX_BRIGHTNESS_PERIOD
        (mode, period, light_id) → MODE_MAX_BRIGHTNESS[(mode, light_id)]
        → default.

        Zone/posture overrides take precedence over the time-period table
        because they reflect specific physical setups (projector-in-bed) that
        should hard-cap regardless of time of day.

        Gaming-mode envelope lift: when ``mode == "gaming"`` and ``period ==
        "day"``, the resolved cap is scaled by ``lux_multiplier *
        get_functional_weather_multiplier(mode, period, weather_condition)``
        (cloudy 1.10×, rain 1.15×, etc.). Screen-sync envelope is gated to
        gaming-day only on purpose (L5 clear-housing perceptual ceiling);
        the bri pipeline applies the same weather multipliers across more
        (mode, period) buckets. Watching's caps stay flat to preserve
        cinematic dim.
        """
        if zone is not None and posture is not None:
            override = self._cap_overrides.get((mode, zone, posture, light_id))
            if override is not None:
                return self._scale_for_ambient(
                    override, mode, period, lux_multiplier, weather_condition,
                )
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, posture, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition,
                )
        if zone is not None:
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition,
                )
        if period is not None:
            cap = MODE_MAX_BRIGHTNESS_PERIOD.get((mode, period, light_id))
            if cap is not None:
                return self._scale_for_ambient(
                    cap, mode, period, lux_multiplier, weather_condition,
                )
        base = MODE_MAX_BRIGHTNESS.get((mode, light_id), DEFAULT_MAX_BRIGHTNESS)
        return self._scale_for_ambient(
            base, mode, period, lux_multiplier, weather_condition,
        )

    def get_floor(
        self,
        mode: str,
        light_id: str,
        period: Optional[str],
        lux_multiplier: float = 1.0,
        weather_condition: Optional[str] = None,
    ) -> int:
        """Resolve the brightness floor for the given context.

        Lookup order: MODE_MIN_BRIGHTNESS_PERIOD (mode, period, light_id) →
        MODE_MIN_BRIGHTNESS (mode, light_id) → MIN_BRIGHTNESS default.

        Subject to the same gaming-day ambient lift as ``get_cap`` — the
        floor lifting is the main eye-comfort payoff (dark game content
        no longer drags L2 down to fabric-shade dimness on a cloudy day).
        """
        if period is not None:
            floor = MODE_MIN_BRIGHTNESS_PERIOD.get((mode, period, light_id))
            if floor is not None:
                return self._scale_for_ambient(
                    floor, mode, period, lux_multiplier, weather_condition,
                )
        base = MODE_MIN_BRIGHTNESS.get((mode, light_id), MIN_BRIGHTNESS)
        return self._scale_for_ambient(
            base, mode, period, lux_multiplier, weather_condition,
        )

    # Worst-case stacked multiplier ceiling: LUX_CURVE peaks at 1.30 (20 lux
    # baseline-shifted) and FUNCTIONAL_WEATHER_BRIGHTNESS peaks at 1.20
    # (thunderstorm), so naive stacking allows 1.56×. L5's clear housing
    # crosses the documented perceptual overdrive threshold (gaming-day cap
    # 60 × 1.56 = 93, above the 90 ceiling from build 4adce9f). 1.40 keeps
    # L5 worst-case at 84 and still passes through the cloudy-daytime lift
    # this change was written for (1.07 × 1.10 ≈ 1.18).
    _AMBIENT_LIFT_CEILING: float = 1.40

    @staticmethod
    def _scale_for_ambient(
        value: int,
        mode: str,
        period: Optional[str],
        lux_multiplier: float,
        weather_condition: Optional[str],
    ) -> int:
        """Apply gaming-day lux × functional-weather scaling to a cap/floor.

        Mirrors the gate in ``apply_functional_weather_brightness``: gaming
        mode only, daytime only. Watching keeps its flat envelope so the
        projector contrast intent isn't disturbed. The combined multiplier
        is capped at ``_AMBIENT_LIFT_CEILING`` to protect L5's clear-housing
        perceptual ceiling. Final value clamped to [1, 254].
        """
        if mode != "gaming":
            return value
        if period != "day":
            return value
        # Screen-sync caps stay gating-restricted to gaming-day on purpose:
        # the L5 clear-housing perceptual ceiling (build 4adce9f) wasn't
        # validated for evening/working lifts. The bri pipeline now applies
        # weather multipliers across more buckets, but the sync envelope
        # holds its narrower scope.
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
        Apply an RGB color to one of the managed bedroom lamps.

        Args:
            light_id: Target Hue light id (e.g. "2" or "5"). Must be in
                ``target_lights`` or the call is a no-op.
            r, g, b: 0-255 RGB values from a screen capture.
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
                ``lux_to_multiplier``). Only consumed for gaming-day; lifts
                the cap+floor envelope on dim ambient. Defaults to 1.0
                (no lift).
            weather_condition: Classified weather string ("clouds" / "rain"
                / "thunderstorm" / "snow" / None). Only consumed for
                gaming-day; stacks multiplicatively with ``lux_multiplier``
                to lift the envelope on overcast conditions.
        """
        if light_id not in self._targets:
            return
        max_bri = self.get_cap(
            mode, light_id, zone, posture, period,
            lux_multiplier, weather_condition,
        )
        min_bri = self.get_floor(
            mode, light_id, period, lux_multiplier, weather_condition,
        )
        sat_boost = PER_LIGHT_SAT_BOOST.get(light_id, DEFAULT_SAT_BOOST)
        luma_comp = PER_LIGHT_LUMA_COMP.get(light_id, DEFAULT_LUMA_COMP)
        h, s, br = rgb_to_hue_hsb(
            (r, g, b), max_bri, min_bri, sat_boost, luma_comp
        )
        sh, ss, sb = self._smooth(light_id, h, s, br)
        await self._hue.set_light(light_id, {
            "on": True,
            "hue": int(sh),
            "sat": int(ss),
            "bri": int(sb),
            "transitiontime": 20,  # 2s transition for smoothness
        })
        self._last_color_at = datetime.now(timezone.utc)
        self._last_source = source

    def _smooth(
        self, light_id: str, h: float, s: float, b: float,
    ) -> tuple[float, float, float]:
        """Apply EMA smoothing with hue-wrap handling for the given light."""
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
