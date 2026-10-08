"""No-device regression tests for microphone lifecycle and sensing health."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from backend.services.pc_agent import ambient_monitor as module
from backend.services.pc_agent.classifier_gate import ClassifierGate
from backend.api.routes.automation import _merge_agent_health_reports


def test_closed_stream_disposed_backoff_and_fresh_recovery(monkeypatch, caplog):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    gate = ClassifierGate(True)
    monitor = module.AmbientMonitor(classifier_gate=gate)
    calls = []

    class Stream:
        def read(self, *_args, **_kwargs):
            if clock[0] < 110:
                raise OSError(-9988, "Stream closed")
            return np.zeros(module.CHUNK_SIZE, dtype=np.int16).tobytes()
        def stop_stream(self):
            calls.append("stop")
            raise OSError("already closed")
        def close(self): calls.append("close")

    class Audio:
        def __init__(self): calls.append("create")
        def get_device_count(self): return 1
        def get_device_info_by_index(self, _index): return {"name": "Blue Yeti"}
        def get_format_from_width(self, _width): return 1
        def open(self, **kwargs):
            assert kwargs["input_device_index"] == 0
            calls.append("open")
            return Stream()
        def terminate(self): calls.append("terminate")

    monkeypatch.setitem(sys.modules, "pyaudio", SimpleNamespace(PyAudio=Audio))
    monitor._quiet_start = 1
    monitor._audio_buffer.extend([1] * module.YAMNET_SAMPLES)
    assert monitor.check() is None
    assert calls == ["create", "open", "stop", "close", "terminate"]
    assert monitor._quiet_start is None
    assert not monitor._audio_buffer
    assert monitor.classify_scene() is None
    assert gate.snapshot()["audio"]["stream_state"] == "recovering"
    for _ in range(20):
        monitor.check()
    assert calls.count("open") == 1
    assert sum(r.levelname == "WARNING" for r in caplog.records) == 1
    clock[0] = 101
    monitor.check()
    assert monitor._audio_retry_after == 103
    clock[0] = 110
    monitor.check()
    assert gate.snapshot()["audio"]["stream_state"] == "healthy"
    assert gate.snapshot()["audio"]["last_success_at"] == 110
    monitor.check()
    assert calls.count("open") == 3
    monitor.close()
    monitor.close()
    assert calls.count("terminate") == 3


def test_partial_open_failure_terminated_and_retry_capped(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    calls = []
    class Audio:
        def get_device_count(self): return 0
        def get_default_input_device_info(self):
            calls.append("default")
            raise OSError("unplugged")
        def terminate(self): calls.append("terminate")
    monkeypatch.setitem(sys.modules, "pyaudio", SimpleNamespace(PyAudio=Audio))
    monitor = module.AmbientMonitor()
    for _ in range(10):
        monitor.check()
        assert monitor._audio is None
        assert monitor._stream is None
        assert monitor._audio_retry_after - clock[0] <= 60
        clock[0] = monitor._audio_retry_after
    assert calls.count("terminate") == 10


def test_classification_consumes_fresh_buffer_and_policy(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monitor = module.AmbientMonitor()
    monitor._classifier_enabled = True
    gate = ClassifierGate(True)
    monitor._classifier_gate = gate
    calls = []
    result = SimpleNamespace(top_class="silence", confidence=0.9, all_scores={},
                             raw_yamnet_top5=[], inference_ms=1)
    monitor._classifier = SimpleNamespace(classify=lambda _audio: calls.append(1) or result,
                                         reset_history=lambda: calls.append("reset"))
    class Scene:
        def update(self, *_args): return None
    monitor._scene_state = Scene()
    class Stream:
        def read(self, *_args, **_kwargs):
            return np.zeros(module.CHUNK_SIZE, dtype=np.int16).tobytes()
    monitor._stream = Stream()
    for _ in range(15):
        clock[0] += 1
        monitor.check()
        assert monitor.classify_scene() is None
    monitor.check()
    assert monitor.classify_scene() is not None
    assert monitor.classify_scene() is None
    assert calls == [1]
    for _ in range(3):
        clock[0] += 1
        monitor.check()
        assert monitor.classify_scene() is not None
        assert monitor.classify_scene() is None
        assert len(monitor._audio_buffer) == module.YAMNET_SAMPLES
    assert calls == [1] * 4
    monitor._classifier.classify = lambda _audio: calls.append("failed") or None
    monitor.check()
    assert monitor.classify_scene() is None
    assert monitor.classify_scene() is None
    assert calls.count("failed") == 1
    assert len(monitor._audio_buffer) == module.YAMNET_SAMPLES
    gate.update_from_status({"current_mode": "gaming"})
    assert monitor.classify_scene() is None
    assert not monitor._audio_buffer
    assert monitor._audio_sample_sequence == monitor._classified_sample_sequence == 0


def test_merge_ages_audio_without_changing_other_agents():
    report = {"classifier": {"audio": {"stream_state": "healthy", "sample_age_seconds": 1}},
              "agents": {"activity_detector": {"status": "running"}}}
    reports = {"desktop": {"report": report, "received_at": 100}}
    # Use the same receipt envelope as the route.
    from backend.api.routes.automation import _stored_agent_health_report
    assert _stored_agent_health_report(reports["desktop"])[1] == 100
    merged = _merge_agent_health_reports(reports, now=170)
    assert merged["classifier"]["audio"]["stream_state"] == "unavailable"
    assert merged["agents"]["activity_detector"]["status"] == "running"
    assert report["classifier"]["audio"]["stream_state"] == "healthy"
    assert "classifier" not in _merge_agent_health_reports(reports, now=500)


async def test_health_audio_degraded_recovered_and_disabled(monkeypatch):
    from backend.api.routes.health import health_check
    from backend.api.routes import routines
    async def no_setting(_key): return None
    monkeypatch.setattr(routines, "load_setting", no_setting)
    classifier = {"configured": True, "desired_enabled": True, "actual_enabled": True,
                  "audio": {"stream_state": "recovering", "last_success_at": 90,
                            "sample_age_seconds": 10}}
    state = SimpleNamespace(agent_health_clock=lambda: 100,
        agent_health_reports={"desktop": {"received_at": 100,
                                         "report": {"classifier": classifier}}})
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    result = await health_check(request)
    assert result["status"] == "degraded"
    classifier["audio"].update(stream_state="healthy", sample_age_seconds=0)
    assert (await health_check(request))["status"] == "healthy"
    classifier["desired_enabled"] = False
    classifier["audio"]["stream_state"] = "recovering"
    result = await health_check(request)
    assert result["status"] == "degraded"
    classifier["audio"]["stream_state"] = "healthy"
    result = await health_check(request)
    assert result["status"] == "healthy"
    assert result["ml"]["audio_classifier"]["status"] == "idle"


def test_recovered_samples_resume_ml_without_old_scene_history(monkeypatch):
    monitor = module.AmbientMonitor()
    monitor._classifier_enabled = True
    calls = []
    result = SimpleNamespace(top_class="silence", confidence=0.9, all_scores={},
                             raw_yamnet_top5=[], inference_ms=1)
    monitor._classifier = SimpleNamespace(classify=lambda _audio: result,
                                         reset_history=lambda: calls.append("reset"))
    class Scene:
        def __init__(self): self.old = False
        def update(self, *_args): return "quiet" if self.old else None
    monitor._scene_state = Scene()
    monitor._scene_state.old = True
    monitor._audio_buffer.extend([99] * module.YAMNET_SAMPLES)
    monitor._audio_failed(OSError(-9988, "Stream closed"))
    assert calls == ["reset"]
    assert not monitor._scene_state.old
    assert not monitor._audio_buffer
    class Stream:
        def read(self, *_args, **_kwargs):
            return np.zeros(module.CHUNK_SIZE, dtype=np.int16).tobytes()
    monitor._stream = Stream()
    for _ in range(16):
        monitor.check()
    assert monitor.classify_scene()["mode_signal"] is None
    assert monitor._last_audio_success is not None


@pytest.mark.parametrize("configured,desired", [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize("stream", ["recovering", "unavailable"])
async def test_mic_failure_independent_of_classifier_policy(monkeypatch, configured, desired, stream):
    from backend.api.routes.health import health_check
    from backend.api.routes import routines
    async def no_setting(_key): return None
    monkeypatch.setattr(routines, "load_setting", no_setting)
    classifier = {"configured": configured, "desired_enabled": desired, "actual_enabled": False,
                  "audio": {"stream_state": stream}}
    state = SimpleNamespace(agent_health_clock=lambda: 100,
        agent_health_reports={"desktop": {"received_at": 100,
                                         "report": {"classifier": classifier}}})
    result = await health_check(SimpleNamespace(app=SimpleNamespace(state=state)))
    assert result["status"] == "degraded"


@pytest.mark.parametrize("legacy", [False, True])
async def test_expired_audio_report_requires_fresh_recovery(monkeypatch, legacy):
    from backend.api.routes.health import health_check
    from backend.api.routes.automation import get_agent_health
    from backend.api.routes import routines
    async def no_setting(_key): return None
    monkeypatch.setattr(routines, "load_setting", no_setting)
    clock = [100.0]
    classifier = {"configured": True, "desired_enabled": True, "actual_enabled": True,
                  "audio": {"stream_state": "recovering", "sample_age_seconds": 0}}
    stored = {"received_at": 100, "report": {"classifier": classifier}}
    state = SimpleNamespace(agent_health_clock=lambda: clock[0])
    if legacy:
        state.agent_health = stored
    else:
        state.agent_health_reports = {"desktop": stored}
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    assert (await health_check(request))["status"] == "degraded"
    for age in [300, 301, 600]:
        clock[0] = 100 + age
        assert (await health_check(request))["status"] == "degraded"
    assert "classifier" not in await get_agent_health(request)
    assert not (await health_check(request))["ml"]["audio_classifier"]["report_current"]
    for engine in [SimpleNamespace(current_mode="sleeping"),
                   SimpleNamespace(current_mode="home", _external_off_detected=True)]:
        engine.last_weather_class = None
        engine.last_lux_multiplier = 1.0
        state.automation = engine
        assert (await health_check(request))["status"] == "healthy"
    state.automation = SimpleNamespace(current_mode="home", last_weather_class=None,
                                       last_lux_multiplier=1.0)
    classifier["audio"]["stream_state"] = "healthy"
    assert (await health_check(request))["status"] == "degraded"
    stored["received_at"] = clock[0]
    assert (await health_check(request))["status"] == "healthy"
    # Untimestamped legacy data cannot claim current sensing health.
    delattr(state, "agent_health" if legacy else "agent_health_reports")
    state.agent_health = {"classifier": classifier}
    assert (await health_check(request))["status"] == "degraded"
    state.agent_health = {}
    assert (await health_check(request))["status"] == "healthy"
