"""
SQLAlchemy models for persistent data.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AppSetting(Base):
    """Key-value store for persistent app settings (survives restarts)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Scene(Base):
    """A saved light scene that can be activated with one tap."""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    light_states: Mapped[dict] = mapped_column(JSON, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, default="custom")
    effect: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ModePlaylist(Base):
    """Maps an activity mode to a Sonos favorite/playlist for auto-play.

    Multiple entries per mode are supported — each can carry a vibe tag
    (energetic, mellow, focus, background, hype) so the mapper can pick
    the right one based on time of day or explicit request.
    """

    __tablename__ = "mode_playlists"
    __table_args__ = (
        UniqueConstraint("mode", "favorite_title", name="uq_mode_favorite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    favorite_title: Mapped[str] = mapped_column(String(200), nullable=False)
    vibe: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
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
    similar_artists: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    similar_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class Recommendation(Base):
    """A music recommendation for a specific activity mode."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_name: Mapped[str] = mapped_column(String(200), nullable=False)
    track_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    album_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    preview_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    artwork_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    itunes_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class RecommendationFeedback(Base):
    """User feedback on a recommendation (like, dismiss, etc.)."""

    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendations.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Event logging — raw behavioral data for the future learning engine
# ---------------------------------------------------------------------------


class ActivityEvent(Base):
    """Records every mode transition for behavioral analysis."""

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # source: "automation", "manual", "pc_agent", "ambient"
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # duration_seconds is filled in when the *next* event arrives
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class LightAdjustment(Base):
    """Records every manual light change issued from the dashboard."""

    __tablename__ = "light_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    light_id: Mapped[str] = mapped_column(String(20), nullable=False)
    light_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bri_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bri_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mode_at_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class SonosPlaybackEvent(Base):
    """Records every Sonos play/pause/skip/volume event."""

    __tablename__ = "sonos_playback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # event_type: "play", "pause", "skip", "volume", "auto_play", "suggestion"
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    favorite_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    mode_at_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # triggered_by: "manual", "auto", "suggestion_accepted"
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
