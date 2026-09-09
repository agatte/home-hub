"""Classifier gaming-mode state-machine tests (no live games or processes)."""

import threading
from pathlib import Path

from backend.services.pc_agent.supervisor import (
    AgentSupervisor,
    SUPERVISOR_MODE_AUTOMATIC,
    SUPERVISOR_MODE_CANONICAL,
    SUPERVISOR_MODE_MANUAL,
    classifier_transition_target,
)
from backend.services.pc_agent.supervisor_recovery import ProcessIdentity


def test_canonical_gaming_edge_requests_automatic_reduced_mode():
    assert classifier_transition_target(
        "gaming", SUPERVISOR_MODE_CANONICAL, True,
    ) == (SUPERVISOR_MODE_AUTOMATIC, "automatic_gaming_start")


def test_automatic_non_gaming_edge_restores_canonical_mode():
    assert classifier_transition_target(
        "working", SUPERVISOR_MODE_AUTOMATIC, False,
    ) == (SUPERVISOR_MODE_CANONICAL, "automatic_gaming_exit")


def test_manual_mode_always_wins_over_automatic_edges():
    for committed_mode in ("gaming", "working", "watching", "idle"):
        assert classifier_transition_target(
            committed_mode, SUPERVISOR_MODE_MANUAL, False,
        ) is None


def test_repeated_matching_states_are_idempotent():
    assert classifier_transition_target(
        "gaming", SUPERVISOR_MODE_AUTOMATIC, False,
    ) is None
    assert classifier_transition_target(
        "idle", SUPERVISOR_MODE_CANONICAL, True,
    ) is None


def test_callback_queues_only_one_transition(monkeypatch):
    from backend.services.pc_agent import supervisor as supervisor_module

    monkeypatch.setattr(supervisor_module.logger, "info", lambda *_args: None)
    supervisor = object.__new__(AgentSupervisor)
    supervisor._supervisor_mode = SUPERVISOR_MODE_CANONICAL
    supervisor._classifier_enabled = True
    supervisor._transition_lock = threading.Lock()
    supervisor._pending_transition = None
    supervisor._write_classifier_transition = lambda *_: None

    supervisor._on_committed_mode_change("gaming")
    supervisor._on_committed_mode_change("gaming")

    assert supervisor._pending_transition == (
        SUPERVISOR_MODE_AUTOMATIC, "automatic_gaming_start",
    )


def test_pending_transition_launches_once_then_exits(monkeypatch):
    from backend.services.pc_agent import supervisor as supervisor_module

    launches = []
    exits = []
    supervisor = object.__new__(AgentSupervisor)
    supervisor._transition_lock = threading.Lock()
    supervisor._pending_transition = (
        SUPERVISOR_MODE_AUTOMATIC, "automatic_gaming_start",
    )
    supervisor._recovery_started = False
    supervisor._process_identity = ProcessIdentity(42, 123)
    supervisor._server_url = "http://192.168.86.210:8000"
    supervisor._write_classifier_transition = lambda *_: None
    supervisor._transition_launcher = lambda *args: launches.append(args)
    supervisor._exit_fn = lambda code: exits.append(code)
    monkeypatch.setattr(supervisor_module.sys, "platform", "win32")

    supervisor._perform_pending_transition()

    assert launches == [(
        ProcessIdentity(42, 123),
        Path("logs/classifier-gaming-transitions.log"),
        SUPERVISOR_MODE_AUTOMATIC,
        "http://192.168.86.210:8000",
    )]
    assert exits == [0]
    assert supervisor._pending_transition is None
