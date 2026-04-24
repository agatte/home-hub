"""
Pydantic schemas for inbound WebSocket messages.

A malformed command from the frontend used to sail through raw `data.get(...)`
into the Hue bridge; a `bri=9999` silently produced undefined behavior. These
models validate range, type, and presence once at the edge so the downstream
handlers can trust their inputs.

Outbound broadcasts (`light_update`, `mode_update`, etc.) are not modeled here.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LightCommandData(BaseModel):
    """Fields accepted on a light_command payload. Ranges mirror the Hue v1 API."""

    model_config = ConfigDict(extra="forbid")

    light_id: str
    on: Optional[bool] = None
    bri: Optional[int] = Field(default=None, ge=0, le=254)
    hue: Optional[int] = Field(default=None, ge=0, le=65535)
    sat: Optional[int] = Field(default=None, ge=0, le=254)
    ct: Optional[int] = Field(default=None, ge=153, le=500)
    transitiontime: Optional[int] = Field(default=None, ge=0, le=600)

    @field_validator("light_id", mode="before")
    @classmethod
    def _coerce_light_id(cls, v):
        # Other code paths emit int ids; accept both and normalize to str so
        # downstream `mark_light_manual(str(light_id))` stays consistent.
        if isinstance(v, int):
            return str(v)
        return v

    @model_validator(mode="after")
    def _require_at_least_one_state_field(self) -> "LightCommandData":
        if all(
            getattr(self, f) is None
            for f in ("on", "bri", "hue", "sat", "ct", "transitiontime")
        ):
            raise ValueError(
                "light_command requires at least one of on/bri/hue/sat/ct/transitiontime"
            )
        return self


class SonosCommandData(BaseModel):
    """Fields accepted on a sonos_command payload."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["play", "pause", "next", "previous", "volume"]
    volume: Optional[int] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _require_volume_iff_volume_action(self) -> "SonosCommandData":
        if self.action == "volume" and self.volume is None:
            raise ValueError("sonos_command action=volume requires a volume field")
        return self


class LightCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["light_command"]
    data: LightCommandData


class SonosCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["sonos_command"]
    data: SonosCommandData


WSCommand = Annotated[
    Union[LightCommand, SonosCommand],
    Field(discriminator="type"),
]
