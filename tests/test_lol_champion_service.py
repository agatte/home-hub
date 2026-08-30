"""Tests for the LoL champion → bedroom-lamp color service.

The service consults the live AutomationEngine.current_mode, the
``champion_color_map`` app-setting, and writes through HueService. All
three are mocked here. Live integration ride-along belongs in a manual
post-deploy verification, not the unit suite.
"""
from __future__ import annotations

import asyncio
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
from backend.services.light_applicator import LightApplyResult
from backend.services.lighting_transition_boundary import LightingTransitionBoundary


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
        self.released: list[set[str]] = []
        self._last_applied_per_light: dict[str, dict] = {}
        self.reapplied = 0
        self.manual_light_overrides: set[str] = set()
        self._transit_light_overrides: dict[str, object] = {}
        self.reclaim_result: Optional[LightApplyResult] = None

    def _get_time_period(self) -> str:
        return self._period

    async def reclaim_external_light_release(
        self, owner, light_ids: set[str],
    ) -> LightApplyResult:
        self.released.append(set(light_ids))
        return self.reclaim_result or LightApplyResult(successful=set(light_ids))

    async def reapply_current_mode(self, *, force_resend: bool = True) -> None:
        self.reapplied += 1


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


@pytest.mark.asyncio
async def test_partial_champion_write_owns_only_acknowledged_lamps(monkeypatch):
    class PartiallyFailingHue(_FakeHue):
        async def set_light(self, light_id: str, state: dict) -> bool:
            self.calls.append((light_id, state))
            return light_id == "2"

    hue = PartiallyFailingHue()
    engine = _FakeEngine()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")

    assert svc.active_lights() == {"2"}
    assert set(svc.owned_light_targets()) == {"2"}


@pytest.mark.asyncio
async def test_only_acknowledged_champion_write_supersedes_screen_sync(monkeypatch):
    class PartiallyFailingHue(_FakeHue):
        async def set_light(self, light_id: str, state: dict) -> bool:
            self.calls.append((light_id, state))
            return light_id == "2"

    class SyncSpy:
        def __init__(self):
            self.superseded: list[str] = []

        def supersede_light(self, light_id: str) -> None:
            self.superseded.append(light_id)

    engine = _FakeEngine()
    engine._screen_sync = SyncSpy()
    svc = LoLChampionService(PartiallyFailingHue(), engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")

    assert engine._screen_sync.superseded == ["2"]


@pytest.mark.asyncio
async def test_champion_write_serializes_on_shared_transition_boundary(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine()
    engine._transition_boundary = LightingTransitionBoundary(hue)
    svc = LoLChampionService(hue, engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with engine._transition_boundary.serialized():
            entered.set()
            await release.wait()

    holding = asyncio.create_task(holder())
    await entered.wait()
    applying = asyncio.create_task(svc.apply("Ahri"))
    await asyncio.sleep(0)
    assert hue.calls == []
    release.set()
    await holding
    await applying
    assert {light_id for light_id, _state in hue.calls} == {"2", "5"}


@pytest.mark.asyncio
async def test_clear_reapplies_released_lamps_from_engine_current_plan(monkeypatch):
    hue = _FakeHue()
    engine = _FakeEngine()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})

    await svc.apply("Ahri")
    await svc.clear()

    assert engine.released == [{"2", "5"}]


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


@pytest.mark.asyncio
async def test_partial_same_champion_failure_retries_only_missing_lamp(monkeypatch):
    class RecoveringHue(_FakeHue):
        def __init__(self):
            super().__init__()
            self.failed_l5 = False

        async def set_light(self, light_id: str, state: dict) -> bool:
            self.calls.append((light_id, state))
            if light_id == "5" and not self.failed_l5:
                self.failed_l5 = True
                return False
            return True

    hue = RecoveringHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=_FakeEngine())
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})
    report = _report(champion="Ahri")

    await svc.on_activity_report(report)
    assert svc.active_lights() == {"2"}
    assert svc.current_champion is None
    await svc.on_activity_report(report)

    assert [lid for lid, _ in hue.calls].count("2") == 1
    assert [lid for lid, _ in hue.calls].count("5") == 2
    assert svc.active_lights() == {"2", "5"}
    assert svc.current_champion == "Ahri"


