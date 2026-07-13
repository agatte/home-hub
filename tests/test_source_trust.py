"""
Unit tests for SourceTrust — the per-source data-validity layer behind the
``/health.sources`` surface and the ML quarantine gate. Pure-data, no DB:
locks the predicate + window math, including a replay of the 2026-05-27
camera lux-pin signature that motivated the whole feature.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.source_trust import (
    AUDIO_COLLAPSE_MIN_SPAN_SECONDS,
    AUDIO_MIN_SAMPLES,
    AUDIO_WINDOW_SECONDS,
    CAMERA_MAX_SAMPLES,
    CAMERA_MIN_SAMPLES,
    CAMERA_WINDOW_SECONDS,
    LUX_COLLAPSE_MIN_SAMPLES,
    SourceTrust,
    camera_sanity,
    register_audio_ml,
    variance_collapse_predicate,
)

# The ambient monitor's steady-state shadow-log cadence (ambient_monitor.py
# SHADOW_LOG_INTERVAL). Hardcoded rather than imported — that module pulls in
# httpx/audio deps at import time. Kept in sync by the sizing-guard test below.
AMBIENT_SHADOW_LOG_INTERVAL = 30

BASE = datetime(2026, 6, 1, 20, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def st() -> SourceTrust:
    return SourceTrust()


def _register_camera(st):
    """Register the camera with production window/buffer so long-horizon feeds
    aren't pruned away before the variance-collapse check can see them."""
    st.register(
        "camera",
        predicate=camera_sanity,
        window_seconds=CAMERA_WINDOW_SECONDS,
        max_samples=CAMERA_MAX_SAMPLES,
    )


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
        _register_camera(st)
        # Frozen lux that PERSISTS past the 90-min horizon while presence toggles
        # — the decoupled-sensor signature. 720 samples × 8s ≈ 96 min span.
        n = max(720, LUX_COLLAPSE_MIN_SAMPLES + 120)
        step = 8.0
        samples = [_camera_sample(49.5, present=(i % 3 == 0)) for i in range(n)]
        _feed(st, "camera", samples, step_seconds=step)
        v = st.verdict("camera", now=BASE + timedelta(seconds=(n - 1) * step))
        assert v["trusted"] is False
        assert v["reason"] == "lux_variance_collapse"
        assert v["metrics"]["presence_toggled"] is True

    def test_short_steady_episode_is_trusted(self, st):
        """Regression for the 2026-06-02 false positive: ~4 min of steady lux
        while presence toggles (person settling in under constant light) must
        NOT trip — the freeze hasn't persisted long enough to mean decoupling."""
        _register_camera(st)
        samples = [_camera_sample(35.0, present=(i % 3 == 0)) for i in range(120)]
        _feed(st, "camera", samples, step_seconds=2.0)  # ~4 min span
        v = st.verdict("camera", now=BASE + timedelta(seconds=240))
        assert v["trusted"] is True
        assert v["reason"] == "ok"

    def test_long_steady_no_presence_toggle_is_trusted(self, st):
        """Person sitting still under constant light for 90+ min (presence never
        toggles) is not conclusive of a decoupled sensor — stay trusted."""
        _register_camera(st)
        n = max(720, LUX_COLLAPSE_MIN_SAMPLES + 120)
        step = 8.0
        samples = [_camera_sample(49.5, present=True) for _ in range(n)]
        _feed(st, "camera", samples, step_seconds=step)
        v = st.verdict("camera", now=BASE + timedelta(seconds=(n - 1) * step))
        assert v["trusted"] is True

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
        _register_camera(st)
        # Genuinely tripping (frozen lux past the 90-min horizon + presence
        # toggling) but operator forces trust — the mark must win.
        n = max(720, LUX_COLLAPSE_MIN_SAMPLES + 120)
        step = 8.0
        _feed(st, "camera", [_camera_sample(49.5, present=(i % 3 == 0)) for i in range(n)],
              step_seconds=step)
        # Sanity: without the mark this would be untrusted.
        assert st.verdict("camera", now=BASE + timedelta(seconds=(n - 1) * step))["trusted"] is False
        st.mark("camera", trusted=True, reason="known_good")
        assert st.verdict("camera", now=BASE + timedelta(seconds=(n - 1) * step))["trusted"] is True


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


