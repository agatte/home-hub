"""Tests for ``backend.services.pc_agent.sleep_watcher``.

The watcher polls the backend's mode, arms a 60-min timer when mode is
``sleeping``, cancels on any other mode, and calls ``SetSuspendState`` on
fire. Non-Windows is a no-op for the suspend call. Tests cover:

1. ``_fetch_mode`` — happy path, HTTP error, missing key
2. ``_suspend_pc`` — non-Windows no-op, Windows calls ctypes
3. ``run_agent`` state machine — arm, disarm, fire, transient-error
   resilience, re-arm after disarm
"""
from __future__ import annotations

import threading
from typing import Optional
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.services.pc_agent import sleep_watcher
from backend.services.pc_agent.sleep_watcher import (
    SLEEP_DELAY_SECONDS,
    _fetch_mode,
    _suspend_pc,
    run_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeStopEvent:
    """Stop event that returns ``False`` from ``.wait`` exactly N times.

    Drives ``run_agent``'s loop a deterministic number of iterations without
    the real ``threading.Event`` 5-second sleeps. After N calls, ``.wait``
    returns ``True`` and the loop exits.
    """

    def __init__(self, n_iterations: int) -> None:
        self._remaining = n_iterations

    def wait(self, _timeout: float) -> bool:  # noqa: D401
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False

    def is_set(self) -> bool:
        return self._remaining <= 0

    def set(self) -> None:
        self._remaining = 0


# ---------------------------------------------------------------------------
# _fetch_mode
# ---------------------------------------------------------------------------


class TestFetchMode:
    """``_fetch_mode`` returns the backend's current_mode or None on error."""

    def test_returns_mode_on_success(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = {"current_mode": "gaming"}
        resp.raise_for_status.return_value = None
        client.get.return_value = resp

        assert _fetch_mode(client, "http://192.168.1.210:8000") == "gaming"
        client.get.assert_called_once_with(
            "http://192.168.1.210:8000/api/automation/status"
        )

    def test_strips_trailing_slash_in_server_url(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = {"current_mode": "sleeping"}
        client.get.return_value = resp

        _fetch_mode(client, "http://192.168.1.210:8000/")
        # No double slash before /api/
        assert client.get.call_args[0][0] == (
            "http://192.168.1.210:8000/api/automation/status"
        )

    def test_returns_none_on_http_error(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=MagicMock()
        )
        client.get.return_value = resp

        assert _fetch_mode(client, "http://x") is None

    def test_returns_none_on_connect_error(self):
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("nope")

        assert _fetch_mode(client, "http://x") is None

    def test_returns_none_when_current_mode_key_missing(self):
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock()
        resp.json.return_value = {"some_other_key": 1}
        resp.raise_for_status.return_value = None
        client.get.return_value = resp

        # .get(key) returns None when key absent — _fetch_mode propagates.
        assert _fetch_mode(client, "http://x") is None


# ---------------------------------------------------------------------------
# _suspend_pc
# ---------------------------------------------------------------------------


class TestSuspendPC:
    """Suspend is Windows-only."""

    def test_non_windows_is_noop(self):
        with patch.object(sleep_watcher.sys, "platform", "linux"):
            # Should not raise even if ctypes.windll doesn't exist.
            _suspend_pc()

    def test_windows_calls_setsuspendstate(self):
        fake_powrprof = MagicMock()
        fake_windll = MagicMock(powrprof=fake_powrprof)
        fake_ctypes = MagicMock(windll=fake_windll)

        with patch.object(sleep_watcher.sys, "platform", "win32"), \
             patch.dict("sys.modules", {"ctypes": fake_ctypes}):
            _suspend_pc()

        fake_powrprof.SetSuspendState.assert_called_once_with(
            False, False, False
        )


# ---------------------------------------------------------------------------
# run_agent state machine
# ---------------------------------------------------------------------------


def _run_with(
    *,
    modes: list[Optional[str]],
    times: list[float],
    suspend_mock: Optional[MagicMock] = None,
):
    """Drive ``run_agent`` for ``len(modes)`` iterations.

    ``modes`` is the sequence of return values from a stubbed ``_fetch_mode``.
    ``times`` is the sequence of ``time.time()`` return values — one per call,
    so test authors must count how many times the loop reads the clock per
    iteration.

    Returns the final ``timer_deadline`` (None if never armed / cancelled)
    only indirectly via the ``suspend_mock`` call count.
    """
    suspend_mock = suspend_mock or MagicMock()
    fetch_mock = MagicMock(side_effect=modes)
    time_mock = MagicMock(side_effect=times)
    stop = _FakeStopEvent(n_iterations=len(modes))

    with patch.object(sleep_watcher, "_fetch_mode", fetch_mock), \
         patch.object(sleep_watcher, "_suspend_pc", suspend_mock), \
         patch.object(sleep_watcher.time, "time", time_mock):
        run_agent("http://x", stop_event=stop)

    return suspend_mock, fetch_mock, time_mock


class TestRunAgentStateMachine:
    """Arm / disarm / fire transitions of the watcher loop."""

    def test_arms_on_first_sleeping_observation(self):
        # Iteration 1: mode=sleeping. Deadline = time.time() + 3600.
        # time.time is called twice per "armed" iteration: once to set
        # deadline, once to check fire condition. 1000 + 3600 = 4600;
        # 1001 < 4600 so no fire.
        suspend, _, _ = _run_with(
            modes=["sleeping"],
            times=[1000.0, 1001.0],
        )
        assert suspend.call_count == 0

    def test_does_not_fire_before_deadline(self):
        # Three sleeping iterations, time advances slightly each tick.
        # Deadline=4600 (set at t=1000); subsequent checks at t=1001, 1002.
        # No fire.
        suspend, _, _ = _run_with(
            modes=["sleeping", "sleeping", "sleeping"],
            times=[1000.0, 1001.0, 1002.0, 1003.0],
        )
        assert suspend.call_count == 0

    def test_fires_when_deadline_passes(self):
        # Iter 1 arms at t=1000; iter 2 checks at t=5000 which is past
        # the t=4600 deadline → fire.
        suspend, _, _ = _run_with(
            modes=["sleeping", "sleeping"],
            times=[1000.0, 1001.0, 5000.0],
        )
        assert suspend.call_count == 1

    def test_disarms_when_mode_changes(self):
        # Arm at iter 1, mode flips to working at iter 2 → disarmed.
        # Iter 3 still working — no fire even though we'd be past the
        # original deadline. Confirms the cancel actually cleared state.
        suspend, _, _ = _run_with(
            modes=["sleeping", "working", "working"],
            times=[
                1000.0, 1001.0,  # iter 1 arms (2 calls: set + check)
                # iter 2: mode != sleeping, no time.time() calls in
                # the disarm branch. The fire-check is gated by
                # `timer_deadline is not None`, which is False here, so
                # short-circuit skips time.time().
                # iter 3: same — no time.time() calls.
            ],
        )
        assert suspend.call_count == 0

    def test_transient_fetch_failure_preserves_timer(self):
        # Arm at iter 1 (sleeping). Iter 2 returns None (transient backend
        # blip) — must NOT cancel the timer. Iter 3 returns sleeping again,
        # by which point time has advanced past the deadline → fire.
        suspend, _, _ = _run_with(
            modes=["sleeping", None, "sleeping"],
            times=[
                1000.0, 1001.0,  # iter 1: set + check
                # iter 2: None short-circuits before any time.time() call
                5000.0,           # iter 3: check only (already armed)
            ],
        )
        assert suspend.call_count == 1

    def test_re_arms_after_disarm(self):
        # sleeping → working → sleeping. The second sleeping must arm a
        # FRESH timer (the cancel cleared the old one). Since we don't
        # advance past 60 minutes in test time, no fire — but the loop
        # exits cleanly with a deadline set.
        suspend, _, _ = _run_with(
            modes=["sleeping", "working", "sleeping"],
            times=[
                1000.0, 1001.0,  # iter 1 arm
                                  # iter 2 disarm (no time.time)
                2000.0, 2001.0,  # iter 3 re-arm (set + check)
            ],
        )
        assert suspend.call_count == 0

    def test_supervisor_restart_in_sleeping_arms_fresh_timer(self):
        # Edge case noted in sleep_watcher.py docstring: if the supervisor
        # restarts while mode is already sleeping, the watcher should arm
        # a fresh 60-min timer from the first observation rather than
        # treating the absence of a prior arm as "user just got up."
        # First observation is "sleeping" — must arm even though there
        # was no prior non-sleeping state.
        suspend, _, time_mock = _run_with(
            modes=["sleeping"],
            times=[1000.0, 1001.0],
        )
        assert suspend.call_count == 0
        # Two time.time() calls confirms we entered the arm branch
        # (set deadline + check fire) and didn't take an early continue.
        assert time_mock.call_count == 2


# ---------------------------------------------------------------------------
# run_agent — stop_event termination
# ---------------------------------------------------------------------------


class TestRunAgentTermination:
    """``run_agent`` exits cleanly when stop_event fires."""

    def test_default_stop_event_does_not_loop_forever_when_set(self):
        # Caller passes None → run_agent creates its own Event. We can't
        # set it externally for this path, so just confirm a pre-set Event
        # exits immediately without making any fetch calls.
        evt = threading.Event()
        evt.set()

        fetch_mock = MagicMock()
        with patch.object(sleep_watcher, "_fetch_mode", fetch_mock):
            run_agent("http://x", stop_event=evt)

        fetch_mock.assert_not_called()
