"""
SQLAlchemy models for persistent data.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Scene(Base):
    """A saved light + sonos preset that can be activated with one tap."""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    light_states: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ModePlaylist(Base):
    """Maps an activity mode to a Sonos favorite/playlist for auto-play."""

    __tablename__ = "mode_playlists"
    __table_args__ = (
        UniqueConstraint("mode", "favorite_title", name="uq_mode_favorite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    favorite_title: Mapped[str] = mapped_column(String(200), nullable=False)
    auto_play: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class MusicArtist(Base):
    """An artist from the user's Apple Music library or recommendations."""

    __tablename__ = "music_artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    genres: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="import")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class TasteProfile(Base):
    """Aggregated taste profile derived from library import (singleton row)."""

    __tablename__ = "taste_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    genre_distribution: Mapped[dict] = mapped_column(JSON, nullable=False)
    top_artists: Mapped[list] = mapped_column(JSON, nullable=False)
    mode_genre_map: Mapped[dict] = mapped_column(JSON, nullable=False)
    import_track_count: Mapped[int] = mapped_column(Integer, default=0)
    import_artist_count: Mapped[int] = mapped_column(Integer, default=0)
    last_import_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
