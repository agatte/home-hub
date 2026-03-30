"""
Pydantic schemas for Music API requests and responses.
"""
from typing import Optional

from pydantic import BaseModel, Field

VALID_VIBES = ("energetic", "mellow", "focus", "background", "hype")


class ModePlaylistEntry(BaseModel):
    """A single mode-to-playlist mapping with optional vibe tag."""

    id: int
    mode: str
    favorite_title: str
    vibe: Optional[str] = None
    auto_play: bool = False
    priority: int = 0


class ModePlaylistAdd(BaseModel):
    """Request to add a new mode-to-playlist mapping."""

    mode: str
    favorite_title: str = Field(..., min_length=1, max_length=200)
    vibe: Optional[str] = Field(None, description="energetic|mellow|focus|background|hype")
    auto_play: bool = False
    priority: int = 0


class ModePlaylistResponse(BaseModel):
    """Response for mode-playlist configuration."""

    mappings: dict[str, list[ModePlaylistEntry]]
    favorites: list[dict]


class ImportResponse(BaseModel):
    """Response after library import."""

    track_count: int
    artist_count: int
    genre_count: int
    top_genres: list[list]
    top_artists: list[dict]


class TasteProfileResponse(BaseModel):
    """Taste profile summary."""

    genre_distribution: dict[str, float]
    top_artists: list[dict]
    mode_genre_map: dict[str, list[str]]
    import_track_count: int
    import_artist_count: int
    last_import_at: Optional[str]
