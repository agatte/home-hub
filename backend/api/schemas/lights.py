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
    ct: Optional[int] = Field(
        None, ge=153, le=500,
        description="Color temperature in mirek (153=6500K coolest, 500=2000K warmest)",
    )
    transitiontime: Optional[int] = Field(None, ge=0)


class LightResponse(BaseModel):
    """Response representing a single light's current state."""

    light_id: str
    name: str
    on: bool
    bri: int
    hue: int
    sat: int
    ct: Optional[int] = None
    colormode: Optional[str] = None
    reachable: bool


class ScenePreset(BaseModel):
    """A named scene preset (light states)."""

    name: str
    on: bool = True
    bri: int = Field(ge=1, le=254)
    hue: int = Field(ge=0, le=65535)
    sat: int = Field(ge=0, le=254)


class CustomSceneCreate(BaseModel):
    """Request body for creating a custom scene."""

    name: str = Field(..., max_length=100)
    light_states: dict
    category: Optional[str] = "custom"
    effect: Optional[str] = None


class CustomSceneResponse(BaseModel):
    """Response for a custom scene."""

    id: int
    name: str
    light_states: dict
    category: Optional[str] = None
    effect: Optional[str] = None
    source: str = "custom"
