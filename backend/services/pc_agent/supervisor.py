"""
PC Agent Supervisor — single process managing all desktop background agents.

Replaces three separate Task Scheduler tasks with one unified supervisor that
uses a Windows kernel mutex for singleton guarantee, monitors child agent
threads, and restarts them on failure with exponential backoff.

Agents managed:
  - activity_detector: process-based mode detection (psutil + Win32 idle API)
  - ambient_monitor: mic-based social detection (PyAudio + optional YAMNet)
  - screen_sync_agent: screen color capture for bias lighting (mss)
  - sleep_watcher: suspends Windows 60min after sleeping mode (Windows-only)

Usage:
    python -m backend.services.pc_agent.supervisor --server http://192.168.86.210:8000
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.86.210:8000

    # With YAMNet classifier in shadow mode
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.86.210:8000 --classifier

    # With YAMNet classifier in active mode (drives mode changes)
    pythonw -m backend.services.pc_agent.supervisor --server http://192.168.86.210:8000 --classifier --active
"""
import argparse
import inspect
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

from backend.services.pc_agent.supervisor_recovery import (
    FileBreadcrumbs,
    ProcessIdentity,
    current_process_identity,
    launch_detached_recovery,
)

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
    "home_hub.sleep_watcher",
    "home_hub.emotion_capture",
    "home_hub.peripheral_rgb",
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

# Per-agent heartbeat staleness ceilings (seconds). An agent whose run-loop
# accepts and calls the injected `heartbeat()` is monitored for *hangs* — a
# thread that's alive() but blocked in a native call (e.g. a wedged cv2 read,
# the 2026-06-03 emotion_capture outage). Agents absent from this map fall back
# to is_alive()-only monitoring. Values are generous multiples of each agent's
# loop period to tolerate slow first-tick init (FaceLandmarker/PoseLandmarker).
HEARTBEAT_TIMEOUTS = {
    "activity_detector": 60.0,
    "ambient_monitor": 60.0,
    "screen_sync": 60.0,
    "emotion_capture": 90.0,
}

# Scheduled Task that ensure-runs the supervisor every 5 min (the backstop that
# respawns a fresh process after a hang-triggered exit releases the mutex).
RESPAWN_TASK_NAME = "Home Hub Agent Supervisor"
RESUME_DETECTION_GAP = 30.0
RESUME_HEARTBEAT_GRACE = 15.0
RECOVERY_BREADCRUMB_FILE = LOG_DIR / "supervisor-recovery.log"


# ---------------------------------------------------------------------------
# Active-runtime clock (S3 does not advance this clock)
# ---------------------------------------------------------------------------

def active_runtime_seconds() -> float:
    """Seconds of active Windows runtime, explicitly excluding S3 sleep.

    ``QueryUnbiasedInterruptTime`` is a Windows kernel clock defined to omit
    time spent suspended. In particular, this deliberately does *not* use
    ``time.monotonic()`` on Windows: its suspend semantics are not the contract
    the supervisor needs. Non-Windows test hosts use monotonic time only
    because they do not run the desktop supervisor in production.
    """
    if sys.platform != "win32":
        return time.monotonic()
    import ctypes

    unbiased = ctypes.c_ulonglong()
    ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(unbiased))
    return unbiased.value / 10_000_000.0  # 100ns units


class SuspendAwareRuntimeClock:
    """Samples active runtime and identifies a wall-clock suspend/resume gap."""

    def __init__(
        self,
        runtime_clock: Callable[[], float] = active_runtime_seconds,
        wall_clock: Callable[[], float] = time.time,
        resume_gap: float = RESUME_DETECTION_GAP,
    ) -> None:
        self._runtime_clock = runtime_clock
        self._wall_clock = wall_clock
        self._resume_gap = resume_gap
        self._last_runtime: float | None = None
        self._last_wall: float | None = None

    def sample(self) -> tuple[float, bool]:
        runtime_now = self._runtime_clock()
        wall_now = self._wall_clock()
        resumed = False
        if self._last_runtime is not None and self._last_wall is not None:
            suspended = (wall_now - self._last_wall) - (runtime_now - self._last_runtime)
            resumed = suspended >= self._resume_gap
        self._last_runtime = runtime_now
        self._last_wall = wall_now
        return runtime_now, resumed

# ---------------------------------------------------------------------------
# Singleton mutex (Windows kernel-level, survives PID reuse)
# ---------------------------------------------------------------------------

