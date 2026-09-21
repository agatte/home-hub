from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from backend.services.gameday_viewer_sync import (
    GameDayViewerSync,
    ViewerReleaseResult,
)


class FakeTime:
    def __init__(self, wall: float = 1_789_500_000.0) -> None:
        self.wall = wall
        self.mono = 100.0

    def clock(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


async def _trust_chrome_hulu(sync: GameDayViewerSync, fake: FakeTime, media: float) -> None:
    for offset in (0.0, 1.0, 2.0):
        if offset:
            fake.advance(1.0)
        await sync.record_sample(
            service="hulu",
            player="chromium",
            playback_status="Playing",
            media_timestamp=media + offset,
            observed_at=_dt(fake.wall),
        )


@pytest.mark.asyncio
async def test_chrome_hulu_requires_consecutive_normal_samples_before_authority():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.5

    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media, observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["authoritative"] is False

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 1, observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["authoritative"] is False

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 2, observed_at=_dt(fake.wall),
    )
    snap = sync.snapshot()
    assert snap["authoritative"] is True
    assert snap["lag_seconds"] == pytest.approx(30.5)


@pytest.mark.asyncio
async def test_paused_trusted_clock_holds_authority_and_defers_future_event():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await _trust_chrome_hulu(sync, fake, media)

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Paused",
        media_timestamp=media + 2, observed_at=_dt(fake.wall),
    )
    snap = sync.snapshot()
    assert snap["authoritative"] is True
    assert snap["playback_status"] == "Paused"

    decision = sync.release_decision(_dt(media + 10))
    assert decision.defer is True
    assert decision.reason == "await viewer clock"


@pytest.mark.asyncio
async def test_playing_clock_that_stops_advancing_loses_authority():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await _trust_chrome_hulu(sync, fake, media)
    assert sync.snapshot()["authoritative"] is True

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 2, observed_at=_dt(fake.wall),
    )
    snap = sync.snapshot()
    assert snap["reason"] == "stalled"
    assert snap["authoritative"] is False


@pytest.mark.asyncio
async def test_firefox_hulu_never_becomes_authoritative():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 24.0
    for offset in (0.0, 1.0, 2.0, 3.0):
        if offset:
            fake.advance(1)
        await sync.record_sample(
            service="hulu", player="firefox", playback_status="Playing",
            media_timestamp=media + offset, observed_at=_dt(fake.wall),
        )
    assert sync.snapshot()["authoritative"] is False
    assert sync.release_decision(_dt(media + 10)).defer is False


@pytest.mark.asyncio
async def test_forward_seek_skips_pending_event_crossed_by_jump_to_live():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 50.0
    await _trust_chrome_hulu(sync, fake, media)
    target = media + 15.0
    decision = sync.release_decision(_dt(target))
    assert decision.defer is True

    waiter = asyncio.create_task(
        sync.wait_until_visible(_dt(target), seek_generation=decision.seek_generation),
    )
    await asyncio.sleep(0)
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 25.0, observed_at=_dt(fake.wall),
    )

    assert await waiter == ViewerReleaseResult.SKIPPED_BY_SEEK
    assert sync.snapshot()["reason"] == "forward_seek"


@pytest.mark.asyncio
async def test_runtime_disable_releases_pending_wait_as_unavailable():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await _trust_chrome_hulu(sync, fake, media)
    decision = sync.release_decision(_dt(media + 10.0))
    waiter = asyncio.create_task(
        sync.wait_until_visible(_dt(media + 10.0), seek_generation=decision.seek_generation),
    )
    await asyncio.sleep(0)

    await sync.set_enabled(False)
    assert await waiter == ViewerReleaseResult.UNAVAILABLE
    assert sync.snapshot()["authoritative"] is False


