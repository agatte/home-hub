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
        breakdown, and scene activation summary.
        """
        since = _since(days)

        async with async_session() as session:
            # Activity events
            activity_rows = (await session.execute(
                select(ActivityEvent).where(ActivityEvent.timestamp >= since)
            )).scalars().all()

            mode_counts: dict[str, int] = defaultdict(int)
            source_counts: dict[str, int] = defaultdict(int)
            mode_durations: dict[str, list[int]] = defaultdict(list)
            for row in activity_rows:
                mode_counts[row.mode] += 1
                source_counts[row.source] += 1
                if row.duration_seconds is not None:
                    mode_durations[row.mode].append(row.duration_seconds)

            avg_duration = {
                mode: round(sum(durs) / len(durs) / 60, 1)
                for mode, durs in mode_durations.items() if durs
            }

            # Light adjustments
            light_rows = (await session.execute(
                select(LightAdjustment).where(LightAdjustment.timestamp >= since)
            )).scalars().all()

            trigger_counts: dict[str, int] = defaultdict(int)
            light_counts: dict[str, dict] = defaultdict(lambda: {"count": 0, "name": ""})
            for row in light_rows:
                if row.trigger:
                    trigger_counts[row.trigger] += 1
                light_counts[row.light_id]["count"] += 1
                light_counts[row.light_id]["name"] = row.light_name or row.light_id

            most_adjusted = None
            if light_counts:
                top_id = max(light_counts, key=lambda k: light_counts[k]["count"])
                most_adjusted = {
                    "id": top_id,
                    "name": light_counts[top_id]["name"],
                    "count": light_counts[top_id]["count"],
                }

            # Sonos events
            sonos_rows = (await session.execute(
                select(SonosPlaybackEvent).where(SonosPlaybackEvent.timestamp >= since)
            )).scalars().all()

            type_counts: dict[str, int] = defaultdict(int)
            fav_counts: dict[str, int] = defaultdict(int)
            for row in sonos_rows:
                type_counts[row.event_type] += 1
                if row.favorite_title:
                    fav_counts[row.favorite_title] += 1

            top_favorites = sorted(
                [{"title": t, "count": c} for t, c in fav_counts.items()],
                key=lambda x: x["count"], reverse=True,
            )[:5]

            # Scene activations
            scene_rows = (await session.execute(
                select(SceneActivation).where(SceneActivation.timestamp >= since)
            )).scalars().all()

            scene_source_counts: dict[str, int] = defaultdict(int)
            scene_name_counts: dict[str, int] = defaultdict(int)
            for row in scene_rows:
                scene_source_counts[row.source] += 1
                name = row.scene_name or row.scene_id
                scene_name_counts[name] += 1

            top_scenes = sorted(
                [{"name": n, "count": c} for n, c in scene_name_counts.items()],
                key=lambda x: x["count"], reverse=True,
            )[:5]

        return {
            "period_days": min(days, MAX_DAYS),
            "activity": {
                "total_transitions": len(activity_rows),
                "modes": dict(mode_counts),
                "sources": dict(source_counts),
                "avg_mode_duration_minutes": avg_duration,
            },
            "lights": {
                "total_adjustments": len(light_rows),
                "by_trigger": dict(trigger_counts),
                "most_adjusted_light": most_adjusted,
            },
            "sonos": {
                "total_events": len(sonos_rows),
                "by_type": dict(type_counts),
                "top_favorites": top_favorites,
            },
            "scenes": {
                "total_activations": len(scene_rows),
                "by_source": dict(scene_source_counts),
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