_mutex_handle = None


def _acquire_mutex() -> bool:
    """Acquire a Windows named mutex. Returns False if another instance holds it.

    Idempotent within a process: once this process owns the mutex, later calls
    return True without re-acquiring. A second CreateMutexW for a name this
    process already owns reports ERROR_ALREADY_EXISTS too, which would
    otherwise look like a competing instance and make us exit on ourselves.
    """
    global _mutex_handle
    if sys.platform != "win32":
        # On Linux the supervisor isn't used (systemd manages agents directly)
        return True
    if _mutex_handle is not None:
        return True
    import ctypes
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
        return False
    return True


def _release_mutex() -> None:
    """Release + close the singleton mutex so a replacement supervisor can
    acquire it. Called on a hang-triggered process restart — without this the
    wedged process keeps the mutex and every scheduled respawn exits as a
    duplicate (the second-order failure behind the 2026-06-03 hour-long outage,
    where the hung supervisor blocked its own replacement)."""
    global _mutex_handle
    if _mutex_handle is None or sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
    except Exception:
        pass
    ctypes.windll.kernel32.CloseHandle(_mutex_handle)
    _mutex_handle = None


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
    # Heartbeat-based hang detection. `heartbeat_timeout` is the staleness
    # ceiling (None = not hang-monitored). `last_progress_at` is stamped by the
    # injected heartbeat() callback each loop iteration. `heartbeat_wired` is set
    # true only when _start_agent actually injected the callback (the target's
    # signature accepts it) — the guard that prevents a misconfigured timeout
    # from flagging an agent that never beats.
    heartbeat_timeout: Optional[float] = None
    last_progress_at: float = 0.0
    heartbeat_wired: bool = False


