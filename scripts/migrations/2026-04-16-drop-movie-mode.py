"""Apply the drop-movie-mode migration.

Run from the repo root:
    python3 scripts/migrations/2026-04-16-drop-movie-mode.py

Idempotent — running twice is a no-op (the second pass finds zero
'movie' rows and updates nothing). Safe to re-run.
"""
import sqlite3
import sys
from pathlib import Path

DB = Path("data/home_hub.db")
SQL = Path(__file__).with_suffix(".sql")


def main() -> int:
    if not DB.exists():
        print(f"FAIL: database not found at {DB.resolve()}", file=sys.stderr)
        return 1
    if not SQL.exists():
        print(f"FAIL: SQL file not found at {SQL.resolve()}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB))
    try:
        before = {
            "activity_events.mode": _count(conn, "activity_events", "mode"),
            "activity_events.previous_mode": _count(conn, "activity_events", "previous_mode"),
            "light_adjustments.mode_at_time": _count(conn, "light_adjustments", "mode_at_time"),
            "sonos_playback_events.mode_at_time": _count(conn, "sonos_playback_events", "mode_at_time"),
        }
        conn.executescript(SQL.read_text())
        conn.commit()
        after = {
            "activity_events.mode": _count(conn, "activity_events", "mode"),
            "activity_events.previous_mode": _count(conn, "activity_events", "previous_mode"),
            "light_adjustments.mode_at_time": _count(conn, "light_adjustments", "mode_at_time"),
            "sonos_playback_events.mode_at_time": _count(conn, "sonos_playback_events", "mode_at_time"),
        }
    finally:
        conn.close()

    print("Migration applied. Rows with mode='movie' before/after:")
    for k, v in before.items():
        print(f"  {k:40} {v} -> {after[k]}")
    return 0


def _count(conn: sqlite3.Connection, table: str, col: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {col} = 'movie'"
    ).fetchone()[0]


if __name__ == "__main__":
    sys.exit(main())
