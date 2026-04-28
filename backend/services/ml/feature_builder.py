"""Shared feature engineering for ML services.

Provides temporal feature extraction used by the lighting learner and
full behavioral feature vectors for the behavioral predictor.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import ActivityEvent, LightAdjustment

logger = logging.getLogger("home_hub.ml")

# Modes the behavioral predictor targets (excluding idle which is
# the "no detection" states the predictor tries to fill).
PREDICTABLE_MODES = ("gaming", "working", "watching", "relax", "social", "cooking")


def _to_utc(dt: datetime) -> datetime:
    """Coerce a DateTime read from SQLite into a tz-aware UTC value.

    SQLAlchemy's SQLite driver deserializes DateTime(timezone=True) columns
    without the tzinfo even though we wrote them as UTC. Any comparison
    against a tz-aware `datetime.now(timezone.utc)` blows up with
    "can't compare offset-naive and offset-aware datetimes". Normalize on
    read so comparisons don't trip.
    """
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_time_period(timestamp: datetime) -> str:
    """Determine time period from a timestamp.

    Uses the same boundaries as ``_get_time_period_static`` in the
    automation engine (hardcoded defaults):

    - ``day``:     08:00 - 17:59
    - ``evening``: 18:00 - 20:59
    - ``night``:   21:00 - 07:59

    Args:
        timestamp: A timezone-aware or naive datetime.

    Returns:
        One of ``"day"``, ``"evening"``, ``"night"``.
    """
    hour = timestamp.hour
    if 8 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    return "night"


def get_season(timestamp: datetime) -> str:
    """Derive season from month (Northern Hemisphere).

    Returns:
        One of ``"winter"``, ``"spring"``, ``"summer"``, ``"fall"``.
    """
    month = timestamp.month
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    return "fall"


def get_temporal_features(timestamp: datetime) -> dict:
    """Build a temporal feature dict from a timestamp.

    Features produced:
        - ``hour``: 0-23
        - ``minute_bucket``: 0-3 (15-minute bins within the hour)
        - ``day_of_week``: 0=Monday, 6=Sunday
        - ``is_weekend``: bool
        - ``season``: winter / spring / summer / fall
        - ``time_period``: day / evening / night

    Args:
        timestamp: A datetime (aware or naive).

    Returns:
        Dict of temporal features.
    """
    return {
        "hour": timestamp.hour,
        "minute_bucket": timestamp.minute // 15,
        "day_of_week": timestamp.weekday(),
        "is_weekend": timestamp.weekday() >= 5,
        "season": get_season(timestamp),
        "time_period": get_time_period(timestamp),
    }


# ------------------------------------------------------------------
# Behavioral prediction features
# ------------------------------------------------------------------

# Label-encoding maps for categorical features (LightGBM needs integers).
MODE_ENCODING = {m: i for i, m in enumerate(PREDICTABLE_MODES)}
MODE_ENCODING.update({"idle": len(PREDICTABLE_MODES)})

SEASON_ENCODING = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}


async def build_training_data(days: int = 60) -> list[dict]:
    """Build feature rows from activity_events for predictor training.

    Each row represents a mode transition with temporal, behavioral,
    and contextual features.  Only events whose ``mode`` is in
    ``PREDICTABLE_MODES`` are used as positive training examples.

    Returns:
        List of feature dicts, each with a ``target`` key for the mode.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(ActivityEvent)
            .where(ActivityEvent.timestamp >= cutoff)
            .order_by(ActivityEvent.timestamp.asc())
        )
        events = result.scalars().all()

    if not events:
        return []

    # Normalize each event's timestamp to tz-aware UTC once so downstream
    # comparisons with datetime.now(timezone.utc) don't blow up on SQLite's
    # tz-naive deserialization.
    for ev in events:
        ev.timestamp = _to_utc(ev.timestamp)

    # Pre-compute per-day "wake time" (first non-idle event each day)
    wake_times: dict[str, datetime] = {}
    for ev in events:
        day_key = ev.timestamp.strftime("%Y-%m-%d")
        if day_key not in wake_times and ev.mode != "idle":
            wake_times[day_key] = ev.timestamp

    # Count manual overrides in last 7 days (rolling, computed once)
    now_utc = datetime.now(timezone.utc)
    override_cutoff = now_utc - timedelta(days=7)
    override_count = sum(
        1 for ev in events
        if ev.source == "manual" and ev.timestamp >= override_cutoff
    )

    rows: list[dict] = []
    for i, ev in enumerate(events):
        if ev.mode not in MODE_ENCODING:
            continue

        ts = ev.timestamp
        features = get_temporal_features(ts)

        # Behavioral features from event sequence
        prev_mode = events[i - 1].mode if i > 0 else "idle"
        prev_duration = ev.duration_seconds or 0
        if i > 0 and events[i - 1].duration_seconds:
            prev_duration = events[i - 1].duration_seconds

        day_key = ts.strftime("%Y-%m-%d")
        wake = wake_times.get(day_key)
        minutes_since_wake = (
            (ts - wake).total_seconds() / 60 if wake and ts > wake else 0
        )

        transitions_today = sum(
            1 for e in events[:i]
            if e.timestamp.strftime("%Y-%m-%d") == day_key
        )

        features.update({
            "previous_mode": MODE_ENCODING.get(prev_mode, len(MODE_ENCODING)),
            "previous_mode_duration_min": prev_duration / 60 if prev_duration else 0,
            "minutes_since_wake": minutes_since_wake,
            "mode_transitions_today": transitions_today,
            "manual_override_count_7d": override_count,
            "season_enc": SEASON_ENCODING.get(features["season"], 0),
        })

        # Target
        features["target"] = ev.mode
        rows.append(features)

    return rows


