from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from backend.services.automation_constants import TZ
from backend.services.decision_clock import SystemDecisionClock
from backend.services.engine_state import EngineState
from backend.services.light_override_manager import LightOverrideManager
from backend.services.presence_fusion import PresenceFusion, PresenceReading
from backend.services.transit_lighting_service import TransitLightingService


class FrozenClock:
    def __init__(self, now: datetime, mono_ns: int = 0) -> None:
        if now.tzinfo is None:
            raise ValueError("FrozenClock requires aware wall time")
        self.now = now.astimezone(timezone.utc)
        self.mono_ns = mono_ns

    def utc_now(self) -> datetime:
        return self.now

    def monotonic_ns(self) -> int:
        return self.mono_ns

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class SteppingClock(FrozenClock):
    def __init__(self, now: datetime, step: timedelta) -> None:
        super().__init__(now)
        self.step = step
        self.calls = 0

    def utc_now(self) -> datetime:
        current = self.now
        self.now += self.step
        self.calls += 1
        return current


class _TransitAutomation:
    current_mode = "working"

    def __init__(self) -> None:
        self.transit_calls: list[dict] = []

    def _read_fresh_camera_lux(self):
        return None, None

    async def apply_transit_override(self, states, **kwargs) -> None:
        self.transit_calls.append({"states": states, **kwargs})

    async def clear_transit_override(self, **_kwargs) -> None:
        return None


class _AbsentCamera:
    def get_status(self) -> dict:
        return {
            "enabled": True,
            "last_detection": "absent",
            "detection_source": None,
            "confidence": 0.0,
            "zone": None,
            "posture": None,
        }


class _Hue:
    connected = True

    async def set_light(self, _light_id: str, _state: dict) -> bool:
        return True


def _manager(state: EngineState, clock: FrozenClock) -> LightOverrideManager:
    async def _reapply(_mode: str) -> None:
        return None

    return LightOverrideManager(
        state=state,
        hue_getter=lambda: None,
        event_logger_getter=lambda: None,
        current_mode_getter=lambda: "working",
        reapply_mode=_reapply,
        clock=clock,
    )



def test_system_decision_clock_returns_aware_utc_and_monotonic() -> None:
    local = datetime(2026, 9, 23, 12, 0, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    clock = SystemDecisionClock(
        utc_now_fn=lambda: local,
        monotonic_ns_fn=lambda: 123,
    )

    assert clock.utc_now() == local.astimezone(timezone.utc)
    assert clock.utc_now().tzinfo == timezone.utc
    assert clock.monotonic_ns() == 123


def test_system_decision_clock_rejects_naive_wall_time() -> None:
    clock = SystemDecisionClock(utc_now_fn=lambda: datetime(2026, 9, 23, 12, 0))

    with pytest.raises(ValueError, match="aware"):
        clock.utc_now()


def test_presence_fusion_preserves_exact_freshness_boundary() -> None:
    now = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
    clock = FrozenClock(now)
    fusion = PresenceFusion(clock=clock)
    fusion.on_observation(
        PresenceReading(
            source="desktop",
            captured_at=now - timedelta(seconds=8),
            face_present=True,
            face_confidence=0.99,
            detection_source="face",
            zone="desk",
        )
    )

    assert fusion.is_strongly_present_any(max_age_s=8) is True
    clock.advance(timedelta(microseconds=1))
    assert fusion.is_strongly_present_any(max_age_s=8) is False


def test_transit_navigation_uses_injected_local_wall_hour() -> None:
    local = datetime(2026, 9, 23, 23, 30, tzinfo=TZ)
    clock = FrozenClock(local)
    service = TransitLightingService(
        _TransitAutomation(),
        camera_service=None,
        clock=clock,
    )

    states = service._navigation_states("relax")

    assert states["1"]["bri"] == 60
    assert states["3"]["bri"] == 40
    assert states["4"]["bri"] == 40



def test_presence_fusion_on_observation_keeps_separate_wall_reads() -> None:
    now = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
    clock = SteppingClock(now, timedelta(microseconds=1))
    fusion = PresenceFusion(clock=clock)
    reading = PresenceReading(
        source="desktop",
        captured_at=now,
        face_present=True,
        face_confidence=0.99,
        detection_source="face",
        zone="desk",
    )

    fusion.on_observation(reading)

    assert clock.calls == 3


@pytest.mark.asyncio
async def test_transit_activation_keeps_separate_tick_target_and_stamp_reads() -> None:
    local = datetime(2026, 9, 23, 12, 0, tzinfo=TZ)
    clock = SteppingClock(local, timedelta(microseconds=1))
    automation = _TransitAutomation()
    service = TransitLightingService(
        automation,
        camera_service=_AbsentCamera(),
        clock=clock,
    )
    service._presence_armed = True

    await service._check()
    absent_since = service._camera_absent_since
    assert absent_since == local

    clock.advance(timedelta(seconds=10))
    calls_before = clock.calls
    await service._check()

    assert service.active is True
    assert len(automation.transit_calls) == 1
    assert clock.calls - calls_before == 3
    assert service._transit_start is not None
    assert service._transit_start > absent_since + timedelta(seconds=10)


@pytest.mark.asyncio
async def test_manager_deadline_uses_injected_wall_time_exactly() -> None:
    local = datetime(2026, 9, 23, 12, 0, tzinfo=TZ)
    clock = FrozenClock(local)
    state = EngineState()

    async def _reapply(_mode: str) -> None:
        return None

    manager = LightOverrideManager(
        state=state,
        hue_getter=lambda: _Hue(),
        event_logger_getter=lambda: None,
        current_mode_getter=lambda: "working",
        reapply_mode=_reapply,
        clock=clock,
    )

    await manager.apply_transit_override(
        {"1": {"on": True, "bri": 60}},
        duration_seconds=10,
    )

    assert state.transit_light_overrides["1"] == local + timedelta(seconds=10)

def test_transit_prune_keeps_existing_less_equal_deadline_semantics() -> None:
    local = datetime(2026, 9, 23, 12, 0, tzinfo=TZ)
    clock = FrozenClock(local)
    state = EngineState()
    state.transit_light_overrides["1"] = local
    state.transit_light_targets["1"] = {"on": True, "bri": 60}
    state.last_applied_per_light["1"] = {"on": True, "bri": 60}
    manager = _manager(state, clock)

    manager.prune_expired_transit()

    assert "1" not in state.transit_light_overrides
    assert "1" not in state.transit_light_targets
    assert "1" not in state.last_applied_per_light



def test_transit_uses_passive_camera_threshold_import() -> None:
    repo = Path(__file__).resolve().parents[1]
    transit_source = (repo / "backend/services/transit_lighting_service.py").read_text(
        encoding="utf-8"
    )
    camera_constants = (repo / "backend/services/camera_constants.py").read_text(
        encoding="utf-8"
    )

    assert "from backend.services.camera_constants import FACE_TRUST_THRESHOLD" in transit_source
    assert "from backend.services.camera_service import FACE_TRUST_THRESHOLD" not in transit_source
    assert "from backend." not in camera_constants

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import backend.services.transit_lighting_service; "
            "assert 'backend.services.camera_service' not in sys.modules; "
            "assert 'backend.config' not in sys.modules",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
