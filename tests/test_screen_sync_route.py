"""
Tests for the /api/automation/screen-color route handler dispatch logic.

Mirror semantics: a single ``{r, g, b}`` payload writes to every lamp in
``sync.target_lights``. Per-light EMA + caps still differentiate output;
this test file covers the dispatch surface only.
"""
from types import SimpleNamespace

import pytest

from backend.api.routes.automation import receive_screen_color
from backend.api.schemas.automation import ScreenColorReport
from backend.services.screen_sync import ScreenSyncService


class _FakeHue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> None:
        self.calls.append((light_id, state))

    def lights_touched(self) -> list[str]:
        return [lid for lid, _ in self.calls]


def _fake_engine(
    current_mode: str,
    manual_light_overrides=None,
    period: str = "day",
    weather_condition=None,
):
    """Minimal fake automation engine — just the attributes the route reads."""
    return SimpleNamespace(
        current_mode=current_mode,
        manual_light_overrides=manual_light_overrides or set(),
        _get_time_period=lambda: period,
        _get_current_weather_condition=lambda: weather_condition,
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
async def test_single_color_mirrors_to_all_target_lights():
    """One {r, g, b} payload fans out to every lamp the service manages."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(result["lights"]) == {"2", "5"}
    assert set(hue.lights_touched()) == {"2", "5"}
    # Both writes carry the same hue (red) — different bri/sat is fine because
    # of per-light caps + luma comp; here we just confirm the input mirrored.
    l2_hue = next(state["hue"] for lid, state in hue.calls if lid == "2")
    l5_hue = next(state["hue"] for lid, state in hue.calls if lid == "5")
    assert abs(l2_hue - l5_hue) < 100, (
        f"mirrored writes should carry the same hue (L2={l2_hue} L5={l5_hue})"
    )


@pytest.mark.asyncio
async def test_manual_override_on_one_light_skips_only_that_one():
    """L2 stamped → skip L2 but L5 still mirrors the screen color."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming", manual_light_overrides={"2"})
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
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

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is False
    assert hue.calls == []


@pytest.mark.asyncio
async def test_all_lights_overridden_returns_skip_list():
    """If every target lamp is stamped, applied=False with both in skipped."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming", manual_light_overrides={"2", "5"})
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is False
    assert set(result["skipped"]) == {"2", "5"}
    assert hue.calls == []


def _calibrated_bedroom_lux(ema, baseline=127.0):
    """A calibrated, fresh bedroom LuxChannel for the route to read (D4 Part E)."""
    from backend.services.lux_channel import LuxChannel
    ch = LuxChannel("bedroom", baseline_lux=baseline)
    ch.update(ema)  # stamps last_update=now → is_fresh(60) True
    return ch


@pytest.mark.asyncio
async def test_gaming_floor_scales_with_bedroom_lux_not_camera():
    """D4 Part E: the gaming-day envelope is scaled by the BEDROOM lux channel,
    not the living-room camera. Hold the camera BRIGHT in both runs (it must be
    ignored for lux) and vary only the bedroom: a dark bedroom must lift the
    floor above a bright one."""
    # Camera reads bright (mult < 1) in BOTH runs — proves it's not the source.
    bright_camera = SimpleNamespace(
        zone=None, posture=None, ema_lux=180.0, baseline_lux=127.0,
    )
    engine = _fake_engine("gaming", period="day")

    async def run(bedroom_ema):
        hue = _FakeHue()
        sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
        req = _make_request(engine, sync, camera=bright_camera)
        req.app.state.bedroom_lux = _calibrated_bedroom_lux(bedroom_ema)
        # Black frame → bri target sits at the (lux-scaled) floor.
        for _ in range(30):
            await receive_screen_color(ScreenColorReport(r=0, g=0, b=0), req)
        return next(s["bri"] for lid, s in reversed(hue.calls) if lid == "2")

    l2_dark = await run(80.0)    # bedroom darker than baseline 127 → lift
    l2_bright = await run(180.0)  # bedroom brighter than baseline → dim

    assert l2_dark > l2_bright, (
        f"a dark bedroom must lift the gaming floor above a bright one "
        f"(dark={l2_dark} bright={l2_bright}); if equal, the route is still "
        f"reading the (constant) camera lux, not the bedroom channel"
    )


@pytest.mark.asyncio
async def test_uncalibrated_bedroom_lux_is_neutral():
    """No calibration → no scaling (lux_mult 1.0), route still applies cleanly."""
    from backend.services.lux_channel import LuxChannel
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming", period="day")
    req = _make_request(engine, sync)
    req.app.state.bedroom_lux = LuxChannel("bedroom")  # uncalibrated
    result = await receive_screen_color(ScreenColorReport(r=0, g=0, b=0), req)
    assert result["applied"] is True
