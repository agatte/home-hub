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
    # Relative path from PROJECT_ROOT to the SvelteKit static build directory.
    FRONTEND_BUILD: str = "frontend-svelte/build"

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

    # Music Discovery
    LASTFM_API_KEY: Optional[str] = None

    # Plant App Integration
    PLANT_APP_API_URL: Optional[str] = None
    PLANT_APP_EMAIL: Optional[str] = None
    PLANT_APP_PASSWORD: Optional[str] = None
    # Escape hatch for the rare case the upstream Plant App API doesn't
    # support TLS. Default False forces https://; setting this to True
    # allows http:// but the service logs a WARNING on every login so
    # the insecure state stays visible. Never set in normal operation.
    PLANT_APP_ALLOW_INSECURE: bool = False

    # Home Bar Integration
    BAR_APP_URL: Optional[str] = None

    # Pi-hole DNS ad blocker (optional — enables network stats widget)
    PIHOLE_API_URL: Optional[str] = None
    PIHOLE_API_KEY: Optional[str] = None

    # Fauxmo Alexa integration (Phase 3 voice control)
    FAUXMO_ENABLED: bool = False

    # Presence webhook — shared secret for iPhone Shortcut POSTs to
    # /api/automation/presence/{arrived,departed}. When unset, the
    # webhook endpoints reject all requests (disabled).
    PRESENCE_WEBHOOK_TOKEN: Optional[str] = None

    # API-key auth on write endpoints. When set, every write
    # (POST / PUT / DELETE) requires X-API-Key matching this value
    # except from localhost (the kiosk) and any TRUSTED_LAN_IPS.
    # When unset, all writes return 503 — deploys must explicitly
    # provision a key. See backend/api/auth.py.
    HOME_HUB_API_KEY: Optional[str] = None
    # Comma-separated LAN IPs that bypass X-API-Key — e.g. the dev
    # desktop. Leave empty for "kiosk only" (only localhost bypasses).
    TRUSTED_LAN_IPS: str = ""

    # Zone+posture → relax rule — when enabled, the automation engine
    # auto-applies the "relax" manual override after a sustained
    # zone=bed + posture=reclined window (evening or weekend afternoons
    # only, no active override, eligible current mode). Default flipped
    # to True after the in-bed-watching-TV scenario surfaced: PC stays
    # "working" while Anthony's actually reclined, so without the rule
    # he was manually pressing relax 5+ times per night and fighting
    # transit-revert. Override lives 4h, refractory matches.
    ZONE_POSTURE_RULE_APPLY: bool = True

    # Phase 2 — Game Day
    OPENAI_API_KEY: Optional[str] = None
    ESPN_POLL_INTERVAL: int = 5
    BIG_PLAY_YARD_THRESHOLD: int = 20
    FIELD_GOAL_YARD_THRESHOLD: int = 40

    @property
    def trusted_lan_ips_set(self) -> frozenset[str]:
        """Parsed view of TRUSTED_LAN_IPS as a frozenset for membership checks."""
        return frozenset(
            ip.strip() for ip in self.TRUSTED_LAN_IPS.split(",") if ip.strip()
        )


settings = Settings()
