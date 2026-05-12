"""
Tests for ModeVolumeService — the actuator that drives Sonos volume curves
on mode-change callbacks.

Pure-policy logic lives in mode_volume_policy and is covered separately.
These tests pin the service's I/O orchestration: it reads current volume
+ transport state, calls policy, kicks ramp_volume, defers on TTS, and
skips on STOPPED transport.
"""
from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.mode_volume_service import ModeVolumeService


def _make_sonos(*, volume: int = 20, state: str = "PLAYING", connected: bool = True):
    sonos = MagicMock()
    sonos.connected = connected
    sonos.get_status = AsyncMock(return_value={"volume": volume, "state": state})
    sonos.ramp_volume = AsyncMock(return_value=True)
    sonos.set_volume = AsyncMock(return_value=True)
    return sonos


def _make_automation(
    *, time_period: str = "day", dnd: bool = False,
):
    automation = MagicMock()
    automation._get_time_period = MagicMock(return_value=time_period)
    automation.is_dnd_active = MagicMock(return_value=dnd)
    return automation


def _make_tts(*, speaking: bool = False) -> Optional[MagicMock]:
    tts = MagicMock()
    tts.is_speaking = speaking
    return tts


async def _settle() -> None:
    """Yield to the loop so background ramp_volume tasks can run."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mode_change_ramps_to_default_target() -> None:
    """Gaming default day=25; from current=20 should ramp."""
    sonos = _make_sonos(volume=20, state="PLAYING")
    automation = _make_automation(time_period="day")
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("gaming")
        await _settle()

    sonos.ramp_volume.assert_called_once()
    kwargs = sonos.ramp_volume.call_args.kwargs
    args = sonos.ramp_volume.call_args.args
    target = args[0] if args else kwargs.get("target")
    assert target == 25


@pytest.mark.asyncio
async def test_persisted_config_overrides_default() -> None:
    sonos = _make_sonos(volume=10, state="PLAYING")
    automation = _make_automation(time_period="day")
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())
    custom = {"gaming": {"day": 40, "evening": 35, "night": 30, "fade_duration_s": 4}}

    with patch(
        "backend.services.mode_volume_service.load_setting",
        AsyncMock(return_value=custom),
    ):
        await service.on_mode_change("gaming")
        await _settle()

    sonos.ramp_volume.assert_called_once()
    assert sonos.ramp_volume.call_args.args[0] == 40


# ---------------------------------------------------------------------------
# Skip paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dnd_skips_ramp() -> None:
    sonos = _make_sonos(volume=20, state="PLAYING")
    automation = _make_automation(dnd=True)
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("gaming")
        await _settle()

    sonos.ramp_volume.assert_not_called()


@pytest.mark.asyncio
async def test_idle_has_no_curve_skips() -> None:
    sonos = _make_sonos(volume=20, state="PLAYING")
    automation = _make_automation()
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("idle")
        await _settle()

    sonos.ramp_volume.assert_not_called()


@pytest.mark.asyncio
async def test_already_at_target_skips() -> None:
    """Working day target is 12; if Sonos is already at 12, skip."""
    sonos = _make_sonos(volume=12, state="PLAYING")
    automation = _make_automation(time_period="day")
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("working")
        await _settle()

    sonos.ramp_volume.assert_not_called()


@pytest.mark.asyncio
async def test_stopped_transport_skips_except_sleeping() -> None:
    sonos = _make_sonos(volume=22, state="STOPPED")
    automation = _make_automation()
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("gaming")
        await _settle()

    sonos.ramp_volume.assert_not_called()


@pytest.mark.asyncio
async def test_stopped_transport_still_silences_for_sleeping() -> None:
    """Sleeping is the defensive case — always fade to 0 even if STOPPED."""
    sonos = _make_sonos(volume=15, state="STOPPED")
    automation = _make_automation()
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("sleeping")
        await _settle()

    sonos.ramp_volume.assert_called_once()
    assert sonos.ramp_volume.call_args.args[0] == 0


@pytest.mark.asyncio
async def test_sonos_disconnected_skips() -> None:
    sonos = _make_sonos(connected=False)
    automation = _make_automation()
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        await service.on_mode_change("gaming")
        await _settle()

    sonos.ramp_volume.assert_not_called()


# ---------------------------------------------------------------------------
# TTS deferral
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_active_defers_ramp() -> None:
    """When TTS is mid-speak the service sleeps once before applying."""
    sonos = _make_sonos(volume=20, state="PLAYING")
    automation = _make_automation()
    tts = _make_tts(speaking=True)
    service = ModeVolumeService(sonos, automation, tts_service=tts)

    sleep_calls = []
    real_sleep = asyncio.sleep

    async def tracking_sleep(seconds, *args, **kwargs):
        sleep_calls.append(seconds)
        await real_sleep(0)  # immediate yield, no actual wait

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)), \
         patch("backend.services.mode_volume_service.asyncio.sleep", tracking_sleep):
        await service.on_mode_change("gaming")
        await _settle()

    # Should have deferred once (5s sleep).
    assert 5.0 in sleep_calls
    # Then proceeded to ramp.
    sonos.ramp_volume.assert_called_once()


# ---------------------------------------------------------------------------
# merged_config helper
# ---------------------------------------------------------------------------

def test_merged_config_returns_defaults_when_none() -> None:
    merged = ModeVolumeService.merged_config(None)
    assert "gaming" in merged
    assert merged["gaming"]["day"] == 25


def test_merged_config_overrides_per_mode() -> None:
    persisted = {"gaming": {"day": 50}}
    merged = ModeVolumeService.merged_config(persisted)
    assert merged["gaming"]["day"] == 50
    # Other keys preserved from defaults.
    assert merged["gaming"]["night"] == 18
    # Other modes untouched.
    assert merged["working"]["day"] == 12


def test_merged_config_adds_unknown_mode() -> None:
    persisted = {"party": {"day": 40, "evening": 38, "night": 34, "fade_duration_s": 3}}
    merged = ModeVolumeService.merged_config(persisted)
    assert merged["party"]["day"] == 40


# ---------------------------------------------------------------------------
# Exception safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_swallows_exceptions() -> None:
    """The callback must never raise — would break the engine's chain."""
    sonos = _make_sonos(volume=20, state="PLAYING")
    automation = _make_automation()
    # Force an unexpected failure inside _apply by making get_status raise.
    sonos.get_status = AsyncMock(side_effect=RuntimeError("transport gone"))
    service = ModeVolumeService(sonos, automation, tts_service=_make_tts())

    with patch("backend.services.mode_volume_service.load_setting", AsyncMock(return_value=None)):
        # Should NOT raise.
        await service.on_mode_change("gaming")
