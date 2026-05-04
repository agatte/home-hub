"""Backfill activity_events.{zone,posture,audio_class,lux} from ml_decisions.

For each activity_events row with NULL enrichment columns, find the
closest camera-source ml_decisions row within ±60 seconds and pull
zone/posture/ambient_lux from its factors JSON. Same window for the
audio_class lookup against audio_ml-source rows.

Idempotent — only writes columns that are currently NULL. Safe to
re-run; subsequent passes find nothing to update for already-populated
rows. Skips rows already populated by the live write path so the
historical backfill never overwrites a real-time enrichment.

Run from the repo root, on the machine that owns the DB (prod = Latitude):
    python3 scripts/migrations/2026-05-04-backfill-activity-event-context.py
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Force line-buffered stdout. ssh "host cmd" doesn't allocate a TTY so
# Python defaults to block-buffered output; without this, progress lines
# don't reach the operator's terminal until the buffer fills (or process
# exits), making a healthy run look stuck. Equivalent to `python3 -u`.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except (AttributeError, OSError):
    pass

print("backfill: starting", flush=True)

DB = Path("data/home_hub.db")
WINDOW_SECONDS = 60
# Print a progress line every PROGRESS_INTERVAL rows scanned.
PROGRESS_INTERVAL = 200
# Commit every COMMIT_INTERVAL rows so an interrupted run preserves partial work.
COMMIT_INTERVAL = 500


def main() -> int:
    if not DB.exists():
        print(f"FAIL: database not found at {DB.resolve()}", file=sys.stderr)
        return 1

    print(f"backfill: opening DB at {DB.resolve()}", flush=True)
    conn = sqlite3.connect(str(DB), timeout=10.0)
    conn.row_factory = sqlite3.Row
    print("backfill: connected", flush=True)
    try:
        before = _count_nulls(conn)
        print(f"NULL counts before: {before}", flush=True)
        # Sanity check — print the query plan so we can confirm the
        # index is being used. Look for "USING INDEX" in the output.
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT factors FROM ml_decisions"
            " WHERE timestamp >= ? AND timestamp <= ?"
            " AND decision_source = 'camera'"
            " ORDER BY ABS(julianday(timestamp) - julianday(?)) ASC LIMIT 1",
            ("2026-04-01 00:00:00.000000", "2026-04-01 00:01:00.000000",
             "2026-04-01 00:00:30"),
        ).fetchall()
        print("Query plan:", flush=True)
        for r in plan:
            print(f"  {dict(r)}", flush=True)

        cam_updates, audio_updates, scanned = _backfill(conn)
        conn.commit()
        after = _count_nulls(conn)
    finally:
        conn.close()

    print(f"Scanned {scanned} activity_events rows needing backfill.")
    print(f"  Camera fields populated on {cam_updates} rows.")
    print(f"  audio_class populated on {audio_updates} rows.")
    print()
    print("NULL counts (before -> after):")
    for col in ("zone", "posture", "audio_class", "lux"):
        delta = before[col] - after[col]
        print(f"  {col:12} {before[col]:5} -> {after[col]:5}  ({delta:+d})")
    return 0


def _count_nulls(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.cursor()
    counts = {}
    for col in ("zone", "posture", "audio_class", "lux"):
        cur.execute(f"SELECT COUNT(*) FROM activity_events WHERE {col} IS NULL")
        counts[col] = cur.fetchone()[0]
    return counts


def _backfill(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Walk every activity_events row missing any enrichment field and try
    to fill from nearby ml_decisions rows. Returns (cam_updates, audio_updates,
    scanned) — scanned is total rows considered, updates count rows where
    at least one column was successfully written.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, timestamp, zone, posture, audio_class, lux
        FROM activity_events
        WHERE zone IS NULL OR posture IS NULL OR audio_class IS NULL OR lux IS NULL
        ORDER BY timestamp ASC
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"Backfilling {total} activity_events rows...", flush=True)

    cam_updates = 0
    audio_updates = 0

    for i, row in enumerate(rows, 1):
        cam_changed = _backfill_camera(cur, row)
        audio_changed = _backfill_audio(cur, row)
        if cam_changed:
            cam_updates += 1
        if audio_changed:
            audio_updates += 1
        if i % PROGRESS_INTERVAL == 0:
            pct = (i / total) * 100
            print(
                f"  [{i}/{total}] {pct:.1f}% — "
                f"camera={cam_updates}, audio={audio_updates}",
                flush=True,
            )
        if i % COMMIT_INTERVAL == 0:
            conn = cur.connection
            conn.commit()
            print(f"  [{i}/{total}] partial commit", flush=True)

    return cam_updates, audio_updates, total


def _backfill_camera(cur: sqlite3.Cursor, row: sqlite3.Row) -> bool:
    """Look up camera context for one row and write only the NULL fields.
    Returns True if any column was actually written."""
    needs_zone = row["zone"] is None
    needs_posture = row["posture"] is None
    needs_lux = row["lux"] is None
    if not (needs_zone or needs_posture or needs_lux):
        return False

    zone, posture, lux = _find_camera_context(cur, row["timestamp"])

    sets: list[str] = []
    vals: list = []
    if needs_zone and zone is not None:
        sets.append("zone = ?")
        vals.append(zone)
    if needs_posture and posture is not None:
        sets.append("posture = ?")
        vals.append(posture)
    if needs_lux and lux is not None:
        sets.append("lux = ?")
        vals.append(lux)

    if not sets:
        return False

    vals.append(row["id"])
    cur.execute(
        f"UPDATE activity_events SET {', '.join(sets)} WHERE id = ?",
        vals,
    )
    return True


def _backfill_audio(cur: sqlite3.Cursor, row: sqlite3.Row) -> bool:
    """Look up audio_class for one row. Returns True if written."""
    if row["audio_class"] is not None:
        return False

    audio_class = _find_audio_class(cur, row["timestamp"])
    if audio_class is None:
        return False

    cur.execute(
        "UPDATE activity_events SET audio_class = ? WHERE id = ?",
        (audio_class, row["id"]),
    )
    return True


def _bounds(event_ts: str) -> tuple[str, str]:
    """Compute ISO-format ±60s bounds around an SQLite-stored timestamp.
    Returned as text so the comparison against ``timestamp`` can use the
    ``ix_ml_decisions_timestamp`` index — wrapping the column in
    ``julianday()`` would force a full-table scan, which on prod's
    ~1M+ row ml_decisions table is far too slow for a per-row loop.
    """
    event_dt = datetime.fromisoformat(event_ts)
    lower = (event_dt - timedelta(seconds=WINDOW_SECONDS)).strftime("%Y-%m-%d %H:%M:%S.%f")
    upper = (event_dt + timedelta(seconds=WINDOW_SECONDS)).strftime("%Y-%m-%d %H:%M:%S.%f")
    return lower, upper


def _find_camera_context(
    cur: sqlite3.Cursor, event_ts: str,
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Closest decision_source='camera' ml_decisions row within ±60s.
    Camera factors carry top-level zone, posture, ambient_lux keys."""
    lower, upper = _bounds(event_ts)
    cur.execute("""
        SELECT factors
        FROM ml_decisions
        WHERE timestamp >= ? AND timestamp <= ?
          AND decision_source = 'camera'
        ORDER BY ABS(julianday(timestamp) - julianday(?)) ASC
        LIMIT 1
    """, (lower, upper, event_ts))
    fetched = cur.fetchone()
    if not fetched:
        return None, None, None
    return _extract_camera_factors(fetched["factors"])


