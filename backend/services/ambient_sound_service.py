"""
Ambient Sound Service — browser-based ambient audio orchestration.

Manages which ambient sound should be playing (rain, fireplace, etc.) and
broadcasts state to the frontend via WebSocket. Actual audio playback happens
in the browser using HTML5 Audio API — this service is the state authority.

Reacts to mode changes (registered as mode-change callback) and weather
conditions (uses cached WeatherService data). Config is persisted to the
app_settings table.
"""
import logging
from pathlib import Path
from typing import Any, Optional

from backend.config import STATIC_DIR

logger = logging.getLogger("home_hub.ambient")

AMBIENT_DIR = STATIC_DIR / "ambient"
AUDIO_EXTENSIONS = frozenset((".mp3", ".ogg", ".wav", ".webm"))
AMBIENT_CONFIG_KEY = "ambient_config"

# Weather description keywords → sound filename stem.
# If the user has e.g. "rain.mp3" in static/ambient/ and the weather
# description contains "rain", it auto-plays.
WEATHER_SOUND_MAP: dict[str, list[str]] = {
    "rain": ["rain", "drizzle", "shower"],
    "thunderstorm": ["thunderstorm", "thunder"],
    "snow": ["snow", "sleet"],
    "wind": ["wind", "gale", "breeze"],
}


def _label_from_filename(filename: str) -> str:
    """Derive a display label from a filename: 'coffee-shop.mp3' → 'Coffee Shop'."""
    stem = Path(filename).stem
    return stem.replace("-", " ").replace("_", " ").title()


