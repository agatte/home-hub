"""
PC Sleep Watcher — suspends the Windows desktop after sleeping mode persists.

Polls the Home Hub backend for the current automation mode. When mode flips
to ``sleeping``, arms a one-shot timer; if ``sleeping`` persists for the full
delay, calls Windows' ``SetSuspendState`` to put the machine to sleep. Any
mode change before the timer fires cancels it.

Runs only on Windows (no-op on other platforms). Registered as a managed
agent in ``backend/services/pc_agent/supervisor.py``.
"""
import logging
import sys
import ctypes
import ctypes.wintypes
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Logging — mirrors activity_detector / ambient_monitor patterns so output
# lands in the supervisor's rotating log file.
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "sleep_watcher.log"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("home_hub.sleep_watcher")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)


POLL_INTERVAL = 5            # Seconds between mode polls
SLEEP_DELAY_SECONDS = 3600   # 60 minutes — hardcoded per plan
LOCAL_INPUT_IDLE_VETO_SECONDS = 600  # 10 minutes — active keyboard/mouse vetoes suspend


def _get_local_input_idle_seconds() -> Optional[int]:
    """Return seconds since local keyboard/mouse input, or None if unavailable."""
    if sys.platform != "win32":
        return None

    try:

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.UINT),
                ("dwTime", ctypes.wintypes.DWORD),
            ]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None

        ctypes.windll.kernel32.GetTickCount.restype = ctypes.wintypes.DWORD
        now_tick = ctypes.windll.kernel32.GetTickCount()
        return ((now_tick - lii.dwTime) & 0xFFFFFFFF) // 1000
    except Exception as e:
        logger.debug("Local input idle read failed: %s", e)
        return None


def _suspend_pc() -> None:
    """Put Windows to sleep (S3). No-op on non-Windows platforms."""
    if sys.platform != "win32":
        logger.warning("Suspend requested on non-Windows platform — skipping")
        return
    import ctypes
    # SetSuspendState(hibernate=False, force=False, wakeup_disabled=False)
    ctypes.windll.powrprof.SetSuspendState(False, False, False)


def _fetch_mode(client: httpx.Client, server_url: str) -> Optional[str]:
    """Return the backend's current_mode, or None on error."""
    try:
        resp = client.get(f"{server_url.rstrip('/')}/api/automation/status")
        resp.raise_for_status()
        return resp.json().get("current_mode")
    except Exception as e:
        logger.debug("Mode fetch failed: %s", e)
        return None


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Main loop — poll mode, arm/disarm sleep timer, suspend Windows on fire.

    Arms whenever ``mode == 'sleeping'`` and no timer is already pending.
    Disarms on any other mode. On supervisor restart while already in
    sleeping mode, arms a fresh timer from the first observation.
    """
    if stop_event is None:
        stop_event = threading.Event()

    timer_deadline: Optional[float] = None  # Unix time when to suspend, or None

    logger.info(
        "Sleep watcher starting (server=%s, delay=%ds)",
        server_url, SLEEP_DELAY_SECONDS,
    )

    with httpx.Client(timeout=5.0) as client:
        while not stop_event.wait(POLL_INTERVAL):
            mode = _fetch_mode(client, server_url)
            if mode is None:
                continue  # Transient — leave timer state alone

            if mode == "sleeping":
                if timer_deadline is None:
                    timer_deadline = time.time() + SLEEP_DELAY_SECONDS
                    logger.info(
                        "Sleep timer armed — suspending in %ds",
                        SLEEP_DELAY_SECONDS,
                    )
            else:
                if timer_deadline is not None:
                    logger.info(
                        "Sleep timer cancelled — mode=%s",
                        mode,
                    )
                    timer_deadline = None

            if timer_deadline is not None:
                now = time.time()
                if now >= timer_deadline:
                    idle_seconds = _get_local_input_idle_seconds()
                    if (
                        idle_seconds is not None
                        and idle_seconds < LOCAL_INPUT_IDLE_VETO_SECONDS
                    ):
                        timer_deadline = now + SLEEP_DELAY_SECONDS
                        logger.info(
                            "Sleep timer fired but local input is active "
                            "(idle=%ds < %ds) — re-arming for %ds",
                            idle_seconds,
                            LOCAL_INPUT_IDLE_VETO_SECONDS,
                            SLEEP_DELAY_SECONDS,
                        )
                        continue

                    logger.info("Sleep timer fired — suspending PC")
                    timer_deadline = None
                    _suspend_pc()
                # On resume, the next poll re-evaluates from the current mode.
                # If user is still in sleeping (rare — they'd have woken to
                # use it), the timer re-arms and we cycle again.

    logger.info("Sleep watcher stopped")
