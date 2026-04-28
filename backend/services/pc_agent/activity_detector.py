"""
PC Activity Detector — standalone agent that monitors running processes.

Runs independently of the FastAPI server. Detects the user's current activity
(gaming, working, watching, idle) based on running processes and PC idle
time, then reports changes to the Home Hub backend.

Usage:
    python -m backend.services.pc_agent.activity_detector
    python -m backend.services.pc_agent.activity_detector --server http://192.168.1.30:8000
"""
import argparse
import atexit
import ctypes
import ctypes.wintypes
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import httpx
import psutil

from backend.services.pc_agent.game_list import (
    BROWSER_PROCESSES,
    GAME_PROCESSES,
    MEDIA_PROCESSES,
    WATCHING_TITLE_KEYWORDS,
    WORK_PROCESSES,
)

# ---------------------------------------------------------------------------
# Logging — file + console (file captures errors even under pythonw.exe)
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "activity_detector.log"
PID_FILE = LOG_DIR / "activity_detector.pid"

LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("home_hub.pc_agent")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

# Console handler (no-op under pythonw.exe, but useful for manual runs)
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)

# Rotating file handler — 5 MB, 2 backups
_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)


# How often to poll processes (seconds). Sets the worst-case lag between
# starting an app (e.g., launching a game) and Home Hub reacting (lights +
# music). 5s gives ~2.5s average lag at negligible CPU cost on the desktop.
POLL_INTERVAL = 5

# PC idle threshold for "idle" mode (seconds) — input idle past this fires idle.
IDLE_THRESHOLD = 600  # 10 minutes

# Late-night threshold for "working" detection (hour, 24h format)
LATE_NIGHT_START = 21  # 9 PM

# Sleep detection: no input for 15 min after 10:30 PM while media/browser is running
SLEEP_DETECT_HOUR = 22    # 10 PM
SLEEP_DETECT_MINUTE = 30  # :30
SLEEP_IDLE_THRESHOLD = 900  # 15 minutes

# Hysteresis — how long a candidate mode must persist before the detector
# commits to it. Prevents quick alt-tabs (e.g. peeking at Slack mid-video,
# running a one-line command mid-YouTube) from churning the lights/music.
DWELL_DEFAULT = 60.0           # All transitions default to 60s of sustained focus
DWELL_LEAVE_WATCHING_DAY = 10.0    # Returning to work from a video — be responsive
DWELL_LEAVE_WATCHING_NIGHT = 300.0  # Sticky watching at night (5 min) — no lights flip when running a quick command in bed
DWELL_LEAVE_WORKING_NIGHT = 300.0   # Symmetric counterpart: once committed working at night, don't flip to watching for 5 min either. Kills the watching↔working alt-tab cycle when Stremio + code are both running.
NIGHT_START_HOUR = 21
NIGHT_END_HOUR = 6

# Gaming gate — a game process being merely *running* is not enough.
# leagueclient.exe and similar launchers persist long after the actual game
# closes; without this gate, mode would lock to "gaming" until Anthony quit
# the launcher. Either of two conditions promotes a running game process to
# committed gaming: (a) the game is the foreground window (you're playing
# right now), or (b) input has been active in the last GAMING_IDLE_THRESHOLD
# seconds (you're at the PC with the game running — covers alt-tab-to-wiki
# scrolling). Walking away from the PC = idle climbs past the threshold and
# the gaming hold releases, allowing late-night rescue / fusion to take over.
GAMING_IDLE_THRESHOLD = 180  # seconds


# ---------------------------------------------------------------------------
# Single-instance PID lock
# ---------------------------------------------------------------------------


def _is_detector_process(proc: psutil.Process) -> bool:
    """Check if a process is an activity_detector instance."""
    try:
        cmdline = " ".join(proc.cmdline()).lower()
        return "activity_detector" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            logger.info(f"Killing child process {child.pid} ({child.name()})")
            child.kill()
        parent.kill()
        logger.info(f"Killed process {pid}")
        # Wait for processes to actually terminate
        gone, alive = psutil.wait_procs([parent, *children], timeout=5)
        for p in alive:
            logger.warning(f"Process {p.pid} did not terminate, forcing")
            p.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        logger.error(f"Error killing process tree {pid}: {e}")


