"""Unit tests for ``clamp_client_timestamp`` (backend.api._guards).

The route-layer clock guard for off-host observation ingest (presence /
lux / blendshapes). Added after the 2026-06-07 mobo-swap incident: a
fresh-CMOS desktop clock ran ~4h40m fast and a future-stamped reading
wedged PresenceFusion + LuxChannel until real time caught up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.api._guards import clamp_client_timestamp


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestClampClientTimestamp:
    def test_none_returns_server_now(self):
        before = _now()
        out = clamp_client_timestamp(None, source="test:none")
        assert before <= out <= _now()
        assert out.tzinfo is not None

    def test_past_timestamp_passes_through(self):
        ts = _now() - timedelta(seconds=30)
        assert clamp_client_timestamp(ts, source="test:past") == ts

    def test_small_forward_skew_within_tolerance_passes(self):
        ts = _now() + timedelta(seconds=1)
        assert clamp_client_timestamp(ts, source="test:jitter") == ts

    def test_future_timestamp_clamped_to_server_now(self):
        ts = _now() + timedelta(hours=4, minutes=40)  # the incident skew
        before = _now()
        out = clamp_client_timestamp(ts, source="test:future")
        assert before <= out <= _now()

    def test_naive_timestamp_assumed_utc(self):
        naive_past = (
            _now().replace(tzinfo=None) - timedelta(seconds=10)
        )
        out = clamp_client_timestamp(naive_past, source="test:naive")
        assert out.tzinfo is not None
        assert out == naive_past.replace(tzinfo=timezone.utc)
