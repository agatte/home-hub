"""
Calibration nudge service.

Fires up to two daily prompts to /personality calibration so paired
mood_calibration rows accumulate toward the Phase A→B Spearman gate
(GH#58: 30+ paired samples, ρ>0.4 on V/A/F).

Five fixed-time buckets across the day. Each bucket fires its scheduled
nudge ONLY if it has < BUCKET_TARGET (7) paired samples in the last 60
days, so the per-bucket counts naturally balance. Auto-retires per
bucket as it fills.

Bucket layout (local ET, tile the day with no overlap):

    morning      10:30   window [09:30, 12:00)
    midday       13:00   window [12:00, 14:30)
    afternoon    16:00   window [14:30, 18:00)
    evening      20:30   window [18:00, 21:30)
    late_evening 22:00   window [21:30, 23:30)

Submissions outside the union of windows still count toward the global
paired_samples total but don't credit a bucket.

Gates at each fire time (all must pass):
    1. personality_enabled AND (emotion_enabled OR desktop_emotion_enabled)
    2. automation.mode NOT IN {sleeping, gameday}
    3. NOT DND
    4. this bucket has < BUCKET_TARGET paired samples in last 60d
    5. > MIN_HOURS_SINCE_SUBMISSION since most recent paired submission
    6. > MIN_HOURS_BETWEEN_NUDGES since last nudge of ANY bucket

Wired as five per-bucket ScheduledTask callbacks in bootstrap.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text

logger = logging.getLogger("home_hub.personality.calibration_nudge")


BUCKET_TARGET = 7

# (name, fire_hour, fire_minute, window_start_minute_of_day, window_end_minute_of_day)
BUCKETS: list[tuple[str, int, int, int, int]] = [
    ("morning",      10, 30,  9 * 60 + 30, 12 * 60),
    ("midday",       13,  0, 12 * 60,      14 * 60 + 30),
    ("afternoon",    16,  0, 14 * 60 + 30, 18 * 60),
    ("evening",      20, 30, 18 * 60,      21 * 60 + 30),
    ("late_evening", 22,  0, 21 * 60 + 30, 23 * 60 + 30),
]

# Look-back for bucket counts. Matches the runbook entry 31 Spearman
# recipe — samples older than 60d may reflect a pre-recalibration
# detector state and shouldn't count toward the per-bucket gate.
COUNT_LOOKBACK_DAYS = 60

# Cross-bucket rate limit. With 5 buckets at fixed times the natural
# spacing is 2-3h between adjacent bucket fires; this prevents a
# midday nudge landing 2.5h after a morning fire.
MIN_HOURS_BETWEEN_NUDGES = 4.0
# Don't nudge if the user just submitted. Avoids "thanks for submitting,
# now do another one" within the same context window.
MIN_HOURS_SINCE_SUBMISSION = 4.0

SUPPRESSED_MODES = frozenset({"sleeping", "gameday"})

NUDGE_STATE_KEY = "mood_calibration_nudge_state"


def _bucket_for_minute_of_day(mod: int) -> Optional[str]:
    """Return the bucket name a local-time minute-of-day lands in, or None."""
    for name, _h, _m, start, end in BUCKETS:
        if start <= mod < end:
            return name
    return None


class CalibrationNudgeService:
    """Twice-daily mood-calibration prompt; auto-retires per-bucket at BUCKET_TARGET."""

    def __init__(
        self,
        *,
        notifier_service: Any,
        automation_engine: Any,
        async_session_factory: Any,
        save_setting: Any,
        load_setting: Any,
        deeplink_base: str,
    ) -> None:
        self._notifier = notifier_service
        self._engine = automation_engine
        self._async_session = async_session_factory
        self._save_setting = save_setting
        self._load_setting = load_setting
        self._deeplink = f"{deeplink_base.rstrip('/')}/personality"

    async def maybe_fire(self, bucket: str) -> None:
        """Bucket's scheduled time hit. Check all gates and fire if appropriate.

        Idempotent — safe to call repeatedly. All errors are caught and
        logged at WARNING; a nudge is best-effort and must never crash
        the scheduler task.
        """
        try:
            await self._maybe_fire_impl(bucket)
        except Exception:
            logger.exception("calibration nudge fire failed (bucket=%s)", bucket)

    async def fire_now(self, *, bucket: str = "test") -> dict[str, Any]:
        """Bypass all gates and fire one nudge. For the test endpoint.

        Returns the payload that was dispatched so the test route can echo
        it back.
        """
        per_bucket, total_paired = await self._read_paired_counts()
        payload = await self._fire(
            bucket=bucket,
            total_paired=total_paired,
            per_bucket=per_bucket,
        )
        return payload

    async def _maybe_fire_impl(self, bucket: str) -> None:
        # 1. Feature enabled?
        personality_on, emotion_path_on = await self._read_enabled()
        if not (personality_on and emotion_path_on):
            logger.debug("nudge[%s]: skip — personality/emotion off", bucket)
            return

        # 2. Mode allows it?
        mode = (getattr(self._engine, "current_mode", "") or "").lower()
        if mode in SUPPRESSED_MODES:
            logger.debug("nudge[%s]: skip — mode=%s suppressed", bucket, mode)
            return

        # 3. DND?
        if self._engine.is_dnd_active():
            logger.debug("nudge[%s]: skip — dnd active", bucket)
            return

        # 4. Per-bucket target met?
        per_bucket, total_paired = await self._read_paired_counts()
        if per_bucket.get(bucket, 0) >= BUCKET_TARGET:
            logger.debug(
                "nudge[%s]: skip — target met (%d/%d)",
                bucket, per_bucket[bucket], BUCKET_TARGET,
            )
            return

        # 5. Recent submission?
        now_utc = datetime.now(timezone.utc)
        last_sub = await self._read_last_paired_submission()
        if last_sub and (now_utc - last_sub).total_seconds() < MIN_HOURS_SINCE_SUBMISSION * 3600:
            logger.debug(
                "nudge[%s]: skip — submission %.1fh ago",
                bucket, (now_utc - last_sub).total_seconds() / 3600,
            )
            return

        # 6. Recent prior nudge?
        nudge_state = (await self._load_setting(NUDGE_STATE_KEY)) or {}
        last_nudge_iso = nudge_state.get("last_nudge_at_utc")
        if last_nudge_iso:
            last_nudge = self._parse_iso_utc(last_nudge_iso)
            if last_nudge and (now_utc - last_nudge).total_seconds() < MIN_HOURS_BETWEEN_NUDGES * 3600:
                logger.debug(
                    "nudge[%s]: skip — prior nudge %.1fh ago",
                    bucket, (now_utc - last_nudge).total_seconds() / 3600,
                )
                return

        # All gates passed.
        await self._fire(
            bucket=bucket,
            total_paired=total_paired,
            per_bucket=per_bucket,
        )
        await self._save_setting(NUDGE_STATE_KEY, {
            "last_nudge_at_utc": now_utc.isoformat(),
            "last_nudge_bucket": bucket,
        })

    # ── DB readers ─────────────────────────────────────────────────────

    async def _read_enabled(self) -> tuple[bool, bool]:
        """(personality_enabled, emotion-or-desktop-emotion enabled)."""
        personality = (await self._load_setting("personality_enabled")) or {}
        emotion = (await self._load_setting("emotion_enabled")) or {}
        desktop = (await self._load_setting("desktop_emotion_enabled")) or {}
        return (
            bool(personality.get("enabled")),
            bool(emotion.get("enabled")) or bool(desktop.get("enabled")),
        )

    async def _read_paired_counts(self) -> tuple[dict[str, int], int]:
        """Return (per-bucket counts, total paired) over the 60d look-back.

        Per-bucket count credits a row only when its local-time HH:MM
        falls inside one of the BUCKETS' [start, end) windows.
        """
        async with self._async_session() as session:
            result = await session.execute(text(
                "SELECT "
                "  CAST(strftime('%H', timestamp, 'localtime') AS INTEGER) * 60 + "
                "  CAST(strftime('%M', timestamp, 'localtime') AS INTEGER) AS mod "
                "FROM mood_calibration "
                "WHERE detected_valence IS NOT NULL "
                "  AND timestamp >= datetime('now', :cutoff)"
            ), {"cutoff": f"-{COUNT_LOOKBACK_DAYS} days"})
            rows = result.fetchall()

        per_bucket: dict[str, int] = {name: 0 for name, *_ in BUCKETS}
        for row in rows:
            mod = row[0]
            if mod is None:
                continue
            try:
                mod_int = int(mod)
            except (TypeError, ValueError):
                continue
            b = _bucket_for_minute_of_day(mod_int)
            if b is not None:
                per_bucket[b] += 1
        return per_bucket, len(rows)

    async def _read_last_paired_submission(self) -> Optional[datetime]:
        async with self._async_session() as session:
            result = await session.execute(text(
                "SELECT MAX(timestamp) FROM mood_calibration "
                "WHERE detected_valence IS NOT NULL"
            ))
            row = result.fetchone()
        if not row or not row[0]:
            return None
        return self._coerce_db_timestamp_to_utc(row[0])

    # ── Dispatch ───────────────────────────────────────────────────────

    async def _fire(
        self,
        *,
        bucket: str,
        total_paired: int,
        per_bucket: dict[str, int],
    ) -> dict[str, Any]:
        title = "Mood check?"
        bucket_count = per_bucket.get(bucket, 0)
        body = (
            f"Rate your current mood — {total_paired}/30 paired total"
            f" (this bucket {bucket}: {bucket_count}/{BUCKET_TARGET})"
        )
        payload: dict[str, Any] = {
            "title": title,
            "subtitle": body,
            "body": body,
            "factors": [],
            "output_delta": None,
            "actions": [
                {
                    "label": "Open calibration",
                    "url": self._deeplink,
                    "method": "GET",
                    "type": "view",
                    "headers": {},
                },
            ],
            "kind": "calibration_nudge",
            "bucket": bucket,
            "click_url": self._deeplink,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid4()),
        }
        await self._notifier.emit_calibration_nudge(payload)
        logger.info(
            "calibration nudge fired (bucket=%s, total_paired=%d, bucket_count=%d/%d)",
            bucket, total_paired, bucket_count, BUCKET_TARGET,
        )
        return payload

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_iso_utc(value: str) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _coerce_db_timestamp_to_utc(value: Any) -> Optional[datetime]:
        """SQLite returns timestamps as naive strings ('YYYY-MM-DD HH:MM:SS')
        or as datetime depending on driver. Normalize to aware UTC."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace(" ", "T"))
            except ValueError:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return None
