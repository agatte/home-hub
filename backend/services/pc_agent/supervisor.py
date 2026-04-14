"""
PC Agent Supervisor — single process managing all desktop background agents.

Replaces three separate Task Scheduler tasks with one unified supervisor that
uses a Windows kernel mutex for singleton guarantee, monitors child agent
threads, and restarts them on failure with exponential backoff.

Agents managed:
  - activity_detector: process-based mode detection (psutil + Win32 idle API)
  - ambient_monitor: mic-based social detection (PyAudio + optional YAMNet)
  - screen_sync_agent: screen color capture for bias lighting (mss)

Usage:
    python -m backend.services.pc_agent.supervisor --server http://192.168.1.210:8000
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.1.210:8000

    # With YAMNet classifier in shadow mode
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.1.210:8000 --classifier

    # With YAMNet classifier in active mode (drives mode changes)
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.1.210:8000 --classifier --active
"""
import argparse
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Logging — file + console (file captures errors even under pythonw.exe)
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "supervisor.log"

logger = logging.getLogger("home_hub.supervisor")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)

# Route child agent loggers through the same file handler so all output
# lands in supervisor.log (especially important under pythonw.exe where
# stderr goes nowhere).
for _child_name in (
    "home_hub.pc_agent",
    "home_hub.ambient",
    "home_hub.screen_sync_agent",
):
    _child = logging.getLogger(_child_name)
    _child.setLevel(logging.INFO)
    _child.addHandler(_file_handler)
    _child.addHandler(_console)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MUTEX_NAME = "HomeHub_AgentSupervisor"
HEALTH_INTERVAL = 30       # Seconds between health heartbeats to server
MONITOR_INTERVAL = 5       # Seconds between thread liveness checks
INITIAL_BACKOFF = 5.0      # First restart delay (seconds)
MAX_BACKOFF = 300.0        # 5 minutes max restart delay
STABLE_THRESHOLD = 300.0   # 5 minutes of uptime = reset backoff


# ---------------------------------------------------------------------------
# Singleton mutex (Windows kernel-level, survives PID reuse)
# ---------------------------------------------------------------------------

_mutex_handle = None


def _acquire_mutex() -> bool:
    """Acquire a Windows named mutex. Returns False if another instance holds it."""
    global _mutex_handle
    if sys.platform != "win32":
        # On Linux the supervisor isn't used (systemd manages agents directly)
        return True
    import ctypes
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
        return False
    return True


