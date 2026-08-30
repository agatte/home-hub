"""
Tests for the /api/automation/screen-color route handler dispatch logic.

Mirror semantics: a single ``{r, g, b}`` payload writes to every lamp in
``sync.target_lights``. Per-light EMA + caps still differentiate output;
this test file covers the dispatch surface only.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.api.routes.automation import (
    get_screen_sync_status,
    receive_screen_color,
    report_activity,
)
from backend.api.schemas.automation import ActivityReport, ScreenColorReport
from backend.services.automation_engine import AutomationEngine
from backend.services.light_state_calculator import resolve_activity_state
from backend.services.presence_fusion import PresenceFusion, PresenceReading
from backend.services.screen_sync import ScreenSyncService


class _FakeHue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> bool:
        self.calls.append((light_id, state))
        return True

    def lights_touched(self) -> list[str]:
        return [lid for lid, _ in self.calls]

    def last_for(self, light_id: str) -> dict:
        for lid, state in reversed(self.calls):
            if lid == light_id:
                return state
        raise KeyError(f"no call for {light_id}")


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


def _owned_watching_engine(device: str):
    engine = _fake_engine("watching")
    engine.get_activity_context = lambda: {
        "current_activity": "watching",
        "current_activity_source_key": f"process:{device}",
        "current_activity_fresh": True,
        "process_evidence_by_device": {
            device: {
                "committed_mode": "watching",
                "age_seconds": 0.0,
            },
        },
    }
    return engine


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
async def test_generic_gaming_report_applies_canonical_target_states():
    """One report writes both targets without adopting sampled RGB."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(result["lights"]) == {"2", "5"}
    assert set(hue.lights_touched()) == {"2", "5"}
    expected = resolve_activity_state("gaming", "day")
    l2 = hue.last_for("2")
    l5 = hue.last_for("5")
    assert l2["ct"] == expected["2"]["ct"] == 286
    assert l5["ct"] == expected["5"]["ct"] == 286
    assert "hue" not in l2 and "sat" not in l2
    assert "hue" not in l5 and "sat" not in l5


@pytest.mark.asyncio
async def test_desktop_gaming_rejects_laptop_frames_before_any_light_write():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    req = _make_request(_fake_engine("gaming"), sync)

    rejected = await receive_screen_color(
        ScreenColorReport(r=220, g=40, b=40, source="laptop"), req,
    )  # type: ignore[arg-type]
    accepted = await receive_screen_color(
        ScreenColorReport(r=220, g=40, b=40, source="desktop"), req,
    )  # type: ignore[arg-type]

    assert rejected == {
        "status": "ok",
        "applied": False,
        "reason": "laptop_source_requires_latitude_watching",
        "reported_source": "laptop",
        "authoritative_source": "desktop",
        "authority_reason": "desktop_gaming",
    }
    assert accepted["applied"] is True
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
async def test_rust_cannot_consume_laptop_luma_from_rejected_latitude_session():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine("gaming")
    engine.current_game = "rust"
    req = _make_request(engine, sync)

    result = await receive_screen_color(
        ScreenColorReport(r=0, g=0, b=0, luma=0, source="laptop"), req,
    )  # type: ignore[arg-type]

    assert result["applied"] is False
    assert result["reason"] == "laptop_source_requires_latitude_watching"
    assert hue.calls == []


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
async def test_desktop_watching_holds_last_media_color_on_non_media_foreground():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    req = _make_request(_owned_watching_engine("desktop"), sync)

    applied = await receive_screen_color(
        ScreenColorReport(
            r=1, g=1, b=100, source="desktop", foreground_media=True,
        ),
        req,
    )  # type: ignore[arg-type]
    calls_after_media = list(hue.calls)
    last_color_after_media = sync.last_color_at

    held = await receive_screen_color(
        ScreenColorReport(
            r=43, g=24, b=49, source="desktop", foreground_media=False,
        ),
        req,
    )  # type: ignore[arg-type]

    assert applied["applied"] is True
    assert held == {
        "status": "ok",
        "applied": False,
        "reason": "watching_foreground_not_media",
        "reported_source": "desktop",
    }
    assert hue.calls == calls_after_media
    assert sync.last_color_at == last_color_after_media

    resumed = await receive_screen_color(
        ScreenColorReport(
            r=1, g=1, b=100, source="desktop", foreground_media=True,
        ),
        req,
    )  # type: ignore[arg-type]
    assert resumed["applied"] is True


