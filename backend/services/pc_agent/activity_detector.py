"""
PC Activity Detector — standalone agent that monitors running processes.

Runs independently of the FastAPI server. Detects the user's current activity
(gaming, working, watching, idle) based on running processes and PC idle
time, then reports changes to the Home Hub backend.

Usage:
    python -m backend.services.pc_agent.activity_detector
    python -m backend.services.pc_agent.activity_detector --server http://192.168.86.30:8000
"""
import argparse
import atexit
import ctypes
import ctypes.wintypes
import logging
import os
import re
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import psutil

from backend.config import settings
from backend.services.pc_agent.game_list import (
    BROWSER_PROCESSES,
    GAME_NAME_BY_PROCESS,
    LOL_PROCESSES,
    get_game_processes,
    MEDIA_PROCESSES,
    WATCHING_TITLE_KEYWORDS,
    WORK_PROCESSES,
)

# Riot Games' Live Client Data API runs locally when a League match is in
# progress (champion select / loading screen returns 404). Self-signed cert
# bound to 127.0.0.1; verify=False is bounded to this single localhost
# endpoint. The 30s freshness window matches steady-in-match cadence —
# champion doesn't change mid-game.
#
# Endpoint moved from /activeplayer to /allgamedata on 2026-05-18: Riot
# dropped the active player's ``championName`` from /activeplayer, so the
# resolver now reads it off the matching entry in the ``allPlayers``
# roster instead (matched by ``riotId``). /allgamedata is one HTTPS GET
# vs the two-endpoint alternative, so timeout budget stays flat.
LOL_LIVE_CLIENT_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
LOL_CHAMPION_CACHE_TTL_S = 30.0
LOL_CHAMPION_HTTP_TIMEOUT_S = 2.0

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

# Sleep detection: no input for 15 min after 10:30 PM while explicit foreground
# media is selected. A merely open browser is not intent; Firefox can route the
# global media key to a background YouTube tab.
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
# Sticky-watching tolerance — if the candidate was ``watching`` within the
# last N seconds, brief terminal/IDE polls don't reset the dwell. Without
# this, a user in bed with YouTube who alt-tabs to type a quick command
# (eg chatting with Claude Code) keeps resetting the working→watching
# dwell to 0; 5-min sustained-firefox is unreachable when each terminal
# poll counts as a fresh "working" candidate. 90s = comfortable for a
# few command lines + reading replies before going back to the video.
# 2026-05-18 root cause for "watching never triggered tonight" — diagnosed
# via ml_decisions factor history showing firefox ↔ windowsterminal
# bouncing every 30–60s.
WATCHING_STICKY_SECONDS = 90.0
NIGHT_START_HOUR = 21
NIGHT_END_HOUR = 6
MAX_MATCHED_WORK_PROCESSES = 3

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

RUNELITE_JAVA_WINDOW_TITLE_RE = re.compile(
    r"^runelite(?:\s*[-–—]\s*.+)?$", re.IGNORECASE
)



def _device_role() -> str:
    """Stable activity-source role for backend source ownership decisions."""
    configured = (
        os.environ.get("HOME_HUB_AGENT_DEVICE")
        or settings.HOME_HUB_AGENT_DEVICE
        or ""
    ).strip().lower()
    if configured:
        return configured
    hostname = socket.gethostname().strip().lower()
    if "latitude" in hostname:
        return "latitude"
    return "desktop"


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


@dataclass
class _Classification:
    """Bounded diagnostic state for one classifier poll."""

    candidate_mode: str
    candidate_reason: str
    foreground_process: Optional[str]
    foreground_kind: str
    matched_work_processes: tuple[str, ...]
    matched_game_process: Optional[str]
    gaming_qualification: Optional[str]
    idle_seconds: int
    browser_running: bool
    active_game: Optional[str]
    classified_mode: Optional[str] = None
    pending_mode: Optional[str] = None
    pending_dwell_age: Optional[float] = None