def _accepts_kwarg(func: Callable, name: str) -> bool:
    """True if `func` accepts a keyword argument `name` (explicitly or via
    **kwargs). Used to inject `heartbeat` only into agents wired to call it, so
    unwired agents stay on is_alive()-only monitoring."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    if name in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _agent_hung(state: AgentState, now: float) -> bool:
    """True when an agent thread is alive but its heartbeat has gone stale.
    Requires the heartbeat to have been wired AND at least one beat recorded, so
    a misconfigured timeout on an unwired agent can never trip this."""
    return (
        state.heartbeat_wired
        and state.heartbeat_timeout is not None
        and state.last_progress_at > 0.0
        and (now - state.last_progress_at) > state.heartbeat_timeout
    )


def _agent_status(state: AgentState, now: float) -> str:
    """Health-report status string for one agent."""
    if not state.enabled:
        return "disabled"
    if not (state.thread and state.thread.is_alive()):
        return "stopped"
    if _agent_hung(state, now):
        return "hung"
    return "running"


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
        runtime_clock: SuspendAwareRuntimeClock | None = None,
        recovery_launcher: Callable[[ProcessIdentity, Path], None] = launch_detached_recovery,
        exit_fn: Callable[[int], None] = os._exit,
    ) -> None:
        self._server_url = server_url
        self._stop = threading.Event()
        self._agents: dict[str, AgentState] = {}
        self._clock = runtime_clock or SuspendAwareRuntimeClock()
        self._start_time, _ = self._clock.sample()
        self._resume_grace_until = 0.0
        self._resume_detection_armed = True
        self._process_identity = current_process_identity()
        self._recovery_launcher = recovery_launcher
        self._exit_fn = exit_fn
        self._recovery_started = False
        self._register_activity_detector()
        self._register_ambient_monitor(classifier, shadow)
        self._register_screen_sync()
        self._register_sleep_watcher()
        self._register_emotion_capture()
        self._register_monitor_brightness()
        self._register_peripheral_rgb()

    # ── Agent registration ────────────────────────────────────────────

    def _register_activity_detector(self) -> None:
        try:
            from backend.services.pc_agent.activity_detector import run_agent
            self._agents["activity_detector"] = AgentState(
                name="activity_detector",
                target=run_agent,
                kwargs={"server_url": self._server_url},
                heartbeat_timeout=HEARTBEAT_TIMEOUTS["activity_detector"],
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
                heartbeat_timeout=HEARTBEAT_TIMEOUTS["ambient_monitor"],
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
                heartbeat_timeout=HEARTBEAT_TIMEOUTS["screen_sync"],
            )
            logger.info("Registered: screen_sync")
        except ImportError as e:
            logger.warning("Cannot register screen_sync: %s", e)

    def _register_emotion_capture(self) -> None:
        # cv2 + mediapipe are lazy-loaded inside the agent's tick, so this
        # import succeeds on any host with httpx; the agent will no-op
        # gracefully on a host that lacks the optional deps.
        try:
            from backend.services.pc_agent.emotion_capture import run_agent
            self._agents["emotion_capture"] = AgentState(
                name="emotion_capture",
                target=run_agent,
                kwargs={"server_url": self._server_url},
                heartbeat_timeout=HEARTBEAT_TIMEOUTS["emotion_capture"],
            )
            logger.info("Registered: emotion_capture")
        except ImportError as e:
            logger.warning("Cannot register emotion_capture: %s", e)

    def _register_sleep_watcher(self) -> None:
        # Windows-only — suspending the PC is meaningless on the Latitude /
        # any non-Windows host that might run this supervisor for testing.
        if sys.platform != "win32":
            logger.info("Skipping sleep_watcher (non-Windows platform)")
            return
        try:
            from backend.services.pc_agent.sleep_watcher import run_agent
            self._agents["sleep_watcher"] = AgentState(
                name="sleep_watcher",
                target=run_agent,
                kwargs={"server_url": self._server_url},
            )
            logger.info("Registered: sleep_watcher")
        except ImportError as e:
            logger.warning("Cannot register sleep_watcher: %s", e)

    def _register_monitor_brightness(self) -> None:
        # Windows-only — DDC/CI tooling + the Night Light registry helper
        # are Win32-specific. The Latitude has no attached monitor the
        # user looks at, so there's no value in running this elsewhere.
        if sys.platform != "win32":
            logger.info("Skipping monitor_brightness (non-Windows platform)")
            return
        try:
            from backend.services.pc_agent.monitor_brightness import run_agent
            self._agents["monitor_brightness"] = AgentState(
                name="monitor_brightness",
                target=run_agent,
                kwargs={"server_url": self._server_url},
            )
            logger.info("Registered: monitor_brightness")
        except ImportError as e:
            logger.warning("Cannot register monitor_brightness: %s", e)

    def _register_peripheral_rgb(self) -> None:
        # Windows-only — drives the desk keyboard + mouse RGB via the local
        # OpenRGB SDK. ImportError (no openrgb-python on the host) is caught
        # below and the agent is simply skipped, like the other optional
        # agents. The Latitude never runs the supervisor (systemd manages
        # its services), so there's no value in running this elsewhere.
        if sys.platform != "win32":
            logger.info("Skipping peripheral_rgb (non-Windows platform)")
            return
        try:
            from backend.services.pc_agent.peripheral_rgb_agent import run_agent
            self._agents["peripheral_rgb"] = AgentState(
                name="peripheral_rgb",
                target=run_agent,
                kwargs={"server_url": self._server_url},
            )
            logger.info("Registered: peripheral_rgb")
        except ImportError as e:
            logger.warning("Cannot register peripheral_rgb: %s", e)

    # ── Thread lifecycle ──────────────────────────────────────────────

    def _start_agent(self, state: AgentState) -> None:
        """Launch an agent in a new daemon thread."""
        call_kwargs = dict(state.kwargs)
        # Inject a heartbeat callback for agents whose run-loop accepts one, so a
        # hung-but-alive thread can be told apart from a healthy one. Gated on
        # the signature so unwired agents are untouched (is_alive-only).
        if _accepts_kwarg(state.target, "heartbeat"):
            def _beat(_s: AgentState = state) -> None:
                _s.last_progress_at = self._active_now()
            call_kwargs["heartbeat"] = _beat
            state.heartbeat_wired = True
        else:
            state.heartbeat_wired = False

        def _wrapper() -> None:
            try:
                state.target(stop_event=self._stop, **call_kwargs)
            except Exception as e:
                state.last_error = str(e)
                logger.error(
                    "Agent %s crashed: %s", state.name, e, exc_info=True,
                )

        state.thread = threading.Thread(
            target=_wrapper, name=f"agent-{state.name}", daemon=True,
        )
        state.last_start = self._active_now()
        # Seed the heartbeat at start so a slow first-tick init (FaceLandmarker /
        # PoseLandmarker / webcam open) doesn't read as an immediate hang; the
        # agent's own beats take over from the first loop iteration.
        state.last_progress_at = state.last_start
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

    def _active_now(self) -> float:
        """Return active runtime and arm a short post-resume heartbeat grace."""
        now, resumed = self._clock.sample()
        if resumed and self._resume_detection_armed and now >= self._resume_grace_until:
            self._resume_grace_until = now + RESUME_HEARTBEAT_GRACE
            self._resume_detection_armed = False
            logger.info(
                "Resume detected; suppressing heartbeat hang decisions for %.0fs",
                RESUME_HEARTBEAT_GRACE,
            )
        elif not resumed and now >= self._resume_grace_until:
            # Require a normal post-grace sample before another divergence can
            # arm grace. Repeated wall corrections therefore cannot extend it.
            self._resume_detection_armed = True
        return now

    def _handle_hung_agent(self, state: AgentState, stale: float) -> None:
        """Make identity-safe external recovery inevitable, then hard-exit.

        Do not report over the network, close shared logging handlers, or join
        threads here. Any of those can block behind the same poisoned native
        state that made a whole-process recovery necessary.
        """
        if self._recovery_started:
            return
        self._recovery_started = True
        state.last_error = f"hung: no heartbeat for {stale:.0f}s"
        breadcrumbs = FileBreadcrumbs(RECOVERY_BREADCRUMB_FILE)
        identity = self._process_identity
        identity_text = identity.value if identity is not None else f"{os.getpid()}:unknown"
        breadcrumbs.write("supervisor", "hang-detected", f"{state.name} {identity_text}")
        if sys.platform == "win32" and identity is not None:
            try:
                self._recovery_launcher(identity, RECOVERY_BREADCRUMB_FILE)
                breadcrumbs.write("supervisor", "recovery-detached", identity.value)
            except Exception:
                breadcrumbs.write("supervisor", "recovery-launch-failed", identity.value)
        # Do not release the mutex: only process death releases the unhealthy
        # owner's handle. The detached worker verifies that before it launches.
        self._exit_fn(1)

    # ── Health heartbeat ──────────────────────────────────────────────

    def _report_health(self) -> None:
        """POST agent status to the backend (best-effort, failures are silent)."""
        import httpx

        endpoint = f"{self._server_url.rstrip('/')}/api/automation/agent-health"
        now = self._active_now()

        agents = {}
        for name, state in self._agents.items():
            heartbeat_age = (
                int(now - state.last_progress_at)
                if state.heartbeat_wired and state.last_progress_at
                else None
            )
            agents[name] = {
                "status": _agent_status(state, now),
                "uptime": int(now - state.last_start) if state.last_start else 0,
                "restarts": state.restarts,
                "last_error": state.last_error,
                "heartbeat_age": heartbeat_age,
            }

        try:
            with httpx.Client(timeout=5.0) as client:
                client.post(endpoint, json={
                    "agents": agents,
                    "supervisor_uptime": int(now - self._start_time),
                    "supervisor_pid": os.getpid(),
                    "supervisor_instance": (
                        self._process_identity.value if self._process_identity else None
                    ),
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
                now = self._active_now()

                for state in self._agents.values():
                    if not state.enabled:
                        continue

                    if state.thread and state.thread.is_alive():
                        if now >= self._resume_grace_until and _agent_hung(state, now):
                            # Alive but blocked in a native call — is_alive()
                            # can't see this. The thread can't be killed, so
                            # recover by recycling the whole process.
                            self._handle_hung_agent(
                                state, now - state.last_progress_at,
                            )
                            # does not return — process exits
                        elif (now - state.last_start) > STABLE_THRESHOLD:
                            # Stable — reset backoff
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
        default="http://192.168.86.210:8000",
        help="Home Hub server URL (default: http://192.168.86.210:8000)",
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

    # Singleton guard FIRST — the ensure-running Scheduled Task respawns this
    # every ~5 min. Acquiring the mutex before constructing the supervisor lets
    # a duplicate exit immediately, instead of importing the (heavy) agent
    # modules and emitting a "Registered: …" burst on every doomed spawn. The
    # routine duplicate-exit is expected, so log it at DEBUG to keep the log
    # quiet; the owning process announces itself with the INFO line in run().
    if not _acquire_mutex():
        logger.debug("Another supervisor already running — exiting")
        sys.exit(0)

    supervisor = AgentSupervisor(
        server_url=args.server,
        classifier=args.classifier,
        shadow=not args.active,
    )
    supervisor.run()
