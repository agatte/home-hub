"""
Screen Sync Agent — standalone desktop process.

Runs on the user's desktop. Captures the dominant color of the primary
screen every 2.5 seconds and POSTs it to the Home Hub backend on the laptop.
The backend gates application by current automation mode (only gaming /
watching modes apply). The agent also reports immediate foreground-media
evidence so sticky Watching can hold the last media color after a tab switch.

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
import ctypes
import ctypes.wintypes
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
import psutil

from backend.services.pc_agent.game_list import MEDIA_PROCESSES
from backend.services.pc_agent.windows_media_session import (
    WindowsMediaSessionProbe,
    browser_title_looks_like_video,
)

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
_MEDIA_SESSION_PROBE = WindowsMediaSessionProbe()

# Sticky-cluster tuning. K-means reassigns cluster labels each fit, so two
# near-tied clusters can trade the "best" slot frame-to-frame and produce
# cycling output even though the scene is stable. The picker remembers its
# prior winner and biases toward any current cluster close to it; that keeps
# the chosen color pinned through busy scenes while still letting real color
# changes break through.
_STICKY_DISTANCE: float = 60.0       # Euclidean RGB distance — centers within this are "same color"
_STICKY_SCORE_MARGIN: float = 0.08   # new best must beat prior by this delta to switch
_STICKY_STALENESS_SEC: float = 10.0  # treat as fresh start after this long idle

# Representative-color tuning. Saturation alone must not let a tiny UI accent
# repaint the room. Chromatic clusters compete against the prevalence of the
# frame's neutral/dark composition; prevalence leads the chromatic score and a
# small ownership margin prevents borderline accents from winning on noise.
_COLOR_SATURATION_GATE: float = 0.15
_COLOR_VALUE_MIN: float = 0.12
_MIN_COLOR_CLUSTER_PREVALENCE: float = 0.03
_COLOR_SUPPORT_DISTANCE: float = 50.0
_COLOR_PREVALENCE_WEIGHT: float = 0.65
_COLOR_SATURATION_WEIGHT: float = 0.25
_COLOR_LUMA_BALANCE_WEIGHT: float = 0.10
_NEUTRAL_SATURATION_GATE: float = 0.20
_NEUTRAL_PREVALENCE_WEIGHT: float = 0.55
_COLOR_OWNERSHIP_MARGIN: float = 0.03
_COLOR_RELEASE_MARGIN: float = 0.03


class StickyClusterPicker:
    """Sticky representative-color picker with prevalence-aware chroma gating.

    K-means still uses 8 groups so meaningful scene colors remain separable,
    but color ownership now depends on how much of the sampled frame actually
    carries chroma. Tiny saturated UI/video accents cannot beat a predominantly
    neutral or dark composition merely by being vivid. Once the frame is
    meaningfully chromatic, cluster prevalence leads the score and sticky bias
    preserves stability across near-tied frames.
    """

    def __init__(self) -> None:
        # np.ndarray once populated; None before the first frame.
        self.last_center: Any = None
        self.last_picked_at: float = 0.0

    def pick(self, pixels: "np.ndarray") -> tuple[int, int, int]:
        """Pick a representative color via prevalence-aware K-means.

        Chromatic clusters are scored with prevalence as the dominant term,
        then saturation and luminance balance, and must beat the competing
        neutral/dark prevalence by a small ownership margin. Sticky bias only
        operates after chromatic ownership is earned. Otherwise the picker
        returns a population-weighted neutral center and releases prior vivid
        color.
        """
        now = time.time()
        prior = self.last_center
        if prior is not None and now - self.last_picked_at > _STICKY_STALENESS_SEC:
            prior = None

        # Keep enough clusters to separate meaningful scene colors, but seed
        # deterministically so identical frames cannot change merely because
        # k-means started from different centroids on the next 2.5s sample.
        kmeans = MiniBatchKMeans(
            n_clusters=8, batch_size=100, n_init=1, random_state=0
        )  # type: ignore[arg-type]
        kmeans.fit(pixels)

        centers = kmeans.cluster_centers_
        counts = np.bincount(kmeans.labels_, minlength=len(centers)).astype(np.float64)
        total = float(counts.sum())
        prevalence = counts / total if total else np.zeros(len(centers), dtype=float)

        cluster_rows: list[tuple[Any, float, float, float, bool]] = []
        neutral: list[tuple[float, Any]] = []
        neutral_share = 0.0
        for center, share in zip(centers, prevalence):
            r, g, b = center / 255.0
            _h, s, v = colorsys.rgb_to_hsv(r, g, b)
            chromatic = s > _COLOR_SATURATION_GATE and v > _COLOR_VALUE_MIN
            cluster_rows.append((center, float(share), s, v, chromatic))

            # Black/dark pixels are conservative even when sensor noise gives
            # them artificial HSV saturation. Low-saturation clusters preserve
            # genuine white/gray/soft-neutral page composition.
            if s <= _NEUTRAL_SATURATION_GATE or v <= _COLOR_VALUE_MIN:
                weight = float(share)
                neutral.append((weight, center))
                neutral_share += weight

        # K-means can split one broad scene color into several nearby centroids.
        # Score each candidate by the combined prevalence of chromatic centers
        # in its local RGB neighborhood so representative support does not
        # depend on arbitrary centroid fragmentation.
        scored: list[tuple[float, Any]] = []
        for center, _share, s, v, chromatic in cluster_rows:
            if not chromatic:
                continue
            support_share = sum(
                other_share
                for other_center, other_share, _os, _ov, other_chromatic in cluster_rows
                if other_chromatic
                and float(np.linalg.norm(other_center - center)) <= _COLOR_SUPPORT_DISTANCE
            )
            if support_share < _MIN_COLOR_CLUSTER_PREVALENCE:
                continue
            score = (
                support_share * _COLOR_PREVALENCE_WEIGHT
                + s * _COLOR_SATURATION_WEIGHT
                + (1.0 - abs(v - 0.5)) * _COLOR_LUMA_BALANCE_WEIGHT
            )
            scored.append((score, center))

        chosen: Any = None
        scored.sort(key=lambda t: t[0], reverse=True)
        if scored:
            best_score, best_center = scored[0]
            neutral_score = neutral_share * _NEUTRAL_PREVALENCE_WEIGHT
            prior_score: Optional[float] = None
            prior_center: Any = None
            prior_is_supported = False
            if prior is not None:
                prior_score, prior_center = min(
                    scored, key=lambda t: float(np.linalg.norm(t[1] - prior))
                )
                prior_is_supported = (
                    float(np.linalg.norm(prior_center - prior)) < _STICKY_DISTANCE
                )

            dominance = best_score - neutral_score
            color_owns = (
                not neutral
                or dominance > _COLOR_OWNERSHIP_MARGIN
                or (
                    prior_is_supported
                    and dominance > -_COLOR_RELEASE_MARGIN
                )
            )
            if color_owns:
                if (
                    prior_is_supported
                    and prior_score is not None
                    and best_score - prior_score < _STICKY_SCORE_MARGIN
                ):
                    chosen = prior_center

                if chosen is None:
                    chosen = best_center

        if chosen is None and neutral:
            neutral_weight = sum(weight for weight, _center in neutral)
            if neutral_weight > 0.0:
                chosen = sum(
                    (weight * center for weight, center in neutral),
                    start=np.zeros(3, dtype=np.float64),
                ) / neutral_weight

        if chosen is None:
            largest = int(np.argmax(counts))
            chosen = centers[largest]

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


def _foreground_snapshot_is_media(
    process_name: Optional[str],
    window_title: Optional[str],
    browser_playback_status: str = "unavailable",
) -> Optional[bool]:
    """Return immediate media intent for an already-captured foreground.

    ``None`` means the foreground looks like browser video but the OS playback
    probe could not resolve it. That preserves the backend's compatibility
    path instead of turning missing probe support into authoritative "not media".
    """
    if process_name in MEDIA_PROCESSES:
        return True
    if not browser_title_looks_like_video(process_name, window_title):
        return False
    if browser_playback_status in {"unavailable", "ambiguous"}:
        return None
    return browser_playback_status == "playing"


def _foreground_media_active() -> Optional[bool]:
    """Read foreground media intent without inheriting activity-mode dwell.

    ``None`` means the foreground identity could not be determined, allowing
    the backend to preserve compatibility/fail open rather than freezing sync
    because of a transient Win32/process-inspection failure.
    """
    if sys.platform != "win32":
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return False

        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""

        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process_name = psutil.Process(pid.value).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
        playback_status = _MEDIA_SESSION_PROBE.browser_playback_status(
            process_name,
            title,
        )
        return _foreground_snapshot_is_media(process_name, title, playback_status)
    except Exception:
        return None


def _build_color_payload(
    rgb: tuple[int, int, int], luma: int,
) -> dict[str, Any]:
    """Build a desktop color report with immediate foreground-media evidence."""
    return {
        "source": "desktop",
        "r": rgb[0], "g": rgb[1], "b": rgb[2],
        "luma": luma,
        "foreground_media": _foreground_media_active(),
    }


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
                                resp = client.post(
                                    color_endpoint, json=_build_color_payload(rgb, luma)
                                )
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