def build_current_features(
    current_mode: str,
    current_mode_duration_s: float = 0,
    transitions_today: int = 0,
    manual_override_count_7d: int = 0,
    minutes_since_wake: float = 0,
) -> dict:
    """Build a feature vector for real-time prediction.

    Pure function — given the runtime context values, produces the same
    feature set as ``build_training_data`` (minus the target). Use
    ``build_runtime_features`` instead when calling from the live
    automation loop; it queries activity_events to fill in the values
    the trained model expects.
    """
    now = datetime.now(timezone.utc)
    features = get_temporal_features(now)
    features.update({
        "previous_mode": MODE_ENCODING.get(current_mode, len(MODE_ENCODING)),
        "previous_mode_duration_min": current_mode_duration_s / 60,
        "minutes_since_wake": minutes_since_wake,
        "mode_transitions_today": transitions_today,
        "manual_override_count_7d": manual_override_count_7d,
        "season_enc": SEASON_ENCODING.get(features["season"], 0),
    })
    return features


async def build_runtime_features(current_mode: str) -> dict:
    """Build a feature vector for live prediction by querying recent events.

    The behavioral predictor was previously trained with four
    history-derived features (``minutes_since_wake``, mode transitions
    today, manual overrides last 7d, current-mode dwell) but called
    with all four defaulted to 0 — so inference saw a feature shape the
    model had never trained on. This async wrapper closes that gap by
    deriving each value from ``activity_events`` the same way
    ``build_training_data`` does, then delegates to
    ``build_current_features`` for assembly.

    All four queries are tiny aggregates against an indexed timestamp
    column; cost at the 60s automation cadence is negligible.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    async with async_session() as session:
        wake_result = await session.execute(
            select(ActivityEvent.timestamp)
            .where(ActivityEvent.timestamp >= today_start)
            .where(ActivityEvent.mode != "idle")
            .order_by(ActivityEvent.timestamp.asc())
            .limit(1)
        )
        wake = wake_result.scalar_one_or_none()

        transitions_result = await session.execute(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.timestamp >= today_start)
        )
        transitions_today = int(transitions_result.scalar() or 0)

        overrides_result = await session.execute(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.timestamp >= week_ago)
            .where(ActivityEvent.source == "manual")
        )
        manual_overrides_7d = int(overrides_result.scalar() or 0)

        last_result = await session.execute(
            select(ActivityEvent.timestamp)
            .order_by(ActivityEvent.timestamp.desc())
            .limit(1)
        )
        last_ts = last_result.scalar_one_or_none()

    wake = _to_utc(wake) if wake else None
    last_ts = _to_utc(last_ts) if last_ts else None

    minutes_since_wake = (
        (now - wake).total_seconds() / 60 if wake and now > wake else 0
    )
    current_mode_duration_s = (
        (now - last_ts).total_seconds() if last_ts else 0
    )

    return build_current_features(
        current_mode=current_mode,
        current_mode_duration_s=current_mode_duration_s,
        transitions_today=transitions_today,
        manual_override_count_7d=manual_overrides_7d,
        minutes_since_wake=minutes_since_wake,
    )
