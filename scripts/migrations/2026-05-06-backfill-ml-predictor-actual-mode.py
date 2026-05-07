"""Backfill ml_decisions.actual_mode for predictor (decision_source='ml') rows.

The behavioral predictor logs only while the engine's current_mode is
``idle``; the standard truth-tagger in ``ml_logger.on_mode_change`` then
backfilled ``actual_mode = leaving_mode`` (always ``idle``). Result:
every truth-tagged predictor row had ``actual_mode='idle'`` even though
predictions are forecasts of "what mode comes next" — and the predictor
never predicts ``idle``. So ``predicted_mode == actual_mode`` reads 0%
on a healthy 72%-accurate model.

This one-shot migration replaces the broken tags with the correct ones
by walking ``activity_events`` for the next non-idle mode that activated
within 30 minutes after each predictor row's timestamp. Same JOIN logic
the ml-model-evaluator agent's D.1 uses.

After 2026-05-06 commit ``<TBD>``, on_mode_change does this for new rows
automatically — this script is for the historical backlog only.

Idempotent — only writes when the existing value is NULL or the broken
``'idle'`` tag. Re-running gives the same result.

Run from the repo root, on the machine that owns the DB (prod = Latitude):
    python3 scripts/migrations/2026-05-06-backfill-ml-predictor-actual-mode.py
"""
import sqlite3
import sys
from pathlib import Path

# Force line-buffered stdout for ssh-without-TTY runs (matches sibling
# migration's pattern). Without this, progress lines block-buffer.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except (AttributeError, OSError):
    pass

print("backfill: starting", flush=True)

DB = Path("data/home_hub.db")

# Modes that are NOT valid truth tags for the predictor:
#   - idle / sleeping: predictor doesn't predict these (PREDICTABLE_MODES
#     in feature_builder.py is {working, gaming, watching, relax, social,
#     cooking}).
#   - movie / away / home: retired modes still possibly present in older
#     activity_events rows.
EXCLUDED_MODES = ("idle", "sleeping", "movie", "away", "home")


def main() -> int:
    if not DB.exists():
        print(f"FAIL: database not found at {DB.resolve()}", file=sys.stderr)
        return 1

    print(f"backfill: opening DB at {DB.resolve()}", flush=True)
    conn = sqlite3.connect(str(DB), timeout=30.0)
    conn.row_factory = sqlite3.Row
    print("backfill: connected", flush=True)
    try:
        before = _count_by_actual(conn)
        print("Predictor rows by actual_mode (before):", flush=True)
        for mode, n in before.items():
            print(f"  {mode!s:12} {n}", flush=True)

        excluded_placeholders = ",".join("?" * len(EXCLUDED_MODES))
        # Single SQL pass — correlated subquery picks the next non-excluded
        # activity_events.mode within +30 min for each predictor row.
        # SQLite handles the rowcount + commit; no per-row Python loop
        # needed because we're not constructing values from external data.
        sql = f"""
            UPDATE ml_decisions
            SET actual_mode = (
                SELECT ae.mode FROM activity_events ae
                WHERE ae.timestamp > ml_decisions.timestamp
                  AND ae.timestamp < datetime(ml_decisions.timestamp, '+30 minutes')
                  AND ae.mode NOT IN ({excluded_placeholders})
                ORDER BY ae.timestamp ASC
                LIMIT 1
            )
            WHERE decision_source = 'ml'
              AND (actual_mode IS NULL OR actual_mode = 'idle')
        """
        cur = conn.cursor()
        cur.execute(sql, EXCLUDED_MODES)
        rowcount = cur.rowcount
        conn.commit()
        print(f"\nUPDATE touched {rowcount} predictor rows.", flush=True)

        after = _count_by_actual(conn)
        print("\nPredictor rows by actual_mode (after):", flush=True)
        for mode, n in after.items():
            print(f"  {mode!s:12} {n}", flush=True)

        # Quick sanity check — any 'idle' tags remaining mean the JOIN
        # didn't pick a non-idle next mode (unlikely but possible if
        # excluded modes were the only thing that ever followed). Those
        # rows would have been overwritten to NULL by the UPDATE.
        idle_still = after.get("idle", 0)
        if idle_still > 0:
            print(
                f"\nWARN: {idle_still} predictor rows still tagged 'idle' after "
                f"backfill. Investigate — none should remain.",
                flush=True,
            )
    finally:
        conn.close()

    return 0


def _count_by_actual(conn: sqlite3.Connection) -> dict:
    """Distribution of actual_mode values for predictor rows. NULLs reported
    as the 'NULL' key for printable output."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(actual_mode, 'NULL') AS am, COUNT(*) AS n
        FROM ml_decisions
        WHERE decision_source = 'ml'
        GROUP BY am
        ORDER BY n DESC
    """)
    return {row["am"]: row["n"] for row in cur.fetchall()}


if __name__ == "__main__":
    sys.exit(main())