def acquire_pid_lock() -> None:
    """Ensure only one detector instance runs. Kill any existing instance."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            old_proc = psutil.Process(old_pid)
            if _is_detector_process(old_proc):
                logger.info(
                    f"Found existing detector (PID {old_pid}) — killing it"
                )
                _kill_process_tree(old_pid)
                time.sleep(1)
            else:
                logger.info(
                    f"PID file points to {old_pid} ({old_proc.name()}) "
                    f"— not a detector, ignoring"
                )
        except (psutil.NoSuchProcess, ValueError):
            logger.info("Stale PID file found — removing")
        except Exception as e:
            logger.warning(f"Error checking existing PID: {e}")

    # Also scan for any orphaned detector processes not tracked by PID file
    my_pid = os.getpid()
    # Build set of PIDs in our own process ancestry (don't kill our parents)
    my_ancestors: set[int] = {my_pid}
    try:
        p = psutil.Process(my_pid)
        while p.ppid() and p.ppid() != p.pid:
            my_ancestors.add(p.ppid())
            p = psutil.Process(p.ppid())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    for proc in psutil.process_iter(["pid", "name"]):
        pid = proc.info["pid"]
        if pid in my_ancestors:
            continue
        try:
            if _is_detector_process(proc):
                logger.info(
                    f"Found orphaned detector (PID {pid}) — killing"
                )
                _kill_process_tree(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Write our PID
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"PID lock acquired (PID {os.getpid()}, file: {PID_FILE})")


def release_pid_lock() -> None:
    """Remove the PID file on clean exit."""
    try:
        if PID_FILE.exists():
            stored_pid = int(PID_FILE.read_text().strip())
            if stored_pid == os.getpid():
                PID_FILE.unlink()
                logger.info("PID lock released")
    except Exception:
        pass


class ActivityDetector:
    """
    Monitors running processes to determine user activity mode.

    Modes:
        gaming  — A game process is running (no Discord dependency)
        watching — A media player is running
        working — Browser running late at night, no game or media
        idle    — PC in use but nothing notable running, or input idle >10 min
    """

    def __init__(self) -> None:
        self._last_mode: Optional[str] = None              # Committed mode after dwell
        self._last_reported_mode: Optional[str] = None      # Last mode the loop POSTed
        self._media_paused: bool = False                    # Track if we already paused media this sleep cycle
        # Hysteresis state — the candidate mode we'd report once the dwell expires.
        self._pending_mode: Optional[str] = None
        self._pending_since: Optional[float] = None

    def _get_running_process_names(self) -> set[str]:
        """Get lowercase names of all running processes."""
        names: set[str] = set()
        try:
            for proc in psutil.process_iter(["name"]):
                name = proc.info.get("name")
                if name:
                    names.add(name.lower())
        except (psutil.Error, OSError):
            pass
        return names

    def _get_idle_seconds(self) -> int:
        """
        Get seconds since last user input (keyboard/mouse) via Win32 API.

        Returns 0 on non-Windows or on error.
        """
        try:

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.UINT),
                    ("dwTime", ctypes.wintypes.DWORD),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return millis // 1000
        except Exception:
            pass
        return 0

    def _pause_media(self) -> None:
        """
        Send a media play/pause key via Win32 to pause YouTube or other media.

        Only fires once per sleep cycle to avoid toggling play/pause repeatedly.
        """
        if self._media_paused:
            return
        try:
            VK_MEDIA_PLAY_PAUSE = 0xB3
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
            self._media_paused = True
            logger.info("Sent media pause key (sleep detected)")
        except Exception as e:
            logger.error(f"Failed to send media pause key: {e}")

    def _is_sleep_window(self) -> bool:
        """Check if current time is past the sleep detection threshold (10:30 PM)."""
        now = datetime.now()
        return (
            (now.hour > SLEEP_DETECT_HOUR)
            or (now.hour == SLEEP_DETECT_HOUR and now.minute >= SLEEP_DETECT_MINUTE)
            or (now.hour < 6)  # Also covers past midnight
        )

    def _get_foreground_window(self) -> tuple[Optional[str], Optional[str]]:
        """
        Get the (process_name, window_title) of the currently focused window.

        Uses Win32 GetForegroundWindow + GetWindowTextW. Returns (None, None)
        on failure or when nothing is focused (e.g. desktop visible).
        """
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None, None

            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""

            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = None

            return proc_name, title
        except Exception:
            return None, None

    def _classify(self) -> str:
        """
        Compute the *candidate* activity mode from current process + focus state.

        This is the raw read every poll; hysteresis is applied separately in
        ``detect()`` so quick alt-tabs don't churn the reported mode.
        """
        idle_seconds = self._get_idle_seconds()
        processes = self._get_running_process_names()

        # Sleep detection: no input for 15 min after 10:30 PM with media/browser running
        if (
            idle_seconds > SLEEP_IDLE_THRESHOLD
            and self._is_sleep_window()
            and (processes & MEDIA_PROCESSES or processes & BROWSER_PROCESSES)
        ):
            self._pause_media()
            return "sleeping"

        # Standard idle detection (input idle >10 min, no special context)
        if idle_seconds > IDLE_THRESHOLD:
            return "idle"

        # Reset media pause flag when user is active again
        if self._media_paused:
            self._media_paused = False
            logger.info("User active again — media pause flag reset")

        # Gaming takes highest priority — but only when the player is
        # actually playing. A merely-running game process (e.g. leagueclient.exe
        # launcher persisting after match close) must NOT lock mode to gaming.
        # Promote to gaming only when the game is foregrounded OR input has
        # been active recently with a game running. See GAMING_IDLE_THRESHOLD
        # docstring above.
        if processes & GAME_PROCESSES:
            fg_proc, _ = self._get_foreground_window()
            if fg_proc in GAME_PROCESSES:
                return "gaming"
            if idle_seconds < GAMING_IDLE_THRESHOLD:
                return "gaming"
            # Game process exists but is unfocused AND user is idle —
            # likely an abandoned launcher. Fall through to normal detection.

        # Media / work / browser disambiguation via foreground window.
        # Media apps (especially Stremio) leave background services running
        # after the main window closes; those services must not be classified
        # as "watching" when a dev tool is the actual foreground. Resolution:
        # check the foreground first, and only return "watching" when either
        # (a) a media app is the foreground window, (b) a browser tab title
        # looks like media playback, or (c) media is running and no work
        # tools are present (preserves passive media-watching behavior).
        media_running = bool(processes & MEDIA_PROCESSES)
        work_running = bool(processes & WORK_PROCESSES)
        browser_running = bool(processes & BROWSER_PROCESSES)

        if media_running or work_running or browser_running:
            fg_proc, fg_title = self._get_foreground_window()

            if fg_proc in MEDIA_PROCESSES:
                return "watching"

            if (
                fg_proc in BROWSER_PROCESSES
                and fg_title
                and any(kw in fg_title.lower() for kw in WATCHING_TITLE_KEYWORDS)
            ):
                return "watching"

            if work_running:
                return "working"

            if media_running:
                # Media running with no work tools and foreground isn't
                # recognized — likely passive watching (e.g. tray media player).
                return "watching"

        # Browser running late at night = working
        current_hour = datetime.now().hour
        if current_hour >= LATE_NIGHT_START or current_hour < 6:
            if browser_running:
                return "working"

        return "idle"

    def _dwell_threshold(self, from_mode: Optional[str], to_mode: str) -> float:
        """
        How long the candidate mode must persist before we commit to reporting it.

        Most transitions use DWELL_DEFAULT. Two night-only stickiness rules
        kill the watching↔working flap when both apps are open:

        - Leaving watching at night: 5 min (a brief command run while a video
          plays shouldn't flip lights to working).
        - Leaving working *to watching* at night: also 5 min (symmetric — a
          brief peek at a video while coding shouldn't flip the other way).

        Day stays responsive in both directions.
        """
        hour = datetime.now().hour
        is_night = hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR

        if from_mode == "watching" and to_mode != "watching":
            return DWELL_LEAVE_WATCHING_NIGHT if is_night else DWELL_LEAVE_WATCHING_DAY
        if is_night and from_mode == "working" and to_mode == "watching":
            return DWELL_LEAVE_WORKING_NIGHT
        return DWELL_DEFAULT

    def detect(self) -> str:
        """
        Return the currently committed mode, applying hysteresis to the raw read.

        A candidate mode must persist for the dwell threshold (see
        ``_dwell_threshold``) before it becomes the reported mode.
        """
        candidate = self._classify()
        now = time.time()

        # First poll — accept immediately, no dwell.
        if self._last_mode is None:
            self._last_mode = candidate
            self._pending_mode = None
            self._pending_since = None
            return candidate

        # Candidate matches the committed mode — clear any pending switch.
        if candidate == self._last_mode:
            if self._pending_mode is not None:
                logger.debug(
                    "Pending switch to %s aborted (returned to %s)",
                    self._pending_mode, self._last_mode,
                )
            self._pending_mode = None
            self._pending_since = None
            return self._last_mode

        # New candidate — start (or restart) the dwell timer.
        if self._pending_mode != candidate:
            self._pending_mode = candidate
            self._pending_since = now
            logger.debug(
                "Pending switch %s → %s (dwell %.0fs required)",
                self._last_mode, candidate,
                self._dwell_threshold(self._last_mode, candidate),
            )
            return self._last_mode

        # Same candidate as last poll — has it persisted long enough to commit?
        threshold = self._dwell_threshold(self._last_mode, candidate)
        if (now - (self._pending_since or now)) >= threshold:
            logger.info(
                "Mode committed: %s → %s (dwelled %.0fs)",
                self._last_mode, candidate, threshold,
            )
            self._last_mode = candidate
            self._pending_mode = None
            self._pending_since = None

        return self._last_mode

    def has_changed(self, mode: str) -> bool:
        """Check if the reported mode has changed since the last call."""
        changed = mode != self._last_reported_mode
        self._last_reported_mode = mode
        return changed

    def build_factors(self) -> list[dict]:
        """Build sub-factor list describing what this lane is seeing.

        Surfaced to the analytics constellation UI. Keeps shape consistent
        with the fusion ``factors`` contract — each entry is a dict with
        ``key``/``label``/``value``/``display``/``impact`` keys.
        """
        fg_proc, fg_title = self._get_foreground_window()
        idle_seconds = self._get_idle_seconds()
        processes = self._get_running_process_names()

        # Foreground bucket — what category is the current focus?
        if fg_proc and fg_proc in GAME_PROCESSES:
            fg_kind = "game"
        elif fg_proc and fg_proc in MEDIA_PROCESSES:
            fg_kind = "media"
        elif fg_proc and fg_proc in WORK_PROCESSES:
            fg_kind = "dev"
        elif fg_proc and fg_proc in BROWSER_PROCESSES:
            fg_kind = "browser"
        elif fg_proc:
            fg_kind = "other"
        else:
            fg_kind = "none"

        # Idle bucket with a readable display
        if idle_seconds < 60:
            idle_display = "active"
            idle_impact = 1.0
        elif idle_seconds < IDLE_THRESHOLD:
            idle_display = f"{idle_seconds // 60}m idle"
            idle_impact = 0.6
        else:
            idle_display = f"{idle_seconds // 60}m idle"
            idle_impact = 0.3

        factors: list[dict] = [
            {
                "key": "foreground",
                "label": "Foreground",
                "value": fg_proc or "none",
                "display": (fg_proc or "none"),
                "impact": 1.0 if fg_kind in ("game", "media", "dev") else 0.5,
            },
            {
                "key": "idle",
                "label": "Input",
                "value": idle_seconds,
                "display": idle_display,
                "impact": idle_impact,
            },
            {
                "key": "foreground_kind",
                "label": "Kind",
                "value": fg_kind,
                "display": fg_kind,
                "impact": 0.7,
            },
        ]

        # Only surface browser flag when it's actually load-bearing (late night).
        current_hour = datetime.now().hour
        is_late = current_hour >= LATE_NIGHT_START or current_hour < 6
        if is_late:
            browser_running = bool(processes & BROWSER_PROCESSES)
            factors.append({
                "key": "browser",
                "label": "Browser",
                "value": browser_running,
                "display": "on" if browser_running else "off",
                "impact": 0.8 if browser_running else 0.2,
            })

        return factors[:4]


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Main loop — poll processes, report mode changes to the Home Hub server.

    Reports immediately on mode changes and periodically as a heartbeat
    so the server recovers quickly after restarts/deploys.

    Args:
        server_url: Base URL of the Home Hub backend (e.g., http://localhost:8000).
        stop_event: Optional threading event for clean shutdown (set by supervisor).
    """
    detector = ActivityDetector()
    endpoint = f"{server_url.rstrip('/')}/api/automation/activity"
    backoff = 1
    last_report_time: float = 0
    heartbeat_interval = 15  # Re-report current mode every 15s

    _stop = stop_event or threading.Event()
    client = httpx.Client(timeout=5.0)

    logger.info(f"PC Activity Detector started — reporting to {endpoint}")

    try:
        while not _stop.is_set():
            try:
                mode = detector.detect()
                now = time.time()
                mode_changed = detector.has_changed(mode)
                heartbeat_due = (now - last_report_time) >= heartbeat_interval

                if mode_changed or heartbeat_due:
                    if mode_changed:
                        logger.info(f"Activity changed: {mode}")
                    else:
                        logger.debug(f"Heartbeat: {mode}")

                    try:
                        resp = client.post(
                            endpoint,
                            json={
                                "mode": mode,
                                "source": "process",
                                "detected_at": datetime.now().isoformat(),
                                "factors": detector.build_factors(),
                            },
                        )
                        resp.raise_for_status()
                        last_report_time = now
                        if mode_changed:
                            logger.info(f"Reported '{mode}' to server (HTTP {resp.status_code})")
                        backoff = 1
                    except httpx.HTTPError as e:
                        logger.warning(f"Failed to report to server: {e}")
                        backoff = min(backoff * 2, 60)

                _stop.wait(POLL_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Activity detector stopped")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                _stop.wait(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Home Hub PC Activity Detector")
    parser.add_argument(
        "--server",
        default="http://localhost:8000",
        help="Home Hub server URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    acquire_pid_lock()
    atexit.register(release_pid_lock)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    run_agent(args.server)