@pytest.mark.asyncio
async def test_legacy_watching_report_without_foreground_media_still_applies():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    req = _make_request(_owned_watching_engine("desktop"), sync)

    result = await receive_screen_color(
        ScreenColorReport(r=1, g=1, b=100, source="desktop"), req,
    )  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
async def test_gaming_ignores_non_media_foreground_flag():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    req = _make_request(_fake_engine("gaming"), sync)

    result = await receive_screen_color(
        ScreenColorReport(
            r=1, g=1, b=100, source="desktop", foreground_media=False,
        ),
        req,
    )  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["working", "sleeping"])
async def test_off_mode_drops_silently(mode):
    """Off modes, including sleeping, drop samples without Hue writes."""
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    engine = _fake_engine(mode)
    req = _make_request(engine, sync)

    report = ScreenColorReport(r=220, g=40, b=40)
    result = await receive_screen_color(report, req)  # type: ignore[arg-type]

    assert result["applied"] is False
    assert hue.calls == []


@pytest.mark.asyncio
async def test_process_watching_release_closes_screen_color_gate(
    mock_hue, mock_hue_v2, mock_ws,
):
    """A committed desktop idle release stops later screen-color writes."""
    presence = PresenceFusion()
    presence.on_observation(PresenceReading(
        source="desktop",
        captured_at=datetime.now(timezone.utc),
        face_present=True,
        face_confidence=0.95,
        zone="desk",
    ))
    sync = ScreenSyncService(
        hue_service=mock_hue, target_light_ids=["2", "5"],
    )
    engine = AutomationEngine(
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
        screen_sync=sync,
        presence_fusion=presence,
    )
    req = _make_request(engine, sync)
    req.app.state.presence = presence
    desktop_factors = [{"key": "device", "value": "desktop"}]

    await engine.report_activity(
        mode="watching", source="process", factors=desktop_factors,
    )
    applied = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="desktop"), req,
    )
    assert applied["applied"] is True

    await engine.report_activity(
        mode="idle", source="process", factors=desktop_factors,
    )
    lights_after_release = [
        light.copy() for light in await mock_hue.get_all_lights()
    ]

    dropped = await receive_screen_color(
        ScreenColorReport(r=220, g=40, b=40, source="desktop"), req,
    )

    assert engine.current_mode == "idle"
    assert dropped["applied"] is False
    assert await mock_hue.get_all_lights() == lights_after_release


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


def _calibrated_bedroom_lux(ema, baseline=127.0, *, age_s=0.0):
    """A calibrated bedroom LuxChannel for the route to read (D4 Part E)."""
    from backend.services.lux_channel import LuxChannel
    ch = LuxChannel("bedroom", baseline_lux=baseline)
    captured_at = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    ch.update(ema, captured_at=captured_at)
    return ch


@pytest.mark.asyncio
async def test_generic_gaming_brightness_ignores_screen_and_lux():
    """Dark samples and bedroom lux cannot reduce canonical day brightness."""
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
        # Black frame should still produce the canonical gaming base.
        for _ in range(30):
            await receive_screen_color(ScreenColorReport(r=0, g=0, b=0), req)
        return next(s["bri"] for lid, s in reversed(hue.calls) if lid == "2")

    l2_dark = await run(80.0)
    l2_bright = await run(180.0)

    expected = resolve_activity_state("gaming", "day")["2"]["bri"]
    assert l2_dark == expected
    assert l2_bright == expected


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


@pytest.mark.asyncio
async def test_watching_lux_lift_holds_through_short_desktop_gap():
    """A late desktop lux sample should not make L2 pulse back to neutral."""
    async def run(age_s):
        hue = _FakeHue()
        sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
        engine = _fake_engine("watching", period="day")
        req = _make_request(engine, sync)
        req.app.state.bedroom_lux = _calibrated_bedroom_lux(40.0, age_s=age_s)
        for _ in range(30):
            await receive_screen_color(ScreenColorReport(r=0, g=0, b=0), req)
        return next(s["bri"] for lid, s in reversed(hue.calls) if lid == "2")

    fresh = await run(5.0)
    held = await run(120.0)
    assert held == fresh


@pytest.mark.asyncio
async def test_watching_lux_lift_falls_back_after_stale_reset_window():
    """Past the LuxChannel reset horizon, screen sync uses neutral lux."""
    async def run(age_s):
        hue = _FakeHue()
        sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
        engine = _fake_engine("watching", period="day")
        req = _make_request(engine, sync)
        req.app.state.bedroom_lux = _calibrated_bedroom_lux(40.0, age_s=age_s)
        for _ in range(30):
            await receive_screen_color(ScreenColorReport(r=0, g=0, b=0), req)
        return next(s["bri"] for lid, s in reversed(hue.calls) if lid == "2")

    held = await run(120.0)
    stale = await run(360.0)
    assert held > stale


