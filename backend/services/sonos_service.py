"""
Sonos speaker service — wraps SoCo for local UPnP control.
"""
import asyncio
import hashlib
import logging
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin
from typing import TYPE_CHECKING, Any, Optional

from backend.config import settings
from backend.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen

if TYPE_CHECKING:
    # Avoid runtime import cost — automation_engine pulls in
    # light_state_calculator + effect_manager, which is heavier than this
    # module needs at load time. String-annotated below.
    from soco import SoCo
    from soco.snapshot import Snapshot
    from backend.services.automation_engine import AutomationEngine
    from backend.services.event_logger import EventLogger
    from backend.services.heartbeat import HeartbeatRegistry

logger = logging.getLogger("home_hub.sonos")

STATUS_FRESHNESS_SECONDS = 10.0
ASSISTED_FINAL_BUDGET_SECONDS = 3.0
ASSISTED_START_VERIFY_SECONDS = 6.0
ASSISTED_START_POLL_SECONDS = 0.25
ASSISTED_START_SAMPLE_BUDGET_SECONDS = 1.0
ASSISTED_START_MIN_ADVANCE_SECONDS = 1.0

_AUDIO_OWNERSHIP_PROOF_KEYS = (
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


# play_uri() makes the speaker fetch arbitrary URLs. Keep generic URL
# playback deliberately narrow so callers cannot use the speaker as an SSRF
# probe. The generic source is HomeHub-local TTS/static audio; admin-curated
# ambient internet streams are admitted separately by exact URL below.
_ALLOWED_PLAY_URI_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        rf"^http://{re.escape(settings.LOCAL_IP)}(:\d+)?/",
        re.IGNORECASE,
    ),
)

# Exact-URL allowlist for admin-curated ambient internet-radio streams.
# Nature-stream hostnames are unpredictable (Shoutcast/Icecast CDN hosts on
# odd ports, sometimes raw IPs), so widening the host-pattern allowlist would
# open SSRF surface. Instead the AmbientSoundService registers the exact set
# of stream URLs from its (admin-edited) library via register_allowed_stream_uris;
# only those precise URLs are playable. Membership is exact-match, not prefix.
_ALLOWED_STREAM_URIS: set[str] = set()


def _absolute_album_art_url(album_art: str, device_ip: Optional[str]) -> str:
    """Turn Sonos relative album-art paths into browser-loadable URLs."""
    if not album_art:
        return ""
    if album_art.startswith(("http://", "https://")):
        return album_art
    if not device_ip:
        return album_art
    return urljoin(f"http://{device_ip}:1400", album_art)


def register_allowed_stream_uris(uris: set[str]) -> None:
    """Replace the curated ambient-stream allowlist (exact-match URLs).

    Called by AmbientSoundService on config load and on every stream-library
    change. SSRF-safe: only the precise URLs the admin curated become playable
    — no host/prefix widening.
    """
    global _ALLOWED_STREAM_URIS
    _ALLOWED_STREAM_URIS = set(uris)


def is_allowed_play_uri(uri: str) -> bool:
    """True if a URI is on the allowlist for sonos.play_uri().

    Enforced inside ``play_uri`` as defense-in-depth so every current or
    future caller remains constrained even if it forgets to pre-validate.

    Accepts locally-served assets (LOCAL_IP) and exact-match members of the
    curated ambient-stream allowlist. Promotional catalog preview hosts are
    intentionally not generic playback sources.
    """
    if not uri:
        return False
    if uri in _ALLOWED_STREAM_URIS:
        return True
    return any(p.match(uri) for p in _ALLOWED_PLAY_URI_PATTERNS)


