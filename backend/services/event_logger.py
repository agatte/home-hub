"""
Event logger — records raw behavioral events to SQLite for future learning.

Captures mode transitions, manual light adjustments, and Sonos playback
events. No analysis is done here — this is pure data capture so the
learning engine has historical data to work with.

Each log call is fire-and-forget: errors are logged but never re-raised
so a DB hiccup never disrupts the main control flow.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from backend.database import async_session
from backend.models import ActivityEvent, LightAdjustment, SceneActivation, SonosPlaybackEvent

logger = logging.getLogger("home_hub.events")


class EventLogger:
    """Thin async wrapper for writing behavioral events to the database."""

    async def log_mode_change(
        self,
        mode: str,
        previous_mode: Optional[str],
        source: str,
    ) -> None:
        """
        Record a mode transition.

        Also backfills duration_seconds on the previous event by computing
        the elapsed time since it was written.

        Args:
            mode: The new mode.
            previous_mode: The mode we're leaving, or None on first start.
            source: Who triggered the change ("automation", "manual", "pc_agent", "ambient").
        """
        try:
            async with async_session() as session:
                now = datetime.now(timezone.utc)

                # Backfill duration on the most recent prior undurated event.
                # Invariant: when a new event lands, the previous event's
                # duration is simply (now - its timestamp), regardless of which
                # mode it represented. Matching on mode is fragile and misses
                # backfills whenever the engine's view of "previous_mode" is
                # stale or overlaps with rapid overrides.
                result = await session.execute(
                    select(ActivityEvent)
                    .where(ActivityEvent.duration_seconds.is_(None))
                    .order_by(ActivityEvent.timestamp.desc())
                    .limit(1)
                )
                prev_event = result.scalar_one_or_none()
                if prev_event:
                    # SQLite stores DateTime(timezone=True) as a naive string,
                    # so SQLAlchemy deserializes it without tzinfo. Normalize
                    # to UTC before subtracting our tz-aware `now`.
                    prev_ts = prev_event.timestamp
                    if prev_ts.tzinfo is None:
                        prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                    elapsed = int((now - prev_ts).total_seconds())
                    await session.execute(
                        update(ActivityEvent)
                        .where(ActivityEvent.id == prev_event.id)
                        .values(duration_seconds=elapsed)
                    )

                session.add(ActivityEvent(
                    timestamp=now,
                    mode=mode,
                    previous_mode=previous_mode,
                    source=source,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to log mode change: {e}", exc_info=True)

    async def log_light_adjustment(
        self,
        light_id: str,
        light_name: Optional[str] = None,
        bri_before: Optional[int] = None,
        bri_after: Optional[int] = None,
        hue_before: Optional[int] = None,
        hue_after: Optional[int] = None,
        sat_before: Optional[int] = None,
        sat_after: Optional[int] = None,
        ct_before: Optional[int] = None,
        ct_after: Optional[int] = None,
        mode_at_time: Optional[str] = None,
        trigger: Optional[str] = None,
    ) -> None:
        """
        Record a light change issued from the dashboard or an API client.

        Args:
            light_id: Hue light ID.
            light_name: Human-readable name (best-effort).
            bri_before/bri_after: Brightness (0-254) around the change.
            hue_before/hue_after: Hue (0-65535) around the change.
            sat_before/sat_after: Saturation (0-254) around the change.
            ct_before/ct_after: Color temperature in mirek (153-500) around the change.
            mode_at_time: Active automation mode when the adjustment was made.
            trigger: Where the change came from: "ws", "rest", "scene",
                "automation", or "all_lights".
        """
        # Skip if nothing actually changed — avoids noise from heartbeat writes
        # and slider debouncing that lands on the same value.
        changed = any(
            after is not None and after != before
            for before, after in (
                (bri_before, bri_after),
                (hue_before, hue_after),
                (sat_before, sat_after),
                (ct_before, ct_after),
            )
        )
        if not changed:
            return
        try:
            async with async_session() as session:
                session.add(LightAdjustment(
                    light_id=light_id,
                    light_name=light_name,
                    bri_before=bri_before,
                    bri_after=bri_after,
                    hue_before=hue_before,
                    hue_after=hue_after,
                    sat_before=sat_before,
                    sat_after=sat_after,
                    ct_before=ct_before,
                    ct_after=ct_after,
                    mode_at_time=mode_at_time,
                    trigger=trigger,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to log light adjustment: {e}", exc_info=True)

    async def log_scene_activation(
        self,
        scene_id: str,
        scene_name: Optional[str],
        source: str,
        mode_at_time: Optional[str],
    ) -> None:
        """
        Record a scene activation.

        Args:
            scene_id: The scene identifier (preset name, "custom_N", or bridge UUID).
            scene_name: Human-readable display name.
            source: "preset", "custom", or "bridge".
            mode_at_time: Active automation mode when the scene was activated.
        """
        try:
            async with async_session() as session:
                session.add(SceneActivation(
                    scene_id=scene_id,
                    scene_name=scene_name,
                    source=source,
                    mode_at_time=mode_at_time,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to log scene activation: {e}", exc_info=True)

    async def log_sonos_event(
        self,
        event_type: str,
        favorite_title: Optional[str],
        mode_at_time: Optional[str],
        volume: Optional[int] = None,
        triggered_by: str = "manual",
    ) -> None:
        """
        Record a Sonos playback event.

        Args:
            event_type: "play", "pause", "skip", "volume", "auto_play", "suggestion".
            favorite_title: Currently playing favorite name, if known.
            mode_at_time: Active automation mode when the event occurred.
            volume: Volume level (0-100), relevant for volume events.
            triggered_by: "manual", "auto", or "suggestion_accepted".
        """
        try:
            async with async_session() as session:
                session.add(SonosPlaybackEvent(
                    event_type=event_type,
                    favorite_title=favorite_title,
                    mode_at_time=mode_at_time,
                    volume=volume,
                    triggered_by=triggered_by,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to log Sonos event: {e}", exc_info=True)