@pytest.mark.asyncio
async def test_partial_champion_switch_retries_only_mismatched_lamp(monkeypatch):
    class SwitchFailHue(_FakeHue):
        fail_next_l5 = False

        async def set_light(self, light_id: str, state: dict) -> bool:
            self.calls.append((light_id, state))
            if light_id == "5" and self.fail_next_l5:
                self.fail_next_l5 = False
                return False
            return True

    hue = SwitchFailHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=_FakeEngine())
    _patch_setting(monkeypatch, {
        "Ahri": {"r": 255, "g": 105, "b": 180},
        "Zed": {"r": 20, "g": 20, "b": 30},
    })
    await svc.apply("Ahri")
    hue.calls.clear()
    hue.fail_next_l5 = True

    await svc.apply("Zed")
    assert svc.current_champion == "Ahri"
    await svc.apply("Zed")

    assert [lid for lid, _ in hue.calls].count("2") == 1
    assert [lid for lid, _ in hue.calls].count("5") == 2
    assert svc.current_champion == "Zed"


@pytest.mark.asyncio
async def test_same_champion_schedule_change_writes_once_then_deduplicates(monkeypatch):
    engine = _FakeEngine(period="day")
    hue = _FakeHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Lux": {"r": 255, "g": 220, "b": 90}})

    await svc.apply("Lux")
    hue.calls.clear()
    engine._period = "late_night"
    await svc.apply("Lux")
    # L2's period cap changes; L5 remains at its luma-compensated floor.
    assert [lid for lid, _ in hue.calls] == ["2"]
    hue.calls.clear()
    await svc.apply("Lux")
    assert hue.calls == []


@pytest.mark.asyncio
async def test_manual_release_makes_only_newly_eligible_lamp_retry(monkeypatch):
    engine = _FakeEngine()
    hue = _FakeHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})
    await svc.apply("Ahri")
    engine.manual_light_overrides = {"5"}
    await svc.apply("Ahri")
    hue.calls.clear()

    engine.manual_light_overrides.clear()
    await svc.apply("Ahri")

    assert [lid for lid, _ in hue.calls] == ["5"]


@pytest.mark.asyncio
async def test_rejected_missing_champion_does_not_release_accepted_does(monkeypatch):
    engine = _FakeEngine()
    hue = _FakeHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})
    await svc.apply("Ahri")

    missing = _report(champion=None)
    await svc.on_activity_report(
        missing, {"semantic_disposition": "rejected"},
    )
    assert svc.active_lights() == {"2", "5"}
    await svc.on_activity_report(
        missing,
        {
            "semantic_disposition": "accepted",
            "observed_source": "process:latitude",
        },
    )
    assert svc.active_lights() == {"2", "5"}
    await svc.on_activity_report(
        missing,
        {
            "semantic_disposition": "accepted",
            "observed_source": "process:desktop",
        },
    )
    assert svc.active_lights() == set()


@pytest.mark.asyncio
async def test_failed_reclaim_keeps_champion_ownership_retryable(monkeypatch):
    engine = _FakeEngine()
    hue = _FakeHue()
    svc = LoLChampionService(hue_service=hue, automation_engine=engine)
    _patch_setting(monkeypatch, {"Ahri": {"r": 255, "g": 105, "b": 180}})
    await svc.apply("Ahri")
    engine.reclaim_result = LightApplyResult(successful={"2"}, failed={"5"})

    assert await svc.clear() is False
    assert svc.active_lights() == {"5"}
    assert set(svc.owned_light_targets()) == {"5"}
    engine.reclaim_result = LightApplyResult(successful={"5"})
    assert await svc.clear() is True
    assert svc.active_lights() == set()


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
