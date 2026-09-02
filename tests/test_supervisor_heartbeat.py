"""
Supervisor heartbeat / hang-detection tests.

Covers the 2026-06-03 failure mode: an agent thread that is alive() but blocked
forever in a native call (a wedged cv2 read) was invisible to the supervisor's
is_alive()-only monitor, so it sat dead for hours. The heartbeat layer stamps a
per-agent `last_progress_at` each loop iteration and flags a stale beat as hung.

These tests exercise the pure decision functions (`_accepts_kwarg`,
`_agent_hung`, `_agent_status`) and the signature contract between the
supervisor and the agents it wires — no hardware, threads, or process exit.
"""
import pytest

from backend.services.pc_agent.supervisor import (
    HEARTBEAT_TIMEOUTS,
    AgentState,
    AgentSupervisor,
    _accepts_kwarg,
    _agent_hung,
    _agent_status,
)


class _FakeThread:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _wired_state(*, last_progress_at: float, timeout: float = 60.0) -> AgentState:
    """A heartbeat-wired, alive agent whose last beat was at the given time."""
    return AgentState(
        name="emotion_capture",
        target=lambda **_: None,
        thread=_FakeThread(alive=True),
        heartbeat_timeout=timeout,
        heartbeat_wired=True,
        last_progress_at=last_progress_at,
    )


# ── _accepts_kwarg ──────────────────────────────────────────────────────

class TestAcceptsKwarg:
    def test_explicit_param(self):
        def f(server_url, stop_event=None, heartbeat=None):
            ...
        assert _accepts_kwarg(f, "heartbeat") is True

    def test_var_keyword(self):
        def f(server_url, **kwargs):
            ...
        assert _accepts_kwarg(f, "heartbeat") is True

    def test_absent(self):
        def f(server_url, stop_event=None):
            ...
        assert _accepts_kwarg(f, "heartbeat") is False


# ── _agent_hung ─────────────────────────────────────────────────────────

class TestAgentHung:
    def test_wired_and_stale_is_hung(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 90.0, timeout=60.0)
        assert _agent_hung(state, now) is True

    def test_wired_and_fresh_is_not_hung(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 5.0, timeout=60.0)
        assert _agent_hung(state, now) is False

    def test_unwired_never_hung_even_if_stale(self):
        # Safety belt: a timeout set on an agent that never beats must not
        # trigger a false hang-restart loop.
        now = 1000.0
        state = _wired_state(last_progress_at=now - 9999.0, timeout=60.0)
        state.heartbeat_wired = False
        assert _agent_hung(state, now) is False

    def test_no_timeout_never_hung(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 9999.0, timeout=60.0)
        state.heartbeat_timeout = None
        assert _agent_hung(state, now) is False

    def test_never_ticked_is_not_hung(self):
        # last_progress_at==0 means no beat recorded yet (e.g. just constructed).
        now = 1000.0
        state = _wired_state(last_progress_at=0.0, timeout=60.0)
        assert _agent_hung(state, now) is False

    def test_exactly_at_timeout_is_not_hung(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 60.0, timeout=60.0)
        assert _agent_hung(state, now) is False  # strictly greater-than


# ── _agent_status ───────────────────────────────────────────────────────

class TestAgentStatus:
    def test_disabled(self):
        state = _wired_state(last_progress_at=1000.0)
        state.enabled = False
        assert _agent_status(state, 1000.0) == "disabled"

    def test_stopped_when_thread_dead(self):
        state = _wired_state(last_progress_at=1000.0)
        state.thread = _FakeThread(alive=False)
        assert _agent_status(state, 1000.0) == "stopped"

    def test_stopped_when_no_thread(self):
        state = _wired_state(last_progress_at=1000.0)
        state.thread = None
        assert _agent_status(state, 1000.0) == "stopped"

    def test_hung(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 120.0, timeout=60.0)
        assert _agent_status(state, now) == "hung"

    def test_running(self):
        now = 1000.0
        state = _wired_state(last_progress_at=now - 2.0, timeout=60.0)
        assert _agent_status(state, now) == "running"


# ── Signature contract: every agent the supervisor hang-monitors must
#    actually accept the heartbeat kwarg, or the timeout would arm against an
#    agent that never beats. ───────────────────────────────────────────────

class TestWiredAgentsAcceptHeartbeat:
    AGENTS = {
        "activity_detector": (
            "backend.services.pc_agent.activity_detector", "run_agent",
        ),
        "ambient_monitor": (
            "backend.services.pc_agent.ambient_monitor", "run_monitor",
        ),
        "screen_sync": (
            "backend.services.pc_agent.screen_sync_agent", "run_agent",
        ),
        "emotion_capture": (
            "backend.services.pc_agent.emotion_capture", "run_agent",
        ),
    }

    @pytest.mark.parametrize("key", sorted(HEARTBEAT_TIMEOUTS))
    def test_monitored_agent_accepts_heartbeat(self, key):
        module_path, func_name = self.AGENTS[key]
        module = pytest.importorskip(module_path)
        func = getattr(module, func_name)
        assert _accepts_kwarg(func, "heartbeat"), (
            f"{key} has a heartbeat_timeout but its entry point "
            f"{func_name} does not accept a `heartbeat` kwarg — the supervisor "
            f"would arm a hang timeout that can never be satisfied."
        )

    def test_every_timeout_has_a_known_agent(self):
        # Guard against a timeout key with no corresponding agent mapping.
        assert set(HEARTBEAT_TIMEOUTS).issubset(self.AGENTS)


def test_backend_health_outage_is_not_a_supervisor_hang(monkeypatch):
    import httpx

    now = 1000.0
    state = _wired_state(last_progress_at=now - 2.0, timeout=60.0)
    state.last_start = now - 120.0
    supervisor = object.__new__(AgentSupervisor)
    supervisor._server_url = "http://unreachable.invalid"
    supervisor._agents = {"emotion_capture": state}
    supervisor._start_time = now - 300.0
    supervisor._process_identity = None
    supervisor._active_now = lambda: now


    class FailingClient:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("planned backend absence")

    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: FailingClient())
    supervisor._report_health()
    assert state.restarts == 0
    assert state.last_error is None
    assert _agent_hung(state, now) is False
