"""
Screen sync service — color receiver for the bedroom lamp.

The capture loop lives in a desktop pc_agent (`screen_sync_agent.py`). This
service receives RGB colors via `POST /api/automation/screen-color`, smooths
them with an exponential moving average, and applies them to a single Hue
light. The mode gate (gaming / watching only) lives in the route
handler — by the time `apply_color` is called, the gate has already passed.

`LaptopLoopbackCapture` is an opt-in escape hatch for the rare case of
plugging the laptop into a TV. It runs the same screen capture loop but
in-process on the laptop and POSTs to its own localhost endpoint, so it
goes through the same wire format as the desktop agent. Disabled by default.
"""
import asyncio
import colorsys
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("home_hub.screen_sync")


# Per-mode max brightness clamps for the synced lamp.
# Gaming gets a higher cap so the lamp can pop on bright moments; watching
# stays subtle so the mirrored projected content doesn't wash the image.
# The projector is on HDMI from the dev PC, so mss captures the same frames
# that are being projected — L2 mirrors the actual content, not the dashboard.
MODE_MAX_BRIGHTNESS = {
    "gaming": 240,
    "watching": 80,
}
DEFAULT_MAX_BRIGHTNESS = 80
MIN_BRIGHTNESS = 15

# Per-mode minimum brightness — gaming stays visible even on dark scenes.
# Watching allows dim bias lighting (dark scenes → dim L2 → projection stays
# the room's brightest surface, which is what we want).
MODE_MIN_BRIGHTNESS: dict[str, int] = {
    "gaming": 85,     # Hold a comfortable bedroom bias level even on dark scenes
                      # so the desk lamp doesn't drop below ~1:3 monitor contrast.
}

# Zone- and posture-aware brightness overrides. When a detected (mode, zone)
# or (mode, zone, posture) tuple matches, the per-mode cap is replaced.
# Used to shape watching-mode screen-sync to the viewing context:
#   • desk            → YouTube on monitor; projector off → brighter bias.
#   • bed + reclined  → lying back watching the projector → hard cap dim so
#                       bright scenes don't blast a reclining viewer.
#   • bed + upright   → sitting up in bed (football game background, reading
#                       with projector on) → middle ground.
# Lookup prefers the more specific 3-tuple key; falls back to the 2-tuple,
# then to MODE_MAX_BRIGHTNESS when neither matches.
MODE_ZONE_MAX_BRIGHTNESS: dict[tuple[str, ...], int] = {
    ("watching", "desk"):               180,
    ("watching", "bed", "reclined"):    25,
    ("watching", "bed", "upright"):     60,
}


