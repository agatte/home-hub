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
