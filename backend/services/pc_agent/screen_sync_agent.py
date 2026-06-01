"""
Screen Sync Agent — standalone desktop process.

Runs on the user's desktop. Captures the dominant color of the primary
screen every 2.5 seconds and POSTs it to the Home Hub backend on the laptop.
The backend gates application by current automation mode (only gaming /
watching modes apply); this agent stays dumb and always sends.

Mirror mode: a single color sampled from the whole-screen center crop is
POSTed and the backend mirrors it to every screen-sync target lamp (L2 +
L5). Dual-region was tried first (left half → L2, right half → L5) but
abandoned because the disagreement created eye strain at close viewing
distance — see the lighting-curator INDEX for the documented anti-pattern.

Usage:
    python -m backend.services.pc_agent.screen_sync_agent
    python -m backend.services.pc_agent.screen_sync_agent --server http://192.168.86.30:8000

Autostart on Windows:
    Create a Task Scheduler task that runs at user logon. Action:
        python.exe -m backend.services.pc_agent.screen_sync_agent --server http://192.168.86.30:8000
    Set "Run whether user is logged on or not" off (it needs the user session
    to capture the screen). Set "Hidden" on so it stays out of the way.
"""
import argparse
import colorsys
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import mss
import numpy as np

try:
    from sklearn.cluster import MiniBatchKMeans
    _HAS_KMEANS = True
except ImportError:
    _HAS_KMEANS = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("home_hub.screen_sync_agent")

CAPTURE_INTERVAL = 2.5  # seconds between captures
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "home-hub" / "logs"
PID_FILE = LOG_DIR / "screen_sync_agent.pid"

# Sticky-cluster tuning. K-means reassigns cluster labels each fit, so two
# near-tied clusters can trade the "best" slot frame-to-frame and produce
# cycling output even though the scene is stable. The picker remembers its
# prior winner and biases toward any current cluster close to it; that keeps
# the chosen color pinned through busy scenes while still letting real color
# changes break through.
_STICKY_DISTANCE: float = 60.0       # Euclidean RGB distance — centers within this are "same color"
_STICKY_SCORE_MARGIN: float = 0.08   # new best must beat prior by this delta to switch
_STICKY_STALENESS_SEC: float = 10.0  # treat as fresh start after this long idle


class StickyClusterPicker:
    """Sticky-cluster dominant-color picker, vibrancy-biased.

    K-means clusters the sampled pixels into 8 groups (8 instead of 5 so a
    small saturated minority — game UI accent, status-bar pip, particle
    effect — gets its own centroid instead of being absorbed into a gray
    centroid by the dominant background). The most-saturated cluster that
    passes the saturation/brightness gate wins, with sticky bias holding
    the prior winner through near-tied scenes.
    """

    def __init__(self) -> None:
        # np.ndarray once populated; None before the first frame.
        self.last_center: Any = None
        self.last_picked_at: float = 0.0

    def pick(self, pixels: "np.ndarray") -> tuple[int, int, int]:
        """Pick the most visually dominant color via K-means with sticky bias.

        Scores clusters by saturation (0.7) + luminance balance (0.3). Biases
        toward the previous frame's winner when a current cluster is close
        to it; only switches when a new candidate beats the prior by more
        than ``_STICKY_SCORE_MARGIN``. Dark-scene fallback prefers the cluster
        nearest the prior pick so a momentary dark frame doesn't snap the
        lamp to near-black.
        """
        now = time.time()
        prior = self.last_center
        if prior is not None and now - self.last_picked_at > _STICKY_STALENESS_SEC:
            prior = None

        # 8 clusters preserves small saturated regions inside a mostly-gray
        # frame — at 5 clusters a small accent gets merged into the dominant
        # gray centroid and the picker has no saturated candidate to score.
        kmeans = MiniBatchKMeans(n_clusters=8, batch_size=100, n_init=1)  # type: ignore[arg-type]
        kmeans.fit(pixels)

        scored: list[tuple[float, Any]] = []
        for center in kmeans.cluster_centers_:
            r, g, b = center / 255.0
            _h, s, v = colorsys.rgb_to_hsv(r, g, b)
            # Permissive gate (0.15 sat, 0.12-0.88 v) lets muted-but-still-
            # colored clusters into scoring. Pure-gray (s≈0) and black/white
            # extremes still get filtered out.
            if s > 0.15 and 0.12 < v < 0.88:
                score = s * 0.7 + (1.0 - abs(v - 0.5)) * 0.3
                scored.append((score, center))

        chosen: Any = None
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

        self.last_center = chosen
        self.last_picked_at = now

        return (int(chosen[0]), int(chosen[1]), int(chosen[2]))


