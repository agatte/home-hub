# Regression coverage for neutral-white daytime Gaming.

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.automation_constants import SCREEN_SYNC_FRESH_SECONDS
from backend.services.light_state_calculator import (
    apply_gaming_day_surround_brightness,
    resolve_activity_state,
)
from backend.services.screen_sync import ScreenSyncService


class _FakeHue:
    connected = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> bool:
        self.calls.append((light_id, state.copy()))
        return True

    def last_for(self, light_id: str) -> dict:
        for candidate, state in reversed(self.calls):
            if candidate == light_id:
                return state
        raise KeyError(light_id)

class _FakeEventLogger:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log_light_adjustment(self, **kwargs) -> None:
        self.calls.append(kwargs)


def test_gaming_day_is_neutral_ct_without_changing_base_brightness():
    state = resolve_activity_state("gaming", "day")

    assert {lid: state[lid]["bri"] for lid in ("1", "2", "3", "4", "5")} == {
        "1": 130,
        "2": 240,
        "3": 30,
        "4": 30,
        "5": 90,
    }
    for light in state.values():
        assert light["ct"] == 286
        assert "hue" not in light
        assert "sat" not in light


def test_cloudy_day_surround_lifts_brightness_without_leaving_ct_space():
    base = resolve_activity_state("gaming", "day")
    state = apply_gaming_day_surround_brightness(
        base,
        "gaming",
        "day",
        "clouds",
    )

    assert state["1"]["bri"] == 155
    assert state["3"]["bri"] == 50
    assert state["4"]["bri"] == 50
    assert state["2"]["bri"] == 240
    assert state["5"]["bri"] == 90
    for light in state.values():
        assert light["ct"] == 286
        assert "hue" not in light
        assert "sat" not in light


@pytest.mark.asyncio
async def test_generic_screen_sync_day_reasserts_ct_and_tracks_ownership():
    hue = _FakeHue()
    event_logger = _FakeEventLogger()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    sync.set_event_logger(event_logger)

    await sync.apply_color(
        "2", 255, 0, 0, mode="gaming", source="desktop", period="day",
    )
    await sync.apply_color(
        "5", 0, 0, 255, mode="gaming", source="desktop", period="day",
    )

    l2 = hue.last_for("2")
    l5 = hue.last_for("5")
    assert l2["ct"] == 286 and l2["bri"] == 240
    assert l5["ct"] == 286 and l5["bri"] == 75
    assert "hue" not in l2 and "sat" not in l2
    assert "hue" not in l5 and "sat" not in l5
    assert sync.fresh_owned_light_ids() == {"2", "5"}
    assert sync.authoritative_state("2") == {"on": True, "ct": 286, "bri": 240}
    assert len(event_logger.calls) == 2
    assert event_logger.calls[0]["ct_after"] == 286
    assert event_logger.calls[0]["hue_after"] is None
    assert event_logger.calls[0]["sat_after"] is None


@pytest.mark.asyncio
async def test_generic_screen_sync_evening_remains_hsb():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    await sync.apply_color(
        "2", 255, 255, 255, mode="gaming", source="desktop", period="evening",
    )
    await sync.apply_color(
        "5", 255, 255, 255, mode="gaming", source="desktop", period="evening",
    )

    l2 = hue.last_for("2")
    l5 = hue.last_for("5")
    assert l2["hue"] == 46920 and l2["sat"] == 190 and l2["bri"] == 150
    assert l5["hue"] == 48000 and l5["sat"] == 170 and l5["bri"] == 75
    assert "ct" not in l2
    assert "ct" not in l5


@pytest.mark.asyncio
async def test_newer_day_frame_does_not_revive_stale_other_light():
    hue = _FakeHue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    await sync.apply_color(
        "5", 0, 0, 0, mode="gaming", source="desktop", period="day",
    )
    sync._last_color_at_by_light["5"] = datetime.now(timezone.utc) - timedelta(
        seconds=SCREEN_SYNC_FRESH_SECONDS + 1,
    )

    await sync.apply_color(
        "2", 0, 0, 0, mode="gaming", source="desktop", period="day",
    )

    assert sync.fresh_owned_light_ids() == {"2"}
    assert sync.fresh_authoritative_state("5") is None
    assert sync.fresh_authoritative_state("2") is not None
