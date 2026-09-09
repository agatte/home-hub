"""Authority-driven classifier gaming gate tests."""

from backend.services.pc_agent.ambient_monitor import AmbientMonitor
from backend.services.pc_agent.classifier_gate import ClassifierGate
from backend.services.pc_agent.supervisor import AgentSupervisor


def test_local_gaming_candidate_cannot_disable_classifier_if_backend_rejects_it():
    gate = ClassifierGate(configured=True)

    changed = gate.update_from_activity(
        "gaming",
        {
            "authoritative_mode": "watching",
            "semantic_disposition": "rejected",
            "reason": "manual_override_held",
        },
    )

    assert not changed
    snapshot = gate.snapshot()
    assert snapshot["desired_enabled"] is True
    assert snapshot["authoritative_mode"] == "watching"
    assert snapshot["reason"] == "manual_override_held"


def test_manual_gaming_authority_disables_classifier_even_if_process_reports_idle():
    gate = ClassifierGate(configured=True)
    assert gate.update_from_activity(
        "idle",
        {
            "authoritative_mode": "gaming",
            "semantic_disposition": "accepted",
            "reason": "manual_override_held",
        },
    )
    snapshot = gate.snapshot()
    assert snapshot["desired_enabled"] is False
    assert snapshot["reported_mode"] == "idle"


def test_missing_authority_never_changes_gate():
    gate = ClassifierGate(configured=True)
    assert not gate.update_from_activity("gaming", {"reason": "legacy"})
    assert gate.snapshot()["desired_enabled"] is True


def test_startup_status_primes_gaming_before_classifier_load():
    gate = ClassifierGate(configured=True)
    assert gate.update_from_status({"current_mode": "gaming"})
    snapshot = gate.snapshot()
    assert snapshot["desired_enabled"] is False
    assert snapshot["reason"] == "startup_status"


def test_ambient_disable_keeps_microphone_lane_alive():
    gate = ClassifierGate(configured=True)
    monitor = AmbientMonitor(classifier_enabled=False, classifier_gate=gate)
    monitor._classifier_enabled = True
    monitor._classifier = object()
    monitor._scene_state = object()
    monitor._stream = object()
    monitor._audio_buffer.extend([1, 2, 3])
    gate.set_actual(True, "loaded")
    gate.update_from_status({"current_mode": "gaming"})

    monitor._reconcile_classifier_gate()

    assert monitor._classifier is None
    assert monitor._scene_state is None
    assert list(monitor._audio_buffer) == []
    assert monitor._stream is not None
    assert gate.snapshot()["actual_enabled"] is False


def test_ambient_reenables_without_supervisor_restart(monkeypatch):
    gate = ClassifierGate(configured=True)
    gate.update_from_status({"current_mode": "gaming"})
    monitor = AmbientMonitor(classifier_enabled=False, classifier_gate=gate)
    monitor._classifier_enabled = True
    calls = []

    def fake_init():
        calls.append("load")
        monitor._classifier = object()
        gate.set_actual(True, "loaded")
        return True
    monkeypatch.setattr(monitor, "_init_classifier", fake_init)
    gate.update_from_status({"current_mode": "working"})

    monitor._reconcile_classifier_gate(force=True)

    assert calls == ["load"]
    assert gate.snapshot()["actual_enabled"] is True


def test_supervisor_passes_one_shared_gate_to_activity_and_ambient_agents():
    supervisor = AgentSupervisor(
        server_url="http://192.168.86.210:8000",
        classifier=True,
        shadow=False,
    )
    activity = supervisor._agents["activity_detector"]
    ambient = supervisor._agents["ambient_monitor"]

    assert activity.kwargs["activity_report_callback"] == supervisor._on_activity_report
    assert ambient.kwargs["classifier_gate"] is supervisor._classifier_gate
    assert ambient.kwargs["classifier_enabled"] is True


def test_health_report_exposes_classifier_desired_actual_and_reason(monkeypatch):
    import httpx

    supervisor = AgentSupervisor(
        server_url="http://192.168.86.210:8000",
        classifier=True,
        shadow=False,
    )
    supervisor._classifier_gate.update_from_activity(
        "gaming",
        {
            "authoritative_mode": "gaming",
            "semantic_disposition": "accepted",
            "reason": "process_authority",
        },
    )
    captured = {}

    class FakeClient:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def post(self, _endpoint, json):
            captured.update(json)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    supervisor._report_health()

    assert captured["classifier"]["desired_enabled"] is False
    assert captured["classifier"]["actual_enabled"] is False
    assert captured["classifier"]["reason"] == "process_authority"


def _run_one_activity_report(monkeypatch, response, callback):
    import threading
    from backend.services.pc_agent import activity_detector as activity_module

    stop = threading.Event()

    class FakeDetector:
        def __init__(self, **_kwargs): pass
        def detect(self): return "gaming"
        def has_changed(self, _mode): return True
        def build_factors(self): return []
        def close(self): pass

    class FakeTracker:
        def start(self): pass
        def close(self): pass

    class FakeClient:
        def __init__(self, **_kwargs): pass
        def post(self, *_args, **_kwargs):
            stop.set()
            return response
        def close(self): pass

    monkeypatch.setattr(activity_module, "ActivityDetector", FakeDetector)
    monkeypatch.setattr(activity_module, "TrustedWakeInputTracker", FakeTracker)
    monkeypatch.setattr(activity_module.httpx, "Client", FakeClient)
    activity_module.run_agent(
        "http://homehub",
        stop_event=stop,
        activity_report_callback=callback,
    )


def test_activity_callback_runs_only_after_successful_authoritative_response(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"authoritative_mode": "gaming", "semantic_disposition": "accepted"}

    _run_one_activity_report(
        monkeypatch,
        Response(),
        lambda mode, result: calls.append((mode, result["authoritative_mode"])),
    )
    assert calls == [("gaming", "gaming")]


def test_activity_http_failure_cannot_change_classifier_gate(monkeypatch):
    import httpx

    calls = []

    class Response:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("bad", request=None, response=None)
        def json(self):
            raise AssertionError("json must not be read after failed status")

    _run_one_activity_report(
        monkeypatch,
        Response(),
        lambda mode, result: calls.append((mode, result)),
    )
    assert calls == []


def test_repeated_disabled_reconcile_does_not_repeat_gc(monkeypatch):
    from backend.services.pc_agent import ambient_monitor as ambient_module

    gate = ClassifierGate(configured=True)
    gate.update_from_status({"current_mode": "gaming"})
    monitor = AmbientMonitor(classifier_enabled=False, classifier_gate=gate)
    monitor._classifier_enabled = True
    monitor._classifier = object()
    monitor._scene_state = object()
    calls = []
    monkeypatch.setattr(ambient_module.gc, "collect", lambda: calls.append("gc"))

    monitor._reconcile_classifier_gate()
    monitor._reconcile_classifier_gate()
    monitor._reconcile_classifier_gate()

    assert calls == ["gc"]
    assert gate.snapshot()["detail"] == "disabled_by_authority"