# Module-level singleton picker (was a per-region dict under the abandoned
# dual-region scheme). One picker is enough now that the full screen is
# sampled as a single region.
_PICKER = StickyClusterPicker()


def _pick_dominant_average(pixels: "np.ndarray") -> tuple[int, int, int]:
    """Fallback: simple arithmetic mean of all pixels."""
    mean = pixels.mean(axis=0)
    return (int(mean[0]), int(mean[1]), int(mean[2]))


_mutex_handle = None


def _acquire_singleton_lock() -> bool:
    """Ensure only one instance runs using a Windows named mutex (kernel-level atomic)."""
    global _mutex_handle
    if sys.platform == "win32":
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, "HomeHub_ScreenSyncAgent")
        last_error = ctypes.windll.kernel32.GetLastError()
        # ERROR_ALREADY_EXISTS = 183
        if last_error == 183:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
            return False
        return True
    # Unix fallback: fcntl file lock
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _mutex_handle = open(PID_FILE, "w")  # noqa: SIM115
        import fcntl
        fcntl.flock(_mutex_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _mutex_handle.write(str(os.getpid()))
        _mutex_handle.flush()
        return True
    except (OSError, IOError):
        if _mutex_handle:
            _mutex_handle.close()
            _mutex_handle = None
        return False


def capture_dominant_color() -> Optional[tuple[int, int, int]]:
    """
    Capture the primary screen and extract the dominant color.

    Grabs the full screen, downsamples the center 60% region (skip 20% on
    every edge to ignore taskbar / window chrome / corner UI), runs the
    sticky-k-means picker. Returns a single RGB triple, or None if the
    capture failed.
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)

            width = screenshot.width
            height = screenshot.height
            raw = screenshot.rgb

            # ~50×30 sample grid across the center crop — enough points for
            # k-means to find clusters without burning CPU.
            step_x = max(1, width // 50)
            step_y = max(1, height // 30)

            x_start = int(width * 0.20)
            x_end   = int(width * 0.80)
            y_start = int(height * 0.20)
            y_end   = int(height * 0.80)

            pixels: list[tuple[int, int, int]] = []
            for y in range(y_start, y_end, step_y):
                for x in range(x_start, x_end, step_x):
                    idx = (y * width + x) * 3
                    if idx + 2 < len(raw):
                        pixels.append((raw[idx], raw[idx + 1], raw[idx + 2]))

            if not pixels:
                return None

            pixel_array = np.array(pixels, dtype=np.float32)
            if _HAS_KMEANS and len(pixels) >= 8:
                return _PICKER.pick(pixel_array)
            return _pick_dominant_average(pixel_array)

    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return None


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Main loop — capture, POST, sleep, repeat. Backs off on HTTP errors.

    Args:
        server_url: Base URL of the Home Hub backend.
        stop_event: Optional threading event for clean shutdown (set by supervisor).
    """
    endpoint = f"{server_url.rstrip('/')}/api/automation/screen-color"
    backoff = 1

    _stop = stop_event or threading.Event()
    client = httpx.Client(timeout=5.0)

    logger.info(f"Screen Sync Agent started — reporting to {endpoint}")

    try:
        while not _stop.is_set():
            try:
                rgb = capture_dominant_color()
                if rgb is not None:
                    body = {
                        "source": "desktop",
                        "r": rgb[0],
                        "g": rgb[1],
                        "b": rgb[2],
                    }
                    try:
                        resp = client.post(endpoint, json=body)
                        resp.raise_for_status()
                        backoff = 1
                    except httpx.HTTPError as e:
                        logger.warning(f"Failed to report color: {e}")
                        backoff = min(backoff * 2, 60)

                _stop.wait(CAPTURE_INTERVAL if backoff == 1 else backoff)

            except KeyboardInterrupt:
                logger.info("Screen sync agent stopped")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                _stop.wait(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Home Hub Screen Sync Agent")
    parser.add_argument(
        "--server",
        default="http://localhost:8000",
        help="Home Hub server URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    if not _acquire_singleton_lock():
        sys.exit(0)

    run_agent(args.server)
