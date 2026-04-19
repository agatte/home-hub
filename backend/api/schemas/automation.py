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
    manual_light_overrides: list[str] = Field(
        default_factory=list,
        description="Light IDs with active per-light manual overrides",
    )


class ManualOverride(BaseModel):
    """Request to manually override the current mode."""

    mode: str = Field(
        ...,
        description="Mode to set: gaming, watching, working, social, cooking, "
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


class DayScheduleSchema(BaseModel):
    """Time-based lighting schedule for one day type."""

    wake_hour: int = Field(default=5, ge=0, le=23)
    wake_brightness: int = Field(default=40, ge=1, le=254)
    ramp_start_hour: int = Field(default=6, ge=0, le=23)
    ramp_duration_minutes: int = Field(default=60, ge=10, le=240)
    evening_start_hour: int = Field(default=18, ge=0, le=23)
    winddown_start_hour: int = Field(default=21, ge=0, le=23)
    late_night_start_hour: int = Field(
        default=23, ge=0, le=23,
        description="Hour after which relax enters the Moss & Ember late-night palette",
    )

    @model_validator(mode="after")
    def validate_hour_order(self):
        """Ensure hours are in a logical order."""
        if self.ramp_start_hour < self.wake_hour:
            raise ValueError("Ramp must start at or after wake time")
        if self.evening_start_hour >= self.winddown_start_hour:
            raise ValueError("Wind-down must start after evening")
        if self.late_night_start_hour < self.winddown_start_hour:
            raise ValueError("Late night must start at or after wind-down")
        return self


class TimeScheduleConfig(BaseModel):
    """Combined weekday + weekend schedule."""

    weekday: DayScheduleSchema = Field(default_factory=DayScheduleSchema)
    weekend: DayScheduleSchema = Field(
        default_factory=lambda: DayScheduleSchema(
            wake_hour=8,
            ramp_start_hour=8,
            ramp_duration_minutes=120,
        )
    )


class ModeBrightnessConfig(BaseModel):
    """Per-mode brightness multipliers (0.3 = 30%, 1.5 = 150%)."""

    gaming: float = Field(default=1.0, ge=0.3, le=1.5)
    working: float = Field(default=1.0, ge=0.3, le=1.5)
    watching: float = Field(default=1.0, ge=0.3, le=1.5)
    relax: float = Field(default=1.0, ge=0.3, le=1.5)
    cooking: float = Field(default=1.0, ge=0.3, le=1.5)
    social: float = Field(default=1.0, ge=0.3, le=1.5)


class ScreenColorReport(BaseModel):
    """RGB color reported by a screen sync source (desktop agent or laptop loopback)."""

    r: int = Field(..., ge=0, le=255, description="Red channel 0-255")
    g: int = Field(..., ge=0, le=255, description="Green channel 0-255")
    b: int = Field(..., ge=0, le=255, description="Blue channel 0-255")
    source: str = Field(
        default="desktop",
        description="Reporting source — 'desktop' or 'laptop'",
    )


class LaptopLoopbackToggle(BaseModel):
    """Toggle for the in-process laptop screen capture (TV-on-laptop escape hatch)."""

    enabled: bool = Field(..., description="True to start the loopback, False to stop")


class PresenceConfigSchema(BaseModel):
    """Presence detection configuration."""

    enabled: bool = Field(default=True, description="Enable/disable presence detection")
    phone_ip: str = Field(default="192.168.1.148", description="Phone IP address")
    phone_mac: str = Field(default="A2:DD:D9:65:EE:F8", description="Phone MAC address")
    ping_interval: int = Field(default=30, ge=10, le=120, description="Seconds between pings")
    away_timeout: int = Field(
        default=600, ge=60, le=3600,
        description="Seconds without response before marking away",
    )
    short_absence_threshold: int = Field(
        default=1800, ge=300, le=7200,
        description="Seconds — skip ceremony for absences shorter than this",
    )
    arrival_volume: int = Field(default=25, ge=0, le=100, description="TTS volume on arrival")
    departure_fade_seconds: int = Field(
        default=30, ge=10, le=120, description="Departure fade duration",
    )
