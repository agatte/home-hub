"""Shared feature engineering for ML services.

Provides temporal feature extraction used by the lighting learner and
full behavioral feature vectors for the behavioral predictor.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from backend.config import settings
from backend.database import async_session
from backend.models import ActivityEvent, LightAdjustment

# Apartment-local zone for temporal feature extraction. Hour/day-of-week/
# time-period buckets are user-facing semantics that must follow the wall
# clock through DST transitions — Indianapolis has its own DST rules so
# `timezone.utc` math silently shifts every "hour" feature by 1 twice a
# year (mis-windowing training data; tracked as #30).
_LOCAL_TZ = ZoneInfo(settings.TIMEZONE)

logger = logging.getLogger("home_hub.ml")

# Modes the behavioral predictor targets (excluding idle which is
# the "no detection" states the predictor tries to fill).
#
# `cooking` was retired from the target set on 2026-05-11. Over the
# trailing 60d window it was 19 / ~1700 filtered rows (1.1%), which gave
# it an inverse-frequency sample weight of ~15× — extreme enough to
# overfit on a handful of cooking-shaped leaves and pollute the softmax
# at conf=1.0. The predictor returning `None` (sub-threshold) for
# cooking-shaped inputs is the right behavior given there's no
# learnable signal at that volume.
PREDICTABLE_MODES = ("gaming", "working", "watching", "relax", "social")


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


def _to_local(dt: datetime) -> datetime:
    """Convert a timestamp to apartment-local time (``config.TIMEZONE``).

    Naive datetimes are treated as UTC (the SQLite read-back contract
    enforced by :func:`_to_utc`). Returns a tz-aware datetime in
    ``_LOCAL_TZ`` — DST-correct on both transition boundaries.
    """
    return _to_utc(dt).astimezone(_LOCAL_TZ)


def get_time_period(timestamp: datetime) -> str:
    """Determine time period from a timestamp (apartment-local clock).

    Uses the same boundaries as ``_get_time_period_static`` in the
    automation engine (hardcoded defaults):

    - ``day``:     08:00 - 17:59
    - ``evening``: 18:00 - 20:59
    - ``night``:   21:00 - 07:59

    Args:
        timestamp: A timezone-aware or naive datetime. Naive values are
            treated as UTC.

    Returns:
        One of ``"day"``, ``"evening"``, ``"night"``.
    """
    hour = _to_local(timestamp).hour
    if 8 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    return "night"


def get_season(timestamp: datetime) -> str:
    """Derive season from month (Northern Hemisphere, apartment-local)."""
    month = _to_local(timestamp).month
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    return "fall"


def get_temporal_features(timestamp: datetime) -> dict:
    """Build a temporal feature dict from a timestamp (apartment-local).

    Features produced:
        - ``hour``: 0-23
        - ``minute_bucket``: 0-3 (15-minute bins within the hour)
        - ``day_of_week``: 0=Monday, 6=Sunday
        - ``is_weekend``: bool
        - ``season``: winter / spring / summer / fall
        - ``time_period``: day / evening / night

    All values are computed in apartment-local time so DST transitions
    don't shift "hour" by 1 across the boundary.

    Args:
        timestamp: A datetime (aware or naive). Naive values are treated
            as UTC.

    Returns:
        Dict of temporal features.
    """
    local = _to_local(timestamp)
    return {
        "hour": local.hour,
        "minute_bucket": local.minute // 15,
        "day_of_week": local.weekday(),
        "is_weekend": local.weekday() >= 5,
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

# Camera + audio context encodings. Stable + hard-coded so a new label
# from upstream (e.g. YAMNet emitting a class we didn't enumerate) maps
# to a known sentinel rather than shifting indices on retrain. Audio
# falls through to "other" so unknown YAMNet classes are still in
# vocabulary; zone/posture use len(MAP) as the unknown bucket — a
# distinct integer the model can split on.
ZONE_ENCODING = {"desk": 0, "bed": 1, "couch": 2}
POSTURE_ENCODING = {"upright": 0, "reclined": 1}
AUDIO_CLASS_ENCODING = {
    "silence": 0,
    "speech_single": 1,
    "speech_multiple": 2,
    "music": 3,
    "mechanical_noise": 4,
    "doorbell": 5,
    "game_audio": 6,
    "other": 7,
}


def _encode_zone(zone: Optional[str]) -> int:
    return ZONE_ENCODING.get(zone, len(ZONE_ENCODING)) if zone else len(ZONE_ENCODING)


def _encode_posture(posture: Optional[str]) -> int:
    return (
        POSTURE_ENCODING.get(posture, len(POSTURE_ENCODING))
        if posture
        else len(POSTURE_ENCODING)
    )


def _encode_audio_class(audio_class: Optional[str]) -> int:
    if not audio_class:
        return AUDIO_CLASS_ENCODING["other"]
    return AUDIO_CLASS_ENCODING.get(audio_class, AUDIO_CLASS_ENCODING["other"])


def _encode_lux(lux: Optional[float]) -> float:
    """LightGBM handles NaN natively, so use it for missing lux. Cleaner
    than a sentinel like -1 because the model doesn't have to learn the
    sentinel's special meaning — NaN routes to a built-in missing-value
    branch."""
    if lux is None:
        return float("nan")
    try:
        return float(lux)
    except (TypeError, ValueError):
        return float("nan")


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

    # Pre-compute per-day "wake time" (first non-idle event each day).
    # Day boundary follows the apartment-local calendar so "today" lines
    # up with the user's wall clock — UTC day_keys split the day at
    # ~19:00 local (EST) / ~20:00 local (EDT), which lumps evening events
    # into the next "day" and creates a 1-hour shift across DST.
    wake_times: dict[str, datetime] = {}
    for ev in events:
        day_key = _to_local(ev.timestamp).strftime("%Y-%m-%d")
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

        day_key = _to_local(ts).strftime("%Y-%m-%d")
        wake = wake_times.get(day_key)
        minutes_since_wake = (
            (ts - wake).total_seconds() / 60 if wake and ts > wake else 0
        )

        transitions_today = sum(
            1 for e in events[:i]
            if _to_local(e.timestamp).strftime("%Y-%m-%d") == day_key
        )

        features.update({
            "previous_mode": MODE_ENCODING.get(prev_mode, len(MODE_ENCODING)),
            "previous_mode_duration_min": prev_duration / 60 if prev_duration else 0,
            "minutes_since_wake": minutes_since_wake,
            "mode_transitions_today": transitions_today,
            "manual_override_count_7d": override_count,
            "season_enc": SEASON_ENCODING.get(features["season"], 0),
            # Camera + audio context (populated by EventLogger going forward,
            # backfilled historically). NULL → sentinel index for categoricals,
            # NaN for continuous lux.
            "zone_enc": _encode_zone(getattr(ev, "zone", None)),
            "posture_enc": _encode_posture(getattr(ev, "posture", None)),
            "audio_class_enc": _encode_audio_class(getattr(ev, "audio_class", None)),
            "lux": _encode_lux(getattr(ev, "lux", None)),
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
    zone: Optional[str] = None,
    posture: Optional[str] = None,
    audio_class: Optional[str] = None,
    lux: Optional[float] = None,
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
        "zone_enc": _encode_zone(zone),
        "posture_enc": _encode_posture(posture),
        "audio_class_enc": _encode_audio_class(audio_class),
        "lux": _encode_lux(lux),
    })
    return features


async def latest_audio_class(window_seconds: int = 60) -> Optional[str]:
    """Return the top_class from the most recent audio_ml ml_decisions row
    within the last N seconds, or None if no such row exists or the query
    fails. Best-effort — never raises.

    Used by the behavioral predictor's runtime feature builder and the
    automation engine's predict() call site to give the model the same
    audio context that EventLogger captured at training time.
    """
    try:
        async with async_session() as session:
            result = await session.execute(
                text(
                    "SELECT json_extract(factors, '$.top_class') "
                    "FROM ml_decisions "
                    "WHERE decision_source = 'audio_ml' "
                    "  AND timestamp >= datetime('now', :window) "
                    "ORDER BY timestamp DESC LIMIT 1"
                ),
                {"window": f"-{int(window_seconds)} seconds"},
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        return None


async def build_runtime_features(
    current_mode: str,
    zone: Optional[str] = None,
    posture: Optional[str] = None,
    audio_class: Optional[str] = None,
    lux: Optional[float] = None,
) -> dict:
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
    # Local midnight, expressed as UTC for the indexed timestamp query.
    # UTC midnight would slice "today" at ~19:00 local (EST) / ~20:00 local
    # (EDT), dropping morning events from "transitions_today".
    today_start = now.astimezone(_LOCAL_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).astimezone(timezone.utc)
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
        zone=zone,
        posture=posture,
        audio_class=audio_class,
        lux=lux,
    )