class ActivityDetector:
    """
    Monitors running processes to determine user activity mode.

    Modes:
        gaming  — A game is foregrounded or has recent user input
        watching — A media player is running
        working — Foreground developer tool, or browser running late at night
        idle    — PC in use but nothing notable running, or input idle >10 min
    """

    def __init__(self) -> None:
        self._last_mode: Optional[str] = None              # Committed mode after dwell
        self._last_reported_mode: Optional[str] = None      # Last mode the loop POSTed
        self._last_classification: Optional[_Classification] = None
        self._media_paused: bool = False                    # Track if we already paused media this sleep cycle
        # When _pause_media() injects a media key, Windows records it as user
        # input — GetLastInputInfo can't distinguish our synthetic keystroke
        # from a real one. We remember the exact input-tick our key produces
        # (_synthetic_last_input_tick) and the user's real last-input tick
        # just before injection (_real_last_input_tick) so _get_idle_seconds
        # can fold our own keystroke out and keep idle climbing. Without this
        # the detector reads its own pause key as "user returned" and
        # oscillates working<->idle all night while the apartment is empty
        # (root cause of the 2026-05-29 "awake while away" incident).
        self._real_last_input_tick: Optional[int] = None
        self._synthetic_last_input_tick: Optional[int] = None
        # True only when the latest Win32 idle probe succeeded. Idle=0 is
        # otherwise ambiguous with an unavailable probe and must never prove
        # contemporaneous human interaction to the backend.
        self._input_idle_valid: bool = False
        # Hysteresis state — the candidate mode we'd report once the dwell expires.
        self._pending_mode: Optional[str] = None
        self._pending_since: Optional[float] = None
        # Last time _classify returned ``watching``. Powers the sticky-watching
        # tolerance in detect() — brief working candidates during a YouTube
        # session (terminal alt-tab) don't reset the dwell timer.
        self._last_watching_candidate_at: Optional[float] = None
        # LoL Live Client Data cache — avoids hammering the localhost API
        # every 5s when the champion doesn't change mid-match.
        self._lol_champion: Optional[str] = None
        self._lol_champion_at: float = 0.0
        self._lol_last_failure_reason: Optional[str] = None
        # Reusable HTTPS client for the LoL Live Client endpoint. Lazy-allocated
        # on first successful gate (LoL process present) so non-LoL sessions
        # never pay the client construction cost. verify=False is bounded to
        # 127.0.0.1:2999 — same pattern as the backend's Hue v2 client.
        self._lol_http_client: Optional[httpx.Client] = None

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

    def _read_last_input(self) -> Optional[tuple[int, int]]:
        """Return ``(now_tick, last_input_tick)`` from Win32, or None on error.

        Both are raw 32-bit GetTickCount millisecond values. Split out from
        ``_get_idle_seconds`` so ``_pause_media`` can capture the exact tick
        its injected key registers (see ``_synthetic_last_input_tick``).
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
                # Declare DWORD return so GetTickCount comes back unsigned;
                # ctypes defaults to signed c_int, which sign-extends to a
                # negative int above ~24.7 days of uptime. (The & 0xFFFFFFFF
                # mask in _get_idle_seconds still yields the right delta, but
                # unsigned is what these values actually are.)
                ctypes.windll.kernel32.GetTickCount.restype = ctypes.wintypes.DWORD
                now_tick = ctypes.windll.kernel32.GetTickCount()
                return now_tick, lii.dwTime
        except Exception:
            pass
        return None

    def _get_idle_seconds(self) -> int:
        """
        Get seconds since last user input (keyboard/mouse) via Win32 API.

        Folds out the synthetic media key our own ``_pause_media`` injects: if
        the most recent input is exactly the keystroke we sent, idle is
        measured from the user's real last input instead, so it keeps
        climbing. Otherwise the detector treats its own pause key as the user
        returning and flaps working<->idle all night when the apartment is
        empty (root cause of the 2026-05-29 "awake while away" incident).

        Returns 0 on non-Windows or on error for legacy classifier behavior;
        ``_input_idle_valid`` separately records whether that value is trustworthy.
        """
        reading = self._read_last_input()
        if reading is None:
            self._input_idle_valid = False
            return 0
        self._input_idle_valid = True
        now_tick, last_input_tick = reading
        if (
            self._synthetic_last_input_tick is not None
            and last_input_tick == self._synthetic_last_input_tick
            and self._real_last_input_tick is not None
        ):
            # The latest "input" is the media key we injected — ignore it and
            # measure idle from the user's genuine last input. A real keystroke
            # landing on the exact same GetTickCount ms as the synthetic key
            # would false-match here, but it self-corrects on the next poll (5s).
            last_input_tick = self._real_last_input_tick
        # GetTickCount is a 32-bit ms counter; mask the delta so a wrap
        # (every ~49.7 days of uptime) can't produce a negative idle.
        return ((now_tick - last_input_tick) & 0xFFFFFFFF) // 1000

    def _pause_media(self) -> None:
        """
        Send a media play/pause key via Win32 to pause YouTube or other media.

        Only fires once per sleep cycle to avoid toggling play/pause
        repeatedly. Captures the user's real last-input tick before injecting
        and the synthetic tick our key produces afterward, so
        ``_get_idle_seconds`` can discount the keystroke — otherwise it resets
        our own idle reading and the detector flaps awake all night.
        """
        if self._media_paused:
            return
        # The user's genuine last-input tick, captured before we inject.
        pre = self._read_last_input()
        if pre is not None:
            self._real_last_input_tick = pre[1]
        try:
            VK_MEDIA_PLAY_PAUSE = 0xB3
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)
            self._media_paused = True
            # Exact input-tick our injected key just registered — lets
            # _get_idle_seconds recognize and fold out our own keystroke.
            post = self._read_last_input()
            if post is not None:
                self._synthetic_last_input_tick = post[1]
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

    def _get_foreground_process_identity(
        self,
    ) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """Get the name, title, and PID of the currently focused window."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None, None, None

            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value or ""

            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                proc_name = psutil.Process(pid.value).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None, title, None

            return proc_name, title, pid.value
        except Exception:
            return None, None, None

    @staticmethod
    def _command_line_has_runelite_client_marker(command_line: list[str]) -> bool:
        """Return whether a Java command line has conclusive RuneLite identity."""
        normalized = " ".join(command_line).lower().replace("/", "\\")
        return "net.runelite\\client" in normalized

    def _pid_has_runelite_client_marker(self, pid: int) -> bool:
        """Fail closed unless ``pid`` exposes the conclusive RuneLite marker."""
        try:
            return self._command_line_has_runelite_client_marker(
                psutil.Process(pid).cmdline(),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            return False

    def _find_running_runelite_java_pid(self) -> Optional[int]:
        """Find a live Java RuneLite client even when another app is foreground.

        Only java.exe/javaw.exe candidates are inspected. Gradle daemons, IDE
        runtimes, and unrelated Java processes fail closed unless their own
        command line contains RuneLite's ``net.runelite\\client`` classpath
        marker. No sticky state is retained: process exit or PID reuse removes
        the evidence on the next poll.
        """
        try:
            processes = psutil.process_iter(["pid", "name"])
        except (psutil.Error, OSError):
            return None

        try:
            for proc in processes:
                try:
                    name = (proc.info.get("name") or "").lower()
                    if name not in {"java.exe", "javaw.exe"}:
                        continue
                    if self._command_line_has_runelite_client_marker(proc.cmdline()):
                        return int(proc.info["pid"])
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                    OSError,
                    TypeError,
                    ValueError,
                ):
                    continue
        except (psutil.Error, OSError):
            return None
        return None

    def _is_foreground_runelite_java(
        self,
        process_name: Optional[str],
        window_title: Optional[str],
        pid: Optional[int],
    ) -> bool:
        """Return whether the focused Java client is conclusively RuneLite."""
        if (
            process_name not in {"java.exe", "javaw.exe"}
            or not window_title
            or pid is None
            or not RUNELITE_JAVA_WINDOW_TITLE_RE.fullmatch(window_title)
        ):
            return False
        return self._pid_has_runelite_client_marker(pid)

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
        fg_proc, fg_title, fg_pid = self._get_foreground_process_identity()
        game_processes = get_game_processes()
        matched_work_processes = tuple(
            sorted(processes & WORK_PROCESSES)[:MAX_MATCHED_WORK_PROCESSES]
        )
        matched_game_process = (
            fg_proc if fg_proc in game_processes
            else next(iter(sorted(processes & game_processes)), None)
        )
        browser_running = bool(processes & BROWSER_PROCESSES)
        running_runelite_java_pid = (
            self._find_running_runelite_java_pid()
            if processes & {"java.exe", "javaw.exe"}
            else None
        )
        if matched_game_process is None and running_runelite_java_pid is not None:
            matched_game_process = "runelite-java"
        gaming_qualification_reason: Optional[str] = None

        if fg_proc and fg_proc in game_processes:
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

        def classified(
            mode: str,
            reason: str,
            gaming_qualification: Optional[str] = None,
        ) -> str:
            self._last_classification = _Classification(
                candidate_mode=mode,
                candidate_reason=reason,
                foreground_process=fg_proc,
                foreground_kind=fg_kind,
                matched_work_processes=matched_work_processes,
                matched_game_process=matched_game_process,
                gaming_qualification=(
                    gaming_qualification or gaming_qualification_reason
                ),
                idle_seconds=idle_seconds,
                browser_running=browser_running,
                active_game=self._resolve_active_game(fg_proc, processes),
            )
            return mode

        # Sleep detection: no input for 15 min after 10:30 PM with explicit
        # foreground media. Do not treat "browser is open" as media intent:
        # Firefox may route the global media key to a background YouTube tab
        # even while the selected tab is Reddit/GitHub/etc.
        if (
            idle_seconds > SLEEP_IDLE_THRESHOLD
            and self._is_sleep_window()
            and self._foreground_snapshot_is_media(fg_proc, fg_title)
        ):
            self._pause_media()
            return classified("sleeping", "sleep_foreground_media")

        # Standard idle detection (input idle >10 min, no special context)
        if idle_seconds > IDLE_THRESHOLD:
            return classified("idle", "global_input_idle")

        # Reset media pause flag when user is active again. Real input has
        # arrived (idle dropped below the threshold), so clear the synthetic-
        # keystroke tracking too — the next sleep cycle recaptures it.
        if self._media_paused:
            self._media_paused = False
            self._real_last_input_tick = None
            self._synthetic_last_input_tick = None
            logger.info("User active again — media pause flag reset")

        # Gaming takes highest priority — but only when the player is
        # actually playing. A merely-running game process (e.g. leagueclient.exe
        # launcher persisting after match close) must NOT lock mode to gaming.
        # Promote to gaming only when the game is foregrounded OR input has
        # been active recently with a game running. See GAMING_IDLE_THRESHOLD
        # docstring above.
        if self._is_foreground_runelite_java(fg_proc, fg_title, fg_pid):
            return classified("gaming", "foreground_game", "foreground_runelite_java")

        if fg_proc in game_processes:
            return classified("gaming", "foreground_game", "foreground_game")

        has_regular_game = bool(processes & game_processes)
        has_background_runelite_java = running_runelite_java_pid is not None
        if has_regular_game or has_background_runelite_java:
            if idle_seconds < GAMING_IDLE_THRESHOLD:
                qualification = (
                    "recent_input_runelite_java_hold"
                    if has_background_runelite_java and not has_regular_game
                    else "recent_input_game_hold"
                )
                return classified("gaming", "recent_input_game_hold", qualification)
            # A verified background game exists, but recent real input has
            # expired. Release Gaming normally instead of inventing a sticky
            # RuneLite/browser exception.
            gaming_qualification_reason = (
                "background_runelite_java_idle"
                if has_background_runelite_java and not has_regular_game
                else "background_game_idle"
            )

        # Media / work / browser disambiguation via foreground window.
        # Media apps (especially Stremio) leave background services running
        # after the main window closes; those services must not be classified
        # as "watching" when a dev tool is the actual foreground. Resolution:
        # check the foreground first, and only return "watching" when either
        # (a) a media app is the foreground window, (b) a browser tab title
        # looks like media playback, or (c) media is running without a
        # foreground work window (preserves passive media-watching behavior).
        media_running = bool(processes & MEDIA_PROCESSES)
        work_running = bool(matched_work_processes)

        if media_running or work_running or browser_running:
            if fg_proc in MEDIA_PROCESSES:
                return classified("watching", "foreground_media")

            if (
                fg_proc in BROWSER_PROCESSES
                and fg_title
                and any(kw in fg_title.lower() for kw in WATCHING_TITLE_KEYWORDS)
            ):
                return classified("watching", "foreground_browser_media")

            if fg_proc in WORK_PROCESSES:
                return classified("working", "foreground_work")

            if media_running:
                # Media running with no foreground work window and foreground
                # isn't otherwise recognized — likely passive watching (e.g.
                # tray media player).
                return classified("watching", "background_media")

        # Browser running late at night = working
        current_hour = datetime.now().hour
        if current_hour >= LATE_NIGHT_START or current_hour < 6:
            if browser_running:
                return classified("working", "late_night_browser")

        return classified("idle", "fallback_idle")

    def _foreground_is_media(self) -> bool:
        """
        True when the user is *explicitly* looking at a video right now.

        Either the foreground process is a known media player, or the
        foreground window is a browser whose title matches one of
        WATCHING_TITLE_KEYWORDS (YouTube, Twitch, Netflix, …). This is an
        unambiguous-intent signal — the user opened the video tab and put
        it front-and-center.
        """
        fg_proc, fg_title = self._get_foreground_window()
        return self._foreground_snapshot_is_media(fg_proc, fg_title)

    @staticmethod
    def _foreground_snapshot_is_media(
        fg_proc: Optional[str],
        fg_title: Optional[str],
    ) -> bool:
        """Evaluate media intent from an already-captured foreground snapshot."""
        if fg_proc in MEDIA_PROCESSES:
            return True
        if fg_proc in BROWSER_PROCESSES and fg_title:
            title_lower = fg_title.lower()
            if any(kw in title_lower for kw in WATCHING_TITLE_KEYWORDS):
                return True
        return False

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

        Fast-path: an explicit foreground media window (YouTube tab is the
        active window, Stremio is foregrounded, …) commits to ``watching``
        on DWELL_DEFAULT regardless of time of day. The 300s night gate was
        protecting against alt-tab churn — when YouTube is literally the
        foreground window, that's not churn, that's intent.
        """
        hour = datetime.now().hour
        is_night = hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR

        # Explicit foreground intent overrides night stickiness — see docstring.
        if to_mode == "watching" and self._foreground_is_media():
            return DWELL_DEFAULT

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

        # Sticky-watching tolerance: once we've seen ``watching`` recently,
        # brief ``working`` candidates (typically terminal/IDE alt-tabs in
        # the middle of a YouTube session) get treated as continuing
        # ``watching`` for hysteresis purposes. Without this, the strict
        # consecutive dwell at night (DWELL_LEAVE_WORKING_NIGHT=300s) is
        # unreachable when the user pops back to a terminal every minute.
        # See WATCHING_STICKY_SECONDS for the rationale.
        hour = datetime.now().hour
        is_night = hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR
        if candidate == "watching":
            self._last_watching_candidate_at = now
        elif (
            is_night
            and candidate == "working"
            and self._last_watching_candidate_at is not None
            and (now - self._last_watching_candidate_at) < WATCHING_STICKY_SECONDS
        ):
            candidate = "watching"
            if self._last_classification is not None:
                self._last_classification.candidate_mode = candidate
                self._last_classification.candidate_reason = "watching_sticky_hold"

        # First poll — accept immediately, no dwell.
        if self._last_mode is None:
            self._last_mode = candidate
            self._pending_mode = None
            self._pending_since = None
            self._update_classification_hysteresis(now)
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
            self._update_classification_hysteresis(now)
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
            self._update_classification_hysteresis(now)
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

        self._update_classification_hysteresis(now)
        return self._last_mode

    def _update_classification_hysteresis(self, now: float) -> None:
        """Attach committed and pending state to the latest classifier poll."""
        if self._last_classification is None:
            return
        self._last_classification.classified_mode = self._last_mode
        self._last_classification.pending_mode = self._pending_mode
        self._last_classification.pending_dwell_age = (
            max(0.0, now - self._pending_since)
            if self._pending_since is not None
            else None
        )

    def has_changed(self, mode: str) -> bool:
        """Check if the reported mode has changed since the last call."""
        changed = mode != self._last_reported_mode
        self._last_reported_mode = mode
        return changed

    def _poll_lol_champion(self, running: set[str]) -> Optional[str]:
        """Return the current League champion name, or None.

        Gates on a LoL binary being present in ``running`` (cheap psutil
        read happens once per tick upstream). Caches successful reads
        for ``LOL_CHAMPION_CACHE_TTL_S`` so the localhost HTTPS GET runs
        ~once every 30s rather than every 5s tick.

        404 / ConnectError = champion select, loading screen, or game
        not running. Treated as "no champion right now" — returns None.
        """
        if not (running & LOL_PROCESSES):
            # League not running at all — flush cache so a fresh match
            # doesn't reuse the prior champion.
            if self._lol_champion is not None:
                self._lol_champion = None
                self._lol_champion_at = 0.0
            self._lol_last_failure_reason = None
            return None

        now = time.time()
        if (
            self._lol_champion is not None
            and (now - self._lol_champion_at) < LOL_CHAMPION_CACHE_TTL_S
        ):
            return self._lol_champion

        if self._lol_http_client is None:
            self._lol_http_client = httpx.Client(
                verify=False,
                timeout=LOL_CHAMPION_HTTP_TIMEOUT_S,
            )
        try:
            resp = self._lol_http_client.get(LOL_LIVE_CLIENT_URL)
        except httpx.HTTPError as e:
            self._note_lol_failure(f"http_error: {type(e).__name__}: {e}")
            return None

        if resp.status_code != 200:
            self._note_lol_failure(f"status_{resp.status_code}")
            return None

        try:
            data = resp.json()
        except ValueError as e:
            self._note_lol_failure(f"json_decode: {e}")
            return None

        champion = _resolve_active_champion(data)
        if not champion:
            self._note_lol_failure(_describe_allgamedata_miss(data))
            return None

        if champion != self._lol_champion or self._lol_last_failure_reason is not None:
            logger.info("LoL champion detected: %s", champion)
        self._lol_champion = champion
        self._lol_champion_at = now
        self._lol_last_failure_reason = None
        return champion

    def _note_lol_failure(self, reason: str) -> None:
        """Log a LoL Live Client poll failure only on transition.

        Polled every 5s while League is running — logging every miss
        would flood ``supervisor.log``. Transition-only emits one
        WARNING per failure-mode change, which is enough to diagnose
        why the bedroom lamps didn't pick up the champion color.
        """
        if reason == self._lol_last_failure_reason:
            return
        logger.warning("LoL Live Client poll failed: %s", reason)
        self._lol_last_failure_reason = reason

    @staticmethod
    def _resolve_active_game(
        fg_proc: Optional[str], processes: set[str],
    ) -> Optional[str]:
        """Resolve the active game to a lighting-profile slug, or None.

        Prefers the foreground process (the game actually on screen); falls
        back to any profiled game in the running set so a brief alt-tab to the
        desktop doesn't drop the profile mid-session. Only games in
        ``GAME_NAME_BY_PROCESS`` resolve — every other game is generic gaming.
        ``fg_proc`` / ``processes`` are already lowercased upstream, so the
        map lookup is direct.
        """
        if fg_proc:
            slug = GAME_NAME_BY_PROCESS.get(fg_proc)
            if slug:
                return slug
        for proc, slug in GAME_NAME_BY_PROCESS.items():
            if proc in processes:
                return slug
        return None

    def build_factors(self) -> list[dict]:
        """Build sub-factor list describing what this lane is seeing.

        Surfaced to the analytics constellation UI. Keeps shape consistent
        with the fusion ``factors`` contract — each entry is a dict with
        ``key``/``label``/``value``/``display``/``impact`` keys. The
        classifier fields are deliberately compact: they identify only the
        decisive foreground process and bounded relevant matches, never a
        full process inventory or foreground title.
        """
        if self._last_classification is None:
            self._classify()
        classification = self._last_classification
        assert classification is not None

        if classification.idle_seconds < 60:
            idle_display = "active"
            idle_impact = 1.0
        elif classification.idle_seconds < IDLE_THRESHOLD:
            idle_display = f"{classification.idle_seconds // 60}m idle"
            idle_impact = 0.6
        else:
            idle_display = f"{classification.idle_seconds // 60}m idle"
            idle_impact = 0.3

        device = _device_role()
        factors: list[dict] = [
            {
                "key": "device",
                "label": "Device",
                "value": device,
                "display": device,
                "impact": 1.0,
            },
            {
                "key": "foreground",
                "label": "Foreground",
                "value": classification.foreground_process or "none",
                "display": classification.foreground_process or "none",
                "impact": (
                    1.0
                    if classification.foreground_kind in ("game", "media", "dev")
                    else 0.5
                ),
            },
            {
                "key": "idle",
                "label": "Input",
                "value": classification.idle_seconds,
                "display": idle_display,
                "impact": idle_impact,
            },
            {
                "key": "input_idle_valid",
                "label": "Input telemetry",
                "value": self._input_idle_valid,
                "display": "valid" if self._input_idle_valid else "unavailable",
                "impact": 1.0 if self._input_idle_valid else 0.0,
            },
            {
                "key": "foreground_kind",
                "label": "Kind",
                "value": classification.foreground_kind,
                "display": classification.foreground_kind,
                "impact": 0.7,
            },
            {
                "key": "candidate_mode",
                "label": "Candidate",
                "value": classification.candidate_mode,
                "display": classification.candidate_mode,
                "impact": 1.0,
            },
            {
                "key": "classified_mode",
                "label": "Classified",
                "value": classification.classified_mode or classification.candidate_mode,
                "display": classification.classified_mode or classification.candidate_mode,
                "impact": 1.0,
            },
            {
                "key": "candidate_reason",
                "label": "Reason",
                "value": classification.candidate_reason,
                "display": classification.candidate_reason,
                "impact": 0.9,
            },
        ]

        if classification.matched_work_processes:
            matches = list(classification.matched_work_processes)
            factors.append({
                "key": "matched_work_processes",
                "label": "Work matches",
                "value": matches,
                "display": ", ".join(matches),
                "impact": 0.8,
            })

        if classification.matched_game_process:
            factors.append({
                "key": "matched_game_process",
                "label": "Game match",
                "value": classification.matched_game_process,
                "display": classification.matched_game_process,
                "impact": 0.9,
            })

        if classification.gaming_qualification:
            factors.append({
                "key": "gaming_qualification",
                "label": "Gaming gate",
                "value": classification.gaming_qualification,
                "display": classification.gaming_qualification,
                "impact": 0.9,
            })

        if classification.pending_mode:
            factors.append({
                "key": "pending_mode",
                "label": "Pending",
                "value": classification.pending_mode,
                "display": classification.pending_mode,
                "impact": 0.5,
            })
            factors.append({
                "key": "pending_dwell_age",
                "label": "Pending age",
                "value": round(classification.pending_dwell_age or 0.0, 1),
                "display": f"{classification.pending_dwell_age or 0.0:.0f}s",
                "impact": 0.4,
            })

        # Per-game lighting profile factor — present only when a game with a
        # dedicated backend profile (e.g. Rust → "Rusted Ember") is active.
        # Drives GAME_LIGHT_PROFILES on the engine + the Rust L2 luma
        # brightness-sync.
        if classification.active_game:
            factors.append({
                "key": "game",
                "label": "Game",
                "value": classification.active_game,
                "display": classification.active_game,
                "impact": 1.0,
            })

        # Only surface browser flag when it's actually load-bearing (late night).
        current_hour = datetime.now().hour
        is_late = current_hour >= LATE_NIGHT_START or current_hour < 6
        if is_late:
            factors.append({
                "key": "browser",
                "label": "Browser",
                "value": classification.browser_running,
                "display": "on" if classification.browser_running else "off",
                "impact": 0.8 if classification.browser_running else 0.2,
            })

        # League champion factor — only present when a LoL match is in progress
        # (Live Client Data API returns 200 with a championName). Drives the
        # bedroom-lamp champion color override on the backend.
        champion = self._poll_lol_champion(self._get_running_process_names())
        if champion:
            factors.append({
                "key": "champion",
                "label": "Champion",
                "value": champion,
                "display": champion,
                "impact": 1.0,
            })

        # Cap reports at 15 factors. This preserves the existing game/champion
        # controls while adding bounded classifier context without persisting
        # arbitrary process inventories.
        return factors[:15]

    def close(self) -> None:
        """Release resources held by the detector (LoL HTTPS client).

        Called from ``run_agent``'s teardown so the supervisor can shut
        down the detector without leaking a TCP connection to the local
        LoL Live Client endpoint.
        """
        if self._lol_http_client is not None:
            try:
                self._lol_http_client.close()
            except Exception:
                pass
            self._lol_http_client = None


def _resolve_active_champion(data: Any) -> Optional[str]:
    """Pull the active player's ``championName`` from /allgamedata.

    Riot's /activeplayer no longer carries ``championName`` directly;
    it only identifies the player by ``riotIdGameName`` +
    ``riotIdTagLine`` (combined as ``riotId``). The champion still lives
    on the matching entry in the ``allPlayers`` roster, so we cross-walk.

    Returns the stripped champion name, or None if the payload is the
    wrong shape, the active player can't be identified, or the matching
    roster entry has no champion (rare — happens during the very first
    tick of /allgamedata responses on the loading screen).
    """
    if not isinstance(data, dict):
        return None

    active = data.get("activePlayer")
    all_players = data.get("allPlayers")
    if not isinstance(active, dict) or not isinstance(all_players, list):
        return None

    # Match key — riotId is "GameName#TagLine". Fall back to the
    # separate fields if the combined form isn't present, then to the
    # legacy summonerName for spectator / replay / older client edge cases.
    riot_id = active.get("riotId")
    if not isinstance(riot_id, str) or not riot_id.strip():
        game_name = active.get("riotIdGameName")
        tag_line = active.get("riotIdTagLine")
        if isinstance(game_name, str) and isinstance(tag_line, str) and game_name and tag_line:
            riot_id = f"{game_name}#{tag_line}"
        else:
            riot_id = None
    summoner_name = active.get("summonerName")

    for entry in all_players:
        if not isinstance(entry, dict):
            continue
        entry_riot_id = entry.get("riotId")
        if riot_id and isinstance(entry_riot_id, str) and entry_riot_id == riot_id:
            matched = entry
            break
        entry_summoner = entry.get("summonerName")
        if (
            summoner_name
            and isinstance(entry_summoner, str)
            and entry_summoner == summoner_name
        ):
            matched = entry
            break
    else:
        return None

    champion = matched.get("championName")
    if isinstance(champion, str) and champion.strip():
        return champion.strip()
    return None


def _describe_allgamedata_miss(data: Any) -> str:
    """Build a diagnostic string when /allgamedata returns 200 but we
    can't resolve a champion. Keeps the WARNING line useful without
    dumping the entire payload."""
    if not isinstance(data, dict):
        return f"non_dict_payload (type={type(data).__name__})"
    keys = list(data.keys())
    active = data.get("activePlayer")
    all_players = data.get("allPlayers")
    if not isinstance(active, dict):
        return f"missing_active_player (top_keys={keys})"
    if not isinstance(all_players, list):
        return f"missing_all_players (top_keys={keys})"
    active_riot_id = active.get("riotId") or (
        f"{active.get('riotIdGameName')}#{active.get('riotIdTagLine')}"
    )
    return (
        f"no_matching_player (active_riot_id={active_riot_id!r}, "
        f"roster_size={len(all_players)})"
    )


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> None:
    """
    Main loop — poll processes, report mode changes to the Home Hub server.

    Reports immediately on mode changes and periodically as a heartbeat
    so the server recovers quickly after restarts/deploys.

    Args:
        server_url: Base URL of the Home Hub backend (e.g., http://localhost:8000).
        stop_event: Optional threading event for clean shutdown (set by supervisor).
        heartbeat: Optional supervisor liveness pulse, called once per loop
            iteration so a hung-but-alive thread can be distinguished from a
            healthy one.
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
            if heartbeat is not None:
                heartbeat()
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
        detector.close()


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
