"""
Tests for the /api/automation/screen-color route handler dispatch logic.

The handler maps payload regions to lights, gates on mode, and skips lights
that have a manual slider override stamped. These tests verify all three
shapes:

  - dual-region payload writes both L2 and L5
  - legacy ``{r, g, b}`` payload writes only L2 (the primary target)
  - a manual override on one light skips that one, but the other still applies
"""
from types import SimpleNamespace

import pytest

from backend.api.routes.automation import receive_screen_color
from backend.api.schemas.automation import RegionColor, ScreenColorReport
from backend.services.screen_sync import ScreenSyncService


class _FakeHue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> None:
        self.calls.append((light_id, state))

    def lights_touched(self) -> list[str]:
        return [lid for lid, _ in self.calls]


def _fake_engine(current_mode: str, manual_light_overrides=None, period: str = "day"):
    """Minimal fake automation engine — just the attributes the route reads."""
    return SimpleNamespace(
        current_mode=current_mode,
        manual_light_overrides=manual_light_overrides or set(),
        _get_time_period=lambda: period,
    )


def _make_request(engine, sync, camera=None):
    """Build the minimal request shape the handler reads."""
    state = SimpleNamespace(
        automation=engine,
        screen_sync=sync,
        camera_service=camera,
    )
    app = SimpleNamespace(state=state)
    return SimpleNamespace(app=app)


@pytest.mark.asyncio
async def test_dual_region_dispatches_to_both_lights():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    req = _make_request(engine, sync)

    report = ScreenColorReport(
        regions={
            "left":  RegionColor(r=220, g=40, b=40),
            "right": RegionColor(r=40, g=40, b=220),
        }
    )
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(result["lights"]) == {"2", "5"}
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
async def test_legacy_payload_writes_only_l2():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is True
    assert result["lights"] == ["2"]
    assert hue.lights_touched() == ["2"]


@pytest.mark.asyncio
async def test_manual_override_on_one_light_skips_only_that_one():
    """L2 stamped → skip L2 but still apply L5."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming", manual_light_overrides={"2"})
    req = _make_request(engine, sync)

    report = ScreenColorReport(
        regions={
            "left":  RegionColor(r=220, g=40, b=40),
            "right": RegionColor(r=40, g=40, b=220),
        }
    )
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is True
    assert result["lights"] == ["5"]
    assert result.get("skipped") == ["2"]
    assert hue.lights_touched() == ["5"]


@pytest.mark.asyncio
async def test_off_mode_drops_silently():
    """Working mode is not in SCREEN_SYNC_MODES → applied=False, no hue writes."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("working")
    req = _make_request(engine, sync)

    report = ScreenColorReport(
        regions={
            "left":  RegionColor(r=220, g=40, b=40),
            "right": RegionColor(r=40, g=40, b=220),
        }
    )
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is False
    assert hue.calls == []


@pytest.mark.asyncio
async def test_empty_payload_returns_empty_reason():
    """No regions and no r/g/b → applied=False, reason=empty_payload."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    req = _make_request(engine, sync)

    report = ScreenColorReport()
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is False
    assert result["reason"] == "empty_payload"
    assert hue.calls == []