class ScreenSyncService:
    """
    Receives RGB colors from any source and applies them to a single Hue light.

    The class holds smoothing state (`_last_hue/sat/bri`) so successive
    `apply_color` calls produce a smooth transition rather than flicker.
    Status fields (`_last_color_at`, `_last_source`) are exposed for the
    `/api/automation/screen-sync/status` endpoint.
    """

    def __init__(self, hue_service, target_light_id: str = "2") -> None:
        self._hue = hue_service
        self._target_light = target_light_id

        # Smoothing
        self._smoothing_alpha: float = 0.3
        self._last_hue: float = 0.0
        self._last_sat: float = 0.0
        self._last_bri: float = 0.0

        # Status tracking
        self._last_color_at: Optional[datetime] = None
        self._last_source: Optional[str] = None

    @property
    def last_color_at(self) -> Optional[datetime]:
        return self._last_color_at

    @property
    def last_source(self) -> Optional[str]:
        return self._last_source

    async def apply_color(
        self,
        r: int,
        g: int,
        b: int,
        mode: str,
        source: str = "desktop",
        zone: Optional[str] = None,
        posture: Optional[str] = None,
    ) -> None:
        """
        Apply an RGB color to the bedroom lamp.

        Args:
            r, g, b: 0-255 RGB values from a screen capture.
            mode: Current automation mode — used to look up the brightness clamp.
            source: "desktop" or "laptop" — recorded for status reporting only.
            zone: Optional camera-detected zone ("desk" | "bed"). When provided,
                ``MODE_ZONE_MAX_BRIGHTNESS`` is consulted so the cap can differ
                between watching-at-desk (brighter bias) and watching-in-bed
                (dim for projector).
            posture: Optional camera-detected posture ("upright" | "reclined").
                Combined with zone into a 3-tuple key; the more specific
                (mode, zone, posture) match wins over (mode, zone). Falls
                through to the mode-only cap if neither matches.
        """
        max_bri: Optional[int] = None
        if zone is not None and posture is not None:
            max_bri = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone, posture))
        if max_bri is None and zone is not None:
            max_bri = MODE_ZONE_MAX_BRIGHTNESS.get((mode, zone))
        if max_bri is None:
            max_bri = MODE_MAX_BRIGHTNESS.get(mode, DEFAULT_MAX_BRIGHTNESS)
        min_bri = MODE_MIN_BRIGHTNESS.get(mode, MIN_BRIGHTNESS)
        h, s, br = self._rgb_to_hue_hsb((r, g, b), max_bri, min_bri)
        sh, ss, sb = self._smooth(h, s, br)
        await self._hue.set_light(self._target_light, {
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
    ) -> tuple[float, float, float]:
        """Convert RGB (0-255) to Hue bridge HSB values, clamped to brightness range."""
        r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
        h, s, v = colorsys.rgb_to_hsv(r, g, b)

        hue_val = h * 65535
        sat_val = min(254, s * 254 * 1.2)  # boost saturation for vibrancy
        bri_val = max(min_brightness, min(max_brightness, v * 254))

        return (hue_val, sat_val, bri_val)

    def _smooth(
        self, h: float, s: float, b: float,
    ) -> tuple[float, float, float]:
        """Apply EMA smoothing with hue-wrap handling."""
        alpha = self._smoothing_alpha

        # Hue wraps at 65535 → 0; pick the shorter path
        hue_diff = h - self._last_hue
        if abs(hue_diff) > 32767:
            if hue_diff > 0:
                hue_diff -= 65535
            else:
                hue_diff += 65535
        smoothed_h = (self._last_hue + alpha * hue_diff) % 65535

        smoothed_s = self._last_sat + alpha * (s - self._last_sat)
        smoothed_b = self._last_bri + alpha * (b - self._last_bri)

        self._last_hue = smoothed_h
        self._last_sat = smoothed_s
        self._last_bri = smoothed_b

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
                rgb = await asyncio.to_thread(_capture_dominant_color)
                if rgb is not None:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(
                            self._url,
                            json={
                                "r": rgb[0],
                                "g": rgb[1],
                                "b": rgb[2],
                                "source": "laptop",
                            },
                        )
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


def _capture_dominant_color() -> Optional[tuple[int, int, int]]:
    """
    Capture the primary screen and extract the dominant color.

    Used by `LaptopLoopbackCapture`. The desktop agent has its own copy of
    this logic in `pc_agent/screen_sync_agent.py` — they're intentionally
    duplicated so the agent has zero backend dependencies.

    Uses K-means clustering (5 clusters) to pick the most saturated dominant
    color. Falls back to simple averaging if scikit-learn is not installed.
    """
    try:
        import mss
    except ImportError:
        logger.error("mss not installed — cannot run laptop loopback")
        return None

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)

            width = screenshot.width
            height = screenshot.height
            raw = screenshot.rgb

            # Downsample to ~50x30 grid (~1500 pixels — enough for K-means)
            step_x = max(1, width // 50)
            step_y = max(1, height // 30)

            # Crop to center 60% (skip 20% edge — taskbar, window chrome)
            x_start = int(width * 0.2)
            x_end = int(width * 0.8)
            y_start = int(height * 0.2)
            y_end = int(height * 0.8)

            pixels = []
            for y in range(y_start, y_end, step_y):
                for x in range(x_start, x_end, step_x):
                    idx = (y * width + x) * 3
                    if idx + 2 < len(raw):
                        pixels.append((raw[idx], raw[idx + 1], raw[idx + 2]))

            if not pixels:
                return None

            if _HAS_KMEANS and len(pixels) >= 5:
                import colorsys

                pixel_array = np.array(pixels, dtype=np.float32)
                kmeans = MiniBatchKMeans(n_clusters=5, batch_size=100, n_init=1)
                kmeans.fit(pixel_array)

                best_score = -1.0
                best_center = None
                for center in kmeans.cluster_centers_:
                    r, g, b = center / 255.0
                    _h, s, v = colorsys.rgb_to_hsv(r, g, b)
                    if s > 0.2 and 0.15 < v < 0.85:
                        score = s * 0.7 + (1.0 - abs(v - 0.5)) * 0.3
                        if score > best_score:
                            best_score = score
                            best_center = center

                if best_center is None:
                    largest = int(np.argmax(np.bincount(kmeans.labels_)))
                    best_center = kmeans.cluster_centers_[largest]

                return (int(best_center[0]), int(best_center[1]), int(best_center[2]))

            # Fallback: simple average
            r_total = sum(p[0] for p in pixels)
            g_total = sum(p[1] for p in pixels)
            b_total = sum(p[2] for p in pixels)
            count = len(pixels)
            return (r_total // count, g_total // count, b_total // count)

    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return None