# ---------------------------------------------------------------------------
# Agent state tracking
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """Tracks a single managed agent thread."""
    name: str
    target: Callable
    kwargs: dict = field(default_factory=dict)
    thread: Optional[threading.Thread] = None
    restarts: int = 0
    backoff: float = INITIAL_BACKOFF
    last_start: float = 0.0
    last_error: Optional[str] = None
    enabled: bool = True


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class AgentSupervisor:
    """
    Manages all PC agent threads from a single process.

    - Starts each agent as a daemon thread
    - Monitors liveness every MONITOR_INTERVAL seconds
    - Restarts crashed agents with exponential backoff (resets after stable run)
    - Reports health to the Home Hub backend every HEALTH_INTERVAL seconds
    - Shuts down cleanly on SIGTERM / SIGINT / KeyboardInterrupt
    """

    def __init__(
        self,
        server_url: str,
        classifier: bool = False,
        shadow: bool = True,
    ) -> None:
        self._server_url = server_url
        self._stop = threading.Event()
        self._agents: dict[str, AgentState] = {}
        self._start_time = time.time()

        self._register_activity_detector()
        self._register_ambient_monitor(classifier, shadow)
        self._register_screen_sync()

    # ── Agent registration ────────────────────────────────────────────

    def _register_activity_detector(self) -> None:
        try:
            from backend.services.pc_agent.activity_detector import run_agent
            self._agents["activity_detector"] = AgentState(
                name="activity_detector",
                target=run_agent,
                kwargs={"server_url": self._server_url},
            )
            logger.info("Registered: activity_detector")
        except ImportError as e:
            logger.warning("Cannot register activity_detector: %s", e)

    def _register_ambient_monitor(
        self, classifier: bool, shadow: bool,
    ) -> None:
        try:
            from backend.services.pc_agent.ambient_monitor import run_monitor
            self._agents["ambient_monitor"] = AgentState(
                name="ambient_monitor",
                target=run_monitor,
                kwargs={
                    "server_url": self._server_url,
                    "classifier_enabled": classifier,
                    "shadow_mode": shadow,
                },
            )
            logger.info("Registered: ambient_monitor")
        except ImportError as e:
            logger.warning("Cannot register ambient_monitor: %s", e)

    def _register_screen_sync(self) -> None:
        try:
            from backend.services.pc_agent.screen_sync_agent import run_agent
            self._agents["screen_sync"] = AgentState(
                name="screen_sync",
                target=run_agent,
                kwargs={"server_url": self._server_url},
            )
            logger.info("Registered: screen_sync")
        except ImportError as e:
            logger.warning("Cannot register screen_sync: %s", e)

    # ── Thread lifecycle ──────────────────────────────────────────────

    def _start_agent(self, state: AgentState) -> None:
        """Launch an agent in a new daemon thread."""
        def _wrapper() -> None:
            try:
                state.target(stop_event=self._stop, **state.kwargs)
            except Exception as e:
                state.last_error = str(e)
                logger.error(
                    "Agent %s crashed: %s", state.name, e, exc_info=True,
                )

        state.thread = threading.Thread(
            target=_wrapper, name=f"agent-{state.name}", daemon=True,
        )
        state.last_start = time.time()
        state.thread.start()
        logger.info(
            "Started agent: %s (thread=%s)", state.name, state.thread.name,
        )

    def _restart_agent(self, state: AgentState) -> None:
        """Restart a crashed agent after its current backoff delay."""
        state.restarts += 1
        delay = state.backoff
        state.backoff = min(state.backoff * 2, MAX_BACKOFF)

        logger.warning(
            "Restarting %s in %.0fs (attempt #%d, last_error: %s)",
            state.name, delay, state.restarts, state.last_error,
        )

        if self._stop.wait(delay):
            return  # Supervisor is shutting down

        self._start_agent(state)

    # ── Health heartbeat ──────────────────────────────────────────────

    def _report_health(self) -> None:
        """POST agent status to the backend (best-effort, failures are silent)."""
        import httpx

        endpoint = f"{self._server_url.rstrip('/')}/api/automation/agent-health"
        now = time.time()

        agents = {}
        for name, state in self._agents.items():
            if not state.enabled:
                status = "disabled"
            elif state.thread and state.thread.is_alive():
                status = "running"
            else:
                status = "stopped"

            agents[name] = {
                "status": status,
                "uptime": int(now - state.last_start) if state.last_start else 0,
                "restarts": state.restarts,
                "last_error": state.last_error,
            }

        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(endpoint, json={
                    "agents": agents,
                    "supervisor_uptime": int(now - self._start_time),
                })
        except Exception:
            pass  # Health reporting is best-effort

    # ── Main loop ─────────────────────────────────────────────────────

    def run(self) -> None:
        """Start all agents and monitor until shutdown signal."""
        if not _acquire_mutex():
            logger.info("Another supervisor is already running — exiting")
            sys.exit(0)

        logger.info(
            "Supervisor started (PID %d) — managing %d agents, server: %s",
            os.getpid(), len(self._agents), self._server_url,
        )

        # Start all registered agents
        for state in self._agents.values():
            if state.enabled:
                self._start_agent(state)
                # Stagger starts slightly so agents don't race for resources
                time.sleep(0.5)

        last_health: float = 0.0

        try:
            while not self._stop.is_set():
                now = time.time()

                for state in self._agents.values():
                    if not state.enabled:
                        continue

                    if state.thread and state.thread.is_alive():
                        # Running — reset backoff if stable long enough
                        if (now - state.last_start) > STABLE_THRESHOLD:
                            if state.backoff > INITIAL_BACKOFF:
                                logger.info(
                                    "Agent %s stable for %.0fs — resetting backoff",
                                    state.name, now - state.last_start,
                                )
                                state.backoff = INITIAL_BACKOFF
                    else:
                        # Dead — restart with backoff
                        self._restart_agent(state)

                # Health heartbeat
                if now - last_health >= HEALTH_INTERVAL:
                    self._report_health()
                    last_health = now

                self._stop.wait(MONITOR_INTERVAL)

        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Supervisor shutting down...")
            self._stop.set()

            # Give threads a moment to notice the stop event and exit cleanly
            for state in self._agents.values():
                if state.thread and state.thread.is_alive():
                    state.thread.join(timeout=5)
                    if state.thread.is_alive():
                        logger.warning(
                            "Agent %s did not stop within 5s", state.name,
                        )

            self._report_health()
            logger.info("Supervisor stopped")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Home Hub PC Agent Supervisor — manages all desktop background agents",
    )
    parser.add_argument(
        "--server",
        default="http://192.168.1.210:8000",
        help="Home Hub server URL (default: http://192.168.1.210:8000)",
    )
    parser.add_argument(
        "--classifier",
        action="store_true",
        help="Enable YAMNet audio scene classifier for ambient monitor",
    )
    parser.add_argument(
        "--shadow",
        action="store_true",
        default=True,
        help="Run YAMNet in shadow mode (log only). Default.",
    )
    parser.add_argument(
        "--active",
        action="store_true",
        help="Run YAMNet in active mode (drives mode changes)",
    )
    args = parser.parse_args()

    # Clean shutdown on SIGTERM (e.g., from Task Scheduler stop)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    supervisor = AgentSupervisor(
        server_url=args.server,
        classifier=args.classifier,
        shadow=not args.active,
    )
    supervisor.run()
