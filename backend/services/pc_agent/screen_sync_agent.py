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
from typing import Any, Callable, Optional

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

CAPTURE_INTERVAL = 2.5  # seconds between color+luma posts

# Phase 2 — Rust damage detection. The loop ticks faster than the color
# cadence so it can catch Rust's brief red damage vignette; color/luma still
# only computes (the expensive k-means) every CAPTURE_INTERVAL off the same
# grab. The vignette score = edge-redness minus center-redness (a red flash
# concentrated at the screen edges = getting hit, vs. fire/sunset which redden
# the whole frame). Posted only above a cheap floor + throttled; the backend
# holds the real, runtime-tunable damage threshold + the flinch/cooldown logic.
DAMAGE_TICK = 0.2                  # 5 Hz base loop
DAMAGE_POST_FLOOR = 16            # agent-side cheap pre-filter (backend gates for real)
DAMAGE_POST_MIN_INTERVAL = 0.25  # ≤4 damage posts/sec
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "home-hub" / "logs"
PID_FILE = LOG_DIR / "screen_sync_agent.pid"
_BACKOFF_HEARTBEAT_INTERVAL = 10.0

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
        # Deterministic initialization is part of the stability contract: the same
        # captured frame must not select a different color merely because k-means
        # started from different random centroids on the next 2.5s sample.
        kmeans = MiniBatchKMeans(
            n_clusters=8, batch_size=100, n_init=1, random_state=0
        )  # type: ignore[arg-type]
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


def _grab_array(sct: "mss.mss") -> Optional["np.ndarray"]:
    """Grab the primary monitor as an ``(h, w, 3)`` uint8 RGB array.

    Takes an existing ``mss`` instance so the fast loop reuses one grabber
    instead of constructing one per tick. Returns None on failure."""
    try:
        shot = sct.grab(sct.monitors[1])
        return np.frombuffer(shot.rgb, dtype=np.uint8).reshape(
            shot.height, shot.width, 3
        )
    except Exception as e:
        logger.error(f"Screen grab error: {e}")
        return None


def compute_vignette_score(arr: "np.ndarray") -> float:
    """Edge-concentrated redness score — high when a red flash hugs the screen
    edges (Rust's damage vignette) but not the center (fire/sunset redden the
    whole frame). Score = mean edge redness − mean center redness, ≥0.

    ``redness(px) = max(0, R − max(G, B))``. The array is strided to ~quarter
    resolution first (the vignette is a coarse spatial feature) so this stays
    cheap at 5 Hz."""
    a = arr[::4, ::4].astype(np.int16)
    h, w = a.shape[:2]
    if h < 8 or w < 8:
        return 0.0
    redness = np.clip(a[:, :, 0] - np.maximum(a[:, :, 1], a[:, :, 2]), 0, 255)
    by, bx = max(1, int(h * 0.12)), max(1, int(w * 0.12))
    edge = np.concatenate([
        redness[:by, :].ravel(), redness[-by:, :].ravel(),
        redness[by:-by, :bx].ravel(), redness[by:-by, -bx:].ravel(),
    ])
    center = redness[int(h * 0.3):int(h * 0.7), int(w * 0.3):int(w * 0.7)]
    edge_red = float(edge.mean()) if edge.size else 0.0
    center_red = float(center.mean()) if center.size else 0.0
    return max(0.0, edge_red - center_red)