class TestAudioLaneWiring:
    """The audio_ml lane registration (GH #98). register_audio_ml is the single
    source bootstrap + this test share, so the production window sizing is what's
    exercised here."""

    def _now(self, n, step=AMBIENT_SHADOW_LOG_INTERVAL):
        # Verdict time = last sample's timestamp, so the window prune keeps the
        # whole feed (n samples at `step`s span well under AUDIO_WINDOW_SECONDS).
        return BASE + timedelta(seconds=(n - 1) * step)

    def test_stuck_classifier_trips(self, st):
        # The abandoned YAMNet speech_multiple tell: a flat ~0.088 top_score.
        register_audio_ml(st)
        n = 25
        _feed(st, "audio_ml", [{"top_score": 0.088, "top_class": "speech"}
                               for _ in range(n)],
              step_seconds=AMBIENT_SHADOW_LOG_INTERVAL)
        v = st.verdict("audio_ml", now=self._now(n))
        assert v["trusted"] is False
        assert v["reason"] == "variance_collapse"

    def test_varying_scores_ok(self, st):
        register_audio_ml(st)
        n = 25
        _feed(st, "audio_ml",
              [{"top_score": 0.2 + (i % 7) * 0.05, "top_class": "music"}
               for i in range(n)],
              step_seconds=AMBIENT_SHADOW_LOG_INTERVAL)
        v = st.verdict("audio_ml", now=self._now(n))
        assert v["trusted"] is True
        assert v["reason"] == "ok"

    def test_below_quorum_fails_open(self, st):
        # Fewer than AUDIO_MIN_SAMPLES → no judgement, stays trusted.
        register_audio_ml(st)
        n = AUDIO_MIN_SAMPLES - 5
        _feed(st, "audio_ml", [{"top_score": 0.088, "top_class": "speech"}
                               for _ in range(n)],
              step_seconds=AMBIENT_SHADOW_LOG_INTERVAL)
        v = st.verdict("audio_ml", now=self._now(n))
        assert v["trusted"] is True
        assert v["reason"] == "insufficient_samples"

    def test_flat_high_confidence_silence_stays_trusted(self, st):
        # A quiet room can legitimately produce sustained near-1.0 idle/silence
        # scores; that is not the low-confidence stuck-classifier signature.
        register_audio_ml(st)
        n = 25
        _feed(st, "audio_ml", [{"top_score": 0.999999, "top_class": "idle"}
                               for _ in range(n)],
              step_seconds=AMBIENT_SHADOW_LOG_INTERVAL)
        v = st.verdict("audio_ml", now=self._now(n))
        assert v["trusted"] is True
        assert v["reason"] == "ok"

    def test_short_flat_burst_fails_open(self, st):
        # The monitor can produce bursts faster than the steady-state cadence;
        # do not quarantine from seconds of flat output alone.
        register_audio_ml(st)
        n = 25
        _feed(st, "audio_ml", [{"top_score": 0.088, "top_class": "speech"}
                               for _ in range(n)],
              step_seconds=1)
        v = st.verdict("audio_ml", now=self._now(n, step=1))
        assert v["trusted"] is True
        assert v["reason"] == "insufficient_span"
        assert v["metrics"]["need_span_seconds"] == AUDIO_COLLAPSE_MIN_SPAN_SECONDS

    def test_window_holds_quorum_at_shadow_cadence(self):
        # Regression guard: the window MUST be wide enough to accumulate
        # AUDIO_MIN_SAMPLES at the ambient monitor's shadow-log cadence.
        # The 300s registry default holds only ~10 samples and would make the
        # predicate fail-open forever (the resume-defaults trap from the camera
        # lane). This assertion fails loudly if anyone reverts the sizing.
        assert AUDIO_WINDOW_SECONDS / AMBIENT_SHADOW_LOG_INTERVAL >= AUDIO_MIN_SAMPLES
