"""
Unit tests for SourceTrust — the per-source data-validity layer behind the
``/health.sources`` surface and the ML quarantine gate. Pure-data, no DB:
locks the predicate + window math, including a replay of the 2026-05-27
camera lux-pin signature that motivated the whole feature.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.source_trust import (
    CAMERA_MIN_SAMPLES,
    SourceTrust,
    camera_sanity,
    variance_collapse_predicate,
)

BASE = datetime(2026, 6, 1, 20, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def st() -> SourceTrust:
    return SourceTrust()


def _feed(st, name, samples, *, start=BASE, step_seconds=2.0):
    """Feed a list of value-dicts as timestamped observations."""
    for i, val in enumerate(samples):
        st.observe(name, val, now=start + timedelta(seconds=i * step_seconds))


def _camera_sample(lux, *, present, calibrated=True, baseline=74.0):
    return {
        "ema_lux": lux,
        "baseline_lux": baseline,
        "calibrated": calibrated,
        "present": present,
        "consecutive_absent": 0 if present else 5,
        "confidence": 0.8 if present else 0.0,
    }


class TestRegistryBasics:
    def test_untracked_source_is_trusted(self, st):
        v = st.verdict("nope")
        assert v["trusted"] is True
        assert v["reason"] == "untracked"

    def test_no_predicate_is_trusted(self, st):
        st.register("plain", predicate=None)
        st.observe("plain", {"x": 1})
        assert st.verdict("plain")["trusted"] is True
        assert st.verdict("plain")["reason"] == "no_predicate"

    def test_deregister_drops_source(self, st):
        st.register("camera", predicate=camera_sanity)
        st.deregister("camera")
        # Back to untracked → trusted fail-open.
        assert st.verdict("camera")["reason"] == "untracked"

    def test_snapshot_sorted(self, st):
        st.register("zebra", predicate=None)
        st.register("alpha", predicate=None)
        names = [r["name"] for r in st.snapshot()]
        assert names == ["alpha", "zebra"]

    def test_observe_unknown_is_noop(self, st):
        st.observe("ghost", {"x": 1})  # must not raise
        assert st.snapshot() == []

    def test_window_prunes_old_observations(self, st):
        st.register("camera", predicate=camera_sanity, window_seconds=60)
        # 50 samples 2s apart = 100s span; oldest should prune out of a 60s window.
        _feed(st, "camera", [_camera_sample(70 + i % 5, present=True) for i in range(50)])
        # Evaluate "now" at the end of the feed; only ~last 30 remain.
        v = st.verdict("camera", now=BASE + timedelta(seconds=98))
        assert v["sample_count"] <= 31


class TestCameraSanity:
    def test_insufficient_samples_trusts(self, st):
        st.register("camera", predicate=camera_sanity)
        _feed(st, "camera", [_camera_sample(70, present=True) for _ in range(5)])
        v = st.verdict("camera", now=BASE + timedelta(seconds=10))
        assert v["trusted"] is True
        assert v["reason"] == "insufficient_samples"

    def test_uncalibrated_is_untrusted(self, st):
        st.register("camera", predicate=camera_sanity)
        _feed(st, "camera", [
            _camera_sample(70 + i % 5, present=True, calibrated=False)
            for i in range(40)
        ])
        v = st.verdict("camera", now=BASE + timedelta(seconds=90))
        assert v["trusted"] is False
        assert v["reason"] == "uncalibrated"

    def test_healthy_varying_lux_is_trusted(self, st):
        st.register("camera", predicate=camera_sanity)
        # Real-room lux wanders; presence toggles. This is the happy path.
        # 90 samples × 2s = 178s span, over the 120s minimum.
        samples = [
            _camera_sample(68 + (i % 11), present=(i % 4 != 0))
            for i in range(90)
        ]
        _feed(st, "camera", samples)
        v = st.verdict("camera", now=BASE + timedelta(seconds=190))
        assert v["trusted"] is True
        assert v["reason"] == "ok"

    def test_lux_variance_collapse_is_untrusted(self, st):
        """The 2026-05-27 signature: ema_lux pinned at ~49.5 for the whole
        window while the user comes and goes. Liveness stays green; sanity
        must catch it."""
        st.register("camera", predicate=camera_sanity)
        samples = [
            _camera_sample(49.5, present=(i % 3 == 0))  # presence toggles
            for i in range(90)
        ]
        _feed(st, "camera", samples)
        v = st.verdict("camera", now=BASE + timedelta(seconds=190))
        assert v["trusted"] is False
        assert v["reason"] == "lux_variance_collapse"
        assert v["metrics"]["presence_toggled"] is True

    def test_flat_lux_without_presence_change_is_trusted(self, st):
        """A frozen lux while the user sits steadily present is NOT conclusive
        — a steady-lit room reads flat too. Don't false-positive."""
        st.register("camera", predicate=camera_sanity)
        samples = [_camera_sample(49.5, present=True) for _ in range(90)]
        _feed(st, "camera", samples)
        v = st.verdict("camera", now=BASE + timedelta(seconds=190))
        assert v["trusted"] is True

    def test_implausible_lux_is_untrusted(self, st):
        """Median lux far outside the baseline band (runaway sensor) trips
        independent of presence — vary the values so it's not caught as a
        variance collapse first."""
        st.register("camera", predicate=camera_sanity)
        samples = [
            _camera_sample(500 + (i % 17), present=(i % 2 == 0), baseline=74.0)
            for i in range(90)
        ]
        _feed(st, "camera", samples)
        v = st.verdict("camera", now=BASE + timedelta(seconds=190))
        assert v["trusted"] is False
        assert v["reason"] == "lux_implausible"