class _FakePresence:
    """Minimal PresenceFusion stand-in returning a fixed fused zone/posture."""

    def __init__(self, zone=None, posture=None) -> None:
        self._zone = zone
        self._posture = posture

    def latest_zone(self, max_age_s: int = 30):
        return self._zone

    def latest_posture(self, max_age_s: int = 30):
        return self._posture


@pytest.mark.asyncio
async def test_watching_desk_cap_fires_off_fused_zone():
    """The watching-at-desk L2 cap (180) must fire off the FUSED desk zone
    (PresenceFusion), not the Latitude couch camera. Post-2026-05-27 the
    Latitude sees the couch, so the route reads ``app.state.presence`` — a
    fresh desktop face makes ``latest_zone()`` return "desk". A white frame at
    the desk drives L2 well above the dim base watching cap (80); with no fused
    desk zone it stays clamped to it."""
    async def run(presence):
        hue = _FakeHue()
        sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
        engine = _fake_engine("watching", period="night")
        req = _make_request(engine, sync)
        if presence is not None:
            req.app.state.presence = presence
        # White frame → max luma → L2 target rides its cap; converge the EMA.
        for _ in range(40):
            await receive_screen_color(ScreenColorReport(r=255, g=255, b=255), req)
        return next(s["bri"] for lid, s in reversed(hue.calls) if lid == "2")

    desk = await run(_FakePresence(zone="desk", posture="slouched"))
    couch = await run(None)  # no fusion → camera fallback (zone None) → cap 80

    assert desk > 80, (
        f"watching-at-desk should lift L2 above the dim 80 cap via the fused "
        f"zone (got {desk}); if ≤80 the route is ignoring app.state.presence"
    )
    assert couch <= 80, f"no desk zone → L2 holds the dim watching cap (got {couch})"
    assert desk > couch


class _FakeActivityEngine:
    def __init__(
        self,
        current_mode: str = "watching",
        result: dict | None = None,
        context: dict | None = None,
    ) -> None:
        self.reports: list[tuple[str, str, list[dict] | None]] = []
        self.current_mode = current_mode
        self.result = result or {
            "reported_mode": "watching",
            "semantic_disposition": "accepted",
            "reason": "accepted",
            "semantic_mode": "watching",
            "authoritative_mode": "watching",
            "included_in_fusion": True,
        }
        self.context = context or {
            "current_activity": "watching",
            "current_activity_source_key": "process:latitude",
            "current_activity_fresh": True,
        }

    async def report_activity(self, mode: str, source: str, factors=None) -> dict:
        self.reports.append((mode, source, factors))
        return self.result

    def get_activity_context(self) -> dict:
        return self.context


class _DispositionActivityEngine:
    current_mode = "working"

    async def report_activity(self, mode: str, source: str, factors=None) -> dict:
        return {
            "reported_mode": mode,
            "observed_source": "process:desktop",
            "semantic_disposition": "rejected",
            "reason": "recent_desk_presence",
            "semantic_mode": "working",
            "authoritative_mode": "working",
            "included_in_fusion": False,
        }


class _FakeLoopback:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.starts = 0
        self.stops = 0

    async def start(self) -> None:
        self.running = True
        self.starts += 1

    async def stop(self) -> None:
        self.running = False
        self.stops += 1


@pytest.mark.asyncio
async def test_latitude_streaming_activity_marks_couch_presence_and_owns_loopback():
    engine = _FakeActivityEngine()
    presence = PresenceFusion()
    loopback = _FakeLoopback()
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                automation=engine,
                presence=presence,
                laptop_loopback=loopback,
            )
        )
    )

    active = ActivityReport(
        mode="watching",
        source="process",
        factors=[
            {"key": "device", "value": "latitude"},
            {"key": "playback_active", "value": True},
        ],
    )
    await report_activity(active, req)  # type: ignore[arg-type]
    await asyncio.sleep(0)

    assert presence.latest_zone() == "couch"
    assert presence.is_strongly_present_any() is True
    assert loopback.running is True
    assert loopback.starts == 1

    idle = ActivityReport(
        mode="idle",
        source="process",
        factors=[
            {"key": "device", "value": "latitude"},
            {"key": "playback_active", "value": False},
        ],
    )
    engine.current_mode = "idle"
    engine.result = {
        "reported_mode": "idle",
        "semantic_disposition": "accepted",
        "reason": "accepted",
        "semantic_mode": "idle",
        "authoritative_mode": "idle",
        "included_in_fusion": True,
    }
    engine.context = {
        "current_activity": "idle",
        "current_activity_source_key": "process:latitude",
        "current_activity_fresh": True,
    }
    await report_activity(idle, req)  # type: ignore[arg-type]

    assert presence.latest_zone() is None
    assert loopback.running is False
    assert loopback.stops == 1