class SonosService:
    """
    Controls a Sonos speaker via local UPnP using the SoCo library.

    Auto-discovers speakers on the network or uses a specified IP.
    Polls now-playing state and pushes changes to WebSocket clients.
    """

    def __init__(self, sonos_ip: Optional[str] = None) -> None:
        self._sonos_ip = sonos_ip
        self._device = None
        self._connected = False
        self._last_status: Optional[dict] = None
        self._last_successful_status: Optional[dict[str, Any]] = None
        self._last_successful_status_at: Optional[datetime] = None
        # Off-dashboard skip emitter — physical buttons, Alexa, Sonos app
        # don't route through main.py:_handle_sonos_command, so skips
        # initiated outside the dashboard were invisible to the bandit
        # until 2026-05-25. attach_event_logger() wires these in
        # post-bootstrap; poll_state_loop emits event_type="skip" with
        # the prior track's title when title changes mid-track.
        self._event_logger = None
        self._automation = None
        self._audio_ownership = None
        # Favorites/playlists cache (5-min TTL)
        self._favorites_cache: Optional[list] = None
        # Raw SoCo favorite objects, parallel to _favorites_cache, needed so
        # play_favorite can call add_to_queue with the original DidlObject
        # (which carries the DIDL metadata Sonos requires for cloud containers).
        self._favorites_objects_cache: Optional[list] = None
        self._favorites_cache_time: float = 0
        self._playlists_cache: Optional[list] = None
        self._playlists_cache_time: float = 0
        self._CACHE_TTL: float = 300.0
        self._heartbeat = None  # HeartbeatRegistry, set via set_heartbeat_registry
        # SoCo / UPnP calls go through this breaker so a slow speaker
        # can't wedge the polling loop or REST handlers indefinitely.
        # 5s call_timeout — Sonos is normally <200ms locally, but SoCo's
        # transport-info call has been observed to hang briefly during
        # speaker firmware updates.
        self._breaker = CircuitBreaker(
            name="sonos", failure_threshold=3, cooldown_seconds=30.0, call_timeout=5.0
        )

    def set_heartbeat_registry(self, registry: "HeartbeatRegistry") -> None:
        """Inject the heartbeat registry (called from lifespan)."""
        self._heartbeat = registry

    def attach_event_logger(
        self,
        event_logger: "EventLogger",
        automation: "AutomationEngine",
    ) -> None:
        """Wire post-bootstrap dependencies for off-dashboard skip emission.

        Called from bootstrap.py once both event_logger and automation
        engine are constructed. Until called, poll_state_loop's skip-
        detection branch no-ops — services that don't attach (tests,
        partial-bootstrap probes) preserve the prior behavior.
        """
        self._event_logger = event_logger
        self._automation = automation

    def attach_audio_ownership(self, audio_ownership) -> None:
        """Wire the shared ownership authority for off-dashboard takeover."""
        self._audio_ownership = audio_ownership

    @property
    def breaker(self) -> CircuitBreaker:
        """Expose the breaker so /health can snapshot its state."""
        return self._breaker

    @property
    def breaker_open(self) -> bool:
        """True when the breaker is fast-failing — distinct from ``connected``.

        Mirror of ``HueService.breaker_open``; see that property for the
        full rationale. Route handlers should 503 on this so clients can
        distinguish "speaker temporarily unavailable" (retry-worthy) from
        "speaker errored on the request" (don't retry).

        Half-open returns False — the next call probes and may succeed.
        """
        return self._breaker.state == CircuitBreaker.OPEN

    async def _safe_call(self, fn, *args, **kwargs):
        """Run a sync SoCo read/call in a thread under the circuit breaker."""
        return await self._breaker.call(asyncio.to_thread, fn, *args, **kwargs)

    @staticmethod
    async def _settled_thread_call(fn, *args, **kwargs):
        """Do not report cancellation until the underlying sync write has settled.

        asyncio.to_thread cannot cancel an already-running SoCo call. For
        ownership-sensitive mutations, returning on timeout/cancellation would
        let the authority lock go while that stale thread could still finish.
        Shield the worker and defer cancellation until the sync operation exits.
        """
        worker = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                task = asyncio.current_task()
                if task is not None and hasattr(task, "uncancel"):
                    task.uncancel()
                continue
        try:
            result = worker.result()
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError
            raise
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _safe_mutation_call(
        self, fn, *args, call_timeout: float | None = None, **kwargs,
    ):
        """Run a sync Sonos mutation without releasing ownership early."""
        return await self._breaker.call(
            self._settled_thread_call,
            fn,
            *args,
            call_timeout=call_timeout,
            **kwargs,
        )

    @property
    def connected(self) -> bool:
        """Whether a Sonos speaker has been found."""
        return self._connected

    @property
    def device(self):
        """The underlying SoCo device object."""
        return self._device

    async def get_queue_context(self) -> dict[str, Any]:
        """Return fresh queue/play-mode facts for playback ownership policy.

        The assisted-playback policy uses this read-only surface to refuse
        takeover when Sonos is in repeat/shuffle or queue state cannot be read.
        """
        if not self._connected or not self._device:
            return {"available": False, "play_mode": None, "queue_size": None}
        try:
            play_mode = await self._safe_call(lambda: str(self._device.play_mode))
            queue_size = await self._safe_call(lambda: int(self._device.queue_size))
        except Exception as exc:
            logger.warning("Sonos queue-context read failed: %s", exc)
            return {"available": False, "play_mode": None, "queue_size": None}
        return {
            "available": True,
            "play_mode": str(play_mode or "").upper(),
            "queue_size": max(0, int(queue_size)),
        }

    async def get_queue_ownership_evidence(self) -> dict[str, Any] | None:
        """Return one fresh fingerprint for queue/source ownership."""
        if not self._connected or not self._device:
            return None
        try:
            return await self._safe_call(self._queue_ownership_evidence_sync)
        except Exception as exc:
            logger.warning("Sonos queue ownership evidence read failed: %s", exc)
            return None

    def _queue_ownership_evidence_sync(self) -> dict[str, Any]:
        device = self._device
        queue_uid = str(device.uid)
        settings_result = device.avTransport.GetTransportSettings([("InstanceID", 0)])
        transport = device.avTransport.GetTransportInfo([("InstanceID", 0)])
        media = device.avTransport.GetMediaInfo([("InstanceID", 0)])
        position = device.avTransport.GetPositionInfo([("InstanceID", 0)])
        browse = device.contentDirectory.Browse([
            ("ObjectID", "Q:0"),
            ("BrowseFlag", "BrowseDirectChildren"),
            ("Filter", "*"),
            ("StartingIndex", 0),
            ("RequestedCount", 1),
            ("SortCriteria", ""),
        ])
        queue_size = max(0, int(browse.get("TotalMatches") or 0))
        raw_first = str(browse.get("Result") or "") if queue_size else ""
        return {
            "queue_uid": queue_uid,
            "queue_update_id": str(browse.get("UpdateID") or ""),
            "queue_size": queue_size,
            "queue_first_item_hash": (
                hashlib.sha256(raw_first.encode("utf-8")).hexdigest()
                if raw_first else None
            ),
            "play_mode": str(settings_result.get("PlayMode") or "").upper(),
            "transport_state": str(
                transport.get("CurrentTransportState") or ""
            ).upper(),
            "current_uri": str(media.get("CurrentURI") or ""),
            "queue_track": max(0, int(position.get("Track") or 0)),
            "queue_track_uri": str(position.get("TrackURI") or ""),
        }

    def get_cached_status_snapshot(self) -> dict[str, Any]:
        """Return held playback health without querying the player."""
        breaker = self._breaker.snapshot()
        observed_at = self._last_successful_status_at
        age_seconds = (
            max(
                0.0,
                (datetime.now(timezone.utc) - observed_at).total_seconds(),
            )
            if observed_at is not None
            else None
        )
        state = (
            self._last_successful_status.get("state")
            if self._last_successful_status is not None
            else None
        )
        if state == "PLAYING":
            coarse_state = "playing"
        elif state in {"STOPPED", "PAUSED_PLAYBACK"}:
            coarse_state = "stopped"
        else:
            coarse_state = "unknown"
        return {
            "configured": bool(self._sonos_ip or self._device),
            "connected": self._connected,
            "breaker_state": breaker["state"],
            "consecutive_failures": breaker["consecutive_failures"],
            "last_successful_status_at": (
                observed_at.isoformat() if observed_at is not None else None
            ),
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "fresh": (
                age_seconds is not None
                and age_seconds <= STATUS_FRESHNESS_SECONDS
            ),
            "state": coarse_state,
        }

    async def discover(self) -> None:
        """
        Find a Sonos speaker on the local network.

        Uses a specific IP if configured, otherwise auto-discovers via SSDP.
        """
        try:
            import soco

            if self._sonos_ip:
                self._device = await asyncio.to_thread(soco.SoCo, self._sonos_ip)
                # Validate connection by requesting device info
                await asyncio.to_thread(lambda: self._device.player_name)
                self._connected = True
                logger.info(
                    f"Connected to Sonos at {self._sonos_ip}: "
                    f"{self._device.player_name}"
                )
            else:
                devices = await asyncio.to_thread(soco.discover)
                if devices:
                    self._device = list(devices)[0]
                    self._connected = True
                    logger.info(
                        f"Discovered Sonos: {self._device.player_name} "
                        f"at {self._device.ip_address}"
                    )
                else:
                    logger.warning("No Sonos speakers found on the network")
                    self._connected = False

        except ImportError:
            logger.error("soco not installed — run: pip install soco")
            self._connected = False
        except Exception as e:
            logger.error(f"Failed to discover Sonos: {e}")
            self._connected = False

    async def get_status(self) -> dict[str, Any]:
        """
        Get current playback status.

        Returns:
            Dict with state, track, artist, album, art_url, volume, mute.
        """
        if not self._connected or not self._device:
            return {"state": "disconnected"}

        try:
            # Each property/method goes through the breaker independently.
            # A single slow get_status burst can therefore record up to four
            # failures, opening the breaker faster than a strict per-call
            # accounting would — that's a deliberate tradeoff in favor of
            # bailing out quickly when the speaker is unresponsive.
            transport, track, volume, mute = await asyncio.gather(
                self._safe_call(self._device.get_current_transport_info),
                self._safe_call(self._device.get_current_track_info),
                self._safe_call(lambda: self._device.volume),
                self._safe_call(lambda: self._device.mute),
            )

            status = {
                "state": transport.get("current_transport_state", "STOPPED"),
                "track": track.get("title", ""),
                "artist": track.get("artist", ""),
                "album": track.get("album", ""),
                "art_url": _absolute_album_art_url(
                    track.get("album_art", ""),
                    getattr(self._device, "ip_address", None),
                ),
                "duration": track.get("duration", "0:00:00"),
                "position": track.get("position", "0:00:00"),
                "volume": volume,
                "mute": mute,
            }
            self._last_successful_status = status
            self._last_successful_status_at = datetime.now(timezone.utc)
            return status
        except CircuitBreakerOpen:
            # Breaker self-narrates state transitions; the 2s poll loop
            # would otherwise log ERROR every cycle while the breaker is
            # open, flooding Sentry on any sustained Sonos outage.
            return {"state": "error", "error": "circuit breaker open"}
        except Exception as e:
            logger.error(f"Error getting Sonos status: {e}")
            return {"state": "error", "error": str(e)}

    async def get_current_media_uri(self) -> str | None:
        """Return the loaded Sonos media URI for internal ownership checks.

        Kept separate from ``get_status`` so provider/service URIs do not become
        part of the public Sonos/WebSocket status contract. ``None`` means the
        identity could not be read safely; callers must fail closed.
        """
        if not self._connected or not self._device:
            return None
        try:
            track = await self._safe_call(self._device.get_current_track_info)
            return str(track.get("uri") or "")
        except CircuitBreakerOpen:
            return None
        except Exception as exc:
            logger.warning("Sonos current media URI read failed: %s", exc)
            return None

    async def play(self) -> bool:
        """Resume playback."""
        if not self._connected or not self._device:
            return False
        try:
            await self._safe_mutation_call(self._device.play)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            logger.error(f"Sonos play error: {e}")
            return False

    async def pause(self) -> bool:
        """Pause playback."""
        if not self._connected or not self._device:
            return False
        try:
            await self._safe_mutation_call(self._device.pause)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            # UPnP 701 ("Transition not available") on pause means the
            # player is already not playing. Pause is idempotent — the
            # desired state IS the current state, so treat as success
            # instead of logging an ERROR Sentry event. The SoCo error
            # message format is stable: ``UPnP Error 701 received:
            # Transition not available from <ip>``.
            err = str(e)
            if "701" in err and "Transition not available" in err:
                return True
            logger.error("Sonos pause error: %s", e)
            return False

    async def set_volume(self, volume: int) -> bool:
        """
        Set speaker volume.

        Args:
            volume: Volume level (0-100).
        """
        if not self._connected or not self._device:
            return False
        try:
            vol = max(0, min(100, volume))
            await self._safe_mutation_call(setattr, self._device, "volume", vol)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            logger.error(f"Sonos volume error: {e}")
            return False

    async def ramp_volume(
        self,
        target: int,
        steps: int = 6,
        interval: float = 1.0,
    ) -> bool:
        """Gradually change Sonos volume from current level to target.

        Args:
            target:   Destination volume 0-100.
            steps:    Number of intermediate writes (minimum 1).
            interval: Seconds between writes.
        Returns:
            True if the ramp completed; False on Sonos error.
        """
        if not self._connected or not self._device:
            return False
        try:
            status = await self.get_status()
            current = int(status.get("volume", target))
        except Exception as e:
            logger.error("ramp_volume: could not read current volume: %s", e)
            return False
        if current == target:
            return True
        steps = max(1, steps)
        step_size = (target - current) / steps
        try:
            for i in range(1, steps + 1):
                next_vol = max(0, min(100, round(current + step_size * i)))
                await self.set_volume(next_vol)
                if i < steps:
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("ramp_volume error: %s", e)
            return False
        return True

    async def next_track(self) -> bool:
        """Skip to next track."""
        if not self._connected or not self._device:
            return False
        try:
            await self._safe_mutation_call(self._device.next)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            logger.error(f"Sonos next error: {e}")
            return False

    async def previous_track(self) -> bool:
        """Go to previous track."""
        if not self._connected or not self._device:
            return False
        try:
            await self._safe_mutation_call(self._device.previous)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            logger.error(f"Sonos previous error: {e}")
            return False

    async def play_uri(
        self,
        uri: str,
        volume: Optional[int] = None,
        meta: Optional[str] = None,
        force_radio: bool = False,
    ) -> bool:
        """
        Play an audio file or stream from a URI.

        Args:
            uri: HTTP URL of the audio file to play.
            volume: If set, volume is applied atomically before playback starts.
            meta: Optional DIDL-Lite XML envelope. Sonos sources Now Playing's
                title/artist/album/album-art from this — without it, plain HTTP
                self-hosted HTTP audio may show empty Now Playing. Build via
                ``backend.services.didl_lite.build_track_didl_lite``.
                Empty string or None falls through to SoCo's default behavior.
            force_radio: Treat the URI as a continuous internet-radio stream.
                SoCo rewrites it to the ``x-rincon-mp3radio:`` scheme that Sonos
                firmware ≥6.4.2 requires for plain HTTP radio (a bare http(s)
                stream URL is otherwise rejected). Use for the ambient
                nature-radio streams; leave False for finite files (TTS, loops).

        URIs are validated by ``is_allowed_play_uri`` here as the last-line
        defense-in-depth against SSRF for every caller.
        """
        if not is_allowed_play_uri(uri):
            logger.warning(
                "Refusing play_uri for non-allowlisted URI: %s", uri[:200]
            )
            return False
        if not self._connected or not self._device:
            return False
        try:
            def _play(device, uri, vol, meta_xml, radio):
                if vol is not None:
                    device.volume = max(0, min(100, vol))
                    logger.info(f"Sonos volume set to {vol} before play_uri")
                logger.info(f"Sonos actual volume now: {device.volume}")
                if not radio:
                    # play_mode is a persistent player setting; SHUFFLE
                    # (= shuffle + repeat-all, set by _shuffle_and_play)
                    # makes a single finite file loop forever — TTS clips
                    # repeated until manually paused. Force NORMAL for
                    # finite files; favorites re-apply SHUFFLE per play.
                    try:
                        if device.play_mode != "NORMAL":
                            device.play_mode = "NORMAL"
                    except Exception as exc:
                        logger.warning(f"play_mode reset failed: {exc}")
                if meta_xml:
                    device.play_uri(uri, meta=meta_xml, force_radio=radio)
                else:
                    device.play_uri(uri, force_radio=radio)
            await self._safe_mutation_call(_play, self._device, uri, volume, meta, force_radio)
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as e:
            logger.error(f"Sonos play_uri error: {e}")
            return False

    # Snapshot.snapshot()/.restore() bundle ~8-13 UPnP round-trips into one
    # sync call; the breaker's default 5s budget is sized for single calls.
    _SNAPSHOT_CALL_TIMEOUT = 15.0

    async def get_current_playback_snapshot(self) -> Optional["Snapshot"]:
        """Capture full player state for duck-and-resume via SoCo Snapshot.

        Captures ALWAYS — even when paused/stopped/idle — so restore()
        parks the TTS clip and returns the transport to its prior state
        (otherwise an idle-at-bedtime TTS leaves the transport sitting on
        the clip with nothing to stop it).

        Returns None on ANY failure (breaker open, UPnP error): TTS must
        still speak without a snapshot; tts_service keeps its own volume
        capture/restore as defense-in-depth.
        """
        if not self._connected or not self._device:
            return None
        try:
            # Lazy import, matching the module's no-soco-at-load policy.
            from soco.snapshot import Snapshot

            # snapshot_queue=False: play_uri doesn't clear the queue, so
            # the queue contents survive TTS without being re-captured.
            snap = Snapshot(self._device)
            await self._breaker.call(
                asyncio.to_thread, snap.snapshot,
                call_timeout=self._SNAPSHOT_CALL_TIMEOUT,
            )
            return snap
        except CircuitBreakerOpen:
            return None
        except Exception as e:
            logger.error(f"Sonos snapshot capture failed: {e}")
            return None

    async def restore_playback(self, snapshot: Optional["Snapshot"]) -> None:
        """Restore from a Snapshot taken by get_current_playback_snapshot.

        Snapshot.restore() pauses a still-playing TTS clip, rebuilds the
        transport (queue position + seek + play_mode for queue playback;
        URI + DIDL metadata for streams — its raw device.play_uri bypasses
        is_allowed_play_uri intentionally, the URI came from the device
        itself), restores volume/mute/EQ, then play()s only if the prior
        state was PLAYING / stop()s if STOPPED. The stream branch never
        touches play_mode, so repeat-all is never re-applied to a bare
        finite URI (the TTS-loop bug).

        Snapshot objects are single-use — never reuse across speak() calls.
        """
        if snapshot is None or not self._connected or not self._device:
            return
        try:
            await self._safe_mutation_call(
                snapshot.restore,
                call_timeout=self._SNAPSHOT_CALL_TIMEOUT,
            )
        except CircuitBreakerOpen:
            return
        except Exception as e:
            logger.error(f"Error restoring playback: {e}")

    async def _get_cloud_favorites_cached(self) -> list[dict[str, Any]]:
        """Fetch cloud favorites with TTL cache."""
        now = time.monotonic()
        if self._favorites_cache is not None and now - self._favorites_cache_time < self._CACHE_TTL:
            return self._favorites_cache

        results = []
        raw_objects = []
        try:
            favorites = await self._safe_call(
                self._device.music_library.get_sonos_favorites
            )
            for fav in favorites:
                # Use the exact same capability rule as play_favorite(): only
                # a resolved reference with concrete resources is queueable.
                # Apple Music artist/station shortcut favorites may expose a
                # display URI but still cannot be resolved by SoCo.
                ref = getattr(fav, "reference", fav)
                ref_resources = getattr(ref, "resources", None) or []
                uri = (
                    getattr(ref_resources[0], "uri", "")
                    if ref_resources
                    else getattr(fav, "uri", "")
                )
                results.append({
                    "title": fav.title,
                    "uri": uri,
                    "source": "favorite",
                    "playback_supported": bool(ref_resources),
                })
                raw_objects.append(fav)
        except CircuitBreakerOpen:
            return self._favorites_cache or []
        except Exception as e:
            logger.error(f"Error getting Sonos favorites: {e}")
            return self._favorites_cache or []

        self._favorites_cache = results
        self._favorites_objects_cache = raw_objects
        self._favorites_cache_time = now
        return results

    async def _get_sonos_playlists_cached(self):
        """Fetch Sonos playlists (raw SoCo objects) with TTL cache."""
        now = time.monotonic()
        if self._playlists_cache is not None and now - self._playlists_cache_time < self._CACHE_TTL:
            return self._playlists_cache

        try:
            playlists = await self._safe_call(
                self._device.get_sonos_playlists
            )
            self._playlists_cache = list(playlists)
            self._playlists_cache_time = now
            return self._playlists_cache
        except CircuitBreakerOpen:
            return self._playlists_cache or []
        except Exception as e:
            logger.error(f"Error getting Sonos playlists: {e}")
            return self._playlists_cache or []

    def invalidate_favorites_cache(self) -> None:
        """Clear the favorites/playlists cache so the next call fetches fresh data."""
        self._favorites_cache = None
        self._favorites_objects_cache = None
        self._favorites_cache_time = 0
        self._playlists_cache = None
        self._playlists_cache_time = 0

    async def get_favorites(self) -> list[dict[str, Any]]:
        """
        List Sonos favorites and Sonos playlists.

        Combines cloud-synced favorites with locally-created Sonos playlists
        (Era 100 / S2 firmware stores Apple Music items as playlists).

        Returns:
            List of dicts with title, uri, source, and playback_supported.
        """
        if not self._connected or not self._device:
            return []

        results = list(await self._get_cloud_favorites_cached())

        # Sonos playlists (where Apple Music items typically land)
        playlists = await self._get_sonos_playlists_cached()
        for pl in playlists:
            results.append({
                "title": pl.title,
                "uri": pl.get_uri() if hasattr(pl, "get_uri") else getattr(pl, "uri", ""),
                "source": "playlist",
                "playback_supported": True,
            })

        return results

    def _shuffle_and_play(self, device: "SoCo") -> None:
        """Set SHUFFLE play mode and start at a random queue index.

        Belt-and-suspenders for "always shuffle on play": SoCo's ``SHUFFLE``
        play_mode randomizes advancement, but the underlying renderer may
        still play queue position 0 first — picking a random start index
        guarantees the first track varies between replays. ``SHUFFLE`` =
        shuffle + repeat-all per SoCo's enum, so playlists also loop.

        Called as a sync function via ``_safe_call`` so the network writes
        run on the SoCo thread the rest of the service uses.
        """
        try:
            queue_size = int(getattr(device, "queue_size", 0))
        except Exception as exc:
            # Catches AttributeError, ValueError, TypeError as expected; also
            # SoCo's RuntimeError on UPnP failures (test_queue_size_unreadable_
            # falls_back_to_zero exercises this path). Log at debug so a
            # storm of UPnP errors surfaces under -vv without blocking
            # playback when one slips through.
            logger.debug("queue_size read failed: %s", exc)
            queue_size = 0
        device.play_mode = "SHUFFLE"
        start = random.randint(0, queue_size - 1) if queue_size > 1 else 0
        device.play_from_queue(start)

    def _replace_queue_if_unchanged_sync(
        self, item, expected: dict[str, Any],
    ) -> bool:
        """Replace the queue only if the fresh Sonos fingerprint still matches."""
        current = self._queue_ownership_evidence_sync()
        if any(
            current.get(key) != expected.get(key)
            for key in _AUDIO_OWNERSHIP_PROOF_KEYS
        ):
            return False
        self._device.clear_queue()
        self._device.add_to_queue(item)
        self._shuffle_and_play(self._device)
        return True

    async def play_favorite(
        self,
        title: str,
        *,
        expected_queue_evidence: dict[str, Any] | None = None,
    ) -> bool:
        """
        Play a Sonos favorite or playlist by title.

        Sonos playlists are matched first (saved-queue items), then cloud
        favorites. Both go through add_to_queue + play_from_queue using the
        raw SoCo DidlObject so SoCo can build the DIDL metadata internally.
        Non-queueable favorites (radio streams) fall back to play_uri with
        explicit metadata.

        Playback always starts in ``SHUFFLE`` mode at a random queue index —
        re-selecting a favorite picks a fresh track each time, and guests
        cycling through vibe tiles don't get stuck on the first few songs.

        Args:
            title: The favorite's display name (case-insensitive match).

        Returns:
            True if the favorite was found and playback started.
        """
        if not self._connected or not self._device:
            return False

        target = title.lower()

        # Check Sonos playlists first (where Apple Music items land)
        try:
            playlists = await self._get_sonos_playlists_cached()
            for pl in playlists:
                if pl.title.lower() == target:
                    if expected_queue_evidence is not None:
                        try:
                            replaced = await self._safe_mutation_call(
                                self._replace_queue_if_unchanged_sync,
                                pl,
                                dict(expected_queue_evidence),
                            )
                        except Exception as exc:
                            logger.warning(
                                "Owned queue replacement failed for '%s': %s",
                                pl.title, exc,
                            )
                            return False
                        if not replaced:
                            logger.info(
                                "Owned queue replacement refused for '%s': "
                                "Sonos changed before mutation",
                                pl.title,
                            )
                            return False
                    else:
                        try:
                            await self._safe_mutation_call(self._device.clear_queue)
                            await self._safe_mutation_call(self._device.add_to_queue, pl)
                            await self._safe_mutation_call(self._shuffle_and_play, self._device)
                        except Exception as e:
                            logger.warning(
                                "Queue play failed mid-sequence for '%s': %s — retrying",
                                pl.title, e,
                            )
                            try:
                                await self._safe_mutation_call(self._device.add_to_queue, pl)
                                await self._safe_mutation_call(self._shuffle_and_play, self._device)
                            except Exception as e2:
                                logger.error(
                                    "Queue recovery also failed for '%s': %s",
                                    pl.title, e2,
                                )
                                return False
                    logger.info(f"Playing Sonos playlist: {pl.title} (shuffled)")
                    return True
        except Exception as e:
            logger.error(f"Error searching Sonos playlists: {e}")

        # Fall back to cloud favorites. Two paths depending on whether the
        # favorite's reference has populated .resources:
        #   Path A — populated (playlists, albums): hand the raw SoCo object
        #     to add_to_queue and let SoCo serialize the DIDL internally.
        #   Path B — empty .resources: Apple Music library artist/station
        #     "shortcut" favorites. These have no static playable URI; the
        #     Sonos app resolves them on-tap via the Apple Music wire protocol,
        #     which SoCo's MusicService machinery doesn't implement for Apple
        #     Music. We can't queue them via any standard SOAP action — we
        #     verified this empirically against AddURIToQueue (UPnP 804) and
        #     SetAVTransportURI (UPnP 714) with every URI scheme/flag/metadata
        #     combo we could find. Detect and report clearly so Anthony knows
        #     to remap the mode to a playlist favorite that does work.
        await self._get_cloud_favorites_cached()
        for fav_obj in (self._favorites_objects_cache or []):
            if fav_obj.title.lower() != target:
                continue

            ref = getattr(fav_obj, "reference", fav_obj)
            ref_resources = getattr(ref, "resources", None) or []

            if ref_resources:
                # Path A: queue the SoCo object directly.
                try:
                    if expected_queue_evidence is not None:
                        replaced = await self._safe_mutation_call(
                            self._replace_queue_if_unchanged_sync,
                            ref,
                            dict(expected_queue_evidence),
                        )
                        if not replaced:
                            logger.info(
                                "Owned queue replacement refused for favorite '%s': "
                                "Sonos changed before mutation",
                                fav_obj.title,
                            )
                            return False
                    else:
                        await self._safe_mutation_call(self._device.clear_queue)
                        await self._safe_mutation_call(self._device.add_to_queue, ref)
                        await self._safe_mutation_call(self._shuffle_and_play, self._device)
                    logger.info(
                        f"Playing Sonos favorite via queue: {fav_obj.title} (shuffled)"
                    )
                    return True
                except Exception as e:
                    logger.error(
                        "Queue play failed for favorite '%s': %s",
                        fav_obj.title, e, exc_info=True,
                    )
                    return False

            # Path B: unsupported shortcut favorite (artist, station, etc.)
            ref_class = getattr(ref, "item_class", "unknown")
            logger.warning(
                "Cannot auto-play favorite '%s' — it's a shortcut to a %s "
                "container with no playable URI (Apple Music artist/station "
                "favorites require on-demand resolution that SoCo doesn't "
                "support). Re-map this mode to a playlist or album favorite.",
                fav_obj.title, ref_class,
            )
            return False

        favorites = await self._get_cloud_favorites_cached()
        available = [fav["title"] for fav in favorites]
        logger.warning(
            "Sonos favorite/playlist '%s' not found. Available: %s",
            title, available,
        )
        return False

    async def play_apple_music_share_link(
        self,
        provider_id: str,
        share_url: str,
        *,
        expected_queue_size: int | None = None,
        before_play=None,
    ) -> bool:
        """Play one exact Apple Music share link through Sonos.

        This is a low-level execution primitive only. Callers remain responsible
        for HomeHub lifecycle/ownership/trust policy before invoking it. The
        public Apple track ID must exactly match the share link identity; there
        is no title matching, provider credential, or URI fallback. The existing
        queue and play mode are preserved; #272 owns any later replace/ownership
        semantics.
        """
        provider_id = str(provider_id or "").strip()
        share_url = str(share_url or "").strip()
        if not provider_id.isdigit() or not share_url:
            return False
        if not self._connected or not self._device:
            return False

        try:
            canonical = self._canonical_apple_music_share_link(share_url)
        except Exception:
            return False
        if canonical != f"song:{provider_id}":
            return False

        queue_number: int | None = None
        try:
            queue_number = await self._safe_mutation_call(
                self._add_apple_music_share_link_sync, share_url,
            )
            if not isinstance(queue_number, int) or queue_number < 1:
                return False
            if (
                expected_queue_size is not None
                and queue_number != int(expected_queue_size) + 1
            ):
                logger.warning(
                    "Apple Music ShareLink queue changed during enqueue "
                    "(expected new position=%s, actual=%s); refusing play",
                    int(expected_queue_size) + 1, queue_number,
                )
                return False
            expected_snapshot = None
            queue_uid = None
            final_max_volume = None
            if expected_queue_size is not None:
                expected_snapshot = await self._safe_call(
                    self._queue_item_snapshot_sync, queue_number - 1, 1.0,
                )
                if expected_snapshot is None:
                    logger.warning(
                        "Apple Music ShareLink appended item could not be fingerprinted; refusing play"
                    )
                    return False
                queue_uid = await self._safe_call(lambda: str(self._device.uid))
                if not queue_uid:
                    return False
            if before_play is not None:
                guard_result = await before_play()
                if isinstance(guard_result, dict):
                    if guard_result.get("reason") is not None:
                        logger.warning(
                            "Apple Music ShareLink pre-play authority changed; refusing play"
                        )
                        return False
                    final_max_volume = int(guard_result.get("volume_used") or 0)
                elif not guard_result:
                    logger.warning(
                        "Apple Music ShareLink pre-play authority changed; refusing play"
                    )
                    return False
            if expected_snapshot is not None:
                # No await after the lifecycle guard: this bounded final UPnP
                # transaction serializes in-process authority and rechecks
                # external Sonos queue/transport/volume/mute immediately before play.
                played = self._play_queue_item_if_unchanged_sync(
                    queue_number - 1,
                    int(expected_queue_size) + 1,
                    expected_snapshot,
                    queue_uid=str(queue_uid),
                    max_volume=final_max_volume,
                )
                if not played:
                    logger.warning(
                        "Apple Music ShareLink queue/transport changed at final play boundary; refusing play"
                    )
                    return False
                verified = await self._verify_queue_playback_started(
                    queue_number - 1,
                    int(expected_queue_size) + 1,
                    expected_snapshot,
                    queue_uid=str(queue_uid),
                    max_volume=final_max_volume,
                )
                if not verified:
                    logger.warning(
                        "Apple Music ShareLink Play command did not produce a verified advancing stream"
                    )
                    return False
            else:
                await self._safe_mutation_call(self._device.play_from_queue, queue_number - 1)
            logger.info(
                "Playing verified Apple Music share-link item id=%s at queue=%s",
                provider_id, queue_number,
            )
            return True
        except CircuitBreakerOpen:
            return False
        except Exception as exc:
            logger.error(
                "Exact Apple Music share-link playback failed: %s; "
                "any successful append is retained rather than risking removal "
                "of a concurrently edited user queue",
                exc, exc_info=True,
            )
            return False

    def _queue_item_snapshot_sync(
        self, index: int, timeout: float | None = None,
    ) -> tuple | None:
        kwargs = {} if timeout is None else {"timeout": timeout}
        response = self._device.contentDirectory.Browse(
            [
                ("ObjectID", "Q:0"),
                ("BrowseFlag", "BrowseDirectChildren"),
                ("Filter", "*"),
                ("StartingIndex", index),
                ("RequestedCount", 1),
                ("SortCriteria", ""),
            ],
            **kwargs,
        )
        if int(response.get("NumberReturned") or 0) != 1:
            return None
        return (
            str(response.get("UpdateID") or ""),
            int(response.get("TotalMatches") or 0),
            str(response.get("Result") or ""),
        )

    @staticmethod
    def _final_timeout(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("assisted Sonos final transaction exceeded budget")
        return remaining

    def _play_queue_item_if_unchanged_sync(
        self, index: int, expected_queue_size: int, expected_snapshot: tuple,
        *, queue_uid: str, max_volume: int | None,
    ) -> bool:
        """Bounded final queue/ownership proof and play with no HomeHub await.

        This deliberately runs on the event-loop thread only after the async
        lifecycle guard. Every Sonos network call receives the remaining shared
        budget, bounding the event-loop stall while preventing in-process
        lifecycle state from advancing between permission and actuation.
        """
        deadline = time.monotonic() + ASSISTED_FINAL_BUDGET_SECONDS
        def timeout() -> float:
            return self._final_timeout(deadline)

        settings_result = self._device.avTransport.GetTransportSettings(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if str(settings_result.get("PlayMode") or "").upper() != "NORMAL":
            return False
        transport = self._device.avTransport.GetTransportInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        state = str(transport.get("CurrentTransportState") or "").upper()
        if state not in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return False
        volume = self._device.renderingControl.GetVolume(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        current_volume = int(volume.get("CurrentVolume") or 0)
        mute = self._device.renderingControl.GetMute(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        if bool(int(mute.get("CurrentMute") or 0)):
            return False
        if current_volume <= 0 or (max_volume is not None and current_volume != max_volume):
            return False
        snapshot = self._queue_item_snapshot_sync(index, timeout=timeout())
        if snapshot != expected_snapshot or snapshot[1] != int(expected_queue_size):
            return False

        uri = f"x-rincon-queue:{queue_uid}#0"
        self._device.avTransport.SetAVTransportURI(
            [("InstanceID", 0), ("CurrentURI", uri), ("CurrentURIMetaData", "")],
            timeout=timeout(),
        )
        self._device.avTransport.Seek(
            [("InstanceID", 0), ("Unit", "TRACK_NR"), ("Target", index + 1)],
            timeout=timeout(),
        )

        # The explicit HomeHub request owns this bounded transport transaction
        # after the async guard. Re-prove the prepared source/track and every
        # externally mutable ownership fact after setup and immediately before
        # Play so a competing Sonos-app action that wins during setup aborts.
        media = self._device.avTransport.GetMediaInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if str(media.get("CurrentURI") or "") != uri:
            return False
        position = self._device.avTransport.GetPositionInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if int(position.get("Track") or 0) != index + 1:
            return False
        settings_result = self._device.avTransport.GetTransportSettings(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if str(settings_result.get("PlayMode") or "").upper() != "NORMAL":
            return False
        transport = self._device.avTransport.GetTransportInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        state = str(transport.get("CurrentTransportState") or "").upper()
        if state not in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return False
        snapshot = self._queue_item_snapshot_sync(index, timeout=timeout())
        if snapshot != expected_snapshot or snapshot[1] != int(expected_queue_size):
            return False
        volume = self._device.renderingControl.GetVolume(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        mute = self._device.renderingControl.GetMute(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        current_volume = int(volume.get("CurrentVolume") or 0)
        if bool(int(mute.get("CurrentMute") or 0)) or current_volume <= 0:
            return False
        if max_volume is not None and current_volume != max_volume:
            return False
        self._device.avTransport.Play(
            [("InstanceID", 0), ("Speed", 1)], timeout=timeout(),
        )
        return True

    async def _verify_queue_playback_started(
        self, index: int, expected_queue_size: int, expected_snapshot: tuple,
        *, queue_uid: str, max_volume: int | None,
    ) -> bool:
        """Prove that the exact queued track actually entered advancing playback.

        A successful UPnP ``Play`` response is only command acceptance. For the
        assisted-playback contract we additionally require the same queue object
        and queue source to remain selected, transport to reach PLAYING, and the
        reported relative position to advance by at least one second inside a
        bounded window. Any ownership/source/queue/volume mismatch fails closed.
        """
        deadline = time.monotonic() + ASSISTED_START_VERIFY_SECONDS
        first_playing_position: float | None = None
        saw_playing = False

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            sample_budget = min(ASSISTED_START_SAMPLE_BUDGET_SECONDS, remaining)
            if sample_budget <= 0:
                break
            try:
                sample = await self._breaker.call(
                    asyncio.to_thread,
                    self._playback_start_sample_sync,
                    index, expected_queue_size, expected_snapshot,
                    queue_uid, max_volume, sample_budget,
                    call_timeout=sample_budget,
                )
            except Exception as exc:
                logger.warning("Assisted playback start verification failed: %s", exc)
                return False
            if sample is None:
                return False

            state = str(sample.get("state") or "").upper()
            position = sample.get("position")
            if state == "PLAYING":
                saw_playing = True
                if position is not None:
                    position = float(position)
                    if first_playing_position is None:
                        first_playing_position = position
                    elif position - first_playing_position >= ASSISTED_START_MIN_ADVANCE_SECONDS:
                        return True
            elif state == "PAUSED_PLAYBACK":
                return False
            elif saw_playing and state not in {"TRANSITIONING"}:
                return False
            elif state not in {"STOPPED", "NO_MEDIA_PRESENT", "TRANSITIONING"}:
                return False

            sleep_for = min(ASSISTED_START_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
        return False

    def _playback_start_sample_sync(
        self, index: int, expected_queue_size: int, expected_snapshot: tuple,
        queue_uid: str, max_volume: int | None, budget_seconds: float,
    ) -> dict[str, Any] | None:
        """Return one bounded exact-owner playback-start sample or fail closed."""
        deadline = time.monotonic() + max(0.05, float(budget_seconds))

        def timeout() -> float:
            return self._final_timeout(deadline)

        settings_result = self._device.avTransport.GetTransportSettings(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if str(settings_result.get("PlayMode") or "").upper() != "NORMAL":
            return None

        media = self._device.avTransport.GetMediaInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        expected_uri = f"x-rincon-queue:{queue_uid}#0"
        if str(media.get("CurrentURI") or "") != expected_uri:
            return None

        position = self._device.avTransport.GetPositionInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        if int(position.get("Track") or 0) != index + 1:
            return None

        snapshot = self._queue_item_snapshot_sync(index, timeout=timeout())
        if snapshot != expected_snapshot or snapshot[1] != int(expected_queue_size):
            return None

        volume = self._device.renderingControl.GetVolume(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        mute = self._device.renderingControl.GetMute(
            [("InstanceID", 0), ("Channel", "Master")], timeout=timeout(),
        )
        current_volume = int(volume.get("CurrentVolume") or 0)
        if bool(int(mute.get("CurrentMute") or 0)) or current_volume <= 0:
            return None
        if max_volume is not None and current_volume != max_volume:
            return None

        transport = self._device.avTransport.GetTransportInfo(
            [("InstanceID", 0)], timeout=timeout(),
        )
        return {
            "state": str(transport.get("CurrentTransportState") or "").upper(),
            "position": self._parse_hms(position.get("RelTime")),
        }

    @staticmethod
    def _canonical_apple_music_share_link(share_url: str) -> str | None:
        from soco.plugins.sharelink import AppleMusicShare

        return AppleMusicShare().canonical_uri(share_url)

    def _add_apple_music_share_link_sync(self, share_url: str) -> int:
        from soco.plugins.sharelink import ShareLinkPlugin

        return ShareLinkPlugin(self._device).add_share_link_to_queue(share_url)

    async def poll_state_loop(self, ws_manager) -> None:
        """
        Continuously poll Sonos state and broadcast changes via WebSocket.

        Runs as a background task. Detects track changes, play/pause,
        volume adjustments from the Sonos app or physical controls. When
        attach_event_logger() has been called, also emits skip events for
        track changes that look like user skips (track changed while the
        prior track's last-observed position was below the natural-end
        threshold — see _classify_track_change).
        """
        logger.info("Starting Sonos state polling")

        while True:
            try:
                if self._heartbeat is not None:
                    self._heartbeat.tick("sonos")
                status = await self.get_status()

                # Only broadcast if something changed
                if status != self._last_status:
                    # Off-dashboard track-boundary detection before stamping
                    # _last_status. Best-effort - never raises.
                    if self._last_status is not None:
                        try:
                            await self._maybe_emit_skip(self._last_status, status)
                        except Exception:
                            logger.debug("skip-emit failed", exc_info=True)
                    self._last_status = status
                    await ws_manager.broadcast("sonos_update", status)

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info("Sonos polling stopped")
                break
            except Exception as e:
                logger.error(f"Sonos polling error: {e}")
                await asyncio.sleep(5)

    @staticmethod
    def _parse_hms(s: Optional[str]) -> Optional[float]:
        """Parse Sonos' ``H:MM:SS`` / ``MM:SS`` time string into seconds.

        Returns None on empty / malformed input. SoCo returns ``"0:00:00"``
        when transport is idle and ``"NOT_IMPLEMENTED"`` for some sources
        (streams without duration). Both yield None.
        """
        if not s or s == "NOT_IMPLEMENTED":
            return None
        try:
            parts = [float(p) for p in s.split(":")]
        except ValueError:
            return None
        if len(parts) == 3:
            h, m, sec = parts
            return h * 3600 + m * 60 + sec
        if len(parts) == 2:
            m, sec = parts
            return m * 60 + sec
        return None

    async def _surrender_owned_queue_for_track_change(self, *, reason: str) -> None:
        """Surrender cleanup authority on any external track boundary."""
        if self._audio_ownership is None:
            return
        from backend.services.audio_ownership import MANUAL_TRANSPORT_DIMENSIONS
        try:
            await self._audio_ownership.invalidate_manual(
                MANUAL_TRANSPORT_DIMENSIONS,
                source="sonos_poll",
                reason=reason,
            )
        except Exception:
            logger.debug(
                "track-change audio ownership invalidation failed",
                exc_info=True,
            )

    async def _maybe_emit_skip(self, prev: dict, new: dict) -> None:
        """Emit ``event_type='skip'`` when a track change looks like a user skip.

        Heuristic: title changed AND the prior track's last-observed
        position was below the natural-end threshold. Natural end = within
        10s of duration OR position >= 80% of duration. Stream sources
        without a parsable duration are treated as natural-end (we can't
        tell skip from track-end on Spotify/Apple Music radio streams, so
        we err on the side of not polluting the bandit signal).

        Matches the bandit's PENALTY_SKIP window indirectly: the bandit's
        ``retrain`` only counts a skip when it follows an ``auto_play``
        within 30s (music_bandit.py:355–363). Skips outside that window
        land in the table but don't penalize the arm — same intent.

        Event logging is optional. When the shared audio ownership authority
        is attached, a confirmed off-dashboard skip also invalidates conflicting
        autonomous queue/transport leases before a later mode-exit cleanup can
        mistake the user-controlled session for HomeHub-owned state.
        """
        prev_title = (prev.get("track") or "").strip()
        new_title = (new.get("track") or "").strip()
        # No emission if title didn't actually change. Empty-string
        # transitions (idle → first track or last track → stop) also skip.
        if not prev_title or not new_title or prev_title == new_title:
            return
        # Only consider PLAYING-to-PLAYING transitions. A pause/stop in
        # between is the user actively controlling, not a skip signal.
        if prev.get("state") != "PLAYING" or new.get("state") != "PLAYING":
            return

        # Sonos exposes only coarse position evidence here, so HomeHub cannot
        # prove whether an off-dashboard boundary was a natural queue advance
        # or a physical/app Next/Previous. Manual intent must win: surrender
        # destructive queue/transport cleanup authority for every such boundary.
        await self._surrender_owned_queue_for_track_change(
            reason="off_dashboard_track_boundary",
        )

        position_s = self._parse_hms(prev.get("position"))
        duration_s = self._parse_hms(prev.get("duration"))
        if position_s is None or duration_s is None or duration_s <= 0:
            return  # ownership already surrendered; skip learning is ambiguous

        # Keep the historical broad heuristic only for preference logging.
        natural_end_threshold = max(duration_s - 10.0, 0.8 * duration_s)
        if position_s >= natural_end_threshold:
            return

        # Preference logging remains optional. mode_at_time mirrors the
        # dashboard-skip path; weather_class is best-effort downstream.
        if self._event_logger is not None:
            mode = self._automation.current_mode if self._automation else None
            try:
                await self._event_logger.log_sonos_event(
                    event_type="skip",
                    favorite_title=prev_title,
                    mode_at_time=mode,
                    triggered_by="off_dashboard",
                )
            except Exception:
                logger.debug("event_logger.log_sonos_event raised", exc_info=True)

        logger.info(
            "Sonos skip detected (off-dashboard): '%s' at %.0fs / %.0fs",
            prev_title, position_s, duration_s,
        )
