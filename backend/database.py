"""
Async SQLite database setup via SQLAlchemy.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import DATA_DIR

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'home_hub.db'}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def _run_migrations(conn) -> None:
    """Apply incremental schema migrations for existing databases."""
    # Add vibe column to mode_playlists (Phase 1: vibe tagging)
    result = await conn.execute(text("PRAGMA table_info(mode_playlists)"))
    existing_cols = {row[1] for row in result.fetchall()}
    if "vibe" not in existing_cols:
        await conn.execute(text("ALTER TABLE mode_playlists ADD COLUMN vibe TEXT"))

    # Add category + effect columns to scenes (lighting enhancement)
    result = await conn.execute(text("PRAGMA table_info(scenes)"))
    scene_cols = {row[1] for row in result.fetchall()}
    if "category" not in scene_cols:
        await conn.execute(text("ALTER TABLE scenes ADD COLUMN category TEXT DEFAULT 'custom'"))
    if "effect" not in scene_cols:
        await conn.execute(text("ALTER TABLE scenes ADD COLUMN effect TEXT"))

    # Expand light_adjustments to cover color/ct and trigger source (event logger)
    result = await conn.execute(text("PRAGMA table_info(light_adjustments)"))
    la_cols = {row[1] for row in result.fetchall()}
    for col in ("hue_before", "hue_after", "sat_before", "sat_after", "ct_before", "ct_after"):
        if col not in la_cols:
            await conn.execute(text(f"ALTER TABLE light_adjustments ADD COLUMN {col} INTEGER"))
    if "trigger" not in la_cols:
        await conn.execute(text("ALTER TABLE light_adjustments ADD COLUMN trigger TEXT"))
    # 2026-05-18: weather_class for LightingLearner weather-aware retrain.
    # Mirrors the sonos_playback_events pattern below. NULL on pre-migration
    # rows folds to "any" at retrain time.
    if "weather_class" not in la_cols:
        await conn.execute(text("ALTER TABLE light_adjustments ADD COLUMN weather_class TEXT"))

    # Camera + audio context columns on activity_events (predictor enrichment)
    result = await conn.execute(text("PRAGMA table_info(activity_events)"))
    ae_cols = {row[1] for row in result.fetchall()}
    for col, ddl_type in (
        ("zone", "TEXT"),
        ("posture", "TEXT"),
        ("audio_class", "TEXT"),
        ("lux", "FLOAT"),
    ):
        if col not in ae_cols:
            await conn.execute(text(f"ALTER TABLE activity_events ADD COLUMN {col} {ddl_type}"))

    # Phase B (2026-05-12): weather class on sonos_playback_events so the
    # music bandit's nightly retrain produces weather-aware arms across
    # 90 days of history. Captured at log time in event_logger.log_sonos_event.
    result = await conn.execute(text("PRAGMA table_info(sonos_playback_events)"))
    spe_cols = {row[1] for row in result.fetchall()}
    if "weather_class" not in spe_cols:
        await conn.execute(text("ALTER TABLE sonos_playback_events ADD COLUMN weather_class TEXT"))

    # 2026-05-18: rule_suggestions extension for kind="brightness" rows.
    # Adds a discriminator column, a JSON payload, and relaxes rule_id from
    # NOT NULL to NULL (kind="brightness" rows don't have a LearnedRule
    # backing them — the bucket lives in payload). SQLite can't change a
    # column's NOT NULL constraint via ALTER, so the rule_id relaxation
    # needs a table-rebuild — done below conditionally so it runs at most
    # once. ADD COLUMN paths cover the new fields on top.
    result = await conn.execute(text("PRAGMA table_info(rule_suggestions)"))
    rs_info = result.fetchall()
    if rs_info:  # table exists (created by Base.metadata)
        rs_cols = {row[1] for row in rs_info}
        # Column 1 is `name`, column 3 is `notnull`. We need rule_id row.
        rule_id_row = next((r for r in rs_info if r[1] == "rule_id"), None)
        rule_id_notnull = bool(rule_id_row[3]) if rule_id_row else False

        if "kind" not in rs_cols:
            await conn.execute(text(
                "ALTER TABLE rule_suggestions ADD COLUMN kind TEXT DEFAULT 'mode'"
            ))
        if "payload" not in rs_cols:
            await conn.execute(text(
                "ALTER TABLE rule_suggestions ADD COLUMN payload TEXT"
            ))

        if rule_id_notnull:
            # Table-rebuild to relax rule_id NOT NULL. SQLite's standard
            # pattern: create new table with target schema, copy, drop, rename.
            await conn.execute(text("""
                CREATE TABLE rule_suggestions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id INTEGER,
                    fired_at DATETIME NOT NULL,
                    predicted_mode VARCHAR(50) NOT NULL,
                    confidence FLOAT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    current_mode_at_fire VARCHAR(50),
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    resolved_at DATETIME,
                    resolved_source VARCHAR(100),
                    kind TEXT DEFAULT 'mode',
                    payload TEXT,
                    FOREIGN KEY(rule_id) REFERENCES learned_rules(id)
                )
            """))
            await conn.execute(text("""
                INSERT INTO rule_suggestions_new
                (id, rule_id, fired_at, predicted_mode, confidence,
                 sample_count, current_mode_at_fire, status, resolved_at,
                 resolved_source, kind, payload)
                SELECT id, rule_id, fired_at, predicted_mode, confidence,
                       sample_count, current_mode_at_fire, status, resolved_at,
                       resolved_source, kind, payload
                FROM rule_suggestions
            """))
            await conn.execute(text("DROP TABLE rule_suggestions"))
            await conn.execute(text(
                "ALTER TABLE rule_suggestions_new RENAME TO rule_suggestions"
            ))
            await conn.execute(text(
                "CREATE INDEX ix_rule_sugg_status_fired "
                "ON rule_suggestions(status, fired_at)"
            ))

    # ML decision and metrics tables (Phase 3: ML foundation)
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='ml_decisions'")
    )
    if not result.fetchone():
        await conn.execute(text("""
            CREATE TABLE ml_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT (datetime('now')),
                predicted_mode VARCHAR(50) NOT NULL,
                actual_mode VARCHAR(50),
                applied BOOLEAN NOT NULL,
                confidence FLOAT,
                decision_source VARCHAR(30) NOT NULL,
                factors JSON,
                quarantined BOOLEAN DEFAULT 0 NOT NULL
            )
        """))
        await conn.execute(text("CREATE INDEX ix_ml_decisions_timestamp ON ml_decisions(timestamp)"))

    # 2026-06-01: quarantine flag on ml_decisions. Rows whose originating
    # source was untrusted at log time (SourceTrust verdict) stay for
    # forensics but drop out of every learner's training set. NULL/0 on
    # pre-migration rows reads as "not quarantined" (trusted), so existing
    # history is unaffected. See backend/services/source_trust.py.
    result = await conn.execute(text("PRAGMA table_info(ml_decisions)"))
    mld_cols = {row[1] for row in result.fetchall()}
    if "quarantined" not in mld_cols:
        await conn.execute(text(
            "ALTER TABLE ml_decisions ADD COLUMN quarantined BOOLEAN DEFAULT 0 NOT NULL"
        ))

    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='ml_metrics'")
    )
    if not result.fetchone():
        await conn.execute(text("""
            CREATE TABLE ml_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                metric_name VARCHAR(50) NOT NULL,
                value FLOAT NOT NULL,
                extra JSON
            )
        """))
        await conn.execute(text("CREATE INDEX ix_ml_metrics_date ON ml_metrics(date)"))

    # Personality layer (Phase A): trim mood_samples to 7 days at startup.
    # Personality tables themselves are created by Base.metadata.create_all
    # at the call site; this block only enforces the rolling window.
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='mood_samples'")
    )
    if result.fetchone():
        await conn.execute(text(
            "DELETE FROM mood_samples "
            "WHERE timestamp < datetime('now', '-7 days')"
        ))


async def init_db() -> None:
    """Create all database tables and apply pending migrations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure all model classes are registered with Base.metadata
    # before create_all runs (import order may not guarantee this).
    import backend.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_session() -> AsyncSession:
    """Yield an async database session."""
    async with async_session() as session:
        yield session