@pytest.mark.asyncio
async def test_rejected_latitude_watching_does_not_start_loopback_or_presence():
    engine = _FakeActivityEngine(
        current_mode="gaming",
        result={
            "reported_mode": "watching",
            "semantic_disposition": "rejected",
            "reason": "source_priority",
            "semantic_mode": None,
            "authoritative_mode": "gaming",
            "included_in_fusion": False,
        },
        context={
            "current_activity": "gaming",
            "current_activity_source_key": "process:desktop",
            "current_activity_fresh": True,
        },
    )
    presence = PresenceFusion()
    loopback = _FakeLoopback()
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                automation=engine,
                presence=presence,
                laptop_loopback=loopback,
            )
        )
    )

    response = await report_activity(
        ActivityReport(
            mode="watching",
            source="process",
            factors=[
                {"key": "device", "value": "latitude"},
                {"key": "playback_active", "value": True},
            ],
        ),
        req,  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)

    assert response["semantic_disposition"] == "rejected"
    assert loopback.starts == 0
    assert loopback.running is False
    assert presence.get_source_reading("latitude_streaming") is None


class _BlockingStartLoopback(_FakeLoopback):
    def __init__(self) -> None:
        super().__init__()
        self.release_start = asyncio.Event()

    async def start(self) -> None:
        self.starts += 1
        await self.release_start.wait()
        self.running = True


@pytest.mark.asyncio
async def test_latitude_activity_post_does_not_wait_for_loopback_start():
    engine = _FakeActivityEngine()
    loopback = _BlockingStartLoopback()
    state = SimpleNamespace(automation=engine, laptop_loopback=loopback)
    req = SimpleNamespace(app=SimpleNamespace(state=state))
    active = ActivityReport(
        mode="watching",
        source="process",
        factors=[
            {"key": "device", "value": "latitude"},
            {"key": "playback_active", "value": True},
        ],
    )

    response = await asyncio.wait_for(
        report_activity(active, req),  # type: ignore[arg-type]
        timeout=0.1,
    )
    await asyncio.sleep(0)

    assert response["status"] == "ok"
    assert loopback.starts == 1
    assert loopback.running is False

    loopback.release_start.set()
    start_task = state.latitude_streaming_loopback_start_task
    await asyncio.wait_for(start_task, timeout=0.1)
    assert loopback.running is True


@pytest.mark.asyncio
async def test_latitude_watching_retraction_cancels_pending_auto_start():
    engine = _FakeActivityEngine()
    loopback = _BlockingStartLoopback()
    state = SimpleNamespace(automation=engine, laptop_loopback=loopback)
    req = SimpleNamespace(app=SimpleNamespace(state=state))
    active = ActivityReport(
        mode="watching",
        source="process",
        factors=[
            {"key": "device", "value": "latitude"},
            {"key": "playback_active", "value": True},
        ],
    )
    await report_activity(active, req)  # type: ignore[arg-type]
    await asyncio.sleep(0)
    start_task = state.latitude_streaming_loopback_start_task

    engine.current_mode = "idle"
    engine.result = {
        "reported_mode": "idle",
        "semantic_disposition": "accepted",
        "reason": "accepted",
        "semantic_mode": "idle",
        "authoritative_mode": "idle",
        "included_in_fusion": True,
    }
    engine.context = {
        "current_activity": "idle",
        "current_activity_source_key": "process:latitude",
        "current_activity_fresh": True,
    }
    await report_activity(
        ActivityReport(
            mode="idle",
            source="process",
            factors=[
                {"key": "device", "value": "latitude"},
                {"key": "playback_active", "value": False},
            ],
        ),
        req,  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)

    assert start_task.cancelled() is True
    assert loopback.running is False
    assert loopback.stops == 0
    assert state.latitude_streaming_loopback_started is False


