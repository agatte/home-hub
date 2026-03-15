"""
Pydantic schemas for light API requests and responses.
"""
from typing import Optional

from pydantic import BaseModel, Field


class LightState(BaseModel):
    """State update for a single light."""

    on: Optional[bool] = None
    bri: Optional[int] = Field(None, ge=1, le=254)
    hue: Optional[int] = Field(None, ge=0, le=65535)
    sat: Optional[int] = Field(None, ge=0, le=254)
    transitiontime: Optional[int] = Field(None, ge=0)


class LightResponse(BaseModel):
    """Response representing a single light's current state."""

    light_id: str
    name: str
    on: bool
    bri: int
    hue: int
    sat: int
    reachable: bool


class ScenePreset(BaseModel):
    """A named scene preset (light states)."""

    name: str
    on: bool = True
    bri: int = Field(ge=1, le=254)
    hue: int = Field(ge=0, le=65535)
    sat: int = Field(ge=0, le=254)
