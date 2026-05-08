"""
Event query service — aggregation and pattern detection over behavioral event tables.

Provides read-only queries against activity_events, light_adjustments,
sonos_playback_events, and scene_activations. Designed as the data layer
for the Phase 3 learning engine, analytics dashboard, and nudge system.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import ActivityEvent, LightAdjustment, SceneActivation, SonosPlaybackEvent

logger = logging.getLogger("home_hub.event_query")

MAX_DAYS = 90


def _since(days: int) -> datetime:
    """Return a UTC datetime `days` ago, clamped to MAX_DAYS."""
    days = min(max(days, 1), MAX_DAYS)
    return datetime.now(timezone.utc) - timedelta(days=days)


class EventQueryService:
    """Read-only aggregation queries over the event tables."""

    async def get_summary(self, days: int = 7) -> dict[str, Any]:
        """
        High-level stats across all event tables for a time window.

        Returns activity mode counts, light adjustment stats, Sonos event
        breakdown, and scene activation summary. All aggregations are
        pushed into SQL — `light_adjustments` alone routinely exceeds 100k
        rows in a 30-day window, so hydrating full ORM objects here would
        blow the analytics-page client timeout.
        """
        since = _since(days)

        async with async_session() as session:
            # ---- activity_events ----
            mode_rows = (await session.execute(
                select(
                    ActivityEvent.mode,
                    func.count().label("n"),
                    func.avg(ActivityEvent.duration_seconds).label("avg_dur"),
                )
                .where(ActivityEvent.timestamp >= since)
                .group_by(ActivityEvent.mode)
            )).all()

            source_rows = (await session.execute(
                select(ActivityEvent.source, func.count().label("n"))
                .where(ActivityEvent.timestamp >= since)
                .group_by(ActivityEvent.source)
            )).all()

            mode_counts = {mode: n for mode, n, _ in mode_rows}
            source_counts = {source: n for source, n in source_rows}
            avg_duration = {
                mode: round(avg_dur / 60, 1)
                for mode, _, avg_dur in mode_rows
                if avg_dur is not None
            }
            total_transitions = sum(mode_counts.values())

            # ---- light_adjustments ----
            trigger_rows = (await session.execute(
                select(LightAdjustment.trigger, func.count().label("n"))
                .where(
                    LightAdjustment.timestamp >= since,
                    LightAdjustment.trigger.isnot(None),
                )
                .group_by(LightAdjustment.trigger)
            )).all()

            total_adjustments = (await session.execute(
                select(func.count(LightAdjustment.id))
                .where(LightAdjustment.timestamp >= since)
            )).scalar() or 0

            top_light_row = (await session.execute(
                select(
                    LightAdjustment.light_id.label("light_id"),
                    func.coalesce(
                        func.max(LightAdjustment.light_name),
                        LightAdjustment.light_id,
                    ).label("name"),
                    func.count().label("n"),
                )
                .where(LightAdjustment.timestamp >= since)
                .group_by(LightAdjustment.light_id)
                .order_by(func.count().desc())
                .limit(1)
            )).first()

            trigger_counts = {trigger: n for trigger, n in trigger_rows}
            most_adjusted = None
            if top_light_row is not None:
                most_adjusted = {
                    "id": top_light_row.light_id,
                    "name": top_light_row.name,
                    "count": top_light_row.n,
                }

            # ---- sonos_playback_events ----
            type_rows = (await session.execute(
                select(SonosPlaybackEvent.event_type, func.count().label("n"))
                .where(SonosPlaybackEvent.timestamp >= since)
                .group_by(SonosPlaybackEvent.event_type)
            )).all()

            fav_rows = (await session.execute(
                select(SonosPlaybackEvent.favorite_title, func.count().label("n"))
                .where(
                    SonosPlaybackEvent.timestamp >= since,
                    SonosPlaybackEvent.favorite_title.isnot(None),
                )
                .group_by(SonosPlaybackEvent.favorite_title)
                .order_by(func.count().desc())
                .limit(5)
            )).all()

            type_counts = {event_type: n for event_type, n in type_rows}
            total_sonos_events = sum(type_counts.values())
            top_favorites = [{"title": title, "count": n} for title, n in fav_rows]

            # ---- scene_activations ----
            scene_source_rows = (await session.execute(
                select(SceneActivation.source, func.count().label("n"))
                .where(SceneActivation.timestamp >= since)
                .group_by(SceneActivation.source)
            )).all()

            scene_name_expr = func.coalesce(
                SceneActivation.scene_name,
                SceneActivation.scene_id,
            )
            top_scene_rows = (await session.execute(
                select(scene_name_expr.label("name"), func.count().label("n"))
                .where(SceneActivation.timestamp >= since)
                .group_by(scene_name_expr)
                .order_by(func.count().desc())
                .limit(5)
            )).all()

            scene_source_counts = {source: n for source, n in scene_source_rows}
            total_scenes = sum(scene_source_counts.values())
            top_scenes = [{"name": name, "count": n} for name, n in top_scene_rows]

        return {
            "period_days": min(days, MAX_DAYS),
            "activity": {
                "total_transitions": total_transitions,
                "modes": mode_counts,
                "sources": source_counts,
                "avg_mode_duration_minutes": avg_duration,
            },
            "lights": {
                "total_adjustments": total_adjustments,
                "by_trigger": trigger_counts,
                "most_adjusted_light": most_adjusted,
            },
            "sonos": {
                "total_events": total_sonos_events,
                "by_type": type_counts,
                "top_favorites": top_favorites,
            },
            "scenes": {
                "total_activations": total_scenes,
                "by_source": scene_source_counts,
                "top_scenes": top_scenes,
            },
        }

    async def get_activity(
        self,
        days: int = 7,
        mode: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated activity event history with optional filters."""
        since = _since(days)

        async with async_session() as session:
            query = select(ActivityEvent).where(ActivityEvent.timestamp >= since)
            if mode:
                query = query.where(ActivityEvent.mode == mode)
            if source:
                query = query.where(ActivityEvent.source == source)

            # Total count for pagination
            count_query = select(func.count()).select_from(query.subquery())
            total = (await session.execute(count_query)).scalar() or 0

            query = query.order_by(ActivityEvent.timestamp.desc()).limit(limit).offset(offset)
            rows = (await session.execute(query)).scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "mode": r.mode,
                    "previous_mode": r.previous_mode,
                    "source": r.source,
                    "duration_seconds": r.duration_seconds,
                    "duration_minutes": round(r.duration_seconds / 60, 1) if r.duration_seconds else None,
                }
                for r in rows
            ],
        }

    async def get_patterns(self, days: int = 30) -> dict[str, Any]:
        """
        Time-based pattern analysis for the rule engine.

        Returns dominant mode per hour, per day+hour, and manual override stats.
        Uses at least 30 days of data by default for meaningful patterns.
        """
        since = _since(days)

        async with async_session() as session:
            rows = (await session.execute(
                select(ActivityEvent).where(ActivityEvent.timestamp >= since)
            )).scalars().all()

        if not rows:
            return {"by_hour": [], "by_day_hour": [], "overrides": {"total": 0, "by_mode": {}, "override_rate": 0}}

        # Count mode occurrences by hour
        hour_mode_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        day_hour_mode_counts: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        override_counts: dict[str, int] = defaultdict(int)
        total_overrides = 0

        for row in rows:
            ts = row.timestamp
            if ts is None:
                continue
            if not isinstance(ts, datetime):
                ts = datetime.fromisoformat(str(ts))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            hour = ts.hour
            day = ts.weekday()

            hour_mode_counts[hour][row.mode] += 1
            day_hour_mode_counts[(day, hour)][row.mode] += 1

            if row.source == "manual":
                total_overrides += 1
                override_counts[row.mode] += 1

        # Compute dominant mode per hour with percentage
        by_hour = []
        for hour in range(24):
            counts = hour_mode_counts.get(hour, {})
            if not counts:
                continue
            total = sum(counts.values())
            top_mode = max(counts, key=counts.get)
            by_hour.append({
                "hour": hour,
                "mode": top_mode,
                "count": counts[top_mode],
                "total": total,
                "pct": round(counts[top_mode] / total * 100, 1),
            })

        # Compute dominant mode per day+hour (only include entries with 2+ occurrences)
        by_day_hour = []
        for (day, hour), counts in sorted(day_hour_mode_counts.items()):
            total = sum(counts.values())
            if total < 2:
                continue
            top_mode = max(counts, key=counts.get)
            pct = round(counts[top_mode] / total * 100, 1)
            if pct >= 60:  # Only report patterns with 60%+ confidence
                by_day_hour.append({
                    "day": day,
                    "hour": hour,
                    "mode": top_mode,
                    "count": counts[top_mode],
                    "total": total,
                    "pct": pct,
                })

        override_rate = round(total_overrides / len(rows), 3) if rows else 0

        return {
            "by_hour": by_hour,
            "by_day_hour": by_day_hour,
            "overrides": {
                "total": total_overrides,
                "by_mode": dict(override_counts),
                "override_rate": override_rate,
            },
        }

    async def get_timeline(self, days: int = 7) -> list[dict[str, Any]]:
        """Mode timeline for visualization — chronological list of mode events."""
        since = _since(days)

        async with async_session() as session:
            rows = (await session.execute(
                select(ActivityEvent)
                .where(ActivityEvent.timestamp >= since)
                .order_by(ActivityEvent.timestamp.asc())
            )).scalars().all()

        return [
            {
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "mode": r.mode,
                "previous_mode": r.previous_mode,
                "source": r.source,
                "duration_minutes": round(r.duration_seconds / 60, 1) if r.duration_seconds else None,
            }
            for r in rows
        ]

    async def get_light_events(
        self,
        days: int = 7,
        light_id: Optional[str] = None,
        trigger: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated light adjustment history with optional filters."""
        since = _since(days)

        async with async_session() as session:
            query = select(LightAdjustment).where(LightAdjustment.timestamp >= since)
            if light_id:
                query = query.where(LightAdjustment.light_id == light_id)
            if trigger:
                query = query.where(LightAdjustment.trigger == trigger)

            count_query = select(func.count()).select_from(query.subquery())
            total = (await session.execute(count_query)).scalar() or 0

            query = query.order_by(LightAdjustment.timestamp.desc()).limit(limit).offset(offset)
            rows = (await session.execute(query)).scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "light_id": r.light_id,
                    "light_name": r.light_name,
                    "bri_before": r.bri_before,
                    "bri_after": r.bri_after,
                    "hue_before": r.hue_before,
                    "hue_after": r.hue_after,
                    "sat_before": r.sat_before,
                    "sat_after": r.sat_after,
                    "ct_before": r.ct_before,
                    "ct_after": r.ct_after,
                    "mode_at_time": r.mode_at_time,
                    "trigger": r.trigger,
                }
                for r in rows
            ],
        }

    async def get_sonos_events(
        self,
        days: int = 7,
        event_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Paginated Sonos event history with optional filters."""
        since = _since(days)

        async with async_session() as session:
            query = select(SonosPlaybackEvent).where(SonosPlaybackEvent.timestamp >= since)
            if event_type:
                query = query.where(SonosPlaybackEvent.event_type == event_type)

            count_query = select(func.count()).select_from(query.subquery())
            total = (await session.execute(count_query)).scalar() or 0

            query = query.order_by(SonosPlaybackEvent.timestamp.desc()).limit(limit).offset(offset)
            rows = (await session.execute(query)).scalars().all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "event_type": r.event_type,
                    "favorite_title": r.favorite_title,
                    "mode_at_time": r.mode_at_time,
                    "volume": r.volume,
                    "triggered_by": r.triggered_by,
                }
                for r in rows
            ],
        }
