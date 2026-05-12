"""
Screen sync service — color receiver for bedroom lamps.

The capture loop lives in a desktop pc_agent (`screen_sync_agent.py`). This
service receives RGB colors via `POST /api/automation/screen-color`, smooths
them with an exponential moving average, and applies them to one or more
Hue lights. The mode gate (gaming / watching only) lives in the route
handler — by the time `apply_color` is called, the gate has already passed.

Multi-light support: the service manages N target lights with independent
per-light EMA state and per-light brightness caps. Dual-region screen sync
maps the left half of the screen to L2 and the right half to L5; each lamp
smooths and clamps independently so the clear-housing L5 doesn't blow out
next to the diffused-shade L2.

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

logger = logging.getLogger("home_hub.screen_sync")


# Per-(mode, light_id) max brightness clamps for the synced lamps.
# Gaming gets a higher cap so the lamp can pop on bright moments; watching
# stays subtle so the mirrored projected content doesn't wash the image.
# L5's clear housing reads ~1.3× brighter than L2's fabric shade, so its
# caps are stepped down to keep it in a peripheral role.
MODE_MAX_BRIGHTNESS: dict[tuple[str, str], int] = {
    ("gaming",   "2"): 240,
    ("watching", "2"):  80,
    ("gaming",   "5"):  70,   # Clear seeded-glass housing reads ~2× brighter
                              # than L2's fabric shade at the same numeric bri.
                              # Tightened below L5's gaming-late_night baseline
                              # (80) because peripheral accent through the
                              # visible bulb still felt hot at 90 on bright
                              # screen moments — third iteration from 180→160→110→90→70.
    ("watching", "5"):  50,
}
DEFAULT_MAX_BRIGHTNESS = 80
MIN_BRIGHTNESS = 15

# Per-(mode, light_id) minimum brightness. Gaming stays visible even on
# dark scenes; watching allows dim bias lighting.
MODE_MIN_BRIGHTNESS: dict[tuple[str, str], int] = {
    ("gaming", "2"): 130,    # Sits at L2's gaming evening/night baseline (140/150).
    ("gaming", "5"):  40,    # Lower than L5's static baseline so dark scenes
                             # can actually dim L5's visible bulb instead of
                             # holding it bright on a black frame.
}

# Per-light saturation boost. RGB→HSB conversion applies this multiplier to
# saturation; L2's fabric shade washes punch out, so +20% restores vibrancy.
# L5's clear glass shows the bulb's color directly with no diffusion, so any
# boost reads as oversaturated next to L2 — leave it at neutral (1.0).
PER_LIGHT_SAT_BOOST: dict[str, float] = {
    "2": 1.2,
    "5": 1.0,
}
DEFAULT_SAT_BOOST = 1.2

# Zone- and posture-aware brightness overrides, keyed by light_id so each
# lamp can have its own projector-safe cap when reclining in bed.
# Lookup prefers the most specific match: (mode, zone, posture, light_id) →
# (mode, zone, light_id) → MODE_MAX_BRIGHTNESS[(mode, light_id)] → default.
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
    ) -> int:
        """Resolve the screen-sync cap for the given context.

        Lookup order: runtime override 4-tuple → MODE_ZONE_MAX_BRIGHTNESS
        4-tuple (mode, zone, posture, light_id) → MODE_ZONE_MAX_BRIGHTNESS
        3-tuple (mode, zone, light_id) → MODE_MAX_BRIGHTNESS[(mode, light_id)]
        → default.
        """
        if zone is not None and posture is not None:
            override = self._cap_overrides.get((mode, zone, posture, light_id))
            if override is not None:
                return override
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, posture, light_id))
            if cap is not None:
                return cap
        if zone is not None:
            cap = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, light_id))
            if cap is not None:
                return cap
        return MODE_MAX_BRIGHTNESS.get((mode, light_id), DEFAULT_MAX_BRIGHTNESS)

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
        """
        if light_id not in self._targets:
            return
        max_bri = self.get_cap(mode, light_id, zone, posture)
        min_bri = MODE_MIN_BRIGHTNESS.get((mode, light_id), MIN_BRIGHTNESS)
        sat_boost = PER_LIGHT_SAT_BOOST.get(light_id, DEFAULT_SAT_BOOST)
        h, s, br = self._rgb_to_hue_hsb((r, g, b), max_bri, min_bri, sat_boost)
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

    def _rgb_to_hue_hsb(
        self, rgb: tuple[int, int, int], max_brightness: int,
        min_brightness: int = MIN_BRIGHTNESS,
        sat_boost: float = DEFAULT_SAT_BOOST,
    ) -> tuple[float, float, float]:
        """Convert RGB (0-255) to Hue bridge HSB values, clamped to brightness range.

        ``sat_boost`` is per-light: L2's fabric shade benefits from +20%
        vibrancy compensation, L5's clear glass needs neutral (1.0) to avoid
        looking oversaturated next to L2.
        """
        r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
        h, s, v = colorsys.rgb_to_hsv(r, g, b)

        hue_val = h * 65535
        sat_val = min(254, s * 254 * sat_boost)
        bri_val = max(min_brightness, min(max_brightness, v * 254))

        return (hue_val, sat_val, bri_val)

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
