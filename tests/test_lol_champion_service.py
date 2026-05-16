"""Tests for the LoL champion → bedroom-lamp color service.

The service consults the live AutomationEngine.current_mode, the
``champion_color_map`` app-setting, and writes through HueService. All
three are mocked here. Live integration ride-along belongs in a manual
post-deploy verification, not the unit suite.
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from backend.api.schemas.automation import ActivityReport
from backend.services import lol_champion_service as lol_mod
from backend.services.lol_champion_service import (
    DEFAULT_FALLBACK_RGB,
    LoLChampionService,
    TARGET_LIGHT_IDS,
)


class _FakeHue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> bool:
        self.calls.append((light_id, state))
        return True

    def last_for(self, light_id: str) -> dict:
        for lid, state in reversed(self.calls):
            if lid == light_id:
                return state
        raise KeyError(f"no call for {light_id}")


class _FakeEngine:
    def __init__(self, mode: str = "gaming", period: str = "night") -> None:
        self.current_mode = mode
        self._period = period

    def _get_time_period(self) -> str:
        return self._period


def _patch_setting(monkeypatch, mapping: Optional[dict[str, Any]]) -> AsyncMock:
    """Stub ``load_setting`` to return the given mapping when the service asks."""
    loader = AsyncMock(return_value=mapping)
    monkeypatch.setattr("backend.api.routes.routines.load_setting", loader)
    return loader


def _report(mode: str = "gaming", champion: Optional[str] = "Ahri") -> ActivityReport:
    factors: list[dict] = []
    if champion is not None:
        factors.append({
            "key": "champion",
            "label": "Champion",
            "value": champion,
            "display": champion,
            "impact": 1.0,
        })
    return ActivityReport(mode=mode, source="process", factors=factors or None)


# ---------------------------------------------------------------------------
# Apply / resolve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_known_champion_uses_mapped_color(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")

    # Both target lamps were written
    written_ids = {lid for lid, _ in hue.calls}
    assert written_ids == set(TARGET_LIGHT_IDS)
    assert svc.current_champion == "Ahri"
    assert svc.current_rgb == (255, 105, 180)
    # Both lamps are owned for screen-sync deferral
    assert svc.active_lights() == set(TARGET_LIGHT_IDS)
    for lid in TARGET_LIGHT_IDS:
        assert svc.is_owning(lid)


@pytest.mark.asyncio
async def test_unknown_champion_falls_back(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Lux": {"r": 255, "g": 220, "b": 90}})

    await svc.apply("NotInTheMap")

    assert svc.current_rgb == DEFAULT_FALLBACK_RGB
    assert hue.calls, "set_light must still be called with the fallback color"


@pytest.mark.asyncio
async def test_malformed_entry_falls_back(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    # Entry missing 'b' channel — service should log and use fallback rather
    # than KeyError-ing during the activity report path.
    _patch_setting(monkeypatch, {"BrokenChamp": {"r": 100, "g": 50}})

    await svc.apply("BrokenChamp")

    assert svc.current_rgb == DEFAULT_FALLBACK_RGB


@pytest.mark.asyncio
async def test_brightness_scales_by_period(monkeypatch):
    """Late-night period must produce a dimmer write than day."""
    _patch_setting(monkeypatch, {"Lux": {"r": 255, "g": 220, "b": 90}})

    hue_day = _FakeHue()
    svc_day = LoLChampionService(hue_service=hue_day, automation_engine=_FakeEngine(period="day"))
    await svc_day.apply("Lux")

    hue_night = _FakeHue()
    svc_night = LoLChampionService(hue_service=hue_night, automation_engine=_FakeEngine(period="late_night"))
    await svc_night.apply("Lux")

    # L2 day bri should be higher than L2 late_night bri.
    assert hue_day.last_for("2")["bri"] > hue_night.last_for("2")["bri"]


# ---------------------------------------------------------------------------
# on_activity_report gating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_activity_report_applies_in_gaming(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.on_activity_report(_report(mode="gaming", champion="Ahri"))

    assert svc.current_champion == "Ahri"
    assert hue.calls


@pytest.mark.asyncio
async def test_on_activity_report_noop_outside_gaming(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="working", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.on_activity_report(_report(mode="working", champion="Ahri"))

    assert svc.current_champion is None
    assert hue.calls == []
    assert svc.active_lights() == set()


@pytest.mark.asyncio
async def test_on_activity_report_noop_without_champion_factor(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    # Report has mode=gaming but no champion factor — League not in match,
    # or PC agent's Live Client poll returned 404.
    await svc.on_activity_report(_report(mode="gaming", champion=None))

    assert hue.calls == []


@pytest.mark.asyncio
async def test_on_activity_report_idempotent_same_champion(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    report = _report(mode="gaming", champion="Ahri")
    await svc.on_activity_report(report)
    initial_call_count = len(hue.calls)

    # Second identical heartbeat shouldn't re-apply.
    await svc.on_activity_report(report)
    assert len(hue.calls) == initial_call_count


# ---------------------------------------------------------------------------
# Mode-change handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_mode_change_clears_when_leaving_gaming(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")
    assert svc.active_lights() == set(TARGET_LIGHT_IDS)

    await svc.on_mode_change("working")
    assert svc.active_lights() == set()
    assert svc.current_champion is None
    for lid in TARGET_LIGHT_IDS:
        assert not svc.is_owning(lid)


@pytest.mark.asyncio
async def test_on_mode_change_keeps_state_when_staying_in_gaming(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine(mode="gaming", period="night")
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)

    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")
    await svc.on_mode_change("gaming")  # callback may fire for non-mode events too

    assert svc.current_champion == "Ahri"
    assert svc.is_owning("2")


# ---------------------------------------------------------------------------
# Factor extraction edge cases
# ---------------------------------------------------------------------------

def test_extract_champion_handles_missing_factors():
    report = ActivityReport(mode="gaming", source="process", factors=None)
    assert lol_mod._extract_champion(report) is None


def test_extract_champion_handles_empty_value():
    report = ActivityReport(
        mode="gaming",
        source="process",
        factors=[{"key": "champion", "value": "", "display": ""}],
    )
    assert lol_mod._extract_champion(report) is None


def test_extract_champion_falls_back_to_display():
    report = ActivityReport(
        mode="gaming",
        source="process",
        factors=[{"key": "champion", "display": "Zed"}],
    )
    assert lol_mod._extract_champion(report) == "Zed"
