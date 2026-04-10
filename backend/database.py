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


async def init_db() -> None:
    """Create all database tables and apply pending migrations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_session() -> AsyncSession:
    """Yield an async database session."""
    async with async_session() as session:
        yield session
