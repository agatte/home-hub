"""
Screen sync service — captures dominant screen color and syncs to bedroom lamp.

Designed for watching mode with a projector. Samples the screen every few
seconds, extracts the dominant color, smooths transitions with an exponential
moving average, and applies to a single target light (bedroom lamp).

Usage:
    Automatically started/stopped by the automation engine when entering/leaving
    watching mode. Can also be controlled manually via API.
"""
import asyncio
import colorsys
import logging
from typing import Optional

logger = logging.getLogger("home_hub.screen_sync")


class ScreenSyncService:
    """
    Captures screen content and syncs dominant color to a single Hue light.

    Uses mss for fast screen capture, downsamples aggressively, and applies
    exponential moving average smoothing to prevent flicker.
    """

    def __init__(self, hue_service, target_light_id: str = "2") -> None:
        self._hue = hue_service
        self._target_light = target_light_id
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

        # Smoothing: lower alpha = smoother but slower response
        self._smoothing_alpha: float = 0.3
        self._capture_interval: float = 2.5  # seconds
        self._last_hue: float = 0.0
        self._last_sat: float = 0.0
        self._last_bri: float = 0.0

        # Brightness clamp to keep it subtle
        self._min_brightness: int = 15
        self._max_brightness: int = 80

    @property
    def running(self) -> bool:
        return self._running

    async def start(self, max_brightness: int = 80) -> None:
        """
        Start the screen sync loop.

        Args:
            max_brightness: Upper brightness clamp (80 for watching, higher for gaming).
        """
        if self._running:
            return
        self._max_brightness = max(self._min_brightness, min(254, max_brightness))
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(
            f"Screen sync started (target light: {self._target_light}, "
            f"max_bri: {self._max_brightness})"
        )

    async def stop(self) -> None:
        """Stop the screen sync loop."""
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
        logger.info("Screen sync stopped")

    async def _sync_loop(self) -> None:
        """Main loop: capture → sample → convert → smooth → apply."""
        while self._running:
            try:
                rgb = await asyncio.to_thread(self._capture_dominant_color)
                if rgb:
                    h, s, b = self._rgb_to_hue_hsb(rgb)
                    sh, ss, sb = self._smooth(h, s, b)
                    await self._hue.set_light(self._target_light, {
                        "on": True,
                        "hue": int(sh),
                        "sat": int(ss),
                        "bri": int(sb),
                        "transitiontime": 20,  # 2s transition for smoothness
                    })

                await asyncio.sleep(self._capture_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Screen sync error: {e}")
                await asyncio.sleep(5)

    def _capture_dominant_color(self) -> Optional[tuple[int, int, int]]:
        """
        Capture screen and extract dominant color.

        Grabs the full screen, downsamples to ~100x60, crops to the center
        60% (avoids taskbar, window chrome), and averages the pixel colors.

        Returns:
            (R, G, B) tuple or None on failure.
        """
        try:
            import mss
            import mss.tools
        except ImportError:
            logger.error("mss not installed — run: pip install mss")
            return None

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Primary monitor
                screenshot = sct.grab(monitor)

                # Get raw pixel data
                width = screenshot.width
                height = screenshot.height
                raw = screenshot.rgb

                # Downsample by stepping through pixels
                step_x = max(1, width // 100)
                step_y = max(1, height // 60)

                # Crop to center 60% (skip 20% on each edge)
                x_start = int(width * 0.2)
                x_end = int(width * 0.8)
                y_start = int(height * 0.2)
                y_end = int(height * 0.8)

                r_total, g_total, b_total = 0, 0, 0
                count = 0

                for y in range(y_start, y_end, step_y):
                    for x in range(x_start, x_end, step_x):
                        idx = (y * width + x) * 3
                        if idx + 2 < len(raw):
                            r_total += raw[idx]
                            g_total += raw[idx + 1]
                            b_total += raw[idx + 2]
                            count += 1

                if count == 0:
                    return None

                return (r_total // count, g_total // count, b_total // count)

        except Exception as e:
            logger.error(f"Screen capture error: {e}")
            return None

    def _rgb_to_hue_hsb(
        self, rgb: tuple[int, int, int],
    ) -> tuple[float, float, float]:
        """
        Convert RGB (0-255) to Hue bridge HSB values.

        Returns:
            (hue 0-65535, saturation 0-254, brightness min-max clamped)
        """
        r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
        h, s, v = colorsys.rgb_to_hsv(r, g, b)

        hue_val = h * 65535
        sat_val = s * 254

        # Boost saturation slightly for more vibrant ambient light
        sat_val = min(254, sat_val * 1.2)

        # Clamp brightness to keep it subtle
        bri_val = v * 254
        bri_val = max(self._min_brightness, min(self._max_brightness, bri_val))

        return (hue_val, sat_val, bri_val)

    def _smooth(
        self, h: float, s: float, b: float,
    ) -> tuple[float, float, float]:
        """
        Apply exponential moving average to prevent flicker.

        Args:
            h, s, b: New HSB values.

        Returns:
            Smoothed HSB values.
        """
        alpha = self._smoothing_alpha

        # Special handling for hue wrapping (0 and 65535 are adjacent)
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
