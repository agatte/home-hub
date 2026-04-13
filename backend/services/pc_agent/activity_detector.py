"""
PC Activity Detector — standalone agent that monitors running processes.

Runs independently of the FastAPI server. Detects the user's current activity
(gaming, working, watching, idle, away) based on running processes and PC idle
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

# PC idle threshold for "away" mode (seconds)
IDLE_THRESHOLD = 600  # 10 minutes

# Late-night threshold for "working" detection (hour, 24h format)
LATE_NIGHT_START = 21  # 9 PM

# Sleep detection: no input for 15 min after 10:30 PM while media/browser is running
SLEEP_DETECT_HOUR = 22    # 10 PM
SLEEP_DETECT_MINUTE = 30  # :30
SLEEP_IDLE_THRESHOLD = 900  # 15 minutes


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
        idle    — PC in use but nothing notable running
        away    — PC has been idle for >10 minutes
    """

    def __init__(self) -> None:
        self._last_mode: Optional[str] = None
        self._media_paused: bool = False  # Track if we already paused media this sleep cycle

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

    def detect(self) -> str:
        """
        Determine the current activity mode based on running processes.

        Returns:
            One of: "gaming", "watching", "working", "idle", "away", "sleeping".
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

        # Standard away detection (idle >10 min, no special context)
        if idle_seconds > IDLE_THRESHOLD:
            return "away"

        # Reset media pause flag when user is active again
        if self._media_paused:
            self._media_paused = False
            logger.info("User active again — media pause flag reset")

        # Gaming takes highest priority
        if processes & GAME_PROCESSES:
            return "gaming"

        # Media player = watching
        if processes & MEDIA_PROCESSES:
            return "watching"

        # Dev/terminal processes = working
        if processes & WORK_PROCESSES:
            return "working"

        # Browser running late at night = working
        current_hour = datetime.now().hour
        if current_hour >= LATE_NIGHT_START or current_hour < 6:
            if processes & BROWSER_PROCESSES:
                return "working"

        return "idle"

    def has_changed(self, mode: str) -> bool:
        """Check if the mode has changed since last report."""
        changed = mode != self._last_mode
        self._last_mode = mode
        return changed


def run_agent(server_url: str) -> None:
    """
    Main loop — poll processes, report mode changes to the Home Hub server.

    Reports immediately on mode changes and periodically as a heartbeat
    so the server recovers quickly after restarts/deploys.

    Args:
        server_url: Base URL of the Home Hub backend (e.g., http://localhost:8000).
    """
    detector = ActivityDetector()
    endpoint = f"{server_url.rstrip('/')}/api/automation/activity"
    backoff = 1
    last_report_time: float = 0
    heartbeat_interval = 60  # Re-report current mode every 60s

    logger.info(f"PC Activity Detector started — reporting to {endpoint}")

    while True:
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

                # Report to server
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.post(
                            endpoint,
                            json={
                                "mode": mode,
                                "source": "process",
                                "detected_at": datetime.now().isoformat(),
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

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Activity detector stopped")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


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
