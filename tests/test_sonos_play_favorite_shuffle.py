"""
Tests for SonosService.play_favorite's always-shuffle-on-play behavior.

User-visible promise: re-selecting a playlist OR letting the mode auto-play
pick the same favorite twice should NOT replay the same track ordering.
Guests cycling through vibe tiles should not hear the same first songs
repeat across the evening.

These tests pin the wire shape — ``play_mode`` is set to ``"SHUFFLE"``
before ``play_from_queue`` is called, and the start index is randomized
when the queue has more than one track.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.sonos_service import SonosService


# ---------------------------------------------------------------------------
# _shuffle_and_play helper — the seam used by both branches of play_favorite
# ---------------------------------------------------------------------------

class TestShuffleAndPlayHelper:

    def test_sets_play_mode_to_shuffle(self):
        service = SonosService.__new__(SonosService)  # bypass __init__
        device = MagicMock()
        device.queue_size = 50

        service._shuffle_and_play(device)

        # play_mode is set as an attribute via SoCo's setter — verify the value.
        assert device.play_mode == "SHUFFLE"

    def test_picks_random_start_when_queue_has_many_tracks(self):
        service = SonosService.__new__(SonosService)
        device = MagicMock()
        device.queue_size = 100

        with patch("backend.services.sonos_service.random.randint", return_value=42) as mock_rand:
            service._shuffle_and_play(device)

        mock_rand.assert_called_once_with(0, 99)
        device.play_from_queue.assert_called_once_with(42)

    def test_starts_at_zero_when_queue_size_is_one(self):
        """Single-track favorites can't be randomized — start at 0, no randint call."""
        service = SonosService.__new__(SonosService)
        device = MagicMock()
        device.queue_size = 1

        with patch("backend.services.sonos_service.random.randint") as mock_rand:
            service._shuffle_and_play(device)

        mock_rand.assert_not_called()
        device.play_from_queue.assert_called_once_with(0)

    def test_starts_at_zero_when_queue_size_is_zero(self):
        """Defensive — if queue_size somehow reads as 0, don't pass a
        negative index to play_from_queue."""
        service = SonosService.__new__(SonosService)
        device = MagicMock()
        device.queue_size = 0

        service._shuffle_and_play(device)

        device.play_from_queue.assert_called_once_with(0)

    def test_queue_size_unreadable_falls_back_to_zero(self):
        """If queue_size attribute access raises, we fall back to 0 (no randint, start=0)."""
        service = SonosService.__new__(SonosService)
        device = MagicMock()
        # Make queue_size raise when read by configuring it as a property that raises.
        type(device).queue_size = property(lambda self: (_ for _ in ()).throw(RuntimeError("upnp error")))

        # Should not raise.
        service._shuffle_and_play(device)
        device.play_from_queue.assert_called_once_with(0)

    def test_play_mode_set_before_play_from_queue(self):
        """Ordering matters — Sonos can interpret play_from_queue differently
        depending on the active play_mode. Set SHUFFLE first."""
        events: list[str] = []

        class _OrderTrackingDevice:
            queue_size = 10

            @property
            def play_mode(self):
                return self._mode

            @play_mode.setter
            def play_mode(self, value):
                self._mode = value
                events.append(f"play_mode={value}")

            def play_from_queue(self, index):
                events.append(f"play_from_queue({index})")

        service = SonosService.__new__(SonosService)
        device = _OrderTrackingDevice()

        service._shuffle_and_play(device)

        assert events == ["play_mode=SHUFFLE", events[1]]
        assert events[1].startswith("play_from_queue(")


# ---------------------------------------------------------------------------
# play_favorite integration — playlist branch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_play_favorite_playlist_branch_uses_shuffle_helper():
    """Playing a Sonos playlist by title routes through _shuffle_and_play
    instead of calling play_from_queue(0) directly."""
    service = SonosService.__new__(SonosService)
    service._connected = True
    service._device = MagicMock()
    service._safe_call = _make_passthrough_safe_call()

    # Mock the playlist cache to return one matching playlist.
    fake_pl = MagicMock()
    fake_pl.title = "Coffee Shop Jazz"

    async def fake_get_cached():
        return [fake_pl]

    service._get_sonos_playlists_cached = fake_get_cached

    spy = MagicMock()
    service._shuffle_and_play = spy

    result = await service.play_favorite("coffee shop jazz")

    assert result is True
    spy.assert_called_once_with(service._device)
    # Verify clear_queue and add_to_queue were called before shuffle
    assert service._device.clear_queue.called
    service._device.add_to_queue.assert_called_with(fake_pl)


# ---------------------------------------------------------------------------
# play_favorite integration — cloud favorite branch (Path A)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_play_favorite_cloud_favorite_branch_uses_shuffle_helper():
    service = SonosService.__new__(SonosService)
    service._connected = True
    service._device = MagicMock()
    service._safe_call = _make_passthrough_safe_call()

    # Empty playlists cache → falls through to cloud favorites.
    async def empty_playlists():
        return []

    service._get_sonos_playlists_cached = empty_playlists

    # Cloud favorite with populated resources (Path A).
    fav_ref = MagicMock()
    fav_ref.resources = [MagicMock()]  # non-empty → Path A
    fav_obj = MagicMock()
    fav_obj.title = "Hype Mix"
    fav_obj.reference = fav_ref

    service._favorites_objects_cache = [fav_obj]

    async def populate_cloud_cache():
        return []  # second call inside the function — unused

    service._get_cloud_favorites_cached = populate_cloud_cache

    spy = MagicMock()
    service._shuffle_and_play = spy

    result = await service.play_favorite("hype mix")

    assert result is True
    spy.assert_called_once_with(service._device)
    service._device.add_to_queue.assert_called_with(fav_ref)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_passthrough_safe_call():
    """Return an async function that calls its arg with remaining args
    directly — bypasses circuit breakers + thread offload for tests."""
    async def safe_call(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    return safe_call
