"""Tests for the 2026-05-04 activity_events context backfill script.

Covers the JSON parsers in isolation plus an end-to-end run against an
in-memory sqlite DB seeded with realistic activity_events + ml_decisions
rows. The script is idempotent and NULL-only — these tests pin both
properties so a future re-run can never overwrite live-path enrichment
or invent context where none is available.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Load the migration script as a module by path — its filename starts
# with a date, so it can't be imported via the usual `import` machinery.
_SPEC = importlib.util.spec_from_file_location(
    "backfill_2026_05_04",
    Path(__file__).parent.parent / "scripts" / "migrations"
    / "2026-05-04-backfill-activity-event-context.py",
)
backfill = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backfill)


# ---------------------------------------------------------------------------
# Pure parser tests
# ---------------------------------------------------------------------------

def test_extract_camera_factors_real_shape():
    """Real camera-source JSON shape from prod ml_decisions."""
    raw = json.dumps({
        "detection": "present",
        "detection_source": "face",
        "ambient_lux": 143.16409830729165,
        "zone": "desk",
        "frame_zone": "desk",
        "posture": "upright",
        "frame_posture": None,
    })
    zone, posture, lux = backfill._extract_camera_factors(raw)
    assert zone == "desk"
    assert posture == "upright"
    assert lux == pytest.approx(143.164, rel=1e-3)


def test_extract_camera_factors_missing_keys_returns_none():
    """A camera row without zone/posture/ambient_lux returns Nones, not crashes."""
    raw = json.dumps({"detection": "absent"})
    assert backfill._extract_camera_factors(raw) == (None, None, None)


def test_extract_camera_factors_malformed_json():
    assert backfill._extract_camera_factors("not json") == (None, None, None)
    assert backfill._extract_camera_factors(None) == (None, None, None)
    assert backfill._extract_camera_factors("") == (None, None, None)
    # JSON list, not dict — defensive
    assert backfill._extract_camera_factors("[1, 2, 3]") == (None, None, None)


def test_extract_camera_factors_non_numeric_lux():
    """ambient_lux that fails to coerce to float comes back as None."""
    raw = json.dumps({"zone": "bed", "posture": "reclined", "ambient_lux": "n/a"})
    zone, posture, lux = backfill._extract_camera_factors(raw)
    assert zone == "bed"
    assert posture == "reclined"
    assert lux is None


def test_extract_audio_top_class_real_shape():
    raw = json.dumps({
        "top_class": "speech_single",
        "all_scores": {"silence": 0.1, "speech_single": 0.8},
        "rms_avg": 18.7,
    })
    assert backfill._extract_audio_top_class(raw) == "speech_single"


def test_extract_audio_top_class_malformed():
    assert backfill._extract_audio_top_class("not json") is None
    assert backfill._extract_audio_top_class(None) is None
    assert backfill._extract_audio_top_class("[]") is None


# ---------------------------------------------------------------------------
# End-to-end against an in-memory sqlite DB
# ---------------------------------------------------------------------------

def _build_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp sqlite DB with the two tables we need + redirect the
    script's DB path constant at it."""
    db_path = tmp_path / "test_home_hub.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            mode VARCHAR(50),
            previous_mode VARCHAR(50),
            source VARCHAR(30),
            duration_seconds INTEGER,
            zone TEXT,
            posture TEXT,
            audio_class TEXT,
            lux FLOAT
        );
        CREATE TABLE ml_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            predicted_mode VARCHAR(50) NOT NULL,
            actual_mode VARCHAR(50),
            applied BOOLEAN NOT NULL,
            confidence FLOAT,
            decision_source VARCHAR(30) NOT NULL,
            factors JSON
        );
        CREATE INDEX ix_ml_decisions_timestamp ON ml_decisions(timestamp);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(backfill, "DB", db_path)
    return db_path


def _insert_event(conn: sqlite3.Connection, ts: str, mode: str = "working") -> int:
    cur = conn.execute(
        "INSERT INTO activity_events (timestamp, mode, source) VALUES (?, ?, 'process')",
        (ts, mode),
    )
    return cur.lastrowid


def _insert_camera_row(conn: sqlite3.Connection, ts: str, **factors) -> None:
    conn.execute(
        "INSERT INTO ml_decisions (timestamp, predicted_mode, applied, decision_source, factors)"
        " VALUES (?, 'present', 0, 'camera', ?)",
        (ts, json.dumps(factors)),
    )


def _insert_audio_row(conn: sqlite3.Connection, ts: str, top_class: str) -> None:
    conn.execute(
        "INSERT INTO ml_decisions (timestamp, predicted_mode, applied, decision_source, factors)"
        " VALUES (?, ?, 0, 'audio_ml', ?)",
        (ts, top_class, json.dumps({"top_class": top_class})),
    )


