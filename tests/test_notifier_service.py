"""Unit tests for NotifierService — threshold logic + dispatch path."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.services.notifier_service import (
    BOOT_SUPPRESS_S,
    BRIGHTNESS_DELTA_THRESHOLD,
    COALESCE_WINDOW_S,
    NotifierService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _MockWS:
    """Captures broadcast calls so tests can assert on them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def broadcast(self, message_type: str, data: Any) -> None:
        self.calls.append((message_type, data))


class _MockEngine:
    """Minimal AutomationEngine shape that NotifierService reads."""

    def __init__(
        self,
        mode: str = "working",
        mode_source: str = "process",
        dnd: bool = False,
        applied: dict | None = None,
        fusion: dict | None = None,
        override_source: str | None = None,
    ) -> None:
        self.current_mode = mode
        self.mode_source = mode_source
        self.override_source = override_source
        self._dnd = dnd
        # Match the engine's private attr name — NotifierService reads it
        # via getattr.
        self._last_applied_per_light = applied or {
            "1": {"on": True, "bri": 127},
            "2": {"on": True, "bri": 127},
            "3": {"on": True, "bri": 127},
            "4": {"on": True, "bri": 127},
        }
        self._last_fusion_result = fusion or {
            "signals": {
                "process": {
                    "factors": [
                        {"label": "process", "value": "working", "impact": 0.9},
                        {"label": "idle_s", "value": "12", "impact": 0.3},
                    ],
                },
                "camera": {
                    "factors": [
                        {"label": "zone", "value": "desk", "impact": 0.6},
                    ],
                },
            },
        }

    def is_dnd_active(self) -> bool:
        return self._dnd


@pytest.fixture
def ws():
    return _MockWS()


@pytest.fixture
def engine():
    return _MockEngine()


@pytest.fixture
async def notifier(ws, engine):
    n = NotifierService(
        ws_manager=ws, automation_engine=engine, ntfy_topic=None,
    )
    # Bypass boot suppression for most tests; individual tests that care
    # can reset boot_at.
    n._state.boot_at = time.time() - BOOT_SUPPRESS_S - 1
    yield n
    await n.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_observation_seeds_no_fire(notifier, ws, engine):
    """First call records the snapshot but does NOT emit."""
    await notifier._maybe_emit(reason="poll")
    assert ws.calls == []
    assert notifier._state.last_mode == "working"


@pytest.mark.asyncio
async def test_mode_change_fires_notification(notifier, ws, engine):
    """An autonomous mode flip fires a single WS broadcast."""
    await notifier._maybe_emit(reason="poll")  # seed
    engine.current_mode = "relax"
    engine.mode_source = "late_night_rescue"
    engine.override_source = "late_night_rescue"
    await notifier._maybe_emit(reason="mode_change")

    assert len(ws.calls) == 1
    msg_type, payload = ws.calls[0]
    assert msg_type == "notification"
    assert payload["title"] == "working → relax"
    assert payload["subtitle"] == "late_night_rescue"
    assert payload["mode_changed"] is True
    assert payload["brightness_shifted"] is False
    assert len(payload["factors"]) <= 3
    # Top factor by impact should be from the process lane (impact 0.9).
    assert payload["factors"][0]["impact"] == 0.9


@pytest.mark.asyncio
async def test_user_initiated_mode_change_suppressed(notifier, ws, engine):
    """A mode flip from api: / manual / alexa: / guest: skips the toast."""
    await notifier._maybe_emit(reason="poll")
    engine.current_mode = "cooking"
    engine.mode_source = "api:192.168.1.30"
    await notifier._maybe_emit(reason="mode_change")
    assert ws.calls == []


@pytest.mark.asyncio
async def test_manual_source_suppressed(notifier, ws, engine):
    await notifier._maybe_emit(reason="poll")
    engine.current_mode = "social"
    engine.mode_source = "manual"
    await notifier._maybe_emit(reason="mode_change")
    assert ws.calls == []


@pytest.mark.asyncio
async def test_brightness_shift_above_threshold_fires(notifier, ws, engine):
    """A 20% brightness drop on the per-light state fires."""
    await notifier._maybe_emit(reason="poll")  # seed at bri=127 avg

    # Drop all brightness by ~40% — should easily clear the 15% threshold.
    for state in engine._last_applied_per_light.values():
        state["bri"] = 70
    await notifier._maybe_emit(reason="poll")

    assert len(ws.calls) == 1
    msg_type, payload = ws.calls[0]
    assert msg_type == "notification"
    assert payload["brightness_shifted"] is True
    assert payload["mode_changed"] is False
    assert "dimmer" in payload["title"]
    assert payload["output_delta"] is not None


@pytest.mark.asyncio
async def test_brightness_shift_below_threshold_skipped(notifier, ws, engine):
    """A 5% brightness drop is below threshold and skipped."""
    await notifier._maybe_emit(reason="poll")

    for state in engine._last_applied_per_light.values():
        state["bri"] = 120  # ~5.5% drop from 127
    await notifier._maybe_emit(reason="poll")

    assert ws.calls == []


@pytest.mark.asyncio
async def test_dnd_suppresses_emit(notifier, ws, engine):
    """Active DND suppresses both seeding and firing."""
    engine._dnd = True
    await notifier._maybe_emit(reason="poll")
    engine.current_mode = "relax"
    await notifier._maybe_emit(reason="mode_change")
    assert ws.calls == []


