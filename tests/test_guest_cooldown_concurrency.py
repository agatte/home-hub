"""Race-condition pin for the guest endpoint cooldowns.

Two simultaneous requests against the same guest action must produce
exactly one acceptance + one 429. Without the asyncio.Lock around each
check-and-set, the cooldown timestamp is racy and both requests can
slip through.
"""
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import backend.api.routes.guest as guest


def _reset_cooldown_state() -> None:
    """Reset module-level cooldown timestamps between tests."""
    guest._last_guest_scene_at = 0.0
    guest._last_guest_vibe_at = 0.0
    guest._last_guest_effect_at = 0.0
    guest._last_guest_brightness_at = 0.0
    guest._last_guest_toast_at = 0.0


@pytest.mark.asyncio
async def test_concurrent_scene_requests_serialize_via_lock() -> None:
    """Two simultaneous /scene/aurora requests: only one succeeds."""
    _reset_cooldown_state()
    # Pre-burn the cooldown to None — both requests will see elapsed > cooldown
    # on entry, but the lock should ensure only the first claims it.
    guest._last_guest_scene_at = 0.0

    # Stub the request + downstream services. We only care about the
    # cooldown check; bail before any Hue/Sonos calls happen.
    request_a = _stub_request()
    request_b = _stub_request()

    # Patch SCENE_PRESETS / hue / app.state so the handler doesn't crash
    # past the cooldown gate. Inject an asyncio.sleep right after the gate
    # to ensure both requests arrive at the lock concurrently.
    async def slow_activate(*args, **kwargs):
        await asyncio.sleep(0.05)

    with patch.object(guest, "_activate_per_light", slow_activate), \
            patch.object(guest, "_activate_effect_if_needed", AsyncMock()), \
            patch.object(guest, "_log_scene_activation", AsyncMock()):
        # Run two requests truly concurrently.
        results = await asyncio.gather(
            guest.activate_guest_scene("aurora", request_a),
            guest.activate_guest_scene("aurora", request_b),
            return_exceptions=True,
        )

    successes = [r for r in results if isinstance(r, dict)]
    rate_limited = [
        r for r in results
        if isinstance(r, HTTPException) and r.status_code == 429
    ]

    # Without the lock, both can succeed. With the lock, exactly one wins
    # and the other gets 429.
    assert len(successes) == 1, f"expected 1 success, got {len(results)}: {results}"
    assert len(rate_limited) == 1, f"expected 1 429, got: {results}"


@pytest.mark.asyncio
async def test_concurrent_brightness_requests_serialize() -> None:
    """The brightness cooldown is the tightest (0.8s) — easiest to race."""
    _reset_cooldown_state()
    guest._last_guest_brightness_at = 0.0

    request_a = _stub_request()
    request_b = _stub_request()

    results = await asyncio.gather(
        guest.adjust_guest_brightness("up", request_a),
        guest.adjust_guest_brightness("up", request_b),
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, dict)]
    rate_limited = [
        r for r in results
        if isinstance(r, HTTPException) and r.status_code == 429
    ]

    assert len(successes) == 1
    assert len(rate_limited) == 1


def _stub_request():
    """Build a minimal mock Request that the guest handlers accept."""

    class _Hue:
        connected = True
        breaker_open = False  # _check_hue_available reads this

        async def get_all_lights(self):
            # Return two lights, both on, so adjust_guest_brightness has work.
            return [
                {"light_id": "1", "on": True, "bri": 100},
                {"light_id": "2", "on": True, "bri": 150},
            ]

        async def set_light(self, lid, state):
            return True

    class _Automation:
        current_mode = "social"
        _mode_brightness = {"social": 1.0}

        async def set_manual_override(self, *_a, **_kw):
            return None

        def mark_light_manual(self, *_a, **_kw):
            return None

    class _AppState:
        hue = _Hue()
        hue_v2 = AsyncMock()
        ws_manager = AsyncMock()
        automation = _Automation()

    class _App:
        state = _AppState()

    class _Client:
        host = "127.0.0.1"

    class _Request:
        app = _App()
        client = _Client()

    return _Request()
