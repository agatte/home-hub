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
from backend.models import ActivityEvent, LightAdjustment, SonosPlaybackEvent

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

                # Backfill duration on the most recent prior event for this session
                if previous_mode:
                    result = await session.execute(
                        select(ActivityEvent)
                        .where(ActivityEvent.duration_seconds.is_(None))
                        .order_by(ActivityEvent.timestamp.desc())
                        .limit(1)
                    )
                    prev_event = result.scalar_one_or_none()
                    if prev_event and prev_event.mode == previous_mode:
                        elapsed = int((now - prev_event.timestamp).total_seconds())
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
        light_name: Optional[str],
        bri_before: Optional[int],
        bri_after: Optional[int],
        mode_at_time: Optional[str],
    ) -> None:
        """
        Record a manual light brightness adjustment.

        Args:
            light_id: Hue light ID.
            light_name: Human-readable name (best-effort).
            bri_before: Brightness before the change (0-254), or None if unknown.
            bri_after: Brightness after the change (0-254), or None if not a bri command.
            mode_at_time: Active automation mode when the adjustment was made.
        """
        try:
            async with async_session() as session:
                session.add(LightAdjustment(
                    light_id=light_id,
                    light_name=light_name,
                    bri_before=bri_before,
                    bri_after=bri_after,
                    mode_at_time=mode_at_time,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to log light adjustment: {e}", exc_info=True)

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
