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


# ---------------------------------------------------------------------------
# Sleeping-mode veto (overnight power-save filter)
#
# Scenario: 2026-04-27 morning showed 8 presence:shortcut away events
# between 04:38 and 09:06 while Anthony was in sleeping mode. The shortcut
# path passes skip_override_guard=True (bypassing manual_override veto), the
# camera is paused during sleeping (camera veto can't fire), and sleeping
# isn't in ACTIVITY_VETO_MODES — so every iOS power-save WiFi blip became
# a fade sequence + arrival ceremony. Sleeping veto closes the gap.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleeping_mode_vetoes_shortcut_departure():
    """Shortcut /departed during sleeping mode → no fade. The actual symptom."""
    service = _make_service(
        current_mode="sleeping", manual_override=True, override_mode="sleeping",
    )

    await _run_and_drain(
        service, skip_override_guard=True, trigger="shortcut",
    )

    service._departure_sequence.assert_not_called()
    # Liveness reset so the next real miss is evaluated freshly.
    assert service._consecutive_failures == 0


@pytest.mark.asyncio
async def test_sleeping_mode_vetoes_arp_departure():
    """ARP timeout during sleeping mode also vetoes — phone power-save during sleep."""
    service = _make_service(
        current_mode="sleeping", manual_override=True, override_mode="sleeping",
    )

    await _run_and_drain(service, trigger="arp_timeout")

    service._departure_sequence.assert_not_called()


@pytest.mark.asyncio
async def test_sleeping_veto_runs_when_camera_paused():
    """Camera service exists but produces no fresh detection (paused in sleeping).
    Sleeping veto must fire as a backstop — the camera veto can't help."""
    service = _make_service(current_mode="sleeping")
    cam = MagicMock()
    cam.enabled = True
    cam.last_detection = "absent"
    cam.last_detection_at = None  # paused → no recent commit
    cam.zone = None
    service.set_camera_service(cam)

    await _run_and_drain(
        service, skip_override_guard=True, trigger="shortcut",
    )

    service._departure_sequence.assert_not_called()


@pytest.mark.asyncio
async def test_non_sleeping_modes_unaffected_by_sleeping_veto():
    """idle without override still proceeds to fade — sleeping veto is mode-specific."""
    service = _make_service(current_mode="idle")

    await _run_and_drain(
        service, skip_override_guard=True, trigger="shortcut",
    )

    service._departure_sequence.assert_awaited_once()


# ---------------------------------------------------------------------------
# Sleeping-mode arrival-ceremony veto
#
# When an arrival fires while the user is still in sleeping override, the
# ceremony (light wave to bri=200 + TTS greeting) should NOT run. After 5am
# `_classify_time` returns "morning" → ARRIVAL_LIGHT_STATES["morning"] =
# bri=200, so any arrival after 5am while sleeping was bright + loud.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arrival_during_sleeping_skips_ceremony(monkeypatch):
    """Arrival while mode=sleeping → no light wave, no TTS, state goes home."""
    service = _make_service(
        current_mode="sleeping", manual_override=True, override_mode="sleeping",
    )
    # Long absence to make sure the flap-threshold gate would not preempt.
    duration = timedelta(minutes=40)

    # Spy: capture whether the ceremony's light writes / TTS were invoked.
    service._broadcast_state = AsyncMock()

    await service._arrival_sequence(duration, force_ceremony=True)

    # No light wave (would have called set_light per ARRIVAL_WAVE_ORDER)
    assert service._hue.set_light.await_count == 0
    # No TTS
    assert service._tts.speak.await_count == 0
    # Presence state still updated to home
    assert service._state == "home"
    service._broadcast_state.assert_awaited()


@pytest.mark.asyncio
async def test_arrival_outside_sleeping_runs_ceremony():
    """Arrival when mode is idle (post-sleeping) — sleeping veto must NOT block.
    Anthony's morning routine: he flips out of sleeping, walks downstairs, the
    next arrival should still get the welcome ceremony."""
    service = _make_service(current_mode="idle")
    service._broadcast_state = AsyncMock()
    duration = timedelta(minutes=40)  # long enough to clear flap gate

    await service._arrival_sequence(duration, force_ceremony=True)

    # Light wave fired (4 lights in ARRIVAL_WAVE_ORDER)
    assert service._hue.set_light.await_count >= 1


@pytest.mark.asyncio
async def test_sleeping_arrival_veto_runs_before_flap_gate(monkeypatch):
    """A 1-min arrival in sleeping mode short-circuits BEFORE the
    flap-threshold gate so we don't re-apply mode lights either —
    sleeping wants its own dim/off state preserved."""
    service = _make_service(current_mode="sleeping")
    service._broadcast_state = AsyncMock()
    duration = timedelta(seconds=30)  # under FLAP_THRESHOLD_MINUTES_SHORTCUT

    # Spy on _apply_mode/_apply_time_based — the flap gate would normally
    # call one of these to "restore lights", but sleeping wants no
    # disturbance.
    service._automation._apply_mode = AsyncMock()
    service._automation._apply_time_based = AsyncMock()

    await service._arrival_sequence(duration, force_ceremony=True)

    service._automation._apply_mode.assert_not_called()
    service._automation._apply_time_based.assert_not_called()
    assert service._state == "home"
