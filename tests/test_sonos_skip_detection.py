"""Tests for off-dashboard skip detection in SonosService.poll_state_loop.

The bandit's nightly retrain already consumes ``event_type='skip'`` rows
(music_bandit.py:355-363), but pre-2026-05-25 only the dashboard WebSocket
``next``/``previous`` actions emitted them — physical buttons, Alexa, and
the Sonos app were silent. ``_maybe_emit_skip`` closes that gap by
inspecting track-change transitions in the polling loop.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.sonos_service import SonosService


class _Logger:
    def __init__(self):
        self.calls = []

    async def log_sonos_event(self, **kwargs):
        self.calls.append(kwargs)


def _make_service(*, current_mode="working"):
    s = SonosService()
    el = _Logger()
    automation = SimpleNamespace(current_mode=current_mode)
    s.attach_event_logger(el, automation)
    return s, el


@pytest.mark.asyncio
async def test_skip_emitted_when_track_changes_mid_song():
    s, el = _make_service(current_mode="working")
    prev = {
        "state": "PLAYING", "track": "Song A", "artist": "X",
        "position": "0:01:00", "duration": "0:04:00",
    }
    new = {
        "state": "PLAYING", "track": "Song B", "artist": "Y",
        "position": "0:00:01", "duration": "0:03:30",
    }
    await s._maybe_emit_skip(prev, new)
    assert len(el.calls) == 1
    call = el.calls[0]
    assert call["event_type"] == "skip"
    assert call["favorite_title"] == "Song A"
    assert call["mode_at_time"] == "working"
    assert call["triggered_by"] == "off_dashboard"


@pytest.mark.asyncio
async def test_no_skip_on_natural_track_end():
    """Track played past the 80% / within-10s natural-end threshold."""
    s, el = _make_service()
    # 3:55 of 4:00 — within 10s of duration
    prev = {
        "state": "PLAYING", "track": "Song A", "position": "0:03:55",
        "duration": "0:04:00",
    }
    new = {"state": "PLAYING", "track": "Song B", "position": "0:00:01", "duration": "0:03:00"}
    await s._maybe_emit_skip(prev, new)
    assert el.calls == []


@pytest.mark.asyncio
async def test_no_skip_when_title_unchanged():
    """Position advanced but title same — no transition, no skip."""
    s, el = _make_service()
    prev = {"state": "PLAYING", "track": "Song A", "position": "0:00:30", "duration": "0:04:00"}
    new = {"state": "PLAYING", "track": "Song A", "position": "0:00:32", "duration": "0:04:00"}
    await s._maybe_emit_skip(prev, new)
    assert el.calls == []


@pytest.mark.asyncio
async def test_no_skip_when_state_not_playing():
    """User paused mid-track; the next observation may differ but it's not a skip."""
    s, el = _make_service()
    prev = {"state": "PLAYING", "track": "Song A", "position": "0:00:30", "duration": "0:04:00"}
    new = {"state": "PAUSED_PLAYBACK", "track": "Song A", "position": "0:00:30", "duration": "0:04:00"}
    await s._maybe_emit_skip(prev, new)
    assert el.calls == []


@pytest.mark.asyncio
async def test_no_skip_when_duration_unparseable():
    """Streams without a parseable duration (NOT_IMPLEMENTED) — conservatively no emit."""
    s, el = _make_service()
    prev = {"state": "PLAYING", "track": "Song A", "position": "0:00:30", "duration": "NOT_IMPLEMENTED"}
    new = {"state": "PLAYING", "track": "Song B", "position": "0:00:01", "duration": "0:03:00"}
    await s._maybe_emit_skip(prev, new)
    assert el.calls == []


@pytest.mark.asyncio
async def test_no_skip_on_empty_title_transition():
    """Idle (empty title) → first track is not a skip."""
    s, el = _make_service()
    prev = {"state": "PLAYING", "track": "", "position": "0:00:00", "duration": "0:00:00"}
    new = {"state": "PLAYING", "track": "Song A", "position": "0:00:01", "duration": "0:04:00"}
    await s._maybe_emit_skip(prev, new)
    assert el.calls == []