@pytest.mark.asyncio
async def test_stale_sample_is_not_used_for_new_deferral():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await _trust_chrome_hulu(sync, fake, media)
    fake.advance(sync.SAMPLE_STALE_SECONDS + 0.5)

    snap = sync.snapshot()
    assert snap["authoritative"] is False
    assert sync.release_decision(_dt(media + 20)).defer is False


@pytest.mark.asyncio
async def test_viewer_state_tracks_media_clock_and_can_rewind():
    fake = FakeTime()
    ws = type("WS", (), {"broadcast": AsyncMock()})()
    sync = GameDayViewerSync(
        ws_manager=ws, clock=fake.clock, monotonic=fake.monotonic,
    )
    base = fake.wall - 40.0
    sync.queue_state({"clock": "12:00"}, _dt(base))
    sync.queue_state({"clock": "11:50"}, _dt(base + 10))
    sync.queue_state({"clock": "11:40"}, _dt(base + 20))
    await asyncio.sleep(0)

    await _trust_chrome_hulu(sync, fake, base + 15)
    assert sync.snapshot()["viewer_state"] == {"clock": "11:50"}

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 25, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 26, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 27, observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["viewer_state"] == {"clock": "11:40"}

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 8, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 9, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 10, observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["viewer_state"] == {"clock": "11:50"}


@pytest.mark.asyncio
async def test_stalled_playing_clock_falls_back_after_shared_grace_window():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await _trust_chrome_hulu(sync, fake, media)
    assert sync.snapshot()["authoritative"] is True

    frozen = media + 2.0
    for _ in range(int(sync.UNTRUSTED_GRACE_SECONDS) + 1):
        fake.advance(1)
        await sync.record_sample(
            service="hulu", player="chromium", playback_status="Playing",
            media_timestamp=frozen, observed_at=_dt(fake.wall),
        )

    snap = sync.snapshot()
    assert snap["authoritative"] is False
    assert snap["presentation_active"] is False
    assert sync.release_decision(_dt(frozen + 10)).defer is False


@pytest.mark.asyncio
async def test_new_event_discovered_inside_completed_forward_seek_is_dropped():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 50.0
    await _trust_chrome_hulu(sync, fake, media)

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 25.0, observed_at=_dt(fake.wall),
    )

    decision = sync.release_decision(_dt(media + 15.0))
    assert decision.defer is False
    assert decision.drop is True
    assert decision.reason == "skipped by forward seek"


@pytest.mark.asyncio
async def test_duplicate_state_anchor_keeps_first_viewer_snapshot():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    anchor = fake.wall - 30.0
    sync.queue_state({"clock": "12:00"}, _dt(anchor))
    sync.queue_state({"clock": "11:51"}, _dt(anchor))

    assert len(sync._state_history) == 1
    assert sync._state_history[0].payload == {"clock": "12:00"}


@pytest.mark.asyncio
async def test_initial_chrome_confidence_window_holds_presentation_timeline():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 30.0
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media, observed_at=_dt(fake.wall),
    )
    snap = sync.snapshot()
    assert snap["authoritative"] is False
    assert snap["presentation_active"] is True
    assert sync.release_decision(_dt(media + 10)).defer is True

@pytest.mark.asyncio
async def test_forward_seek_while_paused_is_recorded_and_drops_skipped_event():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 50.0
    await _trust_chrome_hulu(sync, fake, media)

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Paused",
        media_timestamp=media + 2.0, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Paused",
        media_timestamp=media + 25.0, observed_at=_dt(fake.wall),
    )

    snap = sync.snapshot()
    assert snap["reason"] == "forward_seek"
    assert snap["authoritative"] is True
    decision = sync.release_decision(_dt(media + 15.0))
    assert decision.drop is True
    assert decision.reason == "skipped by forward seek"


