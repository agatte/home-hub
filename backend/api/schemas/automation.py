"""
Pydantic models for the automation system.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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
