"""
Application configuration — reads from .env file.

All secrets and environment-specific values live in .env (never committed).
"""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root is home-hub/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "backend" / "static"
TTS_DIR = STATIC_DIR / "tts"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    LOCAL_IP: str = "127.0.0.1"

    # Hue Bridge
    HUE_BRIDGE_IP: str = "192.168.1.50"
    HUE_USERNAME: str = ""

    # Sonos (auto-discovered if not set)
    SONOS_IP: Optional[str] = None

    # TTS
    TTS_VOICE: str = "en-US-GuyNeural"
    TTS_VOLUME: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"

    # Morning routine
    OPENWEATHER_API_KEY: Optional[str] = None
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    HOME_ADDRESS: str = ""
    WORK_ADDRESS: str = ""
    MORNING_ROUTINE_HOUR: int = 6
    MORNING_ROUTINE_MINUTE: int = 40
    MORNING_VOLUME: int = 10
    TIMEZONE: str = "America/Indiana/Indianapolis"

    # Phase 2 — Game Day
    OPENAI_API_KEY: Optional[str] = None
    ESPN_POLL_INTERVAL: int = 5
    BIG_PLAY_YARD_THRESHOLD: int = 20
    FIELD_GOAL_YARD_THRESHOLD: int = 40


settings = Settings()
