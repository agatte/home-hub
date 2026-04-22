"""
Tests for presence_service._on_departure vetoes.

The fade-to-off departure sequence used to fire any time the phone's
WiFi connection hiccupped (iOS power-save, ARP miss), dimming every
light in the apartment to bri=1 then off — even while the user was
sitting at the desk working. Two vetoes now guard against that:

1. Camera veto — webcam saw a face/pose within CAMERA_VETO_STALE_SECONDS
2. Activity-mode veto — current mode is in ACTIVITY_VETO_MODES

Each test constructs a minimally-stubbed PresenceService and checks
whether ``_departure_sequence`` was scheduled.
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.presence_service import (
    ACTIVITY_VETO_MODES,
    CAMERA_VETO_STALE_SECONDS,
    TZ,
    PresenceService,
)


async def _run_and_drain(service: PresenceService, **kwargs) -> None:
    """Call _on_departure and give the event loop a tick so any scheduled
    _departure_sequence task actually runs before the assertion.
    """
    await service._on_departure(**kwargs)
    # _on_departure dispatches _departure_sequence via create_task; yield
    # so the task scheduler picks it up and the AsyncMock registers the
    # await.
    for _ in range(3):
        await asyncio.sleep(0)


def _make_service(
    *,
    current_mode: str = "idle",
    manual_override: bool = False,
    override_mode: str = "",
) -> PresenceService:
    """Build a PresenceService with just enough to exercise _on_departure."""
    automation = MagicMock()
    automation.manual_override = manual_override
    automation.override_mode = override_mode
    automation.current_mode = current_mode

    service = PresenceService(
        hue=AsyncMock(),
        hue_v2=AsyncMock(),
        sonos=AsyncMock(),
        tts=AsyncMock(),
        weather_service=AsyncMock(),
        automation_engine=automation,
        music_mapper=AsyncMock(),
        ws_manager=AsyncMock(),
    )
    # Real _departure_sequence reads hue state and spawns a long task —
    # swap in a plain AsyncMock so the test can assert "was it called".
    service._departure_sequence = AsyncMock()
    return service


def _attach_camera(
    service: PresenceService,
    *,
    detection: str,
    age_seconds: float,
    enabled: bool = True,
    zone: str | None = "desk",
) -> MagicMock:
    """Attach a stubbed camera service with the given detection state."""
    cam = MagicMock()
    cam.enabled = enabled
    cam.last_detection = detection
    cam.last_detection_at = datetime.now(tz=TZ) - timedelta(seconds=age_seconds)
    cam.zone = zone
    service.set_camera_service(cam)
    return cam


# ---------------------------------------------------------------------------
# Camera veto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_camera_present_recently_vetoes_fade():
    """Camera saw someone 10s ago — phone-off-WiFi is iOS power-save, skip fade."""
    service = _make_service()
    _attach_camera(service, detection="present", age_seconds=10)

    await _run_and_drain(service, trigger="arp_timeout")

    assert service._departure_sequence.await_count == 0
    assert service._consecutive_failures == 0


@pytest.mark.asyncio
async def test_camera_present_stale_does_not_veto():
    """Camera saw someone 90s ago — beyond the 60s window, veto must not apply."""
    service = _make_service()
    _attach_camera(
        service, detection="present", age_seconds=CAMERA_VETO_STALE_SECONDS + 30,
    )

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_camera_absent_does_not_veto():
    """Camera reports absent — no veto, fade should proceed."""
    service = _make_service()
    _attach_camera(service, detection="absent", age_seconds=5)

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_camera_disabled_does_not_veto():
    """Camera service exists but is disabled — fall through to activity check."""
    service = _make_service(current_mode="idle")
    _attach_camera(service, detection="present", age_seconds=5, enabled=False)

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_camera_service_does_not_crash():
    """PresenceService boots before camera — _on_departure must not NPE."""
    service = _make_service(current_mode="idle")
    # No set_camera_service call — _camera_service stays None.

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_camera_veto_applies_even_with_skip_override_guard():
    """Shortcut /departed bypasses manual_override but camera still vetoes."""
    service = _make_service()
    _attach_camera(service, detection="present", age_seconds=5)

    await _run_and_drain(
        service, skip_override_guard=True, trigger="shortcut",
    )

    service._departure_sequence.assert_not_called()


# ---------------------------------------------------------------------------
# Activity-mode veto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", sorted(ACTIVITY_VETO_MODES))
@pytest.mark.asyncio
async def test_activity_mode_vetoes_fade(mode: str):
    """working/gaming/watching/cooking/social — all strong presence evidence."""
    service = _make_service(current_mode=mode)

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_not_called()


@pytest.mark.asyncio
async def test_idle_mode_does_not_veto():
    """idle isn't in the activity set — no veto, fade proceeds."""
    service = _make_service(current_mode="idle")

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_relax_mode_does_not_activity_veto():
    """relax requires manual action — not a presence signal by itself."""
    service = _make_service(current_mode="relax")

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_awaited_once()


# ---------------------------------------------------------------------------
# Preserves existing manual_override guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_override_still_vetoes():
    """Pre-existing behavior: manual_override=True skips fade."""
    service = _make_service(
        current_mode="relax", manual_override=True, override_mode="relax",
    )

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_not_called()


@pytest.mark.asyncio
async def test_shortcut_bypasses_manual_override_but_not_vetoes():
    """skip_override_guard=True bypasses manual_override, but camera veto still applies."""
    service = _make_service(
        current_mode="relax", manual_override=True, override_mode="relax",
    )
    _attach_camera(service, detection="present", age_seconds=3)

    await _run_and_drain(
        service, skip_override_guard=True, trigger="shortcut",
    )

    service._departure_sequence.assert_not_called()
