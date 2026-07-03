"""Unit tests for LuxChannel — the per-room ambient-lux store (D4 Part C).

Covers the EMA blend, stale-reset snap, out-of-order drop, calibration
gating (ema_lux None until a baseline exists), and freshness — the same
semantics CameraService uses for the living-room channel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services.lux_channel import LUX_EMA_STALE_RESET_SECONDS, LuxChannel

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _t(secs: float) -> datetime:
    return T0 + timedelta(seconds=secs)


class TestEMA:
    def test_first_sample_snaps(self):
        c = LuxChannel("bedroom")
        c.update(120.0, captured_at=T0)
        assert c.status()["ema_lux"] == 120.0

    def test_second_sample_blends(self):
        c = LuxChannel("bedroom")
        c.update(100.0, captured_at=T0)
        c.update(50.0, captured_at=_t(2))
        # α=0.3 → 0.3*50 + 0.7*100 = 85
        assert c.status()["ema_lux"] == 85.0

    def test_stale_gap_snaps_not_blend(self):
        c = LuxChannel("bedroom")
        c.update(100.0, captured_at=T0)
        # A gap ≥ stale-reset must snap to the raw reading, not average
        # yesterday's room light with today's.
        c.update(20.0, captured_at=_t(LUX_EMA_STALE_RESET_SECONDS))
        assert c.status()["ema_lux"] == 20.0

    def test_just_under_stale_gap_still_blends(self):
        c = LuxChannel("bedroom")
        c.update(100.0, captured_at=T0)
        c.update(0.0, captured_at=_t(LUX_EMA_STALE_RESET_SECONDS - 1))
        # blended: 0.3*0 + 0.7*100 = 70
        assert c.status()["ema_lux"] == 70.0

    def test_out_of_order_dropped(self):
        c = LuxChannel("bedroom")
        c.update(100.0, captured_at=_t(10))
        c.update(40.0, captured_at=T0)  # older than the kept value → drop
        assert c.status()["ema_lux"] == 100.0

    def test_naive_captured_at_treated_as_utc(self):
        c = LuxChannel("bedroom")
        c.update(80.0, captured_at=datetime(2026, 6, 1, 12, 0, 0))  # naive
        assert c.status()["ema_lux"] == 80.0
        assert c.last_lux_update.tzinfo is not None

    def test_future_stamped_last_update_self_heals(self):
        """Regression (2026-06-07 mobo-swap clock incident): a sample
        stamped hours ahead by a fast client clock must not wedge the
        channel — once honest samples resume they replace the bad stamp
        instead of being dropped as out-of-order."""
        c = LuxChannel("bedroom")
        now = datetime.now(timezone.utc)
        c.update(100.0, captured_at=now + timedelta(hours=4))
        c.update(50.0, captured_at=now)
        # Blended (0.3*50 + 0.7*100) — proof the honest sample was accepted.
        assert c.status()["ema_lux"] == 85.0
        assert c.last_lux_update <= datetime.now(timezone.utc)


class TestCalibrationGating:
    def test_ema_lux_none_until_calibrated(self):
        c = LuxChannel("bedroom")
        c.update(100.0)
        assert c.ema_lux is None  # no baseline → no usable engine reading
        assert c.calibrated is False
        # ...but the raw smoothed value is still observable for shadow-logging.
        assert c.status()["ema_lux"] == 100.0

    def test_set_baseline_unlocks_ema(self):
        c = LuxChannel("bedroom")
        c.update(100.0)
        c.set_baseline(74.0)
        assert c.ema_lux == 100.0
        assert c.baseline_lux == 74.0
        assert c.calibrated is True

    def test_seeded_baseline(self):
        c = LuxChannel("bedroom", baseline_lux=74.0)
        assert c.calibrated is True
        c.update(60.0)
        assert c.ema_lux == 60.0

    def test_set_baseline_none_relocks(self):
        c = LuxChannel("bedroom", baseline_lux=74.0)
        c.set_baseline(None)
        assert c.calibrated is False
        assert c.ema_lux is None


class TestFreshness:
    def test_fresh_after_recent_update(self):
        c = LuxChannel("bedroom")
        c.update(100.0)  # captured_at defaults to now()
        assert c.is_fresh(30) is True

    def test_not_fresh_when_never_updated(self):
        assert LuxChannel("bedroom").is_fresh(30) is False

    def test_not_fresh_when_stale(self):
        c = LuxChannel("bedroom")
        c.update(100.0, captured_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        assert c.is_fresh(30) is False


class TestStatusShape:
    def test_status_fields(self):
        c = LuxChannel("bedroom", baseline_lux=74.0)
        c.update(88.0)
        s = c.status()
        assert s == {
            "room": "bedroom",
            "ema_lux": 88.0,
            "baseline_lux": 74.0,
            "calibrated": True,
            "last_update": s["last_update"],  # ISO string, presence asserted below
        }
        assert s["last_update"] is not None

    def test_status_uncalibrated_empty_channel(self):
        s = LuxChannel("bedroom").status()
        assert s["ema_lux"] is None
        assert s["calibrated"] is False
        assert s["last_update"] is None