def _color_luma_from_array(
    arr: "np.ndarray",
) -> Optional[tuple[tuple[int, int, int], int]]:
    """Dominant color (sticky-k-means) + scene luma (Rec.601 frame mean) from
    a grabbed array. Center 60% crop, strided to a ~50×30 grid. Returns
    ``((r, g, b), luma)`` or None."""
    h, w = arr.shape[:2]
    crop = arr[
        int(h * 0.20):int(h * 0.80):max(1, h // 30),
        int(w * 0.20):int(w * 0.80):max(1, w // 50),
    ]
    pixels = crop.reshape(-1, 3).astype(np.float32)
    if pixels.shape[0] == 0:
        return None
    scene_mean = pixels.mean(axis=0)
    luma = int(max(0, min(255,
        0.299 * scene_mean[0] + 0.587 * scene_mean[1] + 0.114 * scene_mean[2]
    )))
    if _HAS_KMEANS and pixels.shape[0] >= 8:
        rgb = _PICKER.pick(pixels)
    else:
        rgb = _pick_dominant_average(pixels)
    return rgb, luma


def capture_dominant_color() -> Optional[tuple[tuple[int, int, int], int]]:
    """Back-compat one-shot: grab + dominant color + luma. Used by tests and
    any caller that wants a single sample; the live agent loop uses the split
    grab/compute helpers so one grab feeds both the color and damage paths."""
    try:
        with mss.mss() as sct:
            arr = _grab_array(sct)
        return _color_luma_from_array(arr) if arr is not None else None
    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return None


def _wait_for_backoff(
    stop_event: threading.Event,
    duration: float,
    heartbeat: Optional[Callable[[], None]],
) -> bool:
    """Wait out network backoff while reporting only intentional progress.

    Long retry sleeps are sliced when supervised so they cannot look like a
    hung agent. Capture, color computation, and HTTP calls remain outside this
    helper; if any of those block, no heartbeat is emitted and the supervisor
    can still detect the hang. Standalone agents retain the original one-shot
    interruptible wait.
    """
    if heartbeat is None:
        return stop_event.wait(duration)

    remaining = duration
    while remaining > 0:
        wait_slice = min(remaining, _BACKOFF_HEARTBEAT_INTERVAL)
        if stop_event.wait(wait_slice):
            return True
        remaining -= wait_slice
        if remaining > 0:
            heartbeat()
    return False


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> None:
    """
    Main loop — capture, POST, sleep, repeat. Backs off on HTTP errors.

    Args:
        server_url: Base URL of the Home Hub backend.
        stop_event: Optional threading event for clean shutdown (set by supervisor).
        heartbeat: Optional supervisor liveness pulse, called once per loop
            iteration so a hung-but-alive thread (e.g. wedged screen grab) is
            detectable.
    """
    color_endpoint = f"{server_url.rstrip('/')}/api/automation/screen-color"
    event_endpoint = f"{server_url.rstrip('/')}/api/automation/rust-event"
    backoff = 1

    _stop = stop_event or threading.Event()
    client = httpx.Client(timeout=5.0)

    logger.info(f"Screen Sync Agent started — color→{color_endpoint}, damage→{event_endpoint}")

    last_color = 0.0
    last_damage_post = 0.0
    # The fast 5Hz damage loop only runs while we're actually in a Rust
    # session — we learn that from the `profile: "rust"` field the screen-color
    # response returns. Outside Rust the agent stays at the cheap 2.5s color
    # cadence (no continuous-grab CPU cost), and flips to 5Hz within one color
    # post of Rust starting.
    rust_active = False
    # One reusable grabber for the fast loop (don't reconstruct mss per tick).
    sct = mss.mss()
    try:
        while not _stop.is_set():
            if heartbeat is not None:
                heartbeat()
            try:
                now = time.monotonic()
                need_color = now - last_color >= CAPTURE_INTERVAL
                if rust_active or need_color:
                    arr = _grab_array(sct)
                else:
                    arr = None

                if arr is not None:
                    # Damage path — only while Rust is active. Cheap edge-
                    # vignette score, posted above the floor + throttled; the
                    # backend holds the real threshold + flinch logic.
                    if rust_active:
                        score = compute_vignette_score(arr)
                        if (score >= DAMAGE_POST_FLOOR
                                and now - last_damage_post >= DAMAGE_POST_MIN_INTERVAL):
                            last_damage_post = now
                            try:
                                client.post(event_endpoint,
                                            json={"type": "damage", "score": round(score, 1)})
                            except httpx.HTTPError as e:
                                logger.debug(f"Failed to post rust-event: {e}")

                    # Color + luma — every CAPTURE_INTERVAL, off the same grab.
                    # The response tells us whether the Rust profile is live,
                    # which gates the fast loop above.
                    if need_color:
                        last_color = now
                        cl = _color_luma_from_array(arr)
                        if cl is not None:
                            rgb, luma = cl
                            try:
                                resp = client.post(color_endpoint, json={
                                    "source": "desktop",
                                    "r": rgb[0], "g": rgb[1], "b": rgb[2],
                                    "luma": luma,
                                })
                                resp.raise_for_status()
                                backoff = 1
                                try:
                                    rust_active = resp.json().get("profile") == "rust"
                                except (ValueError, AttributeError):
                                    rust_active = False
                            except httpx.HTTPError as e:
                                logger.warning(f"Failed to report color: {e}")
                                backoff = min(backoff * 2, 60)

                if backoff != 1:
                    _wait_for_backoff(_stop, backoff, heartbeat)
                else:
                    _stop.wait(DAMAGE_TICK if rust_active else CAPTURE_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Screen sync agent stopped")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                _wait_for_backoff(_stop, backoff, heartbeat)
                backoff = min(backoff * 2, 60)
    finally:
        client.close()
        try:
            sct.close()
        except Exception:
            pass


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
