"""
Pydantic schemas for Sonos API requests and responses.
"""
from typing import Optional

from pydantic import BaseModel, Field


class SonosStatus(BaseModel):
    """Current Sonos playback status."""

    state: str
    track: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    duration: str = "0:00:00"
    position: str = "0:00:00"
    volume: int = 0
    mute: bool = False


class VolumeRequest(BaseModel):
    """Request to set Sonos volume."""

    volume: int = Field(ge=0, le=100)


class TTSRequest(BaseModel):
    """Request to speak text on Sonos."""

    text: str = Field(min_length=1, max_length=500)
    volume: Optional[int] = Field(None, ge=0, le=100)
