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
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Optional

import httpx

from backend.config import DATA_DIR, STATIC_DIR
from backend.services.audio_ownership import QUEUE_SOURCE, TRANSPORT, VOLUME

logger = logging.getLogger("home_hub.ambient")

AMBIENT_AUDIO_OWNER = "ambient_sound"
AMBIENT_AUDIO_PURPOSE = "ambient_playback"
AMBIENT_AUDIO_DIMENSIONS = frozenset({QUEUE_SOURCE, TRANSPORT, VOLUME})
AMBIENT_SOURCE_TRANSPORT_DIMENSIONS = frozenset({QUEUE_SOURCE, TRANSPORT})
AMBIENT_SOURCE_EVIDENCE_KEYS = (
    "queue_uid",
    "queue_update_id",
    "queue_size",
    "queue_first_item_hash",
    "play_mode",
    "transport_state",
    "current_uri",
    "queue_track",
    "queue_track_uri",
)
AMBIENT_FULL_EVIDENCE_KEYS = (
    *AMBIENT_SOURCE_EVIDENCE_KEYS,
    "volume",
    "mute",
)

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
AMBIENT_START_VERIFY_TIMEOUT_SECONDS = 5.0
AMBIENT_START_VERIFY_POLL_SECONDS = 0.25
AMBIENT_START_SAMPLE_TIMEOUT_SECONDS = 0.75
AMBIENT_PENDING_START_POLL_SECONDS = 1.0
AMBIENT_START_TERMINAL_STATES = frozenset({"STOPPED", "NO_MEDIA_PRESENT"})
AMBIENT_START_STABLE_SOURCE_KEYS = (
    "queue_uid",
    "queue_update_id",
    "queue_size",
    "queue_first_item_hash",
    "play_mode",
)
AMBIENT_START_PREFLIGHT_SOURCE_KEYS = (
    *AMBIENT_START_STABLE_SOURCE_KEYS,
    "current_uri",
    "queue_track",
    "queue_track_uri",
)

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
        audio_ownership: Any = None,
    ) -> None:
        self._ws_manager = ws_manager
        self._weather_service = weather_service
        self._sonos = sonos
        self._audio_ownership = audio_ownership

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
        self._sonos_lease_id: Optional[str] = None
        self._sonos_owned_evidence: Optional[dict[str, Any]] = None
        self._sonos_paused_evidence: Optional[dict[str, Any]] = None
        self._sonos_paused_uri: Optional[str] = None
        self._sonos_paused_is_stream: bool = False
        self._sonos_paused_dimensions: frozenset[str] = frozenset()
        self._shutting_down: bool = False
        self._sonos_mutation_fence = threading.Lock()
        self._command_lock = asyncio.Lock()
        self._sonos_operation_lock = asyncio.Lock()
        self._sonos_loop_task: Optional[asyncio.Task] = None
        self._sonos_start_monitor_task: Optional[asyncio.Task] = None
        self._sonos_pending_start_context: Optional[dict[str, Any]] = None
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
        # Consecutive Sonos-side playback failures for the active stream URL.
        # This remains separate from the TTL cache above: the cache decides
        # whether a stream is selectable; this short-lived state decides when
        # a transient transport blip becomes a behavioral failure.
        self._stream_failure_url: Optional[str] = None
        self._stream_failure_streak: int = 0

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

        # #279 restart semantics: process-local Ambient state is never enough
        # to reclaim the physical speaker. Retire any durable Ambient lease and
        # persist playback as paused without touching Sonos. A later mode/weather
        # evaluation may acquire a brand-new lease only from genuinely neutral
        # physical evidence.
        if self._audio_ownership is not None:
            stale_lease = await self._audio_ownership.find_lease(
                owner=AMBIENT_AUDIO_OWNER,
                purpose=AMBIENT_AUDIO_PURPOSE,
            )
            if stale_lease is not None:
                await self._audio_ownership.release(
                    stale_lease["lease_id"],
                    reason="ambient_restart_safe_abandonment",
                )
                logger.info(
                    "Ambient restart retired stale Sonos lease=%s without device mutation",
                    stale_lease["lease_id"],
                )
            if self._playing:
                self._playing = False
                self._weather_override_active = False
                seeded = True
                logger.info(
                    "Ambient restart abandoned persisted playing intent sound=%s source=%s",
                    self._current_sound,
                    self._source,
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
        """Serialize one Ambient play intent against pause/resume/stop."""
        async with self._command_lock:
            return await self._play_unlocked(filename, source=source)

    async def _play_unlocked(
        self, filename: str, source: str = "manual",
    ) -> dict[str, Any]:
        """Set the active sound and start Sonos playback."""
        if self._shutting_down:
            return {"status": "error", "detail": "Ambient service is shutting down"}
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
        self._reset_stream_failure_streak()
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
                if not (
                    self._sonos_lease_id
                    and self._sonos_pending_start_context is not None
                ):
                    self._spawn_sonos_task(self._start_sonos_ambient())
            else:
                # Already mirroring — swap the URI in place so weather
                # transitions (rain → thunderstorm) don't leave Sonos
                # stuck on the old file while the browser shows the new one.
                expected_uri = self._url_for(filename, absolute=True)
                if expected_uri and expected_uri != self._sonos_ambient_uri:
                    self._spawn_sonos_task(self._swap_sonos_ambient(filename))
        return {"status": "ok"}

    def _spawn_sonos_task(
        self,
        coro: Awaitable[Any],
    ) -> Optional[asyncio.Task]:
        """Track Sonos work unless shutdown has become terminal."""
        if self._shutting_down:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            return None
        task = asyncio.create_task(coro)
        self._pending_sonos_tasks.add(task)
        task.add_done_callback(self._pending_sonos_tasks.discard)
        return task

    async def pause(self, *, learn: bool = False) -> dict[str, Any]:
        """Serialize one Ambient pause intent."""
        async with self._command_lock:
            return await self._pause_unlocked(learn=learn)

    async def _pause_unlocked(self, *, learn: bool = False) -> dict[str, Any]:
        """Pause playback."""
        if learn:
            await self._learn_manual_suppression("pause")
        self._playing = False
        self._reset_stream_failure_streak()
        await self._broadcast_state()
        await self._save_config()
        await self._stop_sonos_ambient(reason="ambient_pause")
        logger.info("Ambient paused")
        return {"status": "ok"}

    async def resume(self) -> dict[str, Any]:
        """Serialize one Ambient resume intent."""
        async with self._command_lock:
            return await self._resume_unlocked()

    async def _resume_unlocked(self) -> dict[str, Any]:
        """Resume playback on Sonos."""
        if self._shutting_down:
            return {"status": "error", "detail": "Ambient service is shutting down"}
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
        if not self._sonos_ambient_active and not (
            self._sonos_lease_id
            and self._sonos_pending_start_context is not None
        ):
            self._spawn_sonos_task(self._start_sonos_ambient())
        logger.info("Ambient resumed: %s", self._current_sound)
        return {"status": "ok"}

    async def stop(self, *, learn: bool = False) -> dict[str, Any]:
        """Serialize one Ambient stop intent."""
        async with self._command_lock:
            return await self._stop_unlocked(learn=learn)

    async def _stop_unlocked(self, *, learn: bool = False) -> dict[str, Any]:
        """Stop and clear current sound."""
        if learn:
            await self._learn_manual_suppression("stop")
        self._current_sound = None
        self._playing = False
        self._reset_stream_failure_streak()
        self._source = "manual"
        self._weather_override_active = False
        await self._broadcast_state()
        await self._save_config()
        await self._stop_sonos_ambient(reason="ambient_stop")
        logger.info("Ambient stopped")
        return {"status": "ok"}

    async def shutdown(self) -> None:
        """Abandon Ambient for process shutdown without mutating Sonos."""
        async with self._command_lock:
            # Fence the latch against the synchronous Sonos mutation itself.
            # Any already-started guarded mutation finishes before the latch;
            # any later one acquires the fence after the latch and fails guard.
            await asyncio.to_thread(self._sonos_mutation_fence.acquire)
            try:
                self._shutting_down = True
            finally:
                self._sonos_mutation_fence.release()
            self._playing = False
            self._weather_override_active = False
            self._sonos_ambient_pending = False
            self._cancel_sonos_loop()

            pending = [
                task
                for task in tuple(self._pending_sonos_tasks)
                if not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            async with self._sonos_operation_lock:
                self._sonos_ambient_active = False
                self._sonos_ambient_pending = False
                self._sonos_ambient_uri = None
                self._sonos_ambient_is_stream = False
                self._sonos_pending_start_context = None
                self._sonos_start_monitor_task = None
                self._sonos_paused_evidence = None
                self._sonos_paused_uri = None
                self._sonos_paused_is_stream = False
                self._sonos_paused_dimensions = frozenset()
                self._sonos_absent_since = None
                self._sonos_present_since = None
                await self._release_sonos_lease(
                    "ambient_shutdown_safe_abandonment"
                )

            await self._save_config()
            logger.info("Ambient shutdown abandoned Sonos without device mutation")

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
        if self._shutting_down:
            return {"status": "error", "detail": "Ambient service is shutting down"}
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
                await self._stop_sonos_ambient(reason="ambient_disabled")
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
        if self._shutting_down:
            return
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

    def _reset_stream_failure_streak(self) -> None:
        """Forget in-progress Sonos transport failures for a stream."""
        self._stream_failure_url = None
        self._stream_failure_streak = 0

    async def _observe_stream_playback_health(self, sonos_state: str) -> bool:
        """Record an active stream's Sonos transport behavior.

        Returns ``True`` when a weather-owned stream became unhealthy and the
        weather evaluator was re-entered to select its existing fallback.
        Non-streams intentionally return ``False`` so the caller preserves its
        finite-file replay behavior.
        """
        stream_url = self._url_for(self._current_sound or "", absolute=True)
        if (
            not self._sonos_ambient_active
            or not self._playing
            or not self._sonos_ambient_is_stream
            or not stream_url
            or self._sonos_ambient_uri != stream_url
        ):
            self._reset_stream_failure_streak()
            return False

        if sonos_state == "PLAYING":
            self._reset_stream_failure_streak()
            return False

        if sonos_state not in ("STOPPED", "TRANSITIONING", "ZPSTR_BUFFERING"):
            # PAUSED_PLAYBACK is expected around TTS duck/resume; any other
            # state outside the defined failures also breaks consecutiveness.
            self._reset_stream_failure_streak()
            return False

        if self._stream_failure_url != stream_url:
            self._stream_failure_url = stream_url
            self._stream_failure_streak = 0
        self._stream_failure_streak += 1
        if self._stream_failure_streak < 2:
            return False

        prior_health = self._stream_health.get(stream_url)
        became_unhealthy = prior_health is None or prior_health[0]
        if became_unhealthy:
            self._stream_health[stream_url] = (False, time.monotonic())
            logger.warning(
                "Ambient stream unhealthy after %d Sonos transport failures: %s",
                self._stream_failure_streak, stream_url,
            )

        if became_unhealthy and self._source == "weather":
            await self._evaluate()
            return True
        return False

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
        """True when lifecycle/DND/mode policy allows Ambient Sonos control."""
        if self._shutting_down or not self._sonos_enabled:
            return False
        if self._automation is not None:
            house_state = getattr(self._automation, "house_state", "home")
            if house_state != "home":
                return False
            is_dnd_active = getattr(self._automation, "is_dnd_active", None)
            if callable(is_dnd_active) and is_dnd_active():
                return False
        mode = getattr(self._automation, "current_mode", None)
        return mode not in SONOS_BLOCKED_MODES if mode else True

    def _sonos_can_attempt(self) -> bool:
        """True when ambient playback has a viable Sonos target right now."""
        return bool(
            not self._shutting_down
            and self._sonos
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

    @staticmethod
    def _evidence_matches(
        current: dict[str, Any],
        expected: dict[str, Any],
        keys: tuple[str, ...],
    ) -> bool:
        return all(current.get(key) == expected.get(key) for key in keys)

    @staticmethod
    def _neutral_sonos_evidence(evidence: dict[str, Any] | None) -> bool:
        if not evidence:
            return False
        if evidence.get("transport_state") not in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return False
        if evidence.get("play_mode") != "NORMAL":
            return False
        if int(evidence.get("queue_size") or 0) != 0:
            return False
        if bool(evidence.get("mute")):
            return False
        current_uri = str(evidence.get("current_uri") or "")
        if not current_uri:
            return True
        queue_uid = str(evidence.get("queue_uid") or "")
        return bool(queue_uid) and current_uri == f"x-rincon-queue:{queue_uid}#0"

    @staticmethod
    def _ambient_uri_matches(
        evidence: dict[str, Any],
        expected_uri: str,
        *,
        is_stream: bool,
    ) -> bool:
        current_uri = str(evidence.get("current_uri") or "")
        if current_uri == expected_uri:
            return True
        if is_stream and current_uri == f"x-rincon-mp3radio:{expected_uri}":
            return True
        return False

    async def _release_sonos_lease(self, reason: str) -> None:
        lease_id = self._sonos_lease_id
        self._sonos_lease_id = None
        self._sonos_owned_evidence = None
        if lease_id and self._audio_ownership is not None:
            await self._audio_ownership.release(lease_id, reason=reason)

    def _cancel_sonos_loop(self) -> None:
        task = self._sonos_loop_task
        self._sonos_loop_task = None
        if (
            task
            and not task.done()
            and task is not asyncio.current_task()
        ):
            task.cancel()

    async def _abandon_sonos_ambient(
        self,
        reason: str,
        *,
        persist_playback_state: bool = True,
    ) -> None:
        """Yield Ambient ownership without mutating the physical speaker."""
        self._cancel_sonos_loop()
        self._sonos_ambient_active = False
        self._sonos_ambient_pending = False
        self._sonos_ambient_uri = None
        self._sonos_ambient_is_stream = False
        self._sonos_absent_since = None
        self._sonos_present_since = None
        self._sonos_paused_evidence = None
        self._sonos_paused_uri = None
        self._sonos_paused_is_stream = False
        self._sonos_paused_dimensions = frozenset()
        self._playing = False
        self._weather_override_active = False
        await self._release_sonos_lease(reason)
        if persist_playback_state:
            await self._save_config()
            await self._broadcast_state()
        logger.info("Sonos ambient ownership yielded reason=%s", reason)

    async def _record_owned_evidence(
        self,
        evidence: dict[str, Any],
    ) -> bool:
        lease_id = self._sonos_lease_id
        if not lease_id or self._audio_ownership is None:
            self._sonos_owned_evidence = dict(evidence)
            return True
        updated = await self._audio_ownership.update_evidence(
            lease_id,
            {
                "phase": "owned",
                "sonos": dict(evidence),
                "uri": self._sonos_ambient_uri,
                "is_stream": self._sonos_ambient_is_stream,
            },
        )
        if updated:
            self._sonos_owned_evidence = dict(evidence)
        return updated

    async def _owned_evidence_now(
        self,
        *,
        require_volume: bool = False,
    ) -> dict[str, Any] | None:
        if (
            not self._sonos_lease_id
            or self._audio_ownership is None
            or not self._sonos
        ):
            return None
        required = (
            AMBIENT_AUDIO_DIMENSIONS
            if require_volume
            else AMBIENT_SOURCE_TRANSPORT_DIMENSIONS
        )
        if not await self._audio_ownership.is_valid(
            self._sonos_lease_id,
            required,
        ):
            return None
        fresh = await self._sonos.get_playback_ownership_evidence()
        if fresh is None or self._sonos_owned_evidence is None:
            return None
        proof_keys = (
            AMBIENT_FULL_EVIDENCE_KEYS
            if require_volume
            else AMBIENT_SOURCE_EVIDENCE_KEYS
        )
        if not self._evidence_matches(
            fresh,
            self._sonos_owned_evidence,
            proof_keys,
        ):
            return None
        if not self._ambient_uri_matches(
            fresh,
            self._sonos_ambient_uri or "",
            is_stream=self._sonos_ambient_is_stream,
        ):
            return None
        return fresh

    async def _reconcile_owned_playback(self) -> dict[str, Any] | None:
        """Fail closed on source/transport takeover; yield volume separately."""
        if (
            not self._sonos_lease_id
            or self._audio_ownership is None
            or not self._sonos
            or self._sonos_owned_evidence is None
        ):
            return None
        if not await self._audio_ownership.is_valid(
            self._sonos_lease_id,
            AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
        ):
            await self._abandon_sonos_ambient("ambient_lease_invalidated")
            return None
        fresh = await self._sonos.get_playback_ownership_evidence()
        if fresh is None:
            await self._abandon_sonos_ambient("ambient_evidence_unavailable")
            return None
        if (
            not self._evidence_matches(
                fresh,
                self._sonos_owned_evidence,
                AMBIENT_SOURCE_EVIDENCE_KEYS,
            )
            or not self._ambient_uri_matches(
                fresh,
                self._sonos_ambient_uri or "",
                is_stream=self._sonos_ambient_is_stream,
            )
        ):
            await self._abandon_sonos_ambient("ambient_source_or_transport_changed")
            return None

        has_volume = await self._audio_ownership.is_valid(
            self._sonos_lease_id,
            (VOLUME,),
        )
        if has_volume and (
            fresh.get("volume") != self._sonos_owned_evidence.get("volume")
            or fresh.get("mute") != self._sonos_owned_evidence.get("mute")
        ):
            await self._audio_ownership.release(
                self._sonos_lease_id,
                dimensions=(VOLUME,),
                reason="ambient_external_volume_takeover",
            )
            await self._record_owned_evidence(fresh)
            logger.info(
                "Sonos ambient yielded volume ownership current=%s mute=%s",
                fresh.get("volume"),
                fresh.get("mute"),
            )
        return fresh

    async def _write_owned_volume(self, target: int) -> bool:
        if (
            not self._sonos_eligible()
            or not self._sonos_lease_id
            or self._audio_ownership is None
            or self._sonos_owned_evidence is None
        ):
            return False
        expected = dict(self._sonos_owned_evidence)

        async def _write() -> bool:
            if not self._sonos_eligible():
                return False
            return await self._sonos.set_volume_if_playback_unchanged(
                expected,
                target,
                still_allowed=self._sonos_eligible,
                mutation_lock=self._sonos_mutation_fence,
            )

        executed, success = await self._audio_ownership.run_if_valid(
            self._sonos_lease_id,
            AMBIENT_AUDIO_DIMENSIONS,
            _write,
        )
        if not executed or not success:
            return False
        fresh = await self._sonos.get_playback_ownership_evidence()
        if (
            fresh is None
            or not self._ambient_uri_matches(
                fresh,
                self._sonos_ambient_uri or "",
                is_stream=self._sonos_ambient_is_stream,
            )
            or fresh.get("transport_state") != "PLAYING"
            or int(fresh.get("volume", -1)) != int(target)
            or fresh.get("mute") != expected.get("mute")
        ):
            return False
        return await self._record_owned_evidence(fresh)

    async def _ramp_owned_volume(
        self,
        target: int,
        *,
        steps: int,
        interval: float,
    ) -> bool:
        fresh = await self._reconcile_owned_playback()
        if fresh is None or not self._sonos_lease_id:
            return False
        if not await self._audio_ownership.is_valid(
            self._sonos_lease_id,
            (VOLUME,),
        ):
            return False
        current = int(fresh.get("volume", target))
        if current == target:
            return True
        steps = max(1, int(steps))
        delta = (target - current) / steps
        for index in range(1, steps + 1):
            step_target = max(
                0,
                min(100, round(current + delta * index)),
            )
            if not await self._write_owned_volume(step_target):
                if not self._sonos_eligible():
                    await self._pause_for_policy("ambient_policy_blocked_during_ramp")
                else:
                    await self._reconcile_owned_playback()
                return False
            if index < steps:
                await asyncio.sleep(interval)
        return True

    async def _pause_for_policy(self, reason: str) -> None:
        """Apply a stronger lifecycle/DND/mode policy through one serialized intent."""
        async with self._command_lock:
            if not self._sonos_ambient_active and not self._playing:
                return
            self._playing = False
            self._weather_override_active = False
            self._sonos_ambient_pending = False
            await self._save_config()
            await self._broadcast_state()
            await self._stop_sonos_ambient(reason=reason)

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
        fresh = await self._reconcile_owned_playback()
        if fresh is None or not self._sonos_lease_id:
            return
        if not await self._audio_ownership.is_valid(
            self._sonos_lease_id,
            (VOLUME,),
        ):
            logger.info(
                "Sonos ambient volume sync skipped: volume ownership yielded"
            )
            return
        target = self._resolve_sonos_volume()
        current = int(fresh.get("volume", target))
        if current == target:
            return
        if await self._ramp_owned_volume(target, steps=4, interval=0.3):
            logger.info(
                "Sonos ambient volume synced %d -> %d (mode=%s)",
                current, target, self._current_mode(),
            )

    async def _read_start_evidence(
        self,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Read one startup fingerprint inside an explicit breaker budget."""
        if timeout_seconds <= 0:
            return None
        return await self._sonos.get_playback_ownership_evidence(
            call_timeout=max(0.05, timeout_seconds),
        )

    def _start_source_matches(
        self,
        fresh: dict[str, Any],
        preflight: dict[str, Any],
        uri: str,
        *,
        is_stream: bool,
    ) -> bool:
        return (
            self._evidence_matches(
                fresh,
                preflight,
                AMBIENT_START_STABLE_SOURCE_KEYS,
            )
            and self._ambient_uri_matches(
                fresh,
                uri,
                is_stream=is_stream,
            )
        )

    def _start_still_shows_preflight(
        self,
        fresh: dict[str, Any],
        preflight: dict[str, Any],
    ) -> bool:
        """True when Sonos has not yet surfaced the accepted source change."""
        return self._evidence_matches(
            fresh,
            preflight,
            AMBIENT_START_PREFLIGHT_SOURCE_KEYS,
        )

    async def _yield_start_volume_if_needed(
        self,
        *,
        lease_id: str,
        fresh: dict[str, Any],
        paused_resume: bool,
        preflight: dict[str, Any],
        start_volume: int,
    ) -> None:
        if not await self._audio_ownership.is_valid(lease_id, (VOLUME,)):
            return
        render_changed = (
            (
                not paused_resume
                and (
                    bool(fresh.get("mute"))
                    or int(fresh.get("volume", -1)) != start_volume
                )
            )
            or (
                paused_resume
                and (
                    fresh.get("volume") != preflight.get("volume")
                    or fresh.get("mute") != preflight.get("mute")
                )
            )
        )
        if not render_changed:
            return
        await self._audio_ownership.release(
            lease_id,
            dimensions=(VOLUME,),
            reason="ambient_external_rendering_during_start",
        )
        logger.info(
            "Sonos ambient start yielded volume ownership volume=%s mute=%s",
            fresh.get("volume"),
            fresh.get("mute"),
        )

    async def _verify_owned_start(
        self,
        *,
        sound_id: str,
        uri: str,
        is_stream: bool,
        paused_resume: bool,
        preflight: dict[str, Any],
        start_volume: int,
        acquire_dimensions: frozenset[str],
    ) -> tuple[str, dict[str, Any] | None, bool]:
        """Bound the initiating wait without ever releasing ambiguous ownership."""
        del acquire_dimensions  # Current lease dimensions are re-read as they change.
        lease_id = self._sonos_lease_id
        if not lease_id or self._audio_ownership is None:
            return "failed", None, False

        deadline = time.monotonic() + AMBIENT_START_VERIFY_TIMEOUT_SECONDS
        last: dict[str, Any] | None = None
        saw_target_progress = False

        while True:
            if not await self._audio_ownership.is_valid(
                lease_id,
                AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
            ):
                logger.info(
                    "Sonos ambient start verification stopped: lease invalidated"
                )
                return "failed", None, saw_target_progress

            if (
                self._shutting_down
                or not self._playing
                or self._current_sound != sound_id
                or not self._sonos_eligible()
            ):
                return "pending", last, saw_target_progress

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "pending", last, saw_target_progress

            fresh = await self._read_start_evidence(
                min(AMBIENT_START_SAMPLE_TIMEOUT_SECONDS, remaining)
            )
            if fresh is not None:
                last = fresh
                target_visible = self._start_source_matches(
                    fresh,
                    preflight,
                    uri,
                    is_stream=is_stream,
                )
                preflight_visible = self._start_still_shows_preflight(
                    fresh,
                    preflight,
                )
                if not target_visible and not preflight_visible:
                    logger.info(
                        "Sonos ambient start verification yielded: source/queue changed "
                        "state=%s uri=%s",
                        fresh.get("transport_state"),
                        fresh.get("current_uri"),
                    )
                    return "failed", fresh, saw_target_progress

                await self._yield_start_volume_if_needed(
                    lease_id=lease_id,
                    fresh=fresh,
                    paused_resume=paused_resume,
                    preflight=preflight,
                    start_volume=start_volume,
                )

                if target_visible:
                    state = str(fresh.get("transport_state") or "").upper()
                    if state in {"TRANSITIONING", "PLAYING"}:
                        saw_target_progress = True
                    if state == "PLAYING":
                        return "started", fresh, saw_target_progress
                    if state == "PAUSED_PLAYBACK":
                        if (
                            paused_resume
                            and self._evidence_matches(
                                fresh,
                                preflight,
                                AMBIENT_FULL_EVIDENCE_KEYS,
                            )
                        ):
                            # Resume can acknowledge Play before the old exact
                            # PAUSED fingerprint stops being observable.
                            pass
                        else:
                            logger.info(
                                "Sonos ambient start verification yielded: "
                                "transport paused"
                            )
                            return "failed", fresh, saw_target_progress
                    # STOPPED/NO_MEDIA immediately after an accepted Play is
                    # ambiguous: production has shown that Sonos can report the
                    # old transport state briefly before it surfaces PLAYING.
                    # Keep ownership and let the bounded wait/pending monitor
                    # reconcile later instead of treating stale STOPPED as proof
                    # that the accepted command cannot still become audible.

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "pending", last, saw_target_progress
            await asyncio.sleep(
                min(AMBIENT_START_VERIFY_POLL_SECONDS, remaining)
            )

    def _schedule_pending_start_monitor(
        self,
        context: dict[str, Any],
    ) -> None:
        task = self._sonos_start_monitor_task
        if task is not None and not task.done():
            return
        self._sonos_pending_start_context = dict(context)
        task = self._spawn_sonos_task(
            self._monitor_pending_start(dict(context))
        )
        self._sonos_start_monitor_task = task
        if task is None:
            self._sonos_pending_start_context = None
            return

        def _clear_monitor(done: asyncio.Task) -> None:
            if self._sonos_start_monitor_task is done:
                self._sonos_start_monitor_task = None

        task.add_done_callback(_clear_monitor)

    async def _finish_pending_start_locked(
        self,
        *,
        sound_id: str,
        reason: str,
    ) -> bool:
        """Release a now-resolved pending lease and report whether to retry."""
        restart = bool(
            self._playing
            and self._current_sound
            and self._current_sound != sound_id
            and self._sonos_eligible()
        )
        if not restart:
            self._playing = False
            self._weather_override_active = False
        self._sonos_ambient_pending = False
        self._sonos_pending_start_context = None
        await self._release_sonos_lease(reason)
        await self._save_config()
        await self._broadcast_state()
        return restart

    async def _activate_pending_start_locked(
        self,
        *,
        sound_id: str,
        uri: str,
        is_stream: bool,
        mode: str | None,
        fresh: dict[str, Any],
    ) -> bool:
        """Promote one proven pending source into normal active Ambient state."""
        lease_id = self._sonos_lease_id
        if (
            not lease_id
            or self._shutting_down
            or not self._playing
            or self._current_sound != sound_id
            or not self._sonos_eligible()
            or not await self._audio_ownership.is_valid(
                lease_id,
                AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
            )
        ):
            return False

        self._sonos_ambient_uri = uri
        self._sonos_ambient_is_stream = is_stream
        if not await self._record_owned_evidence(fresh):
            await self._release_sonos_lease(
                "ambient_pending_start_evidence_not_persisted"
            )
            self._sonos_ambient_pending = False
            self._playing = False
            self._sonos_pending_start_context = None
            await self._save_config()
            await self._broadcast_state()
            return False

        self._sonos_ambient_active = True
        self._sonos_ambient_pending = False
        self._sonos_pending_start_context = None
        self._sonos_paused_evidence = None
        self._sonos_paused_uri = None
        self._sonos_paused_is_stream = False
        self._sonos_paused_dimensions = frozenset()
        self._sonos_absent_since = None
        self._sonos_present_since = None
        self._sonos_loop_task = asyncio.create_task(
            self._sonos_ambient_loop(), name="sonos_ambient_loop"
        )
        logger.info(
            "Sonos ambient pending start resolved: %s volume=%s mode=%s lease=%s",
            sound_id,
            fresh.get("volume"),
            mode,
            lease_id,
        )
        await self._broadcast_state()
        return True

    async def _replace_pending_start_locked(
        self,
        *,
        lease_id: str,
        fresh: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Move a settling Ambient source to a newer requested sound in-place."""
        replacement_sound = self._current_sound
        if (
            self._shutting_down
            or not self._playing
            or not replacement_sound
            or not self._sonos_eligible()
        ):
            return None

        replacement_uri = self._url_for(replacement_sound, absolute=True)
        if not replacement_uri:
            return None
        replacement_mode = self._current_mode()
        replacement_volume = self._resolve_sonos_volume(replacement_mode)
        replacement_is_stream = self._is_stream(replacement_sound)
        owns_volume = await self._audio_ownership.is_valid(
            lease_id,
            (VOLUME,),
        )
        required = (
            AMBIENT_AUDIO_DIMENSIONS
            if owns_volume
            else AMBIENT_SOURCE_TRANSPORT_DIMENSIONS
        )
        expected = dict(fresh)

        def _still_requested() -> bool:
            return bool(
                not self._shutting_down
                and self._playing
                and self._current_sound == replacement_sound
                and self._sonos_eligible()
            )

        async def _replace() -> bool:
            if owns_volume:
                return await self._sonos.play_uri_if_unchanged(
                    expected,
                    replacement_uri,
                    volume=replacement_volume,
                    force_radio=replacement_is_stream,
                    still_allowed=_still_requested,
                    mutation_lock=self._sonos_mutation_fence,
                )
            return await self._sonos.play_uri_if_source_unchanged(
                expected,
                replacement_uri,
                force_radio=replacement_is_stream,
                still_allowed=_still_requested,
                mutation_lock=self._sonos_mutation_fence,
            )

        executed, success = await self._audio_ownership.run_if_valid(
            lease_id,
            required,
            _replace,
        )
        if not executed or not success:
            return None

        context = {
            "sound_id": replacement_sound,
            "uri": replacement_uri,
            "is_stream": replacement_is_stream,
            "paused_resume": False,
            "preflight": expected,
            "start_volume": replacement_volume,
            "mode": replacement_mode,
        }
        self._sonos_pending_start_context = dict(context)
        self._sonos_ambient_pending = True
        logger.info(
            "Sonos pending Ambient start replaced in-place: %s lease=%s",
            replacement_sound,
            lease_id,
        )
        return context

    async def _pause_pending_start_exact(
        self,
        *,
        lease_id: str,
        evidence: dict[str, Any],
    ) -> bool:
        """Pause one exact pending source without releasing ownership early."""
        async def _pause() -> bool:
            return await self._sonos.pause_if_playback_unchanged(
                evidence,
                still_allowed=lambda: not self._shutting_down,
                mutation_lock=self._sonos_mutation_fence,
            )

        executed, paused = await self._audio_ownership.run_if_valid(
            lease_id,
            AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
            _pause,
        )
        return bool(executed and paused)

    async def _finish_pending_pause_locked(
        self,
        *,
        sound_id: str,
        uri: str,
        is_stream: bool,
        fresh: dict[str, Any],
        pre_pause: dict[str, Any] | None = None,
        reason: str,
    ) -> None:
        """Release a proven HomeHub pause while preserving exact resume evidence."""
        paused_dimensions = frozenset()
        lease_id = self._sonos_lease_id
        if lease_id and self._audio_ownership is not None:
            current_lease = await self._audio_ownership.find_lease(
                owner=AMBIENT_AUDIO_OWNER,
                purpose=AMBIENT_AUDIO_PURPOSE,
            )
            if (
                current_lease is not None
                and current_lease.get("lease_id") == lease_id
            ):
                paused_dimensions = frozenset(
                    current_lease.get("dimensions") or ()
                )
        if (
            pre_pause is not None
            and VOLUME in paused_dimensions
            and (
                fresh.get("volume") != pre_pause.get("volume")
                or fresh.get("mute") != pre_pause.get("mute")
            )
        ):
            paused_dimensions = paused_dimensions - {VOLUME}

        self._sonos_paused_evidence = dict(fresh)
        self._sonos_paused_uri = uri
        self._sonos_paused_is_stream = is_stream
        self._sonos_paused_dimensions = paused_dimensions
        self._sonos_ambient_pending = False
        self._sonos_pending_start_context = None
        await self._release_sonos_lease(reason)
        await self._save_config()
        await self._broadcast_state()

    async def _monitor_pending_start(
        self,
        context: dict[str, Any],
    ) -> None:
        """Retain ownership until pending playback becomes observable and resolved."""
        sound_id = str(context["sound_id"])
        uri = str(context["uri"])
        is_stream = bool(context["is_stream"])
        paused_resume = bool(context["paused_resume"])
        preflight = dict(context["preflight"])
        start_volume = int(context["start_volume"])
        mode = context.get("mode")
        saw_target_progress = bool(context.get("saw_target_progress"))
        replay_requested = bool(context.get("replay_requested"))

        try:
            while not self._shutting_down:
                lease_id = self._sonos_lease_id
                if not lease_id:
                    return
                if not await self._audio_ownership.is_valid(
                    lease_id,
                    AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
                ):
                    async with self._sonos_operation_lock:
                        restart = await self._finish_pending_start_locked(
                            sound_id=sound_id,
                            reason="ambient_pending_start_invalidated",
                        )
                    if restart:
                        self._sonos_ambient_pending = True
                        await self._save_config()
                        await self._broadcast_state()
                        self._spawn_sonos_task(self._start_sonos_ambient())
                    return

                fresh = await self._read_start_evidence(
                    AMBIENT_START_SAMPLE_TIMEOUT_SECONDS
                )
                if fresh is None:
                    await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                    continue

                target_visible = self._start_source_matches(
                    fresh,
                    preflight,
                    uri,
                    is_stream=is_stream,
                )
                preflight_visible = self._start_still_shows_preflight(
                    fresh,
                    preflight,
                )
                if not target_visible and not preflight_visible:
                    async with self._sonos_operation_lock:
                        restart = await self._finish_pending_start_locked(
                            sound_id=sound_id,
                            reason="ambient_pending_start_foreign_source",
                        )
                    if restart:
                        self._sonos_ambient_pending = True
                        await self._save_config()
                        await self._broadcast_state()
                        self._spawn_sonos_task(self._start_sonos_ambient())
                    return

                await self._yield_start_volume_if_needed(
                    lease_id=lease_id,
                    fresh=fresh,
                    paused_resume=paused_resume,
                    preflight=preflight,
                    start_volume=start_volume,
                )

                state = str(fresh.get("transport_state") or "").upper()
                desired = bool(
                    self._playing
                    and self._current_sound == sound_id
                    and self._sonos_eligible()
                )
                replacement_requested = bool(
                    self._playing
                    and self._current_sound
                    and self._sonos_eligible()
                    and (
                        self._current_sound != sound_id
                        or replay_requested
                    )
                )
                if replacement_requested:
                    async with self._sonos_operation_lock:
                        replacement = await self._replace_pending_start_locked(
                            lease_id=lease_id,
                            fresh=fresh,
                        )
                    if replacement is not None:
                        sound_id = str(replacement["sound_id"])
                        uri = str(replacement["uri"])
                        is_stream = bool(replacement["is_stream"])
                        paused_resume = bool(replacement["paused_resume"])
                        preflight = dict(replacement["preflight"])
                        start_volume = int(replacement["start_volume"])
                        mode = replacement.get("mode")
                        saw_target_progress = False
                        replay_requested = False
                    await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                    continue

                if not desired:
                    paused = await self._pause_pending_start_exact(
                        lease_id=lease_id,
                        evidence=fresh,
                    )
                    if paused:
                        post = await self._read_start_evidence(
                            AMBIENT_START_SAMPLE_TIMEOUT_SECONDS
                        )
                        replacement = None
                        restart = False
                        async with self._command_lock:
                            async with self._sonos_operation_lock:
                                newer_intent = bool(
                                    self._playing
                                    and self._current_sound
                                    and self._sonos_eligible()
                                )
                                if newer_intent:
                                    if post is not None:
                                        replacement = (
                                            await self._replace_pending_start_locked(
                                                lease_id=lease_id,
                                                fresh=post,
                                            )
                                        )
                                else:
                                    exact_target_pause = bool(
                                        post is not None
                                        and not self._playing
                                        and self._current_sound == sound_id
                                        and self._start_source_matches(
                                            post,
                                            preflight,
                                            uri,
                                            is_stream=is_stream,
                                        )
                                        and str(
                                            post.get("transport_state") or ""
                                        ).upper()
                                        == "PAUSED_PLAYBACK"
                                        and self._evidence_matches(
                                            post,
                                            {
                                                **fresh,
                                                "transport_state": "PAUSED_PLAYBACK",
                                            },
                                            AMBIENT_SOURCE_EVIDENCE_KEYS,
                                        )
                                    )
                                    if exact_target_pause:
                                        await self._finish_pending_pause_locked(
                                            sound_id=sound_id,
                                            uri=uri,
                                            is_stream=is_stream,
                                            fresh=post,
                                            pre_pause=fresh,
                                            reason="ambient_pending_start_paused",
                                        )
                                    else:
                                        restart = (
                                            await self._finish_pending_start_locked(
                                                sound_id=sound_id,
                                                reason=(
                                                    "ambient_pending_start_"
                                                    "intent_retired"
                                                ),
                                            )
                                        )
                            if replacement is not None:
                                sound_id = str(replacement["sound_id"])
                                uri = str(replacement["uri"])
                                is_stream = bool(replacement["is_stream"])
                                paused_resume = bool(
                                    replacement["paused_resume"]
                                )
                                preflight = dict(replacement["preflight"])
                                start_volume = int(replacement["start_volume"])
                                mode = replacement.get("mode")
                                saw_target_progress = False
                                replay_requested = False
                            elif newer_intent:
                                # The new Play/Resume intent arrived after the
                                # old pending source had already been paused.
                                # Keep the proven lease and remember that a
                                # replay is still owed even if the post-pause
                                # evidence read timed out or was too stale for
                                # a conditional replacement.
                                replay_requested = True
                                self._sonos_pending_start_context = {
                                    "sound_id": sound_id,
                                    "uri": uri,
                                    "is_stream": is_stream,
                                    "paused_resume": paused_resume,
                                    "preflight": dict(preflight),
                                    "start_volume": start_volume,
                                    "mode": mode,
                                    "saw_target_progress": saw_target_progress,
                                    "replay_requested": True,
                                }
                            elif restart:
                                self._sonos_ambient_pending = True
                                await self._save_config()
                                await self._broadcast_state()
                                self._spawn_sonos_task(
                                    self._start_sonos_ambient()
                                )
                        if replacement is not None or newer_intent:
                            await asyncio.sleep(
                                AMBIENT_PENDING_START_POLL_SECONDS
                            )
                            continue
                        return
                    await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                    continue

                if not target_visible:
                    await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                    continue

                if state in {"TRANSITIONING", "PLAYING"}:
                    saw_target_progress = True

                if state == "PLAYING" and desired:
                    async with self._sonos_operation_lock:
                        confirmed = await self._read_start_evidence(
                            AMBIENT_START_SAMPLE_TIMEOUT_SECONDS
                        )
                        if (
                            confirmed is not None
                            and self._start_source_matches(
                                confirmed,
                                preflight,
                                uri,
                                is_stream=is_stream,
                            )
                            and str(
                                confirmed.get("transport_state") or ""
                            ).upper()
                            == "PLAYING"
                        ):
                            await self._yield_start_volume_if_needed(
                                lease_id=lease_id,
                                fresh=confirmed,
                                paused_resume=paused_resume,
                                preflight=preflight,
                                start_volume=start_volume,
                            )
                            if await self._activate_pending_start_locked(
                                sound_id=sound_id,
                                uri=uri,
                                is_stream=is_stream,
                                mode=mode,
                                fresh=confirmed,
                            ):
                                return
                    await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                    continue

                if state == "PAUSED_PLAYBACK":
                    if (
                        paused_resume
                        and not saw_target_progress
                        and self._evidence_matches(
                            fresh,
                            preflight,
                            AMBIENT_FULL_EVIDENCE_KEYS,
                        )
                    ):
                        # Exact paused-resume preflight can remain observable
                        # briefly after the accepted Play. Do not surrender
                        # source/transport ownership on that stale sample.
                        await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                        continue
                    async with self._sonos_operation_lock:
                        restart = await self._finish_pending_start_locked(
                            sound_id=sound_id,
                            reason="ambient_pending_start_paused",
                        )
                    if restart:
                        self._sonos_ambient_pending = True
                        await self._save_config()
                        await self._broadcast_state()
                        self._spawn_sonos_task(self._start_sonos_ambient())
                    return

                if state in AMBIENT_START_TERMINAL_STATES:
                    if not saw_target_progress:
                        # The live #279 failure demonstrated that Sonos may
                        # expose the target URI while transport still reports
                        # the pre-Play STOPPED state. That is not proof that an
                        # accepted Play cannot become audible a moment later.
                        await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                        continue
                    async with self._sonos_operation_lock:
                        restart = await self._finish_pending_start_locked(
                            sound_id=sound_id,
                            reason="ambient_pending_start_terminal",
                        )
                    if restart:
                        self._sonos_ambient_pending = True
                        await self._save_config()
                        await self._broadcast_state()
                        self._spawn_sonos_task(self._start_sonos_ambient())
                    return

                await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Preserve ownership on observer failure, but never strand a lease
            # without a reconciler. Re-arm a fresh monitor after a bounded
            # backoff; manual Sonos ingress may still invalidate the lease, and
            # shutdown retires it without device mutation.
            logger.exception(
                "Sonos pending Ambient start monitor failed; retaining ownership"
            )
            retry_context = (
                dict(self._sonos_pending_start_context)
                if (
                    not self._shutting_down
                    and self._sonos_lease_id
                    and self._sonos_pending_start_context is not None
                )
                else None
            )
            if retry_context is not None:
                if self._sonos_start_monitor_task is asyncio.current_task():
                    self._sonos_start_monitor_task = None
                await asyncio.sleep(AMBIENT_PENDING_START_POLL_SECONDS)
                if (
                    not self._shutting_down
                    and self._sonos_lease_id
                    and self._sonos_pending_start_context is not None
                ):
                    self._schedule_pending_start_monitor(
                        dict(self._sonos_pending_start_context)
                    )

    async def _start_sonos_ambient(self) -> None:
        """Acquire #274 ownership and start only from genuinely neutral Sonos."""
        async with self._sonos_operation_lock:
            try:
                if self._shutting_down:
                    return
                if self._sonos_ambient_active:
                    return
                if not self._sonos_eligible():
                    return
                if not getattr(self._sonos, "connected", False):
                    return
                if not self._playing or not self._current_sound:
                    return
                if (
                    self._sonos_lease_id
                    and self._sonos_pending_start_context is not None
                ):
                    return

                sound_id = self._current_sound
                uri = self._url_for(sound_id, absolute=True)
                if not uri:
                    logger.warning(
                        "Sonos ambient: %s no longer indexed, aborting",
                        sound_id,
                    )
                    return
                mode = self._current_mode()
                start_volume = self._resolve_sonos_volume(mode)
                is_stream = self._is_stream(sound_id)

                if self._audio_ownership is None:
                    status = await self._sonos.get_status()
                    if status.get("state") not in {"STOPPED", "PAUSED_PLAYBACK"}:
                        logger.debug(
                            "Sonos ambient: Sonos busy (state=%s), skipping",
                            status.get("state"),
                        )
                        return
                    success = await self._sonos.play_uri(
                        uri,
                        volume=start_volume,
                        force_radio=is_stream,
                    )
                    if not success:
                        return
                    self._sonos_ambient_active = True
                    self._sonos_ambient_pending = False
                    self._sonos_ambient_uri = uri
                    self._sonos_ambient_is_stream = is_stream
                else:
                    preflight = await self._read_start_evidence(
                        AMBIENT_START_SAMPLE_TIMEOUT_SECONDS
                    )
                    paused_resume = bool(
                        preflight
                        and self._sonos_paused_evidence is not None
                        and self._sonos_paused_uri == uri
                        and self._sonos_paused_is_stream == is_stream
                        and self._evidence_matches(
                            preflight,
                            self._sonos_paused_evidence,
                            AMBIENT_FULL_EVIDENCE_KEYS,
                        )
                        and self._ambient_uri_matches(
                            preflight,
                            uri,
                            is_stream=is_stream,
                        )
                    )
                    if not paused_resume and not self._neutral_sonos_evidence(preflight):
                        if self._sonos_paused_evidence is not None:
                            self._sonos_paused_evidence = None
                            self._sonos_paused_uri = None
                            self._sonos_paused_is_stream = False
                            self._sonos_paused_dimensions = frozenset()
                        logger.info(
                            "Sonos ambient start refused: speaker not neutral "
                            "or exact Ambient-paused state=%s play_mode=%s "
                            "queue=%s uri=%s",
                            (preflight or {}).get("transport_state"),
                            (preflight or {}).get("play_mode"),
                            (preflight or {}).get("queue_size"),
                            (preflight or {}).get("current_uri"),
                        )
                        return
                    acquire_dimensions = (
                        self._sonos_paused_dimensions
                        if paused_resume
                        else AMBIENT_AUDIO_DIMENSIONS
                    )
                    if (
                        paused_resume
                        and not AMBIENT_SOURCE_TRANSPORT_DIMENSIONS
                        <= acquire_dimensions
                    ):
                        self._sonos_paused_evidence = None
                        self._sonos_paused_uri = None
                        self._sonos_paused_is_stream = False
                        self._sonos_paused_dimensions = frozenset()
                        logger.info(
                            "Sonos ambient resume refused: paused ownership dimensions lost"
                        )
                        return
                    play_volume = None if paused_resume else start_volume

                    lease = await self._audio_ownership.acquire(
                        owner=AMBIENT_AUDIO_OWNER,
                        purpose=AMBIENT_AUDIO_PURPOSE,
                        dimensions=acquire_dimensions,
                        evidence={
                            "phase": "reserved",
                            "preflight": dict(preflight),
                        },
                        metadata={
                            "sound": sound_id,
                            "source": self._source,
                            "mode": mode,
                            "uri": uri,
                            "is_stream": is_stream,
                            "resume_exact_paused": paused_resume,
                        },
                    )
                    if lease is None:
                        logger.info(
                            "Sonos ambient start refused: audio ownership busy"
                        )
                        return
                    self._sonos_lease_id = lease["lease_id"]

                    async def _owned_play() -> bool:
                        if not self._sonos_eligible():
                            return False
                        return await self._sonos.play_uri_if_unchanged(
                            preflight,
                            uri,
                            volume=play_volume,
                            force_radio=is_stream,
                            still_allowed=self._sonos_eligible,
                            mutation_lock=self._sonos_mutation_fence,
                        )

                    executed, success = await self._audio_ownership.run_if_valid(
                        self._sonos_lease_id,
                        acquire_dimensions,
                        _owned_play,
                    )
                    if not executed or not success:
                        await self._release_sonos_lease(
                            "ambient_start_preflight_changed"
                        )
                        return

                    (
                        start_result,
                        fresh,
                        saw_target_progress,
                    ) = await self._verify_owned_start(
                        sound_id=sound_id,
                        uri=uri,
                        is_stream=is_stream,
                        paused_resume=paused_resume,
                        preflight=preflight,
                        start_volume=start_volume,
                        acquire_dimensions=acquire_dimensions,
                    )
                    if start_result == "pending":
                        self._sonos_ambient_pending = True
                        self._schedule_pending_start_monitor(
                            {
                                "sound_id": sound_id,
                                "uri": uri,
                                "is_stream": is_stream,
                                "paused_resume": paused_resume,
                                "preflight": dict(preflight),
                                "start_volume": start_volume,
                                "mode": mode,
                                "saw_target_progress": saw_target_progress,
                                "replay_requested": False,
                            }
                        )
                        await self._save_config()
                        await self._broadcast_state()
                        logger.info(
                            "Sonos ambient start pending observation: %s lease=%s",
                            sound_id,
                            self._sonos_lease_id,
                        )
                        return
                    if start_result != "started" or fresh is None:
                        await self._release_sonos_lease(
                            "ambient_start_verification_failed"
                        )
                        return

                    self._sonos_ambient_uri = uri
                    self._sonos_ambient_is_stream = is_stream
                    if not await self._record_owned_evidence(fresh):
                        await self._release_sonos_lease(
                            "ambient_start_evidence_not_persisted"
                        )
                        return
                    self._sonos_ambient_active = True
                    self._sonos_ambient_pending = False
                    self._sonos_paused_evidence = None
                    self._sonos_paused_uri = None
                    self._sonos_paused_is_stream = False
                    self._sonos_paused_dimensions = frozenset()

                self._sonos_absent_since = None
                self._sonos_present_since = None
                self._sonos_loop_task = asyncio.create_task(
                    self._sonos_ambient_loop(), name="sonos_ambient_loop"
                )
                logger.info(
                    "Sonos ambient started: %s at volume %d (mode=%s lease=%s)",
                    self._current_sound,
                    start_volume,
                    mode,
                    self._sonos_lease_id,
                )
                await self._broadcast_state()
            finally:
                if (
                    not self._sonos_ambient_active
                    and self._sonos_ambient_pending
                    and self._sonos_pending_start_context is None
                ):
                    self._sonos_ambient_pending = False
                    self._playing = False
                    self._weather_override_active = False
                    await self._release_sonos_lease(
                        "ambient_start_aborted"
                    )
                    try:
                        await self._save_config()
                        await self._broadcast_state()
                    except Exception:
                        logger.exception(
                            "Failed to rebroadcast after Sonos ambient start aborted"
                        )

    async def _stop_sonos_ambient(
        self,
        *,
        reason: str = "ambient_stop",
        pause_owned: bool = True,
    ) -> None:
        """Retire Ambient ownership and pause only the exact still-owned source."""
        async with self._sonos_operation_lock:
            if self._shutting_down:
                pause_owned = False

            if (
                self._audio_ownership is not None
                and self._sonos_lease_id
                and not self._sonos_ambient_active
                and self._sonos_pending_start_context is not None
            ):
                if not pause_owned:
                    self._sonos_ambient_pending = False
                    self._sonos_pending_start_context = None
                    await self._release_sonos_lease(reason)
                    return
                self._sonos_ambient_pending = True
                self._schedule_pending_start_monitor(
                    dict(self._sonos_pending_start_context)
                )
                logger.info(
                    "Sonos ambient stop deferred while startup is pending "
                    "reason=%s lease=%s",
                    reason,
                    self._sonos_lease_id,
                )
                return

            if (
                pause_owned
                and self._sonos_ambient_active
                and self._audio_ownership is not None
                and self._sonos_lease_id
            ):
                fresh = await self._reconcile_owned_playback()
                if fresh is None:
                    logger.info(
                        "Sonos ambient stop yielded before pause: ownership changed"
                    )
                    return

            lease_id = self._sonos_lease_id
            evidence = (
                dict(self._sonos_owned_evidence)
                if self._sonos_owned_evidence is not None
                else None
            )
            owned_uri = self._sonos_ambient_uri
            owned_is_stream = self._sonos_ambient_is_stream
            was_active = self._sonos_ambient_active
            paused = False
            owned_dimensions = frozenset()
            if self._audio_ownership is not None and lease_id:
                current_lease = await self._audio_ownership.find_lease(
                    owner=AMBIENT_AUDIO_OWNER,
                    purpose=AMBIENT_AUDIO_PURPOSE,
                )
                if (
                    current_lease is not None
                    and current_lease.get("lease_id") == lease_id
                ):
                    owned_dimensions = frozenset(
                        current_lease.get("dimensions") or ()
                    )

            self._cancel_sonos_loop()
            self._sonos_ambient_active = False
            self._sonos_ambient_pending = False
            self._sonos_ambient_uri = None
            self._sonos_ambient_is_stream = False
            self._sonos_paused_evidence = None
            self._sonos_paused_uri = None
            self._sonos_paused_is_stream = False
            self._sonos_paused_dimensions = frozenset()
            self._reset_stream_failure_streak()
            self._sonos_absent_since = None
            self._sonos_present_since = None

            if (
                pause_owned
                and was_active
                and self._sonos
                and getattr(self._sonos, "connected", False)
            ):
                if (
                    self._audio_ownership is not None
                    and lease_id
                    and evidence is not None
                ):
                    async def _pause() -> bool:
                        if self._shutting_down:
                            return False
                        return await self._sonos.pause_if_playback_unchanged(
                            evidence,
                            still_allowed=lambda: not self._shutting_down,
                            mutation_lock=self._sonos_mutation_fence,
                        )

                    executed, paused = await self._audio_ownership.run_if_valid(
                        lease_id,
                        AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
                        _pause,
                    )
                    if not executed or not paused:
                        logger.info(
                            "Sonos ambient pause skipped: ownership no longer exact"
                        )
                elif self._audio_ownership is None and not self._shutting_down:
                    paused = bool(await self._sonos.pause())

            if (
                paused
                and not self._shutting_down
                and reason != "ambient_stop"
                and self._audio_ownership is not None
                and owned_uri
            ):
                post = await self._sonos.get_playback_ownership_evidence()
                post_expected = dict(evidence or {})
                post_expected["transport_state"] = "PAUSED_PLAYBACK"
                if (
                    post is not None
                    and evidence is not None
                    and self._evidence_matches(
                        post,
                        post_expected,
                        AMBIENT_SOURCE_EVIDENCE_KEYS,
                    )
                    and self._ambient_uri_matches(
                        post,
                        owned_uri,
                        is_stream=owned_is_stream,
                    )
                ):
                    paused_dimensions = owned_dimensions
                    if (
                        evidence is not None
                        and VOLUME in paused_dimensions
                        and (
                            post.get("volume") != evidence.get("volume")
                            or post.get("mute") != evidence.get("mute")
                        )
                    ):
                        paused_dimensions = paused_dimensions - {VOLUME}
                        logger.info(
                            "Sonos ambient pause yielded volume ownership "
                            "after rendering changed during pause"
                        )
                    self._sonos_paused_evidence = dict(post)
                    self._sonos_paused_uri = owned_uri
                    self._sonos_paused_is_stream = owned_is_stream
                    self._sonos_paused_dimensions = paused_dimensions

            await self._release_sonos_lease(reason)
            logger.info(
                "Sonos ambient stopped reason=%s paused_claim=%s",
                reason,
                self._sonos_paused_evidence is not None,
            )

    async def _swap_sonos_ambient(self, filename: str) -> None:
        """Swap Ambient source only while the current lease/evidence still wins."""
        async with self._sonos_operation_lock:
            if self._shutting_down:
                return
            if not self._sonos_ambient_active or not self._sonos:
                return
            if not self._sonos_eligible():
                return
            fresh = await self._reconcile_owned_playback()
            if fresh is None or not self._sonos_lease_id:
                return

            uri = self._url_for(filename, absolute=True)
            if not uri:
                logger.warning(
                    "Sonos ambient swap: %s no longer indexed, leaving prior URI",
                    filename,
                )
                return
            mode = self._current_mode()
            is_stream = self._is_stream(filename)
            owns_volume = await self._audio_ownership.is_valid(
                self._sonos_lease_id,
                (VOLUME,),
            )
            volume = self._resolve_sonos_volume(mode) if owns_volume else None
            expected = dict(self._sonos_owned_evidence or fresh)
            required = (
                AMBIENT_AUDIO_DIMENSIONS
                if owns_volume
                else AMBIENT_SOURCE_TRANSPORT_DIMENSIONS
            )

            async def _swap() -> bool:
                if not self._sonos_eligible():
                    return False
                return await self._sonos.play_uri_if_unchanged(
                    expected,
                    uri,
                    volume=volume,
                    force_radio=is_stream,
                    still_allowed=self._sonos_eligible,
                    mutation_lock=self._sonos_mutation_fence,
                )

            executed, success = await self._audio_ownership.run_if_valid(
                self._sonos_lease_id,
                required,
                _swap,
            )
            if not executed or not success:
                reconciled = await self._reconcile_owned_playback()
                if reconciled is None or not self._sonos_lease_id:
                    return
                still_owns_volume = await self._audio_ownership.is_valid(
                    self._sonos_lease_id,
                    (VOLUME,),
                )
                if still_owns_volume:
                    await self._abandon_sonos_ambient(
                        "ambient_swap_preflight_changed"
                    )
                    return

                # Rendering intent changed, but source/transport is still ours.
                # Retry the requested source swap without touching volume/mute.
                expected = dict(self._sonos_owned_evidence or reconciled)

                async def _swap_source_only() -> bool:
                    if not self._sonos_eligible():
                        return False
                    return await self._sonos.play_uri_if_source_unchanged(
                        expected,
                        uri,
                        force_radio=is_stream,
                        still_allowed=self._sonos_eligible,
                        mutation_lock=self._sonos_mutation_fence,
                    )

                executed, success = await self._audio_ownership.run_if_valid(
                    self._sonos_lease_id,
                    AMBIENT_SOURCE_TRANSPORT_DIMENSIONS,
                    _swap_source_only,
                )
                if not executed or not success:
                    # Abandon only if fresh source/transport proof is gone.
                    # Otherwise retain the existing Ambient-owned source and
                    # leave the user's rendering intent untouched.
                    if await self._reconcile_owned_playback() is not None:
                        logger.info(
                            "Sonos ambient source-only swap deferred after "
                            "rendering takeover"
                        )
                    return
                owns_volume = False
                volume = None

            post = await self._sonos.get_playback_ownership_evidence()
            if (
                post is None
                or post.get("transport_state") != "PLAYING"
                or not self._ambient_uri_matches(
                    post,
                    uri,
                    is_stream=is_stream,
                )
                or (
                    owns_volume
                    and int(post.get("volume", -1)) != int(volume)
                )
            ):
                await self._abandon_sonos_ambient(
                    "ambient_swap_postplay_unverified"
                )
                return

            if owns_volume and post.get("mute") != expected.get("mute"):
                await self._audio_ownership.release(
                    self._sonos_lease_id,
                    dimensions=(VOLUME,),
                    reason="ambient_external_mute_during_swap",
                )
                owns_volume = False
                logger.info(
                    "Sonos ambient swap yielded volume ownership after mute takeover"
                )

            self._sonos_ambient_uri = uri
            self._sonos_ambient_is_stream = is_stream
            if not await self._record_owned_evidence(post):
                await self._abandon_sonos_ambient(
                    "ambient_swap_evidence_not_persisted"
                )
                return
            logger.info(
                "Sonos ambient swapped to %s at volume=%s (mode=%s)",
                filename,
                volume if volume is not None else "manual-owned",
                mode,
            )

    async def _sonos_ambient_loop(self) -> None:
        """Watch ownership and apply follow-me volume while Ambient still owns it.

        Any transport/source boundary (including PAUSED or STOPPED) fails closed:
        Ambient retires its lease and leaves Sonos untouched. This deliberately
        avoids treating a physical/app pause or stop as a request to restart.
        """
        LOOP_INTERVAL = 5.0
        ABSENT_RAMP_SECONDS = 8.0
        PRESENT_RAMP_SECONDS = 4.0

        try:
            while True:
                await asyncio.sleep(LOOP_INTERVAL)
                if not self._sonos_ambient_active or not self._playing:
                    break
                if not self._sonos_eligible():
                    await self._pause_for_policy("ambient_policy_blocked")
                    break

                fresh = await self._reconcile_owned_playback()
                if fresh is None:
                    break

                sonos_state = str(fresh.get("transport_state") or "")
                if await self._observe_stream_playback_health(sonos_state):
                    continue

                mode = self._current_mode()
                present_volume = self._resolve_sonos_volume(mode)

                if self._camera is None:
                    continue
                cam = self._camera.get_status()
                if not cam.get("enabled") or cam.get("paused"):
                    continue

                detection = cam.get("last_detection", "unknown")
                now = time.monotonic()
                current_vol = int(fresh.get("volume", present_volume))

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
                        await self._ramp_owned_volume(
                            self._sonos_away_volume,
                            steps=6,
                            interval=0.8,
                        )
                        self._sonos_absent_since = now

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
                            present_volume,
                            mode,
                        )
                        await self._ramp_owned_volume(
                            present_volume,
                            steps=4,
                            interval=0.8,
                        )
                        self._sonos_present_since = now

        except asyncio.CancelledError:
            logger.info("Sonos ambient loop cancelled")
            raise
        except Exception as exc:
            logger.error(
                "Sonos ambient loop crashed: %s",
                exc,
                exc_info=True,
            )
            await self._abandon_sonos_ambient(
                "ambient_loop_crashed",
            )

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