@pytest.mark.asyncio
async def test_earlier_forward_seek_range_survives_later_backward_seek():
    fake = FakeTime()
    sync = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    media = fake.wall - 50.0
    await _trust_chrome_hulu(sync, fake, media)

    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 25.0, observed_at=_dt(fake.wall),
    )
    fake.advance(1)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=media + 10.0, observed_at=_dt(fake.wall),
    )

    assert sync.snapshot()["last_seek_direction"] == "backward"
    decision = sync.release_decision(_dt(media + 15.0))
    assert decision.drop is True
    assert decision.reason == "skipped by forward seek"


@pytest.mark.asyncio
async def test_backward_seek_clears_published_viewer_frame_until_safe_state_reselected():
    fake = FakeTime()
    ws = type("WS", (), {"broadcast": AsyncMock()})()
    sync = GameDayViewerSync(ws_manager=ws, clock=fake.clock, monotonic=fake.monotonic)
    base = fake.wall - 50.0
    sync.queue_state({"clock": "12:00"}, _dt(base))
    sync.queue_state({"clock": "11:50"}, _dt(base + 10.0))
    sync.queue_state({"clock": "11:40"}, _dt(base + 20.0))
    await asyncio.sleep(0)

    await _trust_chrome_hulu(sync, fake, base + 25.0)
    assert sync.snapshot()["viewer_state"] == {"clock": "11:40"}
    ws.broadcast.reset_mock()

    fake.advance(1.0)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 5.0, observed_at=_dt(fake.wall),
    )

    snap = sync.snapshot()
    assert snap["reason"] == "backward_seek"
    assert snap["presentation_active"] is True
    assert snap["viewer_state"] is None
    assert any(
        call.args == ("gameday_viewer_state", None)
        for call in ws.broadcast.await_args_list
    )

    fake.advance(1.0)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 6.0, observed_at=_dt(fake.wall),
    )
    fake.advance(1.0)
    await sync.record_sample(
        service="hulu", player="chromium", playback_status="Playing",
        media_timestamp=base + 7.0, observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["viewer_state"] == {"clock": "12:00"}


@pytest.mark.asyncio
async def test_hulu_program_offset_translates_provider_event_time() -> None:
    fake = FakeTime()
    media = fake.wall - 30.0
    provider_target = media - 19.0

    direct = GameDayViewerSync(clock=fake.clock, monotonic=fake.monotonic)
    await _trust_chrome_hulu(direct, fake, media)
    assert direct.release_decision(_dt(provider_target)).defer is False

    # Reset time so both services see the same trusted media position.
    fake = FakeTime()
    media = fake.wall - 30.0
    calibrated = GameDayViewerSync(
        clock=fake.clock,
        monotonic=fake.monotonic,
        program_time_offset_seconds=29.0,
    )
    await _trust_chrome_hulu(calibrated, fake, media)
    decision = calibrated.release_decision(_dt(provider_target))

    assert decision.defer is True
    assert decision.reason == "await viewer clock"
    assert calibrated.snapshot()["program_time_offset_seconds"] == 29.0


@pytest.mark.asyncio
async def test_hulu_program_offset_applies_to_viewer_state_selection() -> None:
    fake = FakeTime()
    ws = type("WS", (), {"broadcast": AsyncMock()})()
    sync = GameDayViewerSync(
        ws_manager=ws,
        clock=fake.clock,
        monotonic=fake.monotonic,
        program_time_offset_seconds=29.0,
    )
    provider_anchor = fake.wall - 60.0
    sync.queue_state({"clock": "score"}, _dt(provider_anchor))

    # Final trusted sample lands at provider_anchor + 28: still one second
    # before the translated visible moment.
    await _trust_chrome_hulu(sync, fake, provider_anchor + 26.0)
    assert sync.snapshot()["viewer_state"] is None

    fake.advance(1.0)
    await sync.record_sample(
        service="hulu",
        player="chromium",
        playback_status="Playing",
        media_timestamp=provider_anchor + 29.0,
        observed_at=_dt(fake.wall),
    )
    assert sync.snapshot()["viewer_state"] == {"clock": "score"}


@pytest.mark.asyncio
async def test_runtime_program_offset_change_reselects_safe_viewer_state() -> None:
    fake = FakeTime()
    ws = type("WS", (), {"broadcast": AsyncMock()})()
    sync = GameDayViewerSync(
        ws_manager=ws,
        clock=fake.clock,
        monotonic=fake.monotonic,
    )
    provider_anchor = fake.wall - 40.0
    sync.queue_state({"clock": "score"}, _dt(provider_anchor))
    await _trust_chrome_hulu(sync, fake, provider_anchor + 10.0)
    assert sync.snapshot()["viewer_state"] == {"clock": "score"}

    await sync.set_program_time_offset_seconds(29.0)

    assert sync.snapshot()["program_time_offset_seconds"] == 29.0
    assert sync.snapshot()["viewer_state"] is None
@pytest.mark.asyncio
async def test_observation_time_target_can_explicitly_bypass_program_offset() -> None:
    fake = FakeTime()
    media = fake.wall - 30.0
    target = media - 10.0
    sync = GameDayViewerSync(
        clock=fake.clock,
        monotonic=fake.monotonic,
        program_time_offset_seconds=29.0,
    )
    await _trust_chrome_hulu(sync, fake, media)

    assert sync.release_decision(target=_dt(target)).defer is True
    bypass = sync.release_decision(
        _dt(target),
        apply_program_time_offset=False,
    )
    assert bypass.defer is False
    assert bypass.reason == "already visible"
@pytest.mark.asyncio
async def test_final_observation_cannot_overtake_last_translated_viewer_frame() -> None:
    fake = FakeTime()
    sync = GameDayViewerSync(
        clock=fake.clock,
        monotonic=fake.monotonic,
        program_time_offset_seconds=29.0,
    )
    provider_anchor = fake.wall - 60.0
    final_observed = provider_anchor + 20.0
    sync.queue_state(
        {"status": "in-progress"},
        _dt(provider_anchor),
        apply_program_time_offset=True,
    )
    sync.queue_state(
        {"status": "final"},
        _dt(final_observed),
        apply_program_time_offset=False,
    )

    # The raw final observation (provider+20) is behind the translated
    # in-progress frame (provider+29), so neither may become visible at +25.
    await _trust_chrome_hulu(sync, fake, provider_anchor + 23.0)
    assert sync._select_viewer_state(provider_anchor + 25.0) is None
    decision = sync.release_decision(
        _dt(final_observed),
        apply_program_time_offset=False,
    )
    assert decision.defer is True

    # Once the viewer reaches the translated in-progress floor, final can
    # advance on the same media instant rather than overtaking it.
    selected = sync._select_viewer_state(provider_anchor + 29.0)
    assert selected is not None
    assert selected.payload == {"status": "final"}


@pytest.mark.asyncio
async def test_quarter_observation_frame_advances_after_translated_play_frame() -> None:
    fake = FakeTime()
    sync = GameDayViewerSync(
        clock=fake.clock,
        monotonic=fake.monotonic,
        program_time_offset_seconds=29.0,
    )
    provider_play = fake.wall - 90.0
    quarter_observed = provider_play + 60.0

    sync.queue_state(
        {"status": "in-progress", "quarter": 1},
        _dt(provider_play),
        apply_program_time_offset=True,
    )
    sync.queue_state(
        {"status": "in-progress", "quarter": 2},
        _dt(quarter_observed),
        apply_program_time_offset=False,
    )

    first = sync._select_viewer_state(provider_play + 29.0)
    assert first is not None
    assert first.payload["quarter"] == 1

    before_q2 = sync._select_viewer_state(quarter_observed - 0.1)
    assert before_q2 is not None
    assert before_q2.payload["quarter"] == 1

    second = sync._select_viewer_state(quarter_observed)
    assert second is not None
    assert second.payload["quarter"] == 2