@pytest.mark.asyncio
async def test_boot_suppression(ws, engine):
    """Within the boot window, nothing fires."""
    n = NotifierService(
        ws_manager=ws, automation_engine=engine, ntfy_topic=None,
    )
    # Default boot_at is now → in the suppression window.
    engine.current_mode = "relax"
    await n._maybe_emit(reason="mode_change")
    assert ws.calls == []
    await n.close()


@pytest.mark.asyncio
async def test_coalesce_window(notifier, ws, engine):
    """Two changes within COALESCE_WINDOW_S collapse to one notification."""
    await notifier._maybe_emit(reason="poll")  # seed

    engine.current_mode = "relax"
    engine.mode_source = "fusion"
    engine.override_source = "fusion"
    await notifier._maybe_emit(reason="mode_change")
    assert len(ws.calls) == 1

    # Immediately follow with a brightness shift — within coalesce window,
    # should NOT fire again.
    for state in engine._last_applied_per_light.values():
        state["bri"] = 60
    await notifier._maybe_emit(reason="poll")
    assert len(ws.calls) == 1

    # But: the snapshot must have been updated so the next fire-after-window
    # compares against post-burst state, not pre-burst.
    assert notifier._state.last_brightness < 0.3


@pytest.mark.asyncio
async def test_factors_sorted_by_impact_top3(notifier, ws, engine):
    """Top 3 factors come out sorted by impact desc, regardless of lane."""
    engine._last_fusion_result = {
        "signals": {
            "process": {"factors": [
                {"label": "p1", "value": "x", "impact": 0.10},
                {"label": "p2", "value": "y", "impact": 0.95},
            ]},
            "camera": {"factors": [
                {"label": "c1", "value": "z", "impact": 0.40},
                {"label": "c2", "value": "w", "impact": 0.20},
            ]},
            "rule_engine": {"factors": [
                {"label": "r1", "value": "v", "impact": 0.80},
            ]},
        },
    }
    await notifier._maybe_emit(reason="poll")
    engine.current_mode = "relax"
    engine.mode_source = "fusion"
    await notifier._maybe_emit(reason="mode_change")

    payload = ws.calls[0][1]
    impacts = [f["impact"] for f in payload["factors"]]
    assert impacts == [0.95, 0.80, 0.40]


@pytest.mark.asyncio
async def test_emit_synthetic_bypasses_gating(ws, engine):
    """emit_synthetic always fires, regardless of DND / boot / coalesce."""
    engine._dnd = True
    n = NotifierService(
        ws_manager=ws, automation_engine=engine, ntfy_topic=None,
    )
    # In boot window AND DND active — emit_synthetic still fires.
    payload = await n.emit_synthetic(title="hello", body="world")
    await n.close()
    assert len(ws.calls) == 1
    assert ws.calls[0][1]["title"] == "hello"
    assert payload["title"] == "hello"


@pytest.mark.asyncio
async def test_ntfy_post_skipped_when_topic_unset(notifier, ws, engine):
    """No NTFY_TOPIC → no HTTP POST attempted, WS still fires."""
    notifier._http = AsyncMock()  # would fail if called

    await notifier._maybe_emit(reason="poll")
    engine.current_mode = "relax"
    engine.mode_source = "fusion"
    await notifier._maybe_emit(reason="mode_change")

    assert len(ws.calls) == 1
    notifier._http.post.assert_not_called()


@pytest.mark.asyncio
async def test_effective_brightness_off_lights_count_zero(notifier, engine):
    """Lights with on=False contribute 0 to the average bri."""
    engine._last_applied_per_light = {
        "1": {"on": True, "bri": 254},
        "2": {"on": False, "bri": 254},  # ignored as off, contributes 0
        "3": {"on": True, "bri": 254},
        "4": {"on": False},               # ignored as off
    }
    # 2 of 4 lights at full = 0.5
    assert abs(notifier._effective_brightness() - 0.5) < 0.01


@pytest.mark.asyncio
async def test_slow_drift_does_not_accumulate_into_false_positive(
    notifier, ws, engine,
):
    """Many small sub-threshold changes must not stack into a shift fire.

    Pre-fix bug (2026-05-17): non-firing checks returned without updating
    last_brightness, so slow EMA-lux drift would eventually cross 15%
    versus a stale baseline and emit a "shift" notification even though
    no rapid change happened. Fix: update last_brightness on every check
    so the comparison is always "shift since the last poll (~5s)."
    """
    await notifier._maybe_emit(reason="poll")  # seed at avg bri 0.5

    # Five sequential ~5% drops. None individually crosses 15%, and the
    # CUMULATIVE drop (127 → 90 = ~29%) must not fire if the bug is
    # actually fixed — each check should re-baseline.
    for new_bri in (120, 113, 106, 99, 90):
        for state in engine._last_applied_per_light.values():
            state["bri"] = new_bri
        await notifier._maybe_emit(reason="poll")

    assert ws.calls == []
    # And the snapshot must have followed the drift, not stayed at the seed.
    assert notifier._state.last_brightness < 0.40


@pytest.mark.asyncio
async def test_brightness_threshold_constant_sanity():
    """Lock in the 15% threshold — bumping it requires a test update."""
    assert BRIGHTNESS_DELTA_THRESHOLD == 0.15
    assert COALESCE_WINDOW_S == 10.0
    assert BOOT_SUPPRESS_S == 30.0