@pytest.mark.asyncio
async def test_activity_route_returns_truthful_semantic_disposition():
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(automation=_DispositionActivityEngine()),
        ),
    )
    response = await report_activity(
        ActivityReport(
            mode="idle", source="process",
            factors=[{"key": "device", "value": "desktop"}],
        ),
        req,  # type: ignore[arg-type]
    )

    assert response["accepted_mode"] == "working"
    assert response["reported_mode"] == "idle"
    assert response["semantic_disposition"] == "rejected"
    assert response["reason"] == "recent_desk_presence"
    assert response["authoritative_mode"] == "working"
    assert response["included_in_fusion"] is False


@pytest.mark.asyncio
async def test_desktop_screen_color_stays_bedroom_when_service_can_write_all_lamps():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4", "6"],
    )
    engine = _fake_engine("watching")
    req = _make_request(engine, sync)

    result = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="desktop"), req,
    )  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(result["lights"]) == {"2", "5"}
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
async def test_laptop_watching_screen_color_targets_living_room_and_kitchen():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4", "6"],
    )
    engine = _fake_engine("watching")
    req = _make_request(engine, sync)

    result = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="laptop"), req,
    )  # type: ignore[arg-type]

    assert result["applied"] is True
    assert set(result["lights"]) == {"1", "3", "4"}
    assert set(hue.lights_touched()) == {"1", "3", "4"}


@pytest.mark.asyncio
async def test_latitude_owned_watching_rejects_desktop_and_accepts_laptop():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4"],
    )
    engine = _owned_watching_engine("latitude")
    req = _make_request(engine, sync)

    rejected = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="desktop"), req,
    )  # type: ignore[arg-type]
    accepted = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="laptop"), req,
    )  # type: ignore[arg-type]

    assert rejected == {
        "status": "ok",
        "applied": False,
        "reason": "non_authoritative_source",
        "reported_source": "desktop",
        "authoritative_source": "laptop",
        "authority_reason": "accepted_latitude_watching",
    }
    assert accepted["applied"] is True
    assert accepted["authoritative_source"] == "laptop"
    assert set(accepted["lights"]) == {"1", "3", "4"}
    assert set(hue.lights_touched()) == {"1", "3", "4"}


@pytest.mark.asyncio
async def test_desktop_owned_watching_uses_desktop_bedroom_targets():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4"],
    )
    engine = _owned_watching_engine("desktop")
    req = _make_request(engine, sync)

    rejected = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="laptop"), req,
    )  # type: ignore[arg-type]
    accepted = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="desktop"), req,
    )  # type: ignore[arg-type]

    assert rejected["reason"] == "non_authoritative_source"
    assert rejected["authoritative_source"] == "desktop"
    assert accepted["applied"] is True
    assert accepted["authoritative_source"] == "desktop"
    assert set(accepted["lights"]) == {"2", "5"}
    assert set(hue.lights_touched()) == {"2", "5"}


@pytest.mark.asyncio
async def test_manual_watching_uses_fresh_desktop_desk_authority():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4"],
    )
    engine = _fake_engine("watching")
    engine.get_activity_context = lambda: {
        "current_activity": "idle",
        "current_activity_source_key": "process:desktop",
        "current_activity_fresh": True,
        "process_evidence_by_device": {},
    }
    presence = PresenceFusion()
    presence.on_observation(PresenceReading(
        source="desktop",
        captured_at=datetime.now(timezone.utc),
        face_present=True,
        face_confidence=0.95,
        zone="desk",
    ))
    req = _make_request(engine, sync)
    req.app.state.presence = presence

    result = await receive_screen_color(
        ScreenColorReport(r=40, g=80, b=220, source="desktop"), req,
    )  # type: ignore[arg-type]

    assert result["applied"] is True
    assert result["authority_reason"] == "fresh_desktop_desk_presence"
    assert set(result["lights"]) == {"2", "5"}


@pytest.mark.asyncio
async def test_screen_sync_status_exposes_watching_source_authority():
    hue = _FakeHue()
    sync = ScreenSyncService(
        hue_service=hue,
        target_light_ids=["2", "5", "1", "3", "4"],
    )
    req = _make_request(_owned_watching_engine("latitude"), sync)

    status = await get_screen_sync_status(req)  # type: ignore[arg-type]

    assert status["source_authority_enforced"] is True
    assert status["authoritative_source"] == "laptop"
    assert status["authority_reason"] == "accepted_latitude_watching"
    assert status["authoritative_targets"] == ["1", "3", "4"]