class AmbientSoundService:
    """Orchestrates ambient audio state and broadcasts to frontend clients."""

    def __init__(
        self,
        ws_manager: Any,
        weather_service: Any = None,
    ) -> None:
        self._ws_manager = ws_manager
        self._weather_service = weather_service

        # Runtime state
        self._current_sound: Optional[str] = None
        self._playing: bool = False
        self._volume: float = 0.3
        self._source: str = "manual"
        self._weather_override_active: bool = False

        # Config (loaded from DB)
        self._mode_sounds: dict[str, str] = {}
        self._mode_auto_play: dict[str, bool] = {}
        self._weather_reactive: bool = True

        # Available sounds (populated by scan_sounds)
        self._available_sounds: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Load persisted config from app_settings."""
        from backend.api.routes.routines import load_setting

        config = await load_setting(AMBIENT_CONFIG_KEY)
        if not config:
            return

        self._volume = config.get("volume", 0.3)
        self._mode_sounds = config.get("mode_sounds", {})
        self._mode_auto_play = config.get("mode_auto_play", {})
        self._weather_reactive = config.get("weather_reactive", True)
        self._current_sound = config.get("last_sound")
        self._playing = config.get("last_playing", False)
        if self._playing and self._current_sound:
            self._source = config.get("last_source", "manual")
        logger.info(
            "Ambient config loaded: volume=%.1f, weather=%s, mappings=%d",
            self._volume, self._weather_reactive, len(self._mode_sounds),
        )

    def scan_sounds(self) -> list[dict[str, str]]:
        """Scan static/ambient/ for audio files. Returns [{filename, label}]."""
        AMBIENT_DIR.mkdir(parents=True, exist_ok=True)
        sounds = []
        for path in sorted(AMBIENT_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                sounds.append({
                    "filename": path.name,
                    "label": _label_from_filename(path.name),
                })
        self._available_sounds = sounds
        logger.info("Scanned %d ambient sound files", len(sounds))
        return sounds

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        """Return full current state for REST / WebSocket init."""
        return {
            "playing": self._playing,
            "sound": self._current_sound,
            "sound_label": (
                _label_from_filename(self._current_sound)
                if self._current_sound else None
            ),
            "volume": self._volume,
            "source": self._source,
            "weather_override": self._weather_override_active,
            "available_sounds": self._available_sounds,
            "mode_sounds": self._mode_sounds,
            "mode_auto_play": self._mode_auto_play,
            "weather_reactive": self._weather_reactive,
        }

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    async def play(self, filename: str, source: str = "manual") -> dict[str, Any]:
        """Set the active sound and broadcast."""
        if not self._file_exists(filename):
            return {"status": "error", "detail": f"File not found: {filename}"}

        self._current_sound = filename
        self._playing = True
        self._source = source
        self._weather_override_active = source == "weather"
        await self._broadcast_state()
        await self._save_config()
        logger.info("Ambient play: %s (source=%s)", filename, source)
        return {"status": "ok"}

    async def pause(self) -> dict[str, Any]:
        """Pause playback."""
        self._playing = False
        await self._broadcast_state()
        await self._save_config()
        logger.info("Ambient paused")
        return {"status": "ok"}

    async def resume(self) -> dict[str, Any]:
        """Resume playback."""
        if not self._current_sound:
            return {"status": "error", "detail": "No sound to resume"}
        self._playing = True
        await self._broadcast_state()
        await self._save_config()
        logger.info("Ambient resumed: %s", self._current_sound)
        return {"status": "ok"}

    async def stop(self) -> dict[str, Any]:
        """Stop and clear current sound."""
        self._current_sound = None
        self._playing = False
        self._source = "manual"
        self._weather_override_active = False
        await self._broadcast_state()
        await self._save_config()
        logger.info("Ambient stopped")
        return {"status": "ok"}

    async def set_volume(self, volume: float) -> dict[str, Any]:
        """Set volume (0.0-1.0), persist, broadcast."""
        self._volume = max(0.0, min(1.0, volume))
        await self._broadcast_state()
        await self._save_config()
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    async def update_config(
        self,
        mode_sounds: Optional[dict[str, Optional[str]]] = None,
        mode_auto_play: Optional[dict[str, bool]] = None,
        weather_reactive: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Update ambient config. Partial updates supported."""
        if mode_sounds is not None:
            for mode, filename in mode_sounds.items():
                if filename is None:
                    self._mode_sounds.pop(mode, None)
                else:
                    self._mode_sounds[mode] = filename
        if mode_auto_play is not None:
            self._mode_auto_play.update(mode_auto_play)
        if weather_reactive is not None:
            self._weather_reactive = weather_reactive

        await self._save_config()
        await self._broadcast_state()
        logger.info("Ambient config updated")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Mode-change callback
    # ------------------------------------------------------------------

    async def on_mode_change_wrapper(self, mode: str) -> None:
        """Thin wrapper for automation.register_on_mode_change."""
        await self.on_mode_change(mode)

    async def on_mode_change(self, mode: str) -> None:
        """React to mode change: check weather first, then mode mapping."""
        if not self._available_sounds:
            return

        # Weather-reactive takes priority
        if self._weather_reactive:
            weather_sound = self._check_weather()
            if weather_sound:
                if weather_sound != self._current_sound or not self._playing:
                    await self.play(weather_sound, source="weather")
                return

        # Clear weather override if weather no longer matches
        if self._weather_override_active:
            self._weather_override_active = False

        # Check mode mapping
        mapped_sound = self._mode_sounds.get(mode)
        auto_play = self._mode_auto_play.get(mode, False)

        if mapped_sound and auto_play and self._file_exists(mapped_sound):
            if mapped_sound != self._current_sound or not self._playing:
                await self.play(mapped_sound, source="mode")
        # Don't stop manually-chosen sounds on mode change

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------

    def _check_weather(self) -> Optional[str]:
        """Check cached weather, return matching sound filename or None."""
        if not self._weather_service:
            return None

        try:
            weather = self._weather_service.get_cached()
            if not weather:
                return None
        except Exception:
            return None

        description = weather.get("description", "").lower()

        for sound_stem, keywords in WEATHER_SOUND_MAP.items():
            if any(kw in description for kw in keywords):
                # Find matching file in available sounds
                for s in self._available_sounds:
                    if s["filename"].lower().startswith(sound_stem):
                        return s["filename"]
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_exists(self, filename: str) -> bool:
        """Check if a sound file exists in the ambient directory."""
        return any(s["filename"] == filename for s in self._available_sounds)

    async def _broadcast_state(self) -> None:
        """Broadcast current state via WebSocket."""
        await self._ws_manager.broadcast("ambient_update", self.get_state())

    async def _save_config(self) -> None:
        """Persist config + playback state to app_settings."""
        from backend.api.routes.routines import save_setting

        await save_setting(AMBIENT_CONFIG_KEY, {
            "volume": self._volume,
            "mode_sounds": self._mode_sounds,
            "mode_auto_play": self._mode_auto_play,
            "weather_reactive": self._weather_reactive,
            "last_sound": self._current_sound,
            "last_playing": self._playing,
            "last_source": self._source,
        })
