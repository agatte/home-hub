"""
Unit tests for HeartbeatRegistry — the pure-data layer behind the
``/health`` task heartbeat surface. No FastAPI wiring here; integration
coverage lives in ``test_api_health.py``.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.heartbeat import HeartbeatRegistry


@pytest.fixture
def registry() -> HeartbeatRegistry:
    return HeartbeatRegistry()


class TestRegister:
    def test_register_seeds_last_tick(self, registry):
        before = datetime.now(timezone.utc)
        registry.register("hue", 1.0)
        after = datetime.now(timezone.utc)
        rows = registry.snapshot()
        assert len(rows) == 1
        # A freshly-registered task is not stale — last_tick is "now".
        assert rows[0]["name"] == "hue"
        assert rows[0]["interval_seconds"] == 1.0
        assert rows[0]["stale"] is False
        # The age sits within the registration window; allow generous slack.
        assert 0 <= rows[0]["age_seconds"] <= (after - before).total_seconds() + 0.05

    def test_register_rejects_nonpositive_interval(self, registry):
        with pytest.raises(ValueError):
            registry.register("hue", 0)
        with pytest.raises(ValueError):
            registry.register("hue", -1)

    def test_re_register_resets_last_tick(self, registry):
        registry.register("hue", 1.0)
        # Re-registering must not preserve a stale timestamp from a prior run.
        before = datetime.now(timezone.utc)
        registry.register("hue", 5.0)
        rows = registry.snapshot()
        assert rows[0]["interval_seconds"] == 5.0
        assert rows[0]["stale"] is False
        assert rows[0]["age_seconds"] < (datetime.now(timezone.utc) - before).total_seconds() + 0.05


class TestTick:
    def test_tick_updates_last_tick(self, registry):
        registry.register("hue", 1.0)
        # Inject a stale snapshot, then tick — staleness should clear.
        registry._beats["hue"].last_tick = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert registry.snapshot()[0]["stale"] is True

        registry.tick("hue")
        assert registry.snapshot()[0]["stale"] is False

    def test_tick_unknown_name_is_noop(self, registry):
        # No exception, no side effects — keeps callers safe during teardown.
        registry.tick("nope")
        assert registry.snapshot() == []


class TestSnapshot:
    def test_stale_at_2x_interval(self, registry):
        registry.register("hue", 1.0)
        # Force last_tick to 2.5x the interval ago.
        registry._beats["hue"].last_tick = (
            datetime.now(timezone.utc) - timedelta(seconds=2.5)
        )
        row = registry.snapshot()[0]
        assert row["stale"] is True
        assert row["age_seconds"] >= 2.5

    def test_just_under_threshold_not_stale(self, registry):
        registry.register("automation", 60.0)
        # 119s ago — under the 120s (2x) threshold.
        registry._beats["automation"].last_tick = (
            datetime.now(timezone.utc) - timedelta(seconds=119)
        )
        assert registry.snapshot()[0]["stale"] is False

    def test_long_cadence_warmup(self, registry):
        # Rule engine ticks every 6h. A freshly-registered rule_engine
        # must not be flagged stale just because it hasn't ticked yet.
        registry.register("rule_engine", 21600.0)
        assert registry.snapshot()[0]["stale"] is False

    def test_snapshot_sorted_by_name(self, registry):
        registry.register("zone_three", 1.0)
        registry.register("alpha", 1.0)
        registry.register("middle", 1.0)
        names = [r["name"] for r in registry.snapshot()]
        assert names == ["alpha", "middle", "zone_three"]

    def test_snapshot_now_argument_injectable(self, registry):
        registry.register("hue", 1.0)
        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        row = registry.snapshot(now=future)[0]
        assert row["stale"] is True
        assert row["age_seconds"] >= 10


class TestDeregister:
    def test_deregister_drops_from_snapshot(self, registry):
        registry.register("camera", 2.0)
        registry.deregister("camera")
        assert registry.snapshot() == []

    def test_deregister_unknown_name_is_noop(self, registry):
        registry.deregister("nope")
        assert registry.snapshot() == []

    def test_deregister_then_register_starts_warm(self, registry):
        # Camera disable → re-enable cycle: must not look stale on re-enable.
        registry.register("camera", 2.0)
        registry._beats["camera"].last_tick = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        )
        registry.deregister("camera")
        registry.register("camera", 2.0)
        assert registry.snapshot()[0]["stale"] is False


class TestClear:
    def test_clear_removes_everything(self, registry):
        registry.register("a", 1.0)
        registry.register("b", 1.0)
        registry.clear()
        assert registry.snapshot() == []