@pytest.mark.asyncio
async def test_helper_no_ops_when_logger_not_attached():
    """Without attach_event_logger() having been called, the helper must
    early-return cleanly even on a skip-triggering payload — so direct
    callers in tests / future refactors don't AttributeError on the
    self._event_logger access. The production poll loop also guards this
    case at its call site, but the helper's self-guard is the documented
    contract."""
    s = SonosService()  # no attach_event_logger called
    assert s._event_logger is None
    prev = {"state": "PLAYING", "track": "A", "position": "0:00:30", "duration": "0:04:00"}
    new = {"state": "PLAYING", "track": "B", "position": "0:00:01", "duration": "0:03:00"}
    # Skip-triggering payload (mid-song title change, both PLAYING). Without
    # the self-guard at the top of _maybe_emit_skip, this would
    # AttributeError on self._event_logger.log_sonos_event.
    await s._maybe_emit_skip(prev, new)
    # No assertion target — the test passes iff the call returns without raising.


@pytest.mark.asyncio
async def test_near_end_track_boundary_surrenders_owned_queue() -> None:
    s, el = _make_service()
    ownership = SimpleNamespace(
        invalidate_manual=AsyncMock(return_value={}),
    )
    s.attach_audio_ownership(ownership)

    prev = {
        "state": "PLAYING",
        "track": "Song A",
        "position": "0:03:58",
        "duration": "0:04:00",
    }
    new = {
        "state": "PLAYING",
        "track": "Song B",
        "position": "0:00:00",
        "duration": "0:03:00",
    }

    await s._maybe_emit_skip(prev, new)

    # Near-end remains excluded from skip-learning, but ownership cannot
    # survive because Sonos cannot prove this was not a physical/app Next.
    assert el.calls == []
    ownership.invalidate_manual.assert_awaited_once_with(
        frozenset({"queue_source", "transport", "interruption"}),
        source="sonos_poll",
        reason="off_dashboard_track_boundary",
    )


@pytest.mark.asyncio
async def test_unparseable_track_boundary_still_surrenders_owned_queue() -> None:
    s, el = _make_service()
    ownership = SimpleNamespace(
        invalidate_manual=AsyncMock(return_value={}),
    )
    s.attach_audio_ownership(ownership)
    prev = {
        "state": "PLAYING",
        "track": "Song A",
        "position": "NOT_IMPLEMENTED",
        "duration": "NOT_IMPLEMENTED",
    }
    new = {
        "state": "PLAYING",
        "track": "Song B",
        "position": "NOT_IMPLEMENTED",
        "duration": "NOT_IMPLEMENTED",
    }

    await s._maybe_emit_skip(prev, new)

    assert el.calls == []
    ownership.invalidate_manual.assert_awaited_once_with(
        frozenset({"queue_source", "transport", "interruption"}),
        source="sonos_poll",
        reason="off_dashboard_track_boundary",
    )


@pytest.mark.asyncio
async def test_unchanged_title_does_not_surrender_owned_queue() -> None:
    s, _ = _make_service()
    ownership = SimpleNamespace(
        invalidate_manual=AsyncMock(return_value={}),
    )
    s.attach_audio_ownership(ownership)
    prev = {
        "state": "PLAYING",
        "track": "Song A",
        "position": "0:00:30",
        "duration": "0:04:00",
    }
    new = dict(prev, position="0:00:32")

    await s._maybe_emit_skip(prev, new)

    ownership.invalidate_manual.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_skip_logs_originating_favorite_before_lease_invalidation() -> None:
    s, el = _make_service(current_mode="social")
    lease = {
        "lease_id": "lease-skip",
        "owner": "music_mapper",
        "purpose": "mode_auto_play",
        "dimensions": ["queue_source", "transport"],
        "evidence": {"phase": "owned", "sonos": {"transport_state": "PLAYING"}},
        "metadata": {
            "mode": "social",
            "favorite_title": "2000s Hits Essentials",
            "weather_class": "clouds",
            "learning_eligible": True,
        },
    }
    ownership = SimpleNamespace(
        find_lease=AsyncMock(return_value=lease),
        invalidate_manual=AsyncMock(return_value={}),
    )
    s.attach_audio_ownership(ownership)
    prev = {
        "state": "PLAYING",
        "track": "Track Inside Container",
        "position": "0:00:12",
        "duration": "0:03:00",
    }
    new = {
        "state": "PLAYING",
        "track": "Next Track",
        "position": "0:00:01",
        "duration": "0:03:10",
    }

    await s._maybe_emit_skip(prev, new)

    assert len(el.calls) == 1
    call = el.calls[0]
    assert call["favorite_title"] == "2000s Hits Essentials"
    assert call["mode_at_time"] == "social"
    assert call["weather_class"] == "clouds"
    assert call["session_id"] == "lease-skip"
    assert call["ownership_lease_id"] == "lease-skip"
    ownership.find_lease.assert_awaited_once()
    ownership.invalidate_manual.assert_awaited_once()
