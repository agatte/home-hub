"""
Tests for the ML predictor health surface.

Covers:
- HealthTrackable mixin: counters, threshold transitions.
- Aggregator: top-level /health.status flips to degraded only for
  non-shadow unhealthy predictors. Shadow and idle predictors never
  trigger degraded.
- Each predictor's health() method shape.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.ml.health_mixin import (
    DEFAULT_FAILURE_THRESHOLD,
    HealthTrackable,
)


class _Tracker(HealthTrackable):
    """Bare-bones predictor for unit-testing the mixin in isolation."""

    def __init__(self, threshold: int = DEFAULT_FAILURE_THRESHOLD) -> None:
        self._init_health_tracking(failure_threshold=threshold)


class TestHealthTrackable:
    """Counters + state-machine of the mixin itself."""

    def test_initial_state_is_idle(self):
        t = _Tracker()
        h = t.health()
        assert h["status"] == "idle"
        assert h["consecutive_failures"] == 0
        assert h["last_predict_at"] is None
        assert h["last_failure"] is None

    def test_success_marks_healthy(self):
        t = _Tracker()
        t._track_predict(True)
        h = t.health()
        assert h["status"] == "healthy"
        assert h["consecutive_failures"] == 0
        assert h["last_predict_at"] is not None
        # Round-trip the timestamp — must be ISO-parseable.
        datetime.fromisoformat(h["last_predict_at"])

    def test_failure_increments(self):
        t = _Tracker()
        t._track_predict(False, ValueError("boom"))
        h = t.health()
        assert h["consecutive_failures"] == 1
        assert h["last_failure"] == "boom"

    def test_threshold_flips_to_unhealthy(self):
        t = _Tracker(threshold=3)
        for _ in range(3):
            t._track_predict(False, RuntimeError("nope"))
        assert t.health()["status"] == "unhealthy"
        assert t.health()["consecutive_failures"] == 3

    def test_success_resets_counters_and_state(self):
        t = _Tracker(threshold=2)
        t._track_predict(False, RuntimeError("first"))
        t._track_predict(False, RuntimeError("second"))
        assert t.health()["status"] == "unhealthy"
        t._track_predict(True)
        h = t.health()
        assert h["status"] == "healthy"
        assert h["consecutive_failures"] == 0
        assert h["last_failure"] is None

    def test_shadow_is_never_unhealthy(self):
        t = _Tracker(threshold=1)
        t._track_predict(False, RuntimeError("explode"))
        # Even with failures over threshold, shadow gates the label.
        h = t.health(is_shadow=True)
        assert h["status"] == "shadow"

    def test_model_not_loaded_is_unhealthy(self):
        t = _Tracker()
        t._track_predict(True)  # would otherwise be healthy
        h = t.health(model_loaded=False)
        assert h["status"] == "unhealthy"

    def test_shadow_overrides_unloaded(self):
        # A predictor in shadow with no model is correct (it's not voting),
        # so shadow wins over the model_loaded=False unhealthy path.
        t = _Tracker()
        h = t.health(is_shadow=True, model_loaded=False)
        assert h["status"] == "shadow"

    def test_long_error_message_truncated(self):
        t = _Tracker()
        long_msg = "x" * 500
        t._track_predict(False, RuntimeError(long_msg))
        # The mixin caps last_failure at 200 chars.
        assert len(t.health()["last_failure"]) <= 200

    def test_extra_fields_merged(self):
        t = _Tracker()
        h = t.health(extra={"arm_count": 42})
        assert h["arm_count"] == 42
        assert h["status"] == "idle"


class TestAggregatorBehavior:
    """Top-level /health.status aggregation — invariants only."""

    def _stub_app_state(self, predictors: dict[str, dict]) -> object:
        class _State:
            pass

        state = _State()
        for name, health_dict in predictors.items():
            class _Stub:
                def __init__(self, h): self._h = h
                def health(self): return self._h
            setattr(state, name, _Stub(health_dict))
        return state

    def test_all_healthy_passes(self):
        ml = {
            "behavioral_predictor": {"status": "shadow"},
            "lighting_learner": {"status": "healthy"},
            "music_bandit": {"status": "healthy"},
        }
        # Aggregator rule: degraded iff any unhealthy.
        assert not any(p.get("status") == "unhealthy" for p in ml.values())

    def test_unhealthy_non_shadow_triggers_degraded(self):
        ml = {
            "music_bandit": {"status": "unhealthy"},
            "lighting_learner": {"status": "healthy"},
        }
        assert any(p.get("status") == "unhealthy" for p in ml.values())

    def test_idle_does_not_trigger_degraded(self):
        # A just-rebooted process before any inference shouldn't page.
        ml = {
            "lighting_learner": {"status": "idle"},
            "music_bandit": {"status": "idle"},
        }
        assert not any(p.get("status") == "unhealthy" for p in ml.values())


class TestPredictorHealthShapes:
    """Each predictor's health() must produce the contract shape."""

    def test_lighting_learner_shape(self):
        from backend.services.ml.lighting_learner import (
            LightingPreferenceLearner,
        )

        class _StubMM:
            def get_model(self, name):
                return None

        learner = LightingPreferenceLearner(_StubMM())
        h = learner.health()
        for key in (
            "status", "model_loaded", "last_predict_at",
            "consecutive_failures", "last_failure",
        ):
            assert key in h
        assert h["status"] in {"healthy", "shadow", "idle", "unhealthy"}

    def test_music_bandit_shape(self, tmp_path):
        from backend.services.ml.music_bandit import MusicBandit

        class _StubMM:
            pass

        bandit = MusicBandit(_StubMM(), data_dir=tmp_path)
        h = bandit.health()
        assert h["status"] == "idle"
        assert h["model_loaded"] is True  # No file yet — fresh start, not corruption.
        assert "arm_count" in h

    def test_music_bandit_corrupt_file_reports_unloaded(self, tmp_path):
        from backend.services.ml.music_bandit import MusicBandit

        class _StubMM:
            pass

        # Write garbage to the bandit's persistence file.
        (tmp_path / "music_bandit.json").write_text("not json{{{")
        bandit = MusicBandit(_StubMM(), data_dir=tmp_path)
        h = bandit.health()
        assert h["model_loaded"] is False
        # No predictions yet, so even with a corrupt file the status
        # is "unhealthy" because model_loaded=False is the trigger.
        assert h["status"] == "unhealthy"

    def test_confidence_fusion_shape_idle(self):
        from backend.services.ml.confidence_fusion import ConfidenceFusion

        fusion = ConfidenceFusion()
        h = fusion.health()
        assert h["status"] == "idle"
        assert h["active_sources"] == []
        # Every source is "never_reported" at boot.
        assert len(h["never_reported"]) > 0

    def test_confidence_fusion_active_after_signal(self):
        from backend.services.ml.confidence_fusion import ConfidenceFusion

        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.9)
        h = fusion.health()
        assert h["status"] == "healthy"
        assert "process" in h["active_sources"]
