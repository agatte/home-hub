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
    # Optional stable role for pc_agent activity reports: desktop or latitude.
    HOME_HUB_AGENT_DEVICE: Optional[str] = None
    # Relative path from PROJECT_ROOT to the SvelteKit static build directory.
    FRONTEND_BUILD: str = "frontend-svelte/build"

    # Hue Bridge
    HUE_BRIDGE_IP: str = "192.168.86.50"
    HUE_USERNAME: str = ""

    # Sonos (auto-discovered if not set)
    SONOS_IP: Optional[str] = None

    # TTS
    TTS_VOICE: str = "en-US-GuyNeural"
    TTS_VOLUME: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"

    # Morning routine — weather comes from NWS (api.weather.gov, no API
    # key needed); the OpenWeather setting from before that switch was
    # removed 2026-05-05 (audit). Don't re-add without a use case.
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

    # Guest WiFi — surfaces a QR on the dashboard and /guest landing page.
    # When SSID/password are empty, the widget renders a "not configured"
    # state and the /api/guest/wifi route returns {configured: false}.
    GUEST_WIFI_SSID: str = ""
    GUEST_WIFI_PASSWORD: str = ""
    GUEST_WIFI_SECURITY: str = "WPA"  # WPA | WEP | nopass

    # Pi-hole DNS ad blocker (optional — enables network stats widget)
    PIHOLE_API_URL: Optional[str] = None
    PIHOLE_API_KEY: Optional[str] = None

    # Fauxmo Alexa integration (Phase 3 voice control)
    FAUXMO_ENABLED: bool = False

    # API-key auth on write endpoints. External/non-bypassed callers need a
    # matching X-API-Key; localhost, configured TRUSTED_LAN_IPS, and private
    # addresses use require_api_key()'s ordinary bypass. See backend/api/auth.py.
    HOME_HUB_API_KEY: Optional[str] = None
    # Comma-separated additional IPs that bypass X-API-Key. Private/LAN
    # addresses are already covered by require_api_key()'s ordinary bypass.
    TRUSTED_LAN_IPS: str = ""

    # Custom Alexa Skill — separate secret from HOME_HUB_API_KEY
    # so the Skill can be rotated independently. Required on tunneled
    # callers (X-Tunnel-Origin: cloudflare); ignored everywhere else.
    HOME_HUB_SKILL_TOKEN: Optional[str] = None

    # Legacy/dormant zone+posture → relax setting pending #80. Retained for
    # compatibility; it does not indicate an active bed-zone capability.
    ZONE_POSTURE_RULE_APPLY: bool = True

    # #198 shadow-only camera challenger harness. Disabled by default.
    CAMERA_SHADOW_BAKEOFF_ENABLED: bool = False
    CAMERA_SHADOW_YOLO_ENABLED: bool = False
    CAMERA_SHADOW_YOLO_MODEL_PATH: str = ""
    CAMERA_SHADOW_YOLO_PERSON_CONFIDENCE: float = 0.05
    CAMERA_SHADOW_YOLO_KEYPOINT_CONFIDENCE: float = 0.25
    CAMERA_SHADOW_CAPTURE_LABEL: str = ""
    CAMERA_SHADOW_CAPTURE_DIR: str = "/tmp/homehub-camera-shadow"
    CAMERA_SHADOW_CAPTURE_MAX_RECORDS: int = 1000


    # Promoted #198 Latitude person-authority path. Disabled until an explicit
    # production rollout supplies the validated OpenVINO model artifact.
    CAMERA_YOLO_AUTHORITY_ENABLED: bool = False
    CAMERA_YOLO_AUTHORITY_MODEL_PATH: str = ""
    CAMERA_YOLO_AUTHORITY_PERSON_CONFIDENCE: float = 0.25
    CAMERA_YOLO_AUTHORITY_BLINDED_CONFIDENCE: float = 0.01
    CAMERA_YOLO_AUTHORITY_PRESENT_DWELL_FRAMES: int = 3

    # First #129/#130 living-room atmosphere slice. Default false keeps the
    # accepted implementation observable but does not change production Hue
    # behavior until the palette has been reviewed and rollout is explicit.
    LIVING_ROOM_ATMOSPHERE_ENABLED: bool = False

    # Sentry error reporting — DSN from sentry.io project. When unset,
    # sentry_sdk.init() is called with dsn=None which silently disables
    # ingestion (no events sent). Free tier = 10k events/month.
    SENTRY_DSN: Optional[str] = None

    # NotifierService — pushes "what just changed and why" to desktop +
    # phone. NTFY_TOPIC doubles as the auth boundary on the hosted ntfy.sh
    # service (anyone subscribed to the topic name gets the messages), so
    # treat it like an API key. When unset, the service still broadcasts
    # the "notification" WS event (desktop toast works), but skips the
    # phone push. NTFY_SERVER lets us point at a self-hosted instance
    # later without code changes.
    NTFY_TOPIC: Optional[str] = None
    NTFY_SERVER: str = "https://ntfy.sh"

    # Bounded auto-remediation (source-trust watchdog). Two-stage kill-switch:
    # REMEDIATION_ENABLED gates the whole subsystem (status endpoint + audit
    # log); REMEDIATION_AUTONOMOUS additionally permits the remediator agent to
    # *execute* whitelisted fixes. With ENABLED=true + AUTONOMOUS=false the
    # remediator runs propose-only: it records what it *would* do and notifies,
    # but mutates nothing. Ship propose-only; flip to autonomous per-action only
    # after the audit log shows clean proposals. Both default false → the
    # subsystem is inert until explicitly turned on.
    REMEDIATION_ENABLED: bool = False
    REMEDIATION_AUTONOMOUS: bool = False
    # Rate ceilings so a misfiring policy can't storm the apartment: at most N
    # auto-executed fixes per rolling 24h, and a per-action cooldown (seconds)
    # so the same fix can't repeat in a tight loop (mirrors the celebration
    # cooldown + rule-refractory patterns).
    REMEDIATION_MAX_AUTO_PER_DAY: int = 6
    REMEDIATION_ACTION_COOLDOWN_SECONDS: int = 1800

    # Game Day
    OPENAI_API_KEY: Optional[str] = None
    # AI Personality Layer Phase C - backend-side free-form vibe parser.
    # Deterministic phrase rules run first; Anthropic is only used for
    # ambiguous requests such as "set something low-key but social".
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-haiku-20240307"
    ESPN_POLL_INTERVAL: int = 5
    BIG_PLAY_YARD_THRESHOLD: int = 20
    FIELD_GOAL_YARD_THRESHOLD: int = 40
    MOMENTUM_WPA_THRESHOLD: float = 0.15  # |WPA| swing that fires a momentum celebration on non-scoring plays

    @property
    def trusted_lan_ips_set(self) -> frozenset[str]:
        """Parsed view of TRUSTED_LAN_IPS as a frozenset for membership checks."""
        return frozenset(
            ip.strip() for ip in self.TRUSTED_LAN_IPS.split(",") if ip.strip()
        )


settings = Settings()