def _find_audio_class(cur: sqlite3.Cursor, event_ts: str) -> Optional[str]:
    """Closest decision_source='audio_ml' ml_decisions row within ±60s."""
    lower, upper = _bounds(event_ts)
    cur.execute("""
        SELECT factors
        FROM ml_decisions
        WHERE timestamp >= ? AND timestamp <= ?
          AND decision_source = 'audio_ml'
        ORDER BY ABS(julianday(timestamp) - julianday(?)) ASC
        LIMIT 1
    """, (lower, upper, event_ts))
    fetched = cur.fetchone()
    if not fetched:
        return None
    return _extract_audio_top_class(fetched["factors"])


def _extract_camera_factors(
    raw: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Parse a camera-source factors JSON string into (zone, posture, lux).
    Tolerates malformed JSON and missing keys — returns Nones rather than
    raising. ``ambient_lux`` is the closest available analog to the live
    write path's ``ema_lux`` (per-frame raw vs. EMA-smoothed; values
    match within a few units)."""
    if not raw:
        return None, None, None
    try:
        f = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, None, None
    if not isinstance(f, dict):
        return None, None, None
    lux = f.get("ambient_lux")
    if lux is not None:
        try:
            lux = float(lux)
        except (TypeError, ValueError):
            lux = None
    return f.get("zone"), f.get("posture"), lux


def _extract_audio_top_class(raw: Optional[str]) -> Optional[str]:
    """Parse an audio_ml factors JSON string and return its top_class."""
    if not raw:
        return None
    try:
        f = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(f, dict):
        return None
    return f.get("top_class")


if __name__ == "__main__":
    sys.exit(main())
