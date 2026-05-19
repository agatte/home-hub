"""
Ambient Sound Service — browser-based ambient audio orchestration.

Manages which ambient sound should be playing (rain, fireplace, etc.) and
broadcasts state to the frontend via WebSocket. Actual audio playback happens
in the browser using HTML5 Audio API — this service is the state authority.

Reacts to mode changes (registered as mode-change callback) and weather
conditions (uses cached WeatherService data). Config is persisted to the
app_settings table.

Optionally mirrors active ambient sounds to the Sonos speaker at low volume
when mode is not gaming/working/watching/sleeping/gameday. A follow-me volume
loop ramps Sonos volume up when the camera detects absence (user in
kitchen/bathroom) and back down on return.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Optional

from backend.config import DATA_DIR, STATIC_DIR

logger = logging.getLogger("home_hub.ambient")

# Short-loop fallbacks (committed to the repo): backend/static/ambient/
# Long-form user-curated MP3s (gitignored): data/ambient/
#
# Scan order = priority — same-name files in DATA dir override committed ones.
# Filenames containing WEATHER_SOUND_MAP keywords (rain, thunderstorm, snow,
# wind) auto-trigger on matching weather, so a long-form "rain.mp3" replaces
# the 2-min loop seamlessly.
SHORT_AMBIENT_DIR = STATIC_DIR / "ambient"
LONG_AMBIENT_DIR = DATA_DIR / "ambient"
SCAN_DIRS: tuple[tuple[Path, str], ...] = (
    (LONG_AMBIENT_DIR, "/static/ambient-long"),  # user-curated, wins on collision
    (SHORT_AMBIENT_DIR, "/static/ambient"),      # short fallbacks, committed
)
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

# Modes where ambient is fully suppressed (both Sonos and browser).
# Watching has its own audio (projector / TV); gameday is celebration-exclusive
# on the Sonos; sleeping is silent. Other "active" modes (working, gaming,
# relax, cooking, idle, social) all allow ambient — Sonos is the primary
# surface, per-mode volume overrides keep gaming at a low background level.
SUPPRESSED_MODES: frozenset[str] = frozenset({"watching", "gameday", "sleeping"})

# Backward-compat alias for any caller still referring to the old name.
# Sonos eligibility uses the same set as the browser block — the surface
# distinction is owned by `sonos_enabled`, not by per-mode policy.
SONOS_BLOCKED_MODES = SUPPRESSED_MODES


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
        sonos: Any = None,
    ) -> None:
        self._ws_manager = ws_manager
        self._weather_service = weather_service
        self._sonos = sonos

        # Late-bound via setters (post-construction DI, set in bootstrap)
        self._camera: Any = None
        self._automation: Any = None

        # Runtime state
        self._current_sound: Optional[str] = None
        self._playing: bool = False
        self._volume: float = 0.3
        self._source: str = "manual"
        self._weather_override_active: bool = False

        # Sonos ambient runtime state
        self._sonos_ambient_active: bool = False
        self._sonos_ambient_uri: Optional[str] = None
        self._sonos_loop_task: Optional[asyncio.Task] = None
        self._sonos_absent_since: Optional[float] = None   # monotonic time
        self._sonos_present_since: Optional[float] = None  # monotonic time
        # Strong references for fire-and-forget Sonos start/pause tasks.
        # asyncio.create_task only weak-refs the task; without holding a
        # strong ref the GC can drop a still-running task, firing the
        # "Task was destroyed but it is pending!" warning (the HOME-HUB-P
        # class of bug). Discard callback prevents unbounded growth.
        self._pending_sonos_tasks: set[asyncio.Task] = set()

        # Config (loaded from DB)
        self._mode_sounds: dict[str, str] = {}
        self._mode_auto_play: dict[str, bool] = {}
        self._weather_reactive: bool = True

        # Sonos config (persisted to DB). Defaults calibrated 2026-05-18 for
        # the cross-room geometry of Anthony's apartment (Sonos in living
        # room, desk in bedroom) — see memory project_sonos_location_and_
        # ambient_volumes. Same-room installs can override down to ~12/18
        # via /settings; these defaults err on the audible side because
        # silence-by-default is worse than too-loud-by-default for a
        # weather-reactive ambient layer.
        self._sonos_enabled: bool = True
        self._sonos_present_volume: int = 25  # Sonos level when user is nearby
        self._sonos_away_volume: int = 35     # Sonos level when user is away
        # Per-mode Sonos volume overrides. Missing modes fall back to
        # _sonos_present_volume. Used in _resolve_sonos_volume(mode) so a
        # gaming-mode override of e.g. 6 plays rain at near-background level
        # while relax-mode 14 plays fireplace louder. Both the initial
        # _start_sonos_ambient call and the camera-driven follow-me ramp
        # consult this map.
        self._sonos_mode_volume_overrides: dict[str, int] = {}

        # Weather-watch loop bookkeeping. _last_weather_class is the most
        # recently classified weather (rain/thunderstorm/snow/wind/None);
        # watch loop only fires _evaluate() when it actually changes so we
        # don't churn on identical-class re-reads of the cached NWS data.
        self._last_weather_class: Optional[str] = None

        # Available sounds (populated by scan_sounds)
        # _sound_index maps filename → {url_prefix, abs_path, label, source_dir}
        # _available_sounds is the legacy [{filename, label}] list rebuilt
        # from _sound_index for backwards-compatible state payloads.
        self._sound_index: dict[str, dict[str, str]] = {}
        self._available_sounds: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Load persisted config from app_settings, seeding defaults on first run."""
        from backend.api.routes.routines import load_setting

        config = await load_setting(AMBIENT_CONFIG_KEY) or {}

        self._volume = config.get("volume", 0.3)
        self._mode_sounds = dict(config.get("mode_sounds", {}))
        self._mode_auto_play = dict(config.get("mode_auto_play", {}))
        self._weather_reactive = config.get("weather_reactive", True)
        self._current_sound = config.get("last_sound")
        self._playing = config.get("last_playing", False)
        if self._playing and self._current_sound:
            self._source = config.get("last_source", "manual")
        self._sonos_enabled = config.get("sonos_enabled", True)
        self._sonos_present_volume = config.get("sonos_present_volume", 25)
        self._sonos_away_volume = config.get("sonos_away_volume", 35)
        self._sonos_mode_volume_overrides = dict(
            config.get("sonos_mode_volume_overrides", {})
        )

        # First-boot defaults — only when truly empty so we don't clobber
        # user-edited config on subsequent restarts. Relax → fireplace is the
        # one mode default we ship; weather-reactive ambient covers
        # working/gaming/cooking organically without forcing a sound when
        # weather is clear.
        seeded = False
        if not self._mode_sounds:
            self._mode_sounds = {"relax": "fireplace.mp3"}
            seeded = True
        if "relax" not in self._mode_auto_play:
            self._mode_auto_play["relax"] = True
            seeded = True
        if seeded:
            await self._save_config()
            logger.info(
                "Ambient defaults seeded: %s",
                {k: v for k, v in self._mode_sounds.items()},
            )

        logger.info(
            "Ambient config loaded: volume=%.1f, weather=%s, mappings=%d, "
            "sonos_enabled=%s",
            self._volume, self._weather_reactive, len(self._mode_sounds),
            self._sonos_enabled,
        )

    def set_camera_service(self, camera: Any) -> None:
        """Late-bind camera service (called from bootstrap after camera starts)."""
        self._camera = camera

    def set_automation(self, automation: Any) -> None:
        """Late-bind automation engine (called from bootstrap after engine created)."""
        self._automation = automation

    def scan_sounds(self) -> list[dict[str, str]]:
        """Scan both ambient dirs for audio files. Returns [{filename, label}].

        Walks SCAN_DIRS in priority order (data/ambient/ first); same-name
        files in a later directory are shadowed and logged at debug. Missing
        directories are skipped silently (data/ambient/ is gitignored and may
        not exist on a fresh checkout).
        """
        # Ensure the short-fallback dir exists (matches legacy mkdir behavior).
        SHORT_AMBIENT_DIR.mkdir(parents=True, exist_ok=True)

        index: dict[str, dict[str, str]] = {}
        for scan_dir, url_prefix in SCAN_DIRS:
            if not scan_dir.is_dir():
                continue
            for path in sorted(scan_dir.iterdir()):
                if not (path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS):
                    continue
                if path.name in index:
                    logger.debug(
                        "Ambient scan: %s in %s shadowed by %s",
                        path.name, scan_dir, index[path.name]["source_dir"],
                    )
                    continue
                index[path.name] = {
                    "url_prefix": url_prefix,
                    "abs_path": str(path),
                    "label": _label_from_filename(path.name),
                    "source_dir": str(scan_dir),
                }

        self._sound_index = index
        self._available_sounds = [
            {"filename": filename, "label": entry["label"]}
            for filename, entry in index.items()
        ]
        long_count = sum(
            1 for e in index.values() if e["url_prefix"] == "/static/ambient-long"
        )
        logger.info(
            "Scanned %d ambient sound files (%d long-form, %d short)",
            len(index), long_count, len(index) - long_count,
        )
        return self._available_sounds

    def _url_for(self, filename: str, *, absolute: bool = False) -> Optional[str]:
        """Resolve a filename to its URL.

        absolute=True returns ``http://{LOCAL_IP}:8000{prefix}/{filename}``
        for Sonos. absolute=False returns just ``{prefix}/{filename}`` for
        browser-side broadcast. Returns None if the filename isn't indexed.
        """
        entry = self._sound_index.get(filename)
        if entry is None:
            return None
        prefix = entry["url_prefix"]
        if absolute:
            from backend.config import settings
            return f"http://{settings.LOCAL_IP}:8000{prefix}/{filename}"
        return f"{prefix}/{filename}"

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        """Return full current state for REST / WebSocket init."""
        return {
            "playing": self._playing,
            "sound": self._current_sound,
            "sound_url": (
                self._url_for(self._current_sound)
                if self._current_sound else None
            ),
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
            "sonos_enabled": self._sonos_enabled,
            "sonos_ambient_active": self._sonos_ambient_active,
            "sonos_present_volume": self._sonos_present_volume,
            "sonos_away_volume": self._sonos_away_volume,
            "sonos_mode_volume_overrides": self._sonos_mode_volume_overrides,
            "suppressed_modes": sorted(SUPPRESSED_MODES),
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
        if self._sonos:
            if not self._sonos_ambient_active:
                self._spawn_sonos_task(self._start_sonos_ambient())
            else:
                # Already mirroring — swap the URI in place so weather
                # transitions (rain → thunderstorm) don't leave Sonos
                # stuck on the old file while the browser shows the new one.
                expected_uri = self._url_for(filename, absolute=True)
                if expected_uri and expected_uri != self._sonos_ambient_uri:
                    self._spawn_sonos_task(self._swap_sonos_ambient(filename))
        return {"status": "ok"}

    def _spawn_sonos_task(self, coro: Awaitable[Any]) -> None:
        """Track a fire-and-forget Sonos coroutine so the GC can't drop it."""
        task = asyncio.create_task(coro)
        self._pending_sonos_tasks.add(task)
        task.add_done_callback(self._pending_sonos_tasks.discard)

    async def pause(self) -> dict[str, Any]:
        """Pause playback."""
        self._playing = False
        await self._broadcast_state()
        await self._save_config()
        self._stop_sonos_ambient()
        logger.info("Ambient paused")
        return {"status": "ok"}

    async def resume(self) -> dict[str, Any]:
        """Resume playback."""
        if not self._current_sound:
            return {"status": "error", "detail": "No sound to resume"}
        self._playing = True
        await self._broadcast_state()
        await self._save_config()
        # pause() stops the Sonos mirror; resume should bring it back so
        # the "Sonos primary" model stays consistent across the pause/play cycle.
        if self._sonos and not self._sonos_ambient_active:
            self._spawn_sonos_task(self._start_sonos_ambient())
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
        self._stop_sonos_ambient()
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
        sonos_enabled: Optional[bool] = None,
        sonos_present_volume: Optional[int] = None,
        sonos_away_volume: Optional[int] = None,
        sonos_mode_volume_overrides: Optional[dict[str, Optional[int]]] = None,
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

        sonos_changed = False
        if sonos_enabled is not None:
            self._sonos_enabled = bool(sonos_enabled)
            sonos_changed = True
        if sonos_present_volume is not None:
            self._sonos_present_volume = max(0, min(60, int(sonos_present_volume)))
            sonos_changed = True
        if sonos_away_volume is not None:
            self._sonos_away_volume = max(0, min(60, int(sonos_away_volume)))
            sonos_changed = True
        if sonos_mode_volume_overrides is not None:
            for mode, vol in sonos_mode_volume_overrides.items():
                if vol is None:
                    self._sonos_mode_volume_overrides.pop(mode, None)
                else:
                    self._sonos_mode_volume_overrides[mode] = max(0, min(60, int(vol)))
            sonos_changed = True

        # If the toggle just flipped off and Sonos was mirroring, stop it.
        # Re-evaluate so the browser surface picks up where Sonos left off.
        if sonos_changed and not self._sonos_enabled and self._sonos_ambient_active:
            self._stop_sonos_ambient()

        await self._save_config()
        await self._broadcast_state()
        # Volume / enable changes warrant re-evaluating so the new policy
        # takes effect immediately on the active sound.
        if sonos_changed:
            await self._evaluate()
        logger.info("Ambient config updated")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Mode-change callback
    # ------------------------------------------------------------------

    async def on_mode_change_wrapper(self, mode: str) -> None:
        """Thin wrapper for automation.register_on_mode_change."""
        await self.on_mode_change(mode)

    async def on_mode_change(self, mode: str) -> None:
        """React to mode change. Delegates to the central evaluator."""
        await self._evaluate(mode)

    async def _evaluate(self, mode: Optional[str] = None) -> None:
        """Central priority chain — weather > mode mapping > existing state.

        Single entry point so the mode-change callback and the weather-watch
        loop produce identical behavior. Both surfaces (Sonos + browser)
        consume the broadcast `playing` / `sound` fields so the choice of
        what's playing is made in exactly one place.
        """
        if mode is None and self._automation is not None:
            mode = getattr(self._automation, "current_mode", None)
        if not self._available_sounds:
            return

        # Hard-blocked modes — silence both surfaces. We pause rather than
        # stop so _current_sound/_source survive for the next _evaluate
        # when the mode opens back up.
        if mode in SUPPRESSED_MODES:
            if self._playing or self._sonos_ambient_active:
                await self.pause()
            return

        weather_sound = self._check_weather() if self._weather_reactive else None

        mode_sound = None
        if mode is not None:
            mapped = self._mode_sounds.get(mode)
            auto_play = self._mode_auto_play.get(mode, False)
            if mapped and auto_play and self._file_exists(mapped):
                mode_sound = mapped

        if weather_sound:
            target, target_source = weather_sound, "weather"
        elif mode_sound:
            target, target_source = mode_sound, "mode"
        else:
            target, target_source = None, None

        if target:
            need_play = (
                target != self._current_sound
                or not self._playing
                or self._source != target_source
            )
            if need_play:
                await self.play(target, source=target_source)
            elif self._sonos_ambient_active:
                # Same target, already mirroring. Mode shift or volume-config
                # change could mean the resolved Sonos volume is now different
                # from what's actually playing — push it through. This is what
                # makes the /settings sliders feel live instead of "saved but
                # nothing happens" (and what keeps mode-change volume policy
                # honest when mode changes but ambient sticks).
                await self._sync_sonos_volume()
            return

        # No active driver. Stop weather/mode-driven playback so the rain
        # sound doesn't outlive the storm; manual selections persist.
        if self._playing and self._source in ("weather", "mode"):
            await self.pause()
            if self._weather_override_active:
                self._weather_override_active = False
                await self._broadcast_state()

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------

    def _classify_weather(self) -> Optional[str]:
        """Classify cached weather into a sound-stem class or None.

        Returns one of WEATHER_SOUND_MAP's keys (rain/thunderstorm/snow/wind)
        if the cached description matches any of that class's keywords;
        otherwise None. Used by weather_watch_loop as a cheap change-detector
        before calling the full _evaluate().
        """
        if not self._weather_service:
            return None
        try:
            weather = self._weather_service.get_cached()
        except Exception:
            return None
        if not weather:
            return None

        description = weather.get("description", "").lower()
        for sound_stem, keywords in WEATHER_SOUND_MAP.items():
            if any(kw in description for kw in keywords):
                return sound_stem
        return None

    def _check_weather(self) -> Optional[str]:
        """Resolve current weather class to a concrete sound filename."""
        wclass = self._classify_weather()
        if not wclass:
            return None
        for s in self._available_sounds:
            if s["filename"].lower().startswith(wclass):
                return s["filename"]
        return None

    async def weather_watch_loop(self) -> None:
        """Background poll: re-evaluate ambient when weather class changes.

        Cached NWS data refreshes on its own 5-min TTL; this loop reads the
        cache, not the API, so the cadence is cheap. The first tick fires
        ~5s after startup so the initial _evaluate runs after Sonos + the
        automation engine have settled — that's what re-arms playback after
        a deploy with persisted `last_playing=True`.
        """
        POLL_INTERVAL = 60.0
        FIRST_TICK_DELAY = 5.0

        try:
            await asyncio.sleep(FIRST_TICK_DELAY)
        except asyncio.CancelledError:
            raise

        try:
            self._last_weather_class = self._classify_weather()
            await self._evaluate()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Initial ambient evaluate failed")

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                wclass = self._classify_weather()
                if wclass != self._last_weather_class:
                    logger.info(
                        "Ambient: weather class %s -> %s, re-evaluating",
                        self._last_weather_class, wclass,
                    )
                    self._last_weather_class = wclass
                    await self._evaluate()
            except asyncio.CancelledError:
                logger.info("Weather watch loop cancelled")
                raise
            except Exception:
                logger.exception("Weather watch loop iteration failed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_exists(self, filename: str) -> bool:
        """Check if a sound file is indexed (present in either scan dir)."""
        return filename in self._sound_index

    async def _broadcast_state(self) -> None:
        """Broadcast current state via WebSocket."""
        await self._ws_manager.broadcast("ambient_update", self.get_state())

    # ------------------------------------------------------------------
    # Sonos ambient helpers
    # ------------------------------------------------------------------

    def _sonos_eligible(self) -> bool:
        """True when Sonos ambient is allowed in the current mode."""
        if not self._sonos_enabled:
            return False
        mode = getattr(self._automation, "current_mode", None)
        return mode not in SONOS_BLOCKED_MODES if mode else True

    def _current_mode(self) -> Optional[str]:
        """Read the engine's current mode for per-mode volume / eligibility."""
        if self._automation is None:
            return None
        return getattr(self._automation, "current_mode", None)

    def _resolve_sonos_volume(self, mode: Optional[str] = None) -> int:
        """Pick the Sonos volume for the given mode (overrides win)."""
        if mode is None:
            mode = self._current_mode()
        if mode and mode in self._sonos_mode_volume_overrides:
            return self._sonos_mode_volume_overrides[mode]
        return self._sonos_present_volume

    async def _sync_sonos_volume(self) -> None:
        """Re-apply the resolved Sonos volume to a currently-playing track.

        The original follow-me loop only ramps DOWN (absent → present); it
        never ramps UP from a lower present_volume to a higher new override.
        And mid-mirror config changes via /api/ambient/config (slider drag in
        /settings) only updated state, never the Sonos. This helper closes
        both gaps — call after any policy change that could affect resolved
        volume.
        """
        if not self._sonos_ambient_active or not self._sonos:
            return
        if not getattr(self._sonos, "connected", False):
            return
        target = self._resolve_sonos_volume()
        try:
            status = await self._sonos.get_status()
        except Exception as e:
            logger.warning("Sonos ambient volume sync: get_status failed: %s", e)
            return
        current = int(status.get("volume", target))
        if current == target:
            return
        try:
            await self._sonos.ramp_volume(target, steps=4, interval=0.3)
            logger.info(
                "Sonos ambient volume synced %d -> %d (mode=%s)",
                current, target, self._current_mode(),
            )
        except Exception as e:
            logger.warning("Sonos ambient volume sync: ramp failed: %s", e)

    async def _start_sonos_ambient(self) -> None:
        """Start Sonos ambient if eligible + Sonos idle + ambient playing.

        Conditions checked in order:
          1. Not already active + mode is eligible.
          2. Sonos connected.
          3. Sonos currently idle (STOPPED or PAUSED_PLAYBACK).
          4. Browser ambient is actively playing.
        """
        if self._sonos_ambient_active:
            return
        if not self._sonos_eligible():
            return
        if not getattr(self._sonos, "connected", False):
            return
        if not self._playing or not self._current_sound:
            return
        try:
            status = await self._sonos.get_status()
        except Exception as e:
            logger.warning("Sonos ambient: could not read status: %s", e)
            return
        if status.get("state") not in ("STOPPED", "PAUSED_PLAYBACK"):
            logger.debug(
                "Sonos ambient: Sonos busy (state=%s), skipping",
                status.get("state"),
            )
            return

        uri = self._url_for(self._current_sound, absolute=True)
        if not uri:
            logger.warning(
                "Sonos ambient: %s no longer indexed, aborting",
                self._current_sound,
            )
            return
        mode = self._current_mode()
        start_volume = self._resolve_sonos_volume(mode)
        success = await self._sonos.play_uri(uri, volume=start_volume)
        if not success:
            logger.warning("Sonos ambient: play_uri failed for %s", uri)
            return

        self._sonos_ambient_active = True
        self._sonos_ambient_uri = uri
        self._sonos_absent_since = None
        self._sonos_present_since = None
        self._sonos_loop_task = asyncio.create_task(
            self._sonos_ambient_loop(), name="sonos_ambient_loop"
        )
        logger.info(
            "Sonos ambient started: %s at volume %d (mode=%s)",
            self._current_sound, start_volume, mode,
        )
        # Re-broadcast so frontends see sonos_ambient_active=true and silence
        # their per-tab audio. Without this the gate in ambientAudio.js
        # wouldn't fire until the next play()/pause() cycle.
        await self._broadcast_state()

    def _stop_sonos_ambient(self) -> None:
        """Cancel ambient loop and pause Sonos. Sync — fire-and-forget pause."""
        if self._sonos_loop_task and not self._sonos_loop_task.done():
            self._sonos_loop_task.cancel()
        self._sonos_loop_task = None
        self._sonos_ambient_active = False
        self._sonos_ambient_uri = None
        self._sonos_absent_since = None
        self._sonos_present_since = None
        if self._sonos and getattr(self._sonos, "connected", False):
            self._spawn_sonos_task(self._sonos.pause())
        logger.info("Sonos ambient stopped")

    async def _swap_sonos_ambient(self, filename: str) -> None:
        """Replace the currently-playing Sonos URI without tearing down the loop.

        Called when the active sound changes mid-mirror (weather class
        transition, manual file pick while Sonos is playing). The loop's
        track-end re-play branch already uses self._sonos_ambient_uri, so
        updating that pointer here is sufficient for future restart cycles.
        """
        if not self._sonos_ambient_active or not self._sonos:
            return
        if not self._sonos_eligible():
            return
        uri = self._url_for(filename, absolute=True)
        if not uri:
            logger.warning(
                "Sonos ambient swap: %s no longer indexed, leaving prior URI",
                filename,
            )
            return
        mode = self._current_mode()
        vol = self._resolve_sonos_volume(mode)
        try:
            success = await self._sonos.play_uri(uri, volume=vol)
        except Exception as e:
            logger.warning("Sonos ambient swap: play_uri error: %s", e)
            return
        if success:
            # Re-check post-await: an interleaved _stop_sonos_ambient() (e.g.
            # mode flipped to a suppressed mode mid-swap) clears
            # _sonos_ambient_active and _sonos_ambient_uri. Writing the
            # pointer here would leave a non-None uri with active=False
            # and the swap track would bleed through to its natural end.
            if not self._sonos_ambient_active:
                logger.info(
                    "Sonos ambient swap: cancelled mid-flight, pausing"
                )
                try:
                    await self._sonos.pause()
                except Exception:
                    pass
                return
            self._sonos_ambient_uri = uri
            logger.info(
                "Sonos ambient swapped to %s at volume %d (mode=%s)",
                filename, vol, mode,
            )

    async def _sonos_ambient_loop(self) -> None:
        """Background task: re-play on track end, follow-me volume via camera.

        Runs every 5s. Re-plays the ambient URI when Sonos hits STOPPED
        (end-of-file), simulating a loop. Ramps Sonos volume up after 8s
        sustained camera absence (user in kitchen/bathroom) and back down
        after 4s of detected presence.
        """

        LOOP_INTERVAL = 5.0
        ABSENT_RAMP_SECONDS = 8.0
        PRESENT_RAMP_SECONDS = 4.0

        try:
            while True:
                await asyncio.sleep(LOOP_INTERVAL)
                if not self._sonos_ambient_active or not self._playing:
                    self._stop_sonos_ambient()
                    break

                try:
                    status = await self._sonos.get_status()
                except Exception as e:
                    logger.warning("Sonos ambient loop: get_status error: %s", e)
                    continue

                sonos_state = status.get("state", "")

                mode = self._current_mode()
                present_volume = self._resolve_sonos_volume(mode)

                # Re-play when track ends or is paused (e.g. post-TTS duck-resume)
                if sonos_state in ("STOPPED", "PAUSED_PLAYBACK") and self._sonos_ambient_uri:
                    logger.info("Sonos ambient: restarting stopped track")
                    await self._sonos.play_uri(
                        self._sonos_ambient_uri,
                        volume=int(status.get("volume", present_volume)),
                    )
                    continue

                # --- Follow-me volume ---
                if self._camera is None:
                    continue
                cam = self._camera.get_status()
                if not cam.get("enabled") or cam.get("paused"):
                    continue

                detection = cam.get("last_detection", "unknown")
                now = time.monotonic()
                current_vol = int(status.get("volume", present_volume))

                if detection == "absent":
                    self._sonos_present_since = None
                    if self._sonos_absent_since is None:
                        self._sonos_absent_since = now
                    elif (
                        now - self._sonos_absent_since >= ABSENT_RAMP_SECONDS
                        and current_vol < self._sonos_away_volume
                    ):
                        logger.info(
                            "Sonos ambient: ramping up to away volume %d",
                            self._sonos_away_volume,
                        )
                        await self._sonos.ramp_volume(
                            self._sonos_away_volume, steps=6, interval=0.8
                        )
                        self._sonos_absent_since = now  # reset — don't re-ramp

                elif detection == "present":
                    self._sonos_absent_since = None
                    if self._sonos_present_since is None:
                        self._sonos_present_since = now
                    elif (
                        now - self._sonos_present_since >= PRESENT_RAMP_SECONDS
                        and current_vol > present_volume
                    ):
                        logger.info(
                            "Sonos ambient: ramping down to present volume %d (mode=%s)",
                            present_volume, mode,
                        )
                        await self._sonos.ramp_volume(
                            present_volume, steps=4, interval=0.8
                        )
                        self._sonos_present_since = now  # reset — don't re-ramp

        except asyncio.CancelledError:
            logger.info("Sonos ambient loop cancelled")
            raise
        except Exception as e:
            logger.error("Sonos ambient loop crashed: %s", e, exc_info=True)
            self._sonos_ambient_active = False

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
            "sonos_enabled": self._sonos_enabled,
            "sonos_present_volume": self._sonos_present_volume,
            "sonos_away_volume": self._sonos_away_volume,
            "sonos_mode_volume_overrides": self._sonos_mode_volume_overrides,
        })
