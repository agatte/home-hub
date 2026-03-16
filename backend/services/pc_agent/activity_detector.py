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
import ctypes
import ctypes.wintypes
import logging
import sys
import time
from datetime import datetime
from typing import Optional

import httpx
import psutil

from backend.services.pc_agent.game_list import (
    BROWSER_PROCESSES,
    GAME_PROCESSES,
    MEDIA_PROCESSES,
    WORK_PROCESSES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("home_hub.pc_agent")

# How often to poll processes (seconds)
POLL_INTERVAL = 15

# PC idle threshold for "away" mode (seconds)
IDLE_THRESHOLD = 600  # 10 minutes

# Late-night threshold for "working" detection (hour, 24h format)
LATE_NIGHT_START = 21  # 9 PM

# Sleep detection: no input for 15 min after 10:30 PM while media/browser is running
SLEEP_DETECT_HOUR = 22    # 10 PM
SLEEP_DETECT_MINUTE = 30  # :30
SLEEP_IDLE_THRESHOLD = 900  # 15 minutes


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

    Args:
        server_url: Base URL of the Home Hub backend (e.g., http://localhost:8000).
    """
    detector = ActivityDetector()
    endpoint = f"{server_url.rstrip('/')}/api/automation/activity"
    backoff = 1

    logger.info(f"PC Activity Detector started — reporting to {endpoint}")

    while True:
        try:
            mode = detector.detect()

            if detector.has_changed(mode):
                logger.info(f"Activity changed: {mode}")

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
    run_agent(args.server)
