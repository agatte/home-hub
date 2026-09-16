"""Adaptive viewer-clock authority for Game Day presentation effects.

Canonical GameDayService state remains real-time. This service only decides when
viewer-facing effects are allowed to catch up with a delayed live stream.
"""
from __future__ import annotations

import asyncio
import copy
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Literal, Optional


class ViewerReleaseResult(str, Enum):
    VISIBLE = "visible"
    SKIPPED_BY_SEEK = "skipped_by_seek"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ViewerSyncDecision:
    defer: bool
    reason: str
    seek_generation: int
    drop: bool = False

@dataclass(frozen=True)
class ViewerClockSample:
    service: str
    player: str
    playback_status: str
    media_timestamp: float
    observed_at: datetime
    received_monotonic: float


@dataclass(frozen=True)
class BufferedViewerState:
    sequence: int
    anchor_timestamp: float
    payload: dict[str, Any]


class GameDayViewerSync:
    """Track a trusted viewer media clock and gate user-facing releases."""

    SAMPLE_STALE_SECONDS = 3.0
    UNTRUSTED_GRACE_SECONDS = 5.0
    MAX_WAIT_SECONDS = 30 * 60.0
    MAX_MEDIA_LAG_SECONDS = 6 * 60 * 60.0
    MAX_MEDIA_FUTURE_SECONDS = 5.0
    FORWARD_SEEK_THRESHOLD_SECONDS = 4.0
    BACKWARD_SEEK_THRESHOLD_SECONDS = 2.0
    NORMAL_RESIDUAL_SECONDS = 1.25
    TRUST_STREAK = 2
    STATE_HISTORY_LIMIT = 2048
    FORWARD_SEEK_HISTORY_LIMIT = 64
    STATUS_HEARTBEAT_SECONDS = 5.0

    def __init__(
        self,
        *,
        ws_manager: Any = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ws = ws_manager
        self._clock = clock
        self._monotonic = monotonic
        self._enabled = True
        self._closed = False
        self._condition = asyncio.Condition()
        self._publish_lock = asyncio.Lock()
        self._sample: Optional[ViewerClockSample] = None
        self._normal_streak = 0
        self._session_trusted = False
        self._last_authoritative_monotonic: Optional[float] = None
        self._candidate_started_monotonic: Optional[float] = None
        self._last_classification = "none"
        self._seek_generation = 0
        self._last_seek_direction: Optional[Literal["forward", "backward"]] = None
        self._last_seek_from: Optional[float] = None
        self._last_seek_to: Optional[float] = None
        self._forward_seek_ranges: deque[tuple[float, float]] = deque(
            maxlen=self.FORWARD_SEEK_HISTORY_LIMIT,
        )
        self._state_history: deque[BufferedViewerState] = deque(
            maxlen=self.STATE_HISTORY_LIMIT,
        )
        self._state_sequence = 0
        self._viewer_state: Optional[dict[str, Any]] = None
        self._viewer_state_sequence: Optional[int] = None
        self._viewer_state_dirty = False
        self._last_status_key: Optional[tuple[Any, ...]] = None
        self._last_status_broadcast_at = 0.0
        self._background_tasks: set[asyncio.Task] = set()
        self._watchdog_task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._closed = False
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name="gameday-viewer-sync-watchdog",
        )

    async def close(self) -> None:
        self._closed = True
        async with self._condition:
            self._enabled = False
            self._condition.notify_all()
        tasks = list(self._background_tasks)
        if self._watchdog_task is not None:
            tasks.append(self._watchdog_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._watchdog_task = None

    async def set_enabled(self, enabled: bool) -> None:
        async with self._condition:
            self._enabled = bool(enabled)
            self._condition.notify_all()
        await self._publish_outputs(force_status=True)

    @staticmethod
    def _preferred_player(player: str) -> bool:
        lowered = player.lower()
        return lowered in {"chrome", "chromium"}

    def _epoch_plausible(self, media_timestamp: float) -> bool:
        now = self._clock()
        lag = now - media_timestamp
        return (
            -self.MAX_MEDIA_FUTURE_SECONDS <= lag <= self.MAX_MEDIA_LAG_SECONDS
        )

    def queue_state(self, payload: dict[str, Any], anchor: datetime) -> None:
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        anchor_timestamp = anchor.astimezone(timezone.utc).timestamp()
        if self._state_history and anchor_timestamp <= self._state_history[-1].anchor_timestamp:
            return
        self._state_sequence += 1
        self._state_history.append(
            BufferedViewerState(
                sequence=self._state_sequence,
                anchor_timestamp=anchor_timestamp,
                payload=copy.deepcopy(payload),
            ),
        )
        self._spawn_publish()

    def _spawn_publish(self) -> None:
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._publish_outputs(), name="gameday-viewer-sync-publish",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def record_sample(
        self,
        *,
        service: str,
        player: str,
        playback_status: str,
        media_timestamp: float,
        observed_at: datetime,
    ) -> dict:
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        now_mono = self._monotonic()
        sample = ViewerClockSample(
            service=service.lower(),
            player=player.lower(),
            playback_status=playback_status,
            media_timestamp=float(media_timestamp),
            observed_at=observed_at.astimezone(timezone.utc),
            received_monotonic=now_mono,
        )
        async with self._condition:
            previous = self._sample
            if (
                previous is not None
                and now_mono - previous.received_monotonic > self.SAMPLE_STALE_SECONDS
            ):
                previous = None
                self._normal_streak = 0
                self._session_trusted = False
                self._last_authoritative_monotonic = None
                self._candidate_started_monotonic = None
            self._sample = sample
            self._classify_sample(previous, sample)
            self._refresh_authority_heartbeat(sample, now_mono)
        await self._publish_outputs()
        async with self._condition:
            self._condition.notify_all()
        return self.snapshot()

    def _invalidate_viewer_state(self) -> None:
        if self._viewer_state is None and self._viewer_state_sequence is None:
            return
        self._viewer_state = None
        self._viewer_state_sequence = None
        self._viewer_state_dirty = True

    def _classify_sample(
        self,
        previous: Optional[ViewerClockSample],
        sample: ViewerClockSample,
    ) -> None:
        same_session = bool(
            previous
            and previous.service == sample.service
            and previous.player == sample.player
        )
        if not same_session:
            self._normal_streak = 0
            self._session_trusted = False
            self._last_authoritative_monotonic = None
            self._candidate_started_monotonic = sample.received_monotonic
            self._invalidate_viewer_state()
            self._last_classification = "new_session"
            return
        if not self._epoch_plausible(sample.media_timestamp):
            self._normal_streak = 0
            self._last_classification = "implausible"
            return

        wall_delta = sample.received_monotonic - previous.received_monotonic
        media_delta = sample.media_timestamp - previous.media_timestamp
        residual = media_delta - wall_delta
        status = sample.playback_status.lower()

        # A real paused Hulu clock is trustworthy, but the user can still seek
        # while paused. For paused samples the expected media delta is zero, so
        # detect seeks from the direct position change instead of the playing
        # residual (which would misclassify an ordinary held pause as rewind).
        seek_delta = media_delta if status == "paused" else residual
        if status in {"playing", "paused"} and seek_delta > self.FORWARD_SEEK_THRESHOLD_SECONDS:
            self._seek_generation += 1
            self._last_seek_direction = "forward"
            self._last_seek_from = previous.media_timestamp
            self._last_seek_to = sample.media_timestamp
            self._forward_seek_ranges.append(
                (previous.media_timestamp, sample.media_timestamp),
            )
            self._normal_streak = 0
            self._last_classification = "forward_seek"
            return
        if status in {"playing", "paused"} and seek_delta < -self.BACKWARD_SEEK_THRESHOLD_SECONDS:
            self._seek_generation += 1
            self._last_seek_direction = "backward"
            self._last_seek_from = previous.media_timestamp
            self._last_seek_to = sample.media_timestamp
            self._normal_streak = 0
            # The old synchronized frame may now be ahead of the viewer. Clear
            # it immediately and hold a no-spoiler placeholder until the clock
            # regains authority and selects a state at/before the rewound frame.
            self._invalidate_viewer_state()
            self._last_classification = "backward_seek"
            return

        if status == "paused":
            self._normal_streak = 0
            self._last_classification = "paused"
            return
        if status != "playing" or wall_delta <= 0:
            self._normal_streak = 0
            self._last_classification = "inactive"
            return
        if abs(residual) <= self.NORMAL_RESIDUAL_SECONDS and media_delta > 0:
            self._normal_streak += 1
            self._last_classification = "normal"
            if self._normal_streak >= self.TRUST_STREAK:
                self._session_trusted = True
            return

        self._normal_streak = 0
        self._last_classification = "stalled"

    def _refresh_authority_heartbeat(
        self, sample: ViewerClockSample, now_mono: float,
    ) -> None:
        supported = sample.service == "hulu" and self._preferred_player(sample.player)
        plausible = self._epoch_plausible(sample.media_timestamp)
        status = sample.playback_status.lower()
        advancing = (
            status == "playing"
            and self._last_classification == "normal"
            and self._normal_streak >= self.TRUST_STREAK
        )
        if (
            self._enabled and supported and plausible and self._session_trusted
            and (status == "paused" or advancing)
        ):
            self._last_authoritative_monotonic = now_mono

    def snapshot(self) -> dict[str, Any]:
        sample = self._sample
        if sample is None:
            return {
                "enabled": self._enabled,
                "active": False,
                "authoritative": False,
                "presentation_active": False,
                "reason": "no_sample",
                "viewer_state": copy.deepcopy(self._viewer_state),
            }
        age = max(0.0, self._monotonic() - sample.received_monotonic)
        supported = sample.service == "hulu" and self._preferred_player(sample.player)
        plausible = self._epoch_plausible(sample.media_timestamp)
        paused = sample.playback_status.lower() == "paused"
        advancing = (
            sample.playback_status.lower() == "playing"
            and self._last_classification == "normal"
            and self._normal_streak >= self.TRUST_STREAK
        )
        authoritative = bool(
            self._enabled
            and supported
            and plausible
            and self._session_trusted
            and age <= self.SAMPLE_STALE_SECONDS
            and (paused or advancing)
        )
        last_authority_age = (
            None
            if self._last_authoritative_monotonic is None
            else max(0.0, self._monotonic() - self._last_authoritative_monotonic)
        )
        candidate_age = (
            None
            if self._candidate_started_monotonic is None
            else max(0.0, self._monotonic() - self._candidate_started_monotonic)
        )
        presentation_active = bool(
            authoritative
            or (
                self._enabled and supported and plausible
                and age <= self.SAMPLE_STALE_SECONDS
                and (
                    (
                        self._session_trusted
                        and last_authority_age is not None
                        and last_authority_age <= self.UNTRUSTED_GRACE_SECONDS
                    )
                    or (
                        not self._session_trusted
                        and candidate_age is not None
                        and candidate_age <= self.UNTRUSTED_GRACE_SECONDS
                    )
                )
            )
        )
        lag = self._clock() - sample.media_timestamp
        return {
            "enabled": self._enabled,
            "active": supported and plausible and age <= self.SAMPLE_STALE_SECONDS,
            "authoritative": authoritative,
            "presentation_active": presentation_active,
            "reason": self._last_classification,
            "service": sample.service,
            "player": sample.player,
            "playback_status": sample.playback_status,
            "media_timestamp": sample.media_timestamp,
            "observed_at": sample.observed_at.isoformat(),
            "sample_age_seconds": round(age, 3),
            "lag_seconds": round(lag, 3),
            "normal_streak": self._normal_streak,
            "seek_generation": self._seek_generation,
            "last_seek_direction": self._last_seek_direction,
            "viewer_state": copy.deepcopy(self._viewer_state),
        }

    def _was_skipped_by_forward_seek(self, target_epoch: float) -> bool:
        return any(
            start < target_epoch <= end
            for start, end in reversed(self._forward_seek_ranges)
        )

    def release_decision(self, target: datetime) -> ViewerSyncDecision:
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        target_epoch = target.astimezone(timezone.utc).timestamp()
        if self._was_skipped_by_forward_seek(target_epoch):
            return ViewerSyncDecision(
                False, "skipped by forward seek", self._seek_generation, drop=True,
            )
        snap = self.snapshot()
        if not snap.get("authoritative"):
            if snap.get("presentation_active"):
                return ViewerSyncDecision(
                    True, "await viewer clock confidence", self._seek_generation,
                )
            return ViewerSyncDecision(False, "viewer clock unavailable", self._seek_generation)
        media_timestamp = float(snap["media_timestamp"])
        if media_timestamp >= target_epoch:
            return ViewerSyncDecision(False, "already visible", self._seek_generation)
        return ViewerSyncDecision(True, "await viewer clock", self._seek_generation)

    async def wait_until_visible(
        self,
        target: datetime,
        *,
        seek_generation: int,
    ) -> ViewerReleaseResult:
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        target_epoch = target.astimezone(timezone.utc).timestamp()
        deadline = self._monotonic() + self.MAX_WAIT_SECONDS
        generation = seek_generation

        while True:
            now_mono = self._monotonic()
            if now_mono >= deadline:
                return ViewerReleaseResult.TIMEOUT
            if not self._enabled:
                return ViewerReleaseResult.UNAVAILABLE

            if self._seek_generation != generation:
                if self._was_skipped_by_forward_seek(target_epoch):
                    return ViewerReleaseResult.SKIPPED_BY_SEEK
                generation = self._seek_generation

            snap = self.snapshot()
            if snap.get("authoritative"):
                if float(snap["media_timestamp"]) >= target_epoch:
                    return ViewerReleaseResult.VISIBLE
            elif not snap.get("presentation_active"):
                return ViewerReleaseResult.UNAVAILABLE

            remaining = max(0.0, deadline - self._monotonic())
            try:
                async with self._condition:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=min(1.0, remaining),
                    )
            except TimeoutError:
                pass

    def _select_viewer_state(self, media_timestamp: float) -> Optional[BufferedViewerState]:
        for state in reversed(self._state_history):
            if state.anchor_timestamp <= media_timestamp:
                return state
        return None

    def _status_payload(self, snap: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in snap.items()
            if key != "viewer_state"
        }

    def _status_key(self, snap: dict[str, Any]) -> tuple[Any, ...]:
        return (
            snap.get("enabled"),
            snap.get("active"),
            snap.get("authoritative"),
            snap.get("presentation_active"),
            snap.get("reason"),
            snap.get("service"),
            snap.get("player"),
            snap.get("playback_status"),
            snap.get("seek_generation"),
        )

    async def _publish_outputs(self, *, force_status: bool = False) -> None:
        if self._ws is None or self._closed:
            return
        async with self._publish_lock:
            snap = self.snapshot()
            now_mono = self._monotonic()
            status_key = self._status_key(snap)
            if (
                force_status
                or status_key != self._last_status_key
                or now_mono - self._last_status_broadcast_at >= self.STATUS_HEARTBEAT_SECONDS
            ):
                try:
                    await self._ws.broadcast(
                        "gameday_viewer_sync", self._status_payload(snap),
                    )
                except Exception:
                    # WebSocket delivery is diagnostic/presentation-only. A
                    # disconnected kiosk must never break clock ingestion.
                    pass
                self._last_status_key = status_key
                self._last_status_broadcast_at = now_mono

            viewer_state_changed = self._viewer_state_dirty
            if snap.get("authoritative"):
                media_timestamp = float(snap["media_timestamp"])
                selected = self._select_viewer_state(media_timestamp)
                if (
                    selected is not None
                    and selected.sequence != self._viewer_state_sequence
                ):
                    self._viewer_state = copy.deepcopy(selected.payload)
                    self._viewer_state_sequence = selected.sequence
                    viewer_state_changed = True

            # Rewinds/new sessions must explicitly clear a previously published
            # frame even while authority is being reacquired; otherwise clients
            # can briefly show a future score/clock. Once authoritative again,
            # the same path publishes the newly selected safe frame.
            if viewer_state_changed:
                try:
                    await self._ws.broadcast(
                        "gameday_viewer_state", copy.deepcopy(self._viewer_state),
                    )
                except Exception:
                    pass
                self._viewer_state_dirty = False

    async def _watchdog_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(1.0)
                await self._publish_outputs()
                async with self._condition:
                    self._condition.notify_all()
        except asyncio.CancelledError:
            raise
