"""
Pydantic models for the automation system.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ActivityReport(BaseModel):
    """Activity report from the PC agent or ambient monitor."""

    mode: str = Field(
        ...,
        description="Detected activity mode: gaming, watching, working, "
        "social, idle, away",
    )
    source: str = Field(
        default="process",
        description="Detection source: 'process' (PC agent) or 'ambient' (mic)",
    )
    detected_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of when the activity was detected",
    )


class AutomationStatus(BaseModel):
    """Current state of the automation engine."""

    current_mode: str = Field(
        default="idle",
        description="Active mode: gaming, watching, working, social, idle, away",
    )
    mode_source: str = Field(
        default="time",
        description="What set the current mode: time, process, ambient, manual",
    )
    manual_override: bool = Field(
        default=False,
        description="Whether a manual override is active",
    )
    override_mode: Optional[str] = Field(
        default=None,
        description="The manually overridden mode (if manual_override is True)",
    )
    last_activity_change: Optional[str] = Field(
        default=None,
        description="ISO timestamp of last mode change",
    )
    automation_enabled: bool = Field(
        default=True,
        description="Whether the automation engine is active",
    )


class ManualOverride(BaseModel):
    """Request to manually override the current mode."""

    mode: str = Field(
        ...,
        description="Mode to set: gaming, watching, working, social, movie, "
        "relax, auto (clears override)",
    )


class MicCalibrationResult(BaseModel):
    """Result of microphone calibration."""

    threshold: int = Field(..., description="New noise threshold after calibration")
    avg_floor: float = Field(..., description="Measured average noise floor")


class AutomationConfig(BaseModel):
    """Configurable automation settings."""

    enabled: bool = Field(default=True, description="Enable/disable automation")
    override_timeout_hours: int = Field(
        default=4,
        description="Hours before manual override auto-clears",
    )
    gaming_effect: Optional[str] = Field(
        default=None,
        description="Hue effect to activate in gaming mode (e.g., 'candle')",
    )
    social_effect: Optional[str] = Field(
        default="prism",
        description="Hue effect to activate in social/party mode",
    )


class DayScheduleSchema(BaseModel):
    """Time-based lighting schedule for one day type."""

    wake_hour: int = Field(default=5, ge=0, le=23)
    wake_brightness: int = Field(default=40, ge=1, le=254)
    ramp_start_hour: int = Field(default=6, ge=0, le=23)
    ramp_duration_minutes: int = Field(default=60, ge=10, le=240)
    away_start_hour: Optional[int] = Field(default=7, ge=0, le=23)
    away_end_hour: Optional[int] = Field(default=18, ge=0, le=23)
    evening_start_hour: int = Field(default=18, ge=0, le=23)
    winddown_start_hour: int = Field(default=21, ge=0, le=23)

    @model_validator(mode="after")
    def validate_hour_order(self):
        """Ensure hours are in a logical order."""
        if self.ramp_start_hour < self.wake_hour:
            raise ValueError("Ramp must start at or after wake time")
        if self.away_start_hour is not None and self.away_end_hour is not None:
            if self.away_start_hour >= self.away_end_hour:
                raise ValueError("Away end must be after away start")
            if self.away_end_hour > self.evening_start_hour:
                raise ValueError("Away end must be at or before evening start")
        if self.evening_start_hour >= self.winddown_start_hour:
            raise ValueError("Wind-down must start after evening")
        return self


class TimeScheduleConfig(BaseModel):
    """Combined weekday + weekend schedule."""

    weekday: DayScheduleSchema = Field(default_factory=DayScheduleSchema)
    weekend: DayScheduleSchema = Field(
        default_factory=lambda: DayScheduleSchema(
            wake_hour=8,
            ramp_start_hour=8,
            ramp_duration_minutes=120,
            away_start_hour=None,
            away_end_hour=None,
        )
    )


class ModeBrightnessConfig(BaseModel):
    """Per-mode brightness multipliers (0.3 = 30%, 1.5 = 150%)."""

    gaming: float = Field(default=1.0, ge=0.3, le=1.5)
    working: float = Field(default=1.0, ge=0.3, le=1.5)
    watching: float = Field(default=1.0, ge=0.3, le=1.5)
    relax: float = Field(default=1.0, ge=0.3, le=1.5)
    movie: float = Field(default=1.0, ge=0.3, le=1.5)
    social: float = Field(default=1.0, ge=0.3, le=1.5)