def test_backfill_populates_from_nearby_camera_and_audio_rows(
    tmp_path, monkeypatch
):
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    event_ts = fmt(base)
    event_id = _insert_event(conn, event_ts)
    # Camera row 5 seconds before the event
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=5)),
        zone="bed", posture="reclined", ambient_lux=88.5,
    )
    # Audio row 3 seconds after the event
    _insert_audio_row(conn, fmt(base + timedelta(seconds=3)), top_class="music")
    conn.commit()
    conn.close()

    rc = backfill.main()
    assert rc == 0

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, audio_class, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    assert row == ("bed", "reclined", "music", pytest.approx(88.5))


def test_backfill_skips_rows_outside_60s_window(tmp_path, monkeypatch):
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    event_id = _insert_event(conn, fmt(base))
    # Camera row 120 seconds before — outside the window
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=120)),
        zone="desk", posture="upright", ambient_lux=150.0,
    )
    conn.commit()
    conn.close()

    backfill.main()

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, audio_class, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    assert row == (None, None, None, None)


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    """Running twice produces the same DB state and writes nothing on pass 2."""
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    _insert_event(conn, fmt(base))
    _insert_camera_row(
        conn, fmt(base),
        zone="desk", posture="upright", ambient_lux=145.0,
    )
    conn.commit()
    conn.close()

    backfill.main()
    backfill.main()  # idempotent — second pass is a no-op

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT zone, posture, lux FROM activity_events"
    ).fetchall()
    conn.close()
    assert rows == [("desk", "upright", pytest.approx(145.0))]


def test_backfill_does_not_overwrite_existing_values(tmp_path, monkeypatch):
    """Live-path enrichment must survive a re-run of the historical backfill."""
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    cur = conn.execute(
        "INSERT INTO activity_events (timestamp, mode, source, zone, posture, lux)"
        " VALUES (?, 'working', 'process', 'desk', 'upright', 200.0)",
        (fmt(base),),
    )
    event_id = cur.lastrowid
    # Nearby camera row would suggest different values — backfill must NOT clobber.
    _insert_camera_row(
        conn, fmt(base),
        zone="bed", posture="reclined", ambient_lux=50.0,
    )
    conn.commit()
    conn.close()

    backfill.main()

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    # Original values preserved — never overwritten.
    assert row == ("desk", "upright", pytest.approx(200.0))


def test_backfill_partial_population(tmp_path, monkeypatch):
    """Camera row with only zone (no posture / lux) writes just zone; the
    other NULL fields stay NULL until a later row provides them."""
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    event_id = _insert_event(conn, fmt(base))
    _insert_camera_row(conn, fmt(base), zone="desk")  # no posture / lux
    conn.commit()
    conn.close()

    backfill.main()

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, audio_class, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    assert row == ("desk", None, None, None)


def test_backfill_walks_outward_for_missing_camera_fields(
    tmp_path, monkeypatch
):
    """When the closest camera row has zone=None, the picker walks outward
    in time and uses the next closest row that actually has zone set.
    Per-field — so zone, posture, and lux can each come from different rows
    in the same window."""
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    event_id = _insert_event(conn, fmt(base))
    # Closest camera row (1s before) — face detection failed, no zone/posture.
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=1)),
        ambient_lux=145.0,
    )
    # 5s before — has zone but still no posture.
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=5)),
        zone="desk", ambient_lux=144.0,
    )
    # 10s before — finally has posture.
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=10)),
        zone="desk", posture="upright", ambient_lux=143.0,
    )
    conn.commit()
    conn.close()

    backfill.main()

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    # zone from the 5s-before row, posture from the 10s-before row,
    # lux from the closest (1s-before) row that had it.
    assert row == ("desk", "upright", pytest.approx(145.0))


def test_backfill_picks_closest_camera_row(tmp_path, monkeypatch):
    """When multiple camera rows are within ±60s, the closest one wins."""
    db = _build_test_db(tmp_path, monkeypatch)
    base = datetime(2026, 5, 4, 18, 0, 0, tzinfo=timezone.utc)
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731

    conn = sqlite3.connect(str(db))
    event_id = _insert_event(conn, fmt(base))
    # Far candidate (45s before) — wrong values.
    _insert_camera_row(
        conn, fmt(base - timedelta(seconds=45)),
        zone="bed", posture="reclined", ambient_lux=20.0,
    )
    # Closest candidate (2s after) — correct values.
    _insert_camera_row(
        conn, fmt(base + timedelta(seconds=2)),
        zone="desk", posture="upright", ambient_lux=160.0,
    )
    conn.commit()
    conn.close()

    backfill.main()

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT zone, posture, lux FROM activity_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    assert row == ("desk", "upright", pytest.approx(160.0))