class TestManualOverride:
    def test_mark_untrusted_wins_over_predicate(self, st):
        st.register("camera", predicate=camera_sanity)
        _feed(st, "camera", [_camera_sample(70 + i % 5, present=True) for i in range(40)])
        st.mark("camera", trusted=False, reason="operator_quarantine")
        v = st.verdict("camera", now=BASE + timedelta(seconds=90))
        assert v["trusted"] is False
        assert v["manual"] is True
        assert v["reason"] == "operator_quarantine"

    def test_clear_mark_returns_to_predicate(self, st):
        st.register("camera", predicate=camera_sanity)
        _feed(st, "camera", [_camera_sample(68 + i % 9, present=(i % 3 != 0)) for i in range(90)])
        st.mark("camera", trusted=False, reason="x")
        st.clear_mark("camera")
        v = st.verdict("camera", now=BASE + timedelta(seconds=190))
        assert v["manual"] is False
        assert v["trusted"] is True

    def test_mark_trusted_overrides_a_tripped_predicate(self, st):
        st.register("camera", predicate=camera_sanity)
        # Tripping (frozen + presence toggling) but operator forces trust.
        _feed(st, "camera", [_camera_sample(49.5, present=(i % 3 == 0)) for i in range(60)])
        st.mark("camera", trusted=True, reason="known_good")
        assert st.verdict("camera", now=BASE + timedelta(seconds=130))["trusted"] is True


class TestVarianceCollapseFactory:
    def test_flat_series_trips(self, st):
        pred = variance_collapse_predicate("score", min_samples=20, epsilon=1e-3)
        st.register("audio", predicate=pred)
        _feed(st, "audio", [{"score": 0.088} for _ in range(30)])
        v = st.verdict("audio", now=BASE + timedelta(seconds=70))
        assert v["trusted"] is False
        assert v["reason"] == "variance_collapse"

    def test_varying_series_ok(self, st):
        pred = variance_collapse_predicate("score", min_samples=20, epsilon=1e-3)
        st.register("audio", predicate=pred)
        _feed(st, "audio", [{"score": 0.1 + (i % 7) * 0.05} for i in range(30)])
        assert st.verdict("audio", now=BASE + timedelta(seconds=70))["trusted"] is True

    def test_predicate_exception_fails_open(self, st):
        def boom(observations, now):
            raise RuntimeError("predicate bug")

        st.register("x", predicate=boom)
        st.observe("x", {"a": 1})
        v = st.verdict("x")
        # A crashing predicate must never make /health crash or drop data.
        assert v["trusted"] is True
        assert v["reason"].startswith("predicate_error")
