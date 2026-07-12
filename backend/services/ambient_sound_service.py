"""
Ambient Sound Service - Sonos-only ambient audio orchestration.

Manages which ambient sound should be playing (rain, fireplace, etc.) and
broadcasts state to the frontend via WebSocket. Playback is intentionally
restricted to Sonos; browser clients render state and controls only.

Reacts to mode changes (registered as mode-change callback) and weather
conditions (uses cached WeatherService data). Config is persisted to the
app_settings table.

Ambient sounds play to the Sonos speaker at low volume when the mode is
eligible. A follow-me volume loop ramps Sonos volume up when the camera detects
absence (user in kitchen/bathroom) and back down on return.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Optional

import httpx

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
STREAM_CONFIG_KEY = "ambient_streams"

# Weather description keywords → sound filename stem.
# If the user has e.g. "rain.mp3" in static/ambient/ and the weather
# description contains "rain", it auto-plays.
# Order matters: _classify_weather returns the FIRST matching class, so more
# specific/severe conditions come first. "thunderstorm" precedes "rain" because
# NWS phrases like "thunderstorm and rain" must classify as the storm (mirrors
# the severity order in light_state_calculator.classify_weather).
WEATHER_SOUND_MAP: dict[str, list[str]] = {
    "thunderstorm": ["thunderstorm", "thunder"],
    "rain": ["rain", "drizzle", "shower"],
    "snow": ["snow", "sleet"],
    "wind": ["wind", "gale", "breeze"],
}

# Curated internet-radio nature streams, keyed by class. Keys that match a
# WEATHER_SOUND_MAP class (rain/thunderstorm/snow/wind) auto-trigger on that
# weather and take priority over the committed loop files; non-weather keys
# (e.g. "nature") are manual-pick only — selectable in the dropdown but never
# weather-triggered. Each entry's `id` is the index key ("filename") the rest
# of the pipeline uses, so a stream is just a virtual sound.
#
# Continuous streams need no looping or disk. They are played on Sonos via
# play_uri(force_radio=True) and in the browser as a direct <audio> src
# (cross-origin streams play without CORS). Prefer https where a station
# offers it — the kiosk is LAN-HTTP today so http works, but https survives
# any future move to an HTTPS origin (mixed-content blocking otherwise).
#
# Seeded into the editable `ambient_streams` app_setting on first run; the
# user can add/replace URLs there without a redeploy. Each URL below was
# verified live (HTTP 200 + Content-Type audio/mpeg) on 2026-05-26 — verify
# any replacement the same way before committing it.
#
# Stations without a reliable dedicated 24/7 stream (thunderstorm, snow, wind,
# fireplace) intentionally have no entry: they fall back to the committed loop
# files (thunderstorm.mp3, wind.mp3, …) automatically. Add streams here as you
# find ones you trust.
DEFAULT_STREAM_LIBRARY: dict[str, list[dict[str, str]]] = {
    "rain": [
        {
            "id": "rain-stream",
            "label": "Nature Radio Rain",
            "url": "http://maggie.torontocast.com:8108/stream",
        },
    ],
    "nature": [
        {
            "id": "nature-stream",
            "label": "Real World Sounds",
            "url": "http://uk5.internet-radio.com:8260/stream",
        },
    ],
}

# How long a stream-health probe result stays trusted before re-probing.
STREAM_HEALTH_TTL_SECONDS = 300.0

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
        # Optimistic gate set the instant we decide Sonos will be attempted,
        # cleared once _start_sonos_ambient confirms success or fails out.
        # Browsers never play ambient audio; pending is still broadcast so the
        # UI can show that Sonos is being attempted.
        self._sonos_ambient_pending: bool = False
        self._sonos_ambient_uri: Optional[str] = None
        # Whether the active Sonos ambient URI is a continuous radio stream
        # (needs force_radio on every (re)play) vs a finite local file.
        self._sonos_ambient_is_stream: bool = False
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
        self._sonos_only_migrated: bool = False
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
        # _sound_index maps filename → {kind, url_prefix, abs_path, label,
        # source_dir} for files, or {kind:"stream", url, label, wclass} for
        # injected internet-radio streams.
        # _available_sounds is the legacy [{filename, label}] list rebuilt
        # from _sound_index for backwards-compatible state payloads.
        self._sound_index: dict[str, dict[str, Any]] = {}
        self._available_sounds: list[dict[str, str]] = []

        # Internet-radio stream library (loaded from DB, seeded from
        # DEFAULT_STREAM_LIBRARY). {wclass: [{id, label, url}, ...]}.
        self._stream_library: dict[str, list[dict[str, str]]] = {}
        # Per-URL health cache: url -> (healthy, checked_at_monotonic). Probed
        # off the hot path by the weather-watch loop; _pick_healthy_stream
        # reads this synchronously so mode-change callbacks stay fast.
        self._stream_health: dict[str, tuple[bool, float]] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Load persisted config from app_settings, seeding defaults on first run."""
        from backend.api.routes.routines import load_setting

        config = await load_setting(AMBIENT_CONFIG_KEY) or {}
        seeded = False

        self._volume = config.get("volume", 0.3)
        self._mode_sounds = dict(config.get("mode_sounds", {}))
        self._mode_auto_play = dict(config.get("mode_auto_play", {}))
        self._weather_reactive = config.get("weather_reactive", True)
        self._current_sound = config.get("last_sound")
        self._playing = config.get("last_playing", False)
        if self._playing and self._current_sound:
            self._source = config.get("last_source", "manual")
        self._sonos_enabled = config.get("sonos_enabled", True)
        self._sonos_only_migrated = config.get("sonos_only_migrated", False)
        if self._sonos_enabled is False and not self._sonos_only_migrated:
            # Before browser playback was removed, false meant "browser only".
            # In the Sonos-only world that legacy value would make ambient
            # permanently silent, so migrate it once. Future explicit disables
            # set sonos_only_migrated=True and remain respected.
            self._sonos_enabled = True
            self._sonos_only_migrated = True
            seeded = True
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

        await self._load_stream_library()

        logger.info(
            "Ambient config loaded: volume=%.1f, weather=%s, mappings=%d, "
            "sonos_enabled=%s, stream_classes=%d",
            self._volume, self._weather_reactive, len(self._mode_sounds),
            self._sonos_enabled, len(self._stream_library),
        )

    async def _load_stream_library(self) -> None:
        """Load the internet-radio stream library, seeding defaults on first run.

        Persisted under the editable `ambient_streams` app_setting. On load we
        re-register the flattened set of stream URLs with the Sonos allowlist
        so only admin-curated URLs are playable (SSRF defense). Streams become
        selectable on the next scan_sounds() (called by the route + at boot).
        """
        from backend.api.routes.routines import load_setting, save_setting

        library = await load_setting(STREAM_CONFIG_KEY)
        if not library:
            library = {
                k: [dict(e) for e in entries]
                for k, entries in DEFAULT_STREAM_LIBRARY.items()
            }
            await save_setting(STREAM_CONFIG_KEY, library)
            logger.info("Ambient stream library seeded with defaults")

        self._stream_library = library
        self._register_stream_allowlist()
        # Refresh the in-memory sound index so streams are immediately
        # selectable (scan_sounds also runs, but boot ordering can vary).
        self.scan_sounds()

    def _register_stream_allowlist(self) -> None:
        """Push the curated stream URLs into the Sonos exact-match allowlist."""
        from backend.services.sonos_service import register_allowed_stream_uris

        uris = {
            entry["url"]
            for entries in self._stream_library.values()
            for entry in entries
            if entry.get("url")
        }
        register_allowed_stream_uris(uris)

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
                    "kind": "file",
                    "url_prefix": url_prefix,
                    "abs_path": str(path),
                    "label": _label_from_filename(path.name),
                    "source_dir": str(scan_dir),
                }

        # Inject internet-radio streams as virtual sounds. Each stream `id`
        # becomes an index key, so the dropdown + play(filename) path treat it
        # exactly like a file. `wclass` carries the library key for weather
        # matching (which keys off the class, not the id prefix).
        stream_count = 0
        for wclass, entries in self._stream_library.items():
            for entry in entries:
                sid = entry.get("id")
                url = entry.get("url")
                if not sid or not url or sid in index:
                    continue
                index[sid] = {
                    "kind": "stream",
                    "url": url,
                    "label": entry.get("label") or _label_from_filename(sid),
                    "wclass": wclass,
                }
                stream_count += 1

        self._sound_index = index
        self._available_sounds = [
            {
                "filename": filename,
                "label": entry["label"],
                "kind": entry.get("kind", "file"),
            }
            for filename, entry in index.items()
        ]
        file_count = len(index) - stream_count
        long_count = sum(
            1 for e in index.values()
            if e.get("url_prefix") == "/static/ambient-long"
        )
        logger.info(
            "Scanned %d ambient sounds (%d files [%d long-form], %d streams)",
            len(index), file_count, long_count, stream_count,
        )
        return self._available_sounds

    def _url_for(self, filename: str, *, absolute: bool = False) -> Optional[str]:
        """Resolve a filename to its URL.

        For files: absolute=True returns ``http://{LOCAL_IP}:8000{prefix}/{filename}``
        for Sonos; absolute=False returns just ``{prefix}/{filename}`` for
        browser-side broadcast. For streams the external URL is returned
        verbatim regardless of `absolute` — Sonos fetches it (force_radio) and
        the browser plays it directly as an <audio> src. Returns None if the
        filename isn't indexed.
        """
        entry = self._sound_index.get(filename)
        if entry is None:
            return None
        if entry.get("kind") == "stream":
            return entry["url"]
        prefix = entry["url_prefix"]
        if absolute:
            from backend.config import settings
            return f"http://{settings.LOCAL_IP}:8000{prefix}/{filename}"
        return f"{prefix}/{filename}"

    def _is_stream(self, filename: Optional[str]) -> bool:
        """True when the indexed sound is an internet-radio stream."""
        if not filename:
            return False
        entry = self._sound_index.get(filename)
        return bool(entry and entry.get("kind") == "stream")

    def _label_for(self, filename: str) -> str:
        """Display label for a sound — curated index label, else derived."""
        entry = self._sound_index.get(filename)
        if entry and entry.get("label"):
            return entry["label"]
        return _label_from_filename(filename)

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
                self._label_for(self._current_sound)
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
            "sonos_ambient_pending": self._sonos_ambient_pending,
            "sonos_present_volume": self._sonos_present_volume,
            "sonos_away_volume": self._sonos_away_volume,
            "sonos_mode_volume_overrides": self._sonos_mode_volume_overrides,
            "suppressed_modes": sorted(SUPPRESSED_MODES),
        }

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------

    async def play(self, filename: str, source: str = "manual") -> dict[str, Any]:
        """Set the active sound and start Sonos playback."""
        if not self._file_exists(filename):
            return {"status": "error", "detail": f"File not found: {filename}"}
        if not self._sonos_can_attempt():
            logger.info(
                "Ambient play skipped: Sonos unavailable/ineligible "
                "(sound=%s, source=%s, mode=%s)",
                filename, source, self._current_mode(),
            )
            self._current_sound = filename
            self._playing = False
            self._source = source
            self._weather_override_active = False
            self._sonos_ambient_pending = False
            await self._broadcast_state()
            await self._save_config()
            return {"status": "error", "detail": "Ambient sound requires Sonos"}

        self._current_sound = filename
        self._playing = True
        self._source = source
        self._weather_override_active = source == "weather"
        # Set pending BEFORE the first broadcast so the UI shows that Sonos is
        # being attempted. Browser clients stay silent regardless.
        if not self._sonos_ambient_active:
            self._sonos_ambient_pending = True
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

    async def pause(self, *, learn: bool = False) -> dict[str, Any]:
        """Pause playback."""
        if learn:
            await self._learn_manual_suppression("pause")
        self._playing = False
        self._sonos_ambient_pending = False
        await self._broadcast_state()
        await self._save_config()
        self._stop_sonos_ambient()
        logger.info("Ambient paused")
        return {"status": "ok"}

    async def resume(self) -> dict[str, Any]:
        """Resume playback on Sonos."""
        if not self._current_sound:
            return {"status": "error", "detail": "No sound to resume"}
        if not self._sonos_can_attempt():
            self._playing = False
            self._sonos_ambient_pending = False
            await self._broadcast_state()
            await self._save_config()
            return {"status": "error", "detail": "Ambient sound requires Sonos"}
        self._playing = True
        if not self._sonos_ambient_active:
            self._sonos_ambient_pending = True
        await self._broadcast_state()
        await self._save_config()
        if not self._sonos_ambient_active:
            self._spawn_sonos_task(self._start_sonos_ambient())
        logger.info("Ambient resumed: %s", self._current_sound)
        return {"status": "ok"}

    async def stop(self, *, learn: bool = False) -> dict[str, Any]:
        """Stop and clear current sound."""
        if learn:
            await self._learn_manual_suppression("stop")
        self._current_sound = None
        self._playing = False
        self._source = "manual"
        self._weather_override_active = False
        await self._broadcast_state()
        await self._save_config()
        self._stop_sonos_ambient()
        logger.info("Ambient stopped")
        return {"status": "ok"}

    async def _learn_manual_suppression(self, action: str) -> None:
        """Persist a user's manual rejection of an auto ambient decision."""
        changed = False
        mode = self._current_mode()

        if self._source == "mode" and mode and self._mode_auto_play.get(mode):
            self._mode_auto_play[mode] = False
            changed = True
            logger.info(
                "Ambient learned suppression: mode auto-play disabled "
                "(mode=%s, action=%s, sound=%s)",
                mode, action, self._current_sound,
            )
        elif self._source == "weather" and self._weather_reactive:
            self._weather_reactive = False
            self._weather_override_active = False
            changed = True
            logger.info(
                "Ambient learned suppression: weather reactive disabled "
                "(action=%s, sound=%s)",
                action, self._current_sound,
            )

        if changed:
            await self._save_config()

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
        sonos_enabled_turned_on = False
        if sonos_enabled is not None:
            was_enabled = self._sonos_enabled
            self._sonos_enabled = bool(sonos_enabled)
            self._sonos_only_migrated = True
            sonos_changed = True
            sonos_enabled_turned_on = self._sonos_enabled and not was_enabled
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

        # If the toggle just flipped off and Sonos was mirroring (or about
        # to), stop it. Browser fallback is disabled, so this becomes silent.
        if sonos_changed and not self._sonos_enabled:
            self._playing = False
            self._weather_override_active = False
            if self._sonos_ambient_active:
                self._stop_sonos_ambient()
            elif self._sonos_ambient_pending:
                self._sonos_ambient_pending = False

        await self._save_config()
        await self._broadcast_state()
        # Volume / enable changes warrant re-evaluating so the new policy
        # takes effect immediately on the active sound.
        if sonos_changed:
            await self._evaluate()

        # When `sonos_enabled` flips false → true while something is already
        # playing locally, `_evaluate()` short-circuits (target == current
        # sound) and never kicks Sonos off. Migrate the active playback
        # directly so the toggle feels instant — pending flag goes out first
        # to silence the browsers, then we spawn the start task.
        if (
            sonos_enabled_turned_on
            and self._playing
            and self._current_sound
            and self._sonos
            and not self._sonos_ambient_active
            and not self._sonos_ambient_pending
            and self._sonos_eligible()
        ):
            self._sonos_ambient_pending = True
            await self._broadcast_state()
            self._spawn_sonos_task(self._start_sonos_ambient())
            logger.info(
                "Ambient: sonos_enabled flipped on, migrating %s to Sonos",
                self._current_sound,
            )
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
        loop produce identical behavior. Sonos is the only playback surface;
        broadcasts exist for UI state and controls.
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
                await self.pause(learn=False)
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
            await self.pause(learn=False)
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
        """Resolve current weather class to a concrete sound id/filename.

        Prefers a healthy curated internet-radio stream for the class; falls
        back to a committed/long-form loop file matching the class name when no
        stream is available or healthy. Sync — reads the stream-health cache
        (refreshed off the hot path by the watch loop) so it stays fast on the
        mode-change callback.
        """
        wclass = self._classify_weather()
        if not wclass:
            return None
        stream_id = self._pick_healthy_stream(wclass)
        if stream_id:
            return stream_id
        for s in self._available_sounds:
            fn = s["filename"]
            if self._is_stream(fn):
                continue
            if fn.lower().startswith(wclass):
                return fn
        return None

    def _pick_healthy_stream(self, wclass: Optional[str]) -> Optional[str]:
        """Return the first usable stream id for a class, or None.

        "Usable" = known-healthy, or health unknown (optimistic first try —
        the watch loop probes and corrects), or a known-bad result that has
        gone stale (retry). A fresh known-bad stream is skipped so a dead
        station falls through to the file fallback without thrashing.
        """
        if not wclass:
            return None
        now = time.monotonic()
        for entry in self._stream_library.get(wclass, []):
            sid, url = entry.get("id"), entry.get("url")
            if not sid or not url or sid not in self._sound_index:
                continue
            health = self._stream_health.get(url)
            if health is None:
                return sid
            healthy, checked_at = health
            if healthy or (now - checked_at) >= STREAM_HEALTH_TTL_SECONDS:
                return sid
        return None

    async def _probe_stream_health(self, url: str) -> bool:
        """Probe a stream URL (2xx + audio/* content-type), cache the result.

        Uses a streaming GET and reads only the headers (never the infinite
        body). Servers that answer with a bare ``ICY 200 OK`` status line
        instead of HTTP will raise and be marked unhealthy — the curated
        defaults speak HTTP/1.x, so verify any replacement with curl first.
        """
        ok = False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                async with client.stream(
                    "GET", url, headers={"Icy-MetaData": "0"}
                ) as resp:
                    ctype = resp.headers.get("content-type", "").lower()
                    ok = resp.status_code < 400 and ctype.startswith("audio")
        except Exception as e:
            logger.debug("Stream health probe failed for %s: %s", url, e)
        self._stream_health[url] = (ok, time.monotonic())
        return ok

    async def _refresh_stream_health(self, wclass: Optional[str]) -> None:
        """Re-probe streams for a class whose cached health is stale/missing."""
        if not wclass:
            return
        now = time.monotonic()
        for entry in self._stream_library.get(wclass, []):
            url = entry.get("url")
            if not url:
                continue
            cached = self._stream_health.get(url)
            if cached and (now - cached[1]) < STREAM_HEALTH_TTL_SECONDS:
                continue
            await self._probe_stream_health(url)

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
            # Warm the stream-health cache for the current class before the
            # first selection so _check_weather doesn't have to guess blind.
            await self._refresh_stream_health(self._last_weather_class)
            await self._evaluate()
            # Boot-restore safety net: if persisted state had last_playing=true
            # and _evaluate's diff check short-circuited (target equals the
            # already-loaded _current_sound), nothing was actually dispatched
            # this session. Force a play() so Sonos picks up the persisted
            # sound. Skips if _evaluate already kicked something off
            # (active/pending true) or Sonos isn't a viable surface right now.
            if (
                self._playing
                and self._current_sound
                and not self._sonos_ambient_active
                and not self._sonos_ambient_pending
                and self._sonos
                and self._sonos_enabled
                and self._sonos_eligible()
            ):
                logger.info(
                    "Ambient boot-restore: re-issuing play for %s (source=%s)",
                    self._current_sound, self._source,
                )
                await self.play(self._current_sound, source=self._source)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Initial ambient evaluate failed")

        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                wclass = self._classify_weather()
                # TTL-gated re-probe of the current class's streams (cheap when
                # fresh). Catches a station dying mid-play or recovering.
                await self._refresh_stream_health(wclass)
                if wclass != self._last_weather_class:
                    logger.info(
                        "Ambient: weather class %s -> %s, re-evaluating",
                        self._last_weather_class, wclass,
                    )
                    self._last_weather_class = wclass
                    await self._evaluate()
                elif (
                    self._weather_reactive
                    and self._playing
                    and self._source == "weather"
                    and self._check_weather() != self._current_sound
                ):
                    # Same weather class, but stream health flipped — the
                    # resolved target changed (stream died → file fallback, or
                    # recovered → back to stream). Re-evaluate to switch.
                    logger.info(
                        "Ambient: stream health changed for %s, re-evaluating",
                        wclass,
                    )
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

    def _sonos_can_attempt(self) -> bool:
        """True when ambient playback has a viable Sonos target right now."""
        return bool(
            self._sonos
            and self._sonos_enabled
            and self._sonos_eligible()
            and getattr(self._sonos, "connected", False)
        )

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
          4. Ambient state says playback is desired.

        On any failure path we clear `_sonos_ambient_pending`, mark playback
        paused, and rebroadcast. Browser fallback is intentionally disabled:
        ambient audio should only ever come from Sonos.
        """
        try:
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
            is_stream = self._is_stream(self._current_sound)
            success = await self._sonos.play_uri(
                uri, volume=start_volume, force_radio=is_stream
            )
            if not success:
                logger.warning("Sonos ambient: play_uri failed for %s", uri)
                return

            self._sonos_ambient_active = True
            self._sonos_ambient_pending = False
            self._sonos_ambient_uri = uri
            self._sonos_ambient_is_stream = is_stream
            self._sonos_absent_since = None
            self._sonos_present_since = None
            self._sonos_loop_task = asyncio.create_task(
                self._sonos_ambient_loop(), name="sonos_ambient_loop"
            )
            logger.info(
                "Sonos ambient started: %s at volume %d (mode=%s)",
                self._current_sound, start_volume, mode,
            )
            # Re-broadcast so frontends show that Sonos is active.
            await self._broadcast_state()
        finally:
            # Any non-success exit (early return, exception) must clear
            # pending and pause state. Success already cleared pending above.
            if not self._sonos_ambient_active and self._sonos_ambient_pending:
                self._sonos_ambient_pending = False
                try:
                    self._playing = False
                    self._weather_override_active = False
                    await self._save_config()
                    await self._broadcast_state()
                except Exception:
                    logger.exception(
                        "Failed to rebroadcast after Sonos ambient start aborted"
                    )

    def _stop_sonos_ambient(self) -> None:
        """Cancel ambient loop and pause Sonos. Sync — fire-and-forget pause."""
        if self._sonos_loop_task and not self._sonos_loop_task.done():
            self._sonos_loop_task.cancel()
        self._sonos_loop_task = None
        self._sonos_ambient_active = False
        self._sonos_ambient_pending = False
        self._sonos_ambient_uri = None
        self._sonos_ambient_is_stream = False
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
        is_stream = self._is_stream(filename)
        try:
            success = await self._sonos.play_uri(
                uri, volume=vol, force_radio=is_stream
            )
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
            self._sonos_ambient_is_stream = is_stream
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
                        force_radio=self._sonos_ambient_is_stream,
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
            "sonos_only_migrated": self._sonos_only_migrated,
            "sonos_present_volume": self._sonos_present_volume,
            "sonos_away_volume": self._sonos_away_volume,
            "sonos_mode_volume_overrides": self._sonos_mode_volume_overrides,
        })
