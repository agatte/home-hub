"""Tests for the pure exposure-search helper (D4 Part B bedroom-lux calibration).

``search_exposure`` is camera-agnostic — it drives a ``measure_fn`` callback,
so we test the convergence logic with a synthetic monotonic brightness curve
(no webcam / OpenCV needed). The real ``_run_lux_calibration`` wraps this with
a cv2 measure function and is exercised live (it needs the Brio).
"""
from __future__ import annotations

from backend.services.pc_agent.emotion_capture import (
    LUX_ACCEPT_HI,
    LUX_ACCEPT_LO,
    search_exposure,
)


def _room(k: float):
    """Synthetic camera: brighter exposure (less negative) → higher mean.

    ``mean(e) = k * 2**((e+6)/2)`` — at e=-6 the mean is ``k``. Higher ``k``
    models a brighter room. Each ±2 exposure step ~halves/doubles the mean,
    matching the driver behavior the search assumes.
    """
    return lambda e: k * 2 ** ((e + 6) / 2.0)


class TestSearchExposure:
    def test_in_band_at_start_accepts_immediately(self):
        calls = []
        e, m = search_exposure(lambda x: calls.append(x) or _room(83.0)(x))
        assert e == -6.0  # start, no adjustment
        assert LUX_ACCEPT_LO <= m <= LUX_ACCEPT_HI
        assert len(calls) == 1  # accepted on the first measure

    def test_dark_room_raises_exposure(self):
        e, m = search_exposure(_room(20.0))
        assert e > -6.0  # stepped toward brighter exposure
        assert LUX_ACCEPT_LO <= m <= LUX_ACCEPT_HI

    def test_bright_room_lowers_exposure(self):
        e, m = search_exposure(_room(400.0))
        assert e < -6.0  # stepped toward darker exposure
        assert LUX_ACCEPT_LO <= m <= LUX_ACCEPT_HI

    def test_read_failure_aborts_immediately(self):
        calls = []

        def m(e):
            calls.append(e)
            return -1.0

        exposure, measured = search_exposure(m)
        assert measured < 0
        assert len(calls) == 1  # no further sweeping after a read failure

    def test_too_dark_clamps_to_max_exposure(self):
        # Even at the brightest exposure the room never reaches the band.
        e, m = search_exposure(_room(5.0))
        assert e == 0.0  # clamped at exp_max
        assert m < LUX_ACCEPT_LO  # out of band → caller warns + recalibrates

    def test_too_bright_clamps_to_min_exposure(self):
        e, m = search_exposure(_room(5000.0))
        assert e == -12.0  # clamped at exp_min
        assert m > LUX_ACCEPT_HI

    def test_respects_max_iter(self):
        calls = []

        def m(e):
            calls.append(e)
            return 10.0  # always too dark → never accepts

        search_exposure(m, max_iter=3)
        assert len(calls) == 3


class TestShouldSampleLux:
    """Part A cadence gate: calibrated + interval elapsed → sample."""

    def _agent(self):
        from backend.services.pc_agent.emotion_capture import EmotionCapture
        return EmotionCapture("http://test:8000")

    def test_uncalibrated_never_samples(self):
        a = self._agent()
        try:
            a._lux_exposure = None
            assert a._should_sample_lux(1000.0) is False
        finally:
            a.close()

    def test_first_sample_fires_when_calibrated(self):
        a = self._agent()
        try:
            a._lux_exposure = -5.0
            a._last_lux_sample_at = None
            assert a._should_sample_lux(1000.0) is True
        finally:
            a.close()

    def test_waits_for_interval_then_fires(self):
        from backend.services.pc_agent.emotion_capture import LUX_SAMPLE_INTERVAL_S
        a = self._agent()
        try:
            a._lux_exposure = -5.0
            a._last_lux_sample_at = 1000.0
            # Just before the interval → no sample.
            assert a._should_sample_lux(
                1000.0 + LUX_SAMPLE_INTERVAL_S - 0.5
            ) is False
            # At/after the interval → sample.
            assert a._should_sample_lux(1000.0 + LUX_SAMPLE_INTERVAL_S) is True
        finally:
            a.close()


class TestLuxAutoExposureRecovery:
    def test_sample_keeps_handle_when_auto_recovers(self, monkeypatch):
        from backend.services.pc_agent import emotion_capture as ec

        class Cap:
            def __init__(self):
                self.released = False
                self.set_calls = []

            def isOpened(self):
                return True

            def set(self, prop, value):
                self.set_calls.append((prop, value))
                return True

            def read(self):
                return True, object()

            def release(self):
                self.released = True

        class Gray:
            @staticmethod
            def mean():
                return 42.0

        class CV2:
            CAP_PROP_AUTO_EXPOSURE = 1
            CAP_PROP_EXPOSURE = 2
            COLOR_BGR2GRAY = 3

            @staticmethod
            def cvtColor(frame, code):
                return Gray()

        monkeypatch.setattr(ec.time, "sleep", lambda _: None)
        agent = ec.EmotionCapture("http://test:8000")
        cap = Cap()
        posted = []
        agent._cap = cap
        agent._lux_exposure = -6.0
        monkeypatch.setattr(agent, "_post_lux", posted.append)
        try:
            agent._sample_lux(CV2)
            assert posted == [42.0]
            assert cap.released is False
            assert agent._cap is cap
        finally:
            agent.close()


class TestLuxRecoveryDecision:
    def test_black_collapse_reopens(self):
        from backend.services.pc_agent.emotion_capture import _lux_auto_recovery_needs_reopen
        assert _lux_auto_recovery_needs_reopen(90.0, 0.1, True) is True

    def test_normal_recovery_keeps_handle(self):
        from backend.services.pc_agent.emotion_capture import _lux_auto_recovery_needs_reopen
        assert _lux_auto_recovery_needs_reopen(90.0, 35.0, True) is False

    def test_failed_restore_reopens(self):
        from backend.services.pc_agent.emotion_capture import _lux_auto_recovery_needs_reopen
        assert _lux_auto_recovery_needs_reopen(90.0, 35.0, False) is True

    def test_very_dark_reference_does_not_churn(self):
        from backend.services.pc_agent.emotion_capture import _lux_auto_recovery_needs_reopen
        assert _lux_auto_recovery_needs_reopen(4.0, 0.2, True) is False
