"""
Text-to-Speech service — generates audio and plays it on Sonos.

Uses edge-tts (free Microsoft voices) as the primary engine.
Falls back to gTTS (Google) if edge-tts fails.
"""
import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Optional

from backend.services.audio_ownership import (
    AUDIO_DIMENSIONS,
    MANUAL_TRANSPORT_DIMENSIONS,
    MANUAL_VOLUME_DIMENSIONS,
    QUEUE_SOURCE,
    TRANSPORT,
    VOLUME,
)

logger = logging.getLogger("home_hub.tts")

TTS_AUDIO_OWNER = "tts"
TTS_AUDIO_PURPOSE = "announcement"
TTS_SOURCE_TRANSPORT_DIMENSIONS = frozenset({QUEUE_SOURCE, TRANSPORT})


class TTSService:
    """
    Converts text to speech and plays it on the Sonos speaker.

    Flow: text → edge-tts generates MP3 → save to static/tts/ →
          FastAPI serves the file → SoCo play_uri() → Sonos plays it.

    Implements duck-and-resume via SoCo Snapshot: full player state is
    captured before every TTS (even when idle), volume is set for the
    clip, then restore rebuilds the transport — resuming music where it
    left off, or parking a finished clip when the speaker was idle.
    """

    def __init__(
        self,
        sonos_service,
        static_dir: Path,
        local_ip: str,
        voice: str = "en-US-GuyNeural",
        default_volume: int = 80,
        server_port: int = 8000,
        audio_ownership: Any = None,
    ) -> None:
        self._sonos = sonos_service
        self._tts_dir = static_dir / "tts"
        self._local_ip = local_ip
        self._voice = voice
        self._default_volume = default_volume
        self._server_port = server_port
        self._audio_ownership = audio_ownership
        self._speaking = False
        self._shutdown = False
        # TTS owns a snapshot/play/restore transaction on one shared Sonos
        # player. Keep the lock with this service instance, which is created
        # once for the application's event loop, rather than sharing a
        # module-level lock across application lifecycles.
        self._speak_lock = asyncio.Lock()
        self._tts_dir.mkdir(parents=True, exist_ok=True)
        # Strong references for fire-and-forget cleanup tasks. The event
        # loop only weak-refs tasks created via asyncio.create_task; without
        # a strong ref the GC can drop a still-sleeping cleanup task,
        # firing the asyncio "Task was destroyed but it is pending!" warning
        # (and leaking the MP3 file on disk).
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._cleanup_paths: dict[asyncio.Task, Path] = {}
        # Track every live speak() caller, including fire-and-forget tasks
        # created outside this service. Shutdown cancels and joins them so no
        # announcement can acquire ownership or mutate Sonos after close().
        self._speech_tasks: set[asyncio.Task] = set()

    def attach_audio_ownership(self, audio_ownership: Any) -> None:
        """Attach #274 authority after bootstrap constructs persisted settings."""
        self._audio_ownership = audio_ownership

    @property
    def is_speaking(self) -> bool:
        """True between TTS start and finally-block volume/playback restore.

        Mode-change callbacks that touch Sonos volume (e.g. ModeVolumeService)
        consult this to defer their ramp — TTS's duck-and-resume snapshots
        ``original_volume``, so a mid-TTS volume write would be clobbered on
        restore.
        """
        return self._speaking

    async def close(self) -> None:
        """Stop TTS-owned work and leave no post-close Sonos/file activity."""
        self._shutdown = True

        current = asyncio.current_task()
        speech_tasks = [
            task
            for task in self._speech_tasks
            if task is not current and not task.done()
        ]
        for task in speech_tasks:
            task.cancel()
        if speech_tasks:
            await asyncio.gather(*speech_tasks, return_exceptions=True)

        cleanup_tasks = list(self._cleanup_tasks)
        cleanup_paths = set(self._cleanup_paths.values())
        for task in cleanup_tasks:
            task.cancel()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        # A cleanup task cancelled before its coroutine first runs may never
        # execute its own finally block, so close owns a deterministic sweep.
        for path in cleanup_paths:
            try:
                if path.exists():
                    path.unlink()
                    logger.debug("Cleaned up TTS file during shutdown: %s", path.name)
            except Exception as exc:
                logger.warning("Failed shutdown cleanup for %s: %s", path.name, exc)

        self._cleanup_tasks.clear()
        self._cleanup_paths.clear()

    async def recover_stale_interruption(self) -> None:
        """Retire process-orphaned TTS leases without touching Sonos."""
        if self._audio_ownership is None:
            return
        while True:
            lease = await self._audio_ownership.find_lease(
                owner=TTS_AUDIO_OWNER,
                purpose=TTS_AUDIO_PURPOSE,
            )
            if lease is None:
                return
            retired = await self._audio_ownership.abandon_interruption(
                lease["lease_id"],
                reason="tts_restart_safe_abandonment",
            )
            logger.info(
                "Retired stale TTS interruption lease=%s and %d overlaid "
                "owner(s) without Sonos mutation",
                lease["lease_id"],
                len(retired),
            )

    @staticmethod
    def _same_preflight(
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> bool:
        if not before or not after:
            return False
        keys = (
            "queue_uid",
            "queue_update_id",
            "queue_size",
            "queue_first_item_hash",
            "play_mode",
            "transport_state",
            "current_uri",
            "queue_track",
            "queue_track_uri",
            "volume",
            "mute",
        )
        return all(before.get(key) == after.get(key) for key in keys)

    def _forget_cleanup_task(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.discard(task)
        self._cleanup_paths.pop(task, None)

    def _schedule_cleanup(self, mp3_path: Optional[Path]) -> None:
        if mp3_path is None or not mp3_path.exists():
            return
        if self._shutdown:
            try:
                mp3_path.unlink()
                logger.debug(
                    "Cleaned up TTS file immediately during shutdown: %s",
                    mp3_path.name,
                )
            except Exception as exc:
                logger.warning(
                    "Failed immediate shutdown cleanup for %s: %s",
                    mp3_path.name,
                    exc,
                )
            return
        task = asyncio.create_task(self._cleanup_file(mp3_path, delay=60))
        self._cleanup_tasks.add(task)
        self._cleanup_paths[task] = mp3_path
        task.add_done_callback(self._forget_cleanup_task)

    async def speak(
        self,
        text: str,
        volume: Optional[int] = None,
        *,
        manual_source: Optional[str] = None,
        manual_reason: Optional[str] = None,
    ) -> bool:
        """Generate TTS and conditionally duck/restore Sonos.

        When central ownership is available, TTS uses a temporary interruption
        overlay. Newer manual source/transport/volume intent strips only the
        corresponding restore dimensions, so stale snapshots can never win
        after the user takes over.
        """
        if not text.strip() or self._shutdown:
            return False
        if not self._sonos.connected:
            logger.warning("Cannot speak — Sonos not connected")
            return False

        current = asyncio.current_task()
        if current is not None:
            self._speech_tasks.add(current)
        try:
            async with self._speak_lock:
                if self._shutdown:
                    return False
                vol = volume if volume is not None else self._default_volume
                logger.info(
                    "TTS requested volume=%s, default=%s, using vol=%s",
                    volume, self._default_volume, vol,
                )
                if self._audio_ownership is None:
                    return await self._speak_without_ownership(text, vol)
                return await self._speak_with_ownership(
                    text,
                    vol,
                    manual_source=manual_source,
                    manual_reason=manual_reason,
                )
        finally:
            if current is not None:
                self._speech_tasks.discard(current)

    async def _speak_without_ownership(self, text: str, vol: int) -> bool:
        """Legacy fallback for tests/partial bootstrap without #274 authority."""
        mp3_path: Optional[Path] = None
        snapshot = None
        original_volume: Optional[int] = None
        success = False
        self._speaking = True
        try:
            mp3_path = await self._generate_audio(text)
            if not mp3_path:
                return False
            audio_url = (
                f"http://{self._local_ip}:{self._server_port}"
                f"/static/tts/{mp3_path.name}"
            )
            snapshot = await self._sonos.get_current_playback_snapshot()
            status = await self._sonos.get_status()
            original_volume = status.get("volume", vol)
            success = await self._sonos.play_uri(audio_url, volume=vol)
            if success:
                logger.info("TTS playing: '%s...' at volume %s", text[:50], vol)
                await asyncio.sleep(max(2.0, len(text.split()) * 0.4 + 1.0))
            return success
        except Exception as exc:
            logger.error("TTS error: %s", exc, exc_info=True)
            return False
        finally:
            if not self._shutdown:
                if original_volume is not None:
                    try:
                        await self._sonos.set_volume(original_volume)
                    except Exception as exc:
                        logger.error("TTS restore volume failed: %s", exc)
                if snapshot:
                    try:
                        await self._sonos.restore_playback(snapshot)
                    except Exception as exc:
                        logger.error("TTS restore playback failed: %s", exc)
            self._schedule_cleanup(mp3_path)
            self._speaking = False

    async def _speak_with_ownership(
        self,
        text: str,
        vol: int,
        *,
        manual_source: Optional[str],
        manual_reason: Optional[str],
    ) -> bool:
        mp3_path: Optional[Path] = None
        snapshot = None
        preflight: dict[str, Any] | None = None
        lease_id: Optional[str] = None
        audio_url = ""
        success = False

        try:
            # Do network TTS generation before claiming the physical speaker.
            mp3_path = await self._generate_audio(text)
            if not mp3_path:
                return False
            audio_url = (
                f"http://{self._local_ip}:{self._server_port}"
                f"/static/tts/{mp3_path.name}"
            )

            lease = await self._audio_ownership.acquire_interruption(
                owner=TTS_AUDIO_OWNER,
                purpose=TTS_AUDIO_PURPOSE,
                dimensions=AUDIO_DIMENSIONS,
                evidence={"phase": "reserved"},
                metadata={
                    "source": manual_source or "autonomous",
                    "reason": manual_reason,
                },
                manual_source=manual_source,
                manual_reason=manual_reason,
            )
            if lease is None:
                logger.info("TTS suppressed: audio interruption authority unavailable")
                return False
            lease_id = lease["lease_id"]
            self._speaking = True

            # Snapshot only a stable Sonos state. A HomeHub manual action
            # invalidates the lease; an off-dashboard change is caught by the
            # before/after fingerprint and aborts before TTS actuation.
            before = await self._sonos.get_playback_ownership_evidence()
            snapshot = await self._sonos.get_current_playback_snapshot()
            preflight = await self._sonos.get_playback_ownership_evidence()
            if snapshot is None or not self._same_preflight(before, preflight):
                logger.info("TTS suppressed: Sonos changed during snapshot capture")
                return False
            if getattr(snapshot, "is_playing_cloud_queue", False) is True:
                logger.info(
                    "TTS suppressed: current Sonos cloud queue cannot be restored safely"
                )
                return False

            await self._audio_ownership.update_evidence(
                lease_id,
                {
                    "phase": "reserved",
                    "preflight": dict(preflight),
                    "tts_uri": audio_url,
                    "tts_volume": int(vol),
                },
            )

            async def _play_owned() -> bool:
                return await self._sonos.play_uri_if_unchanged(
                    preflight,
                    audio_url,
                    volume=vol,
                )

            executed, played = await self._audio_ownership.run_if_valid(
                lease_id,
                AUDIO_DIMENSIONS,
                _play_owned,
            )
            success = bool(executed and played)
            if not success:
                logger.info("TTS play refused: interruption authority/evidence changed")
                return False

            await self._audio_ownership.update_evidence(
                lease_id,
                {
                    "phase": "speaking",
                    "preflight": dict(preflight),
                    "tts_uri": audio_url,
                    "tts_volume": int(vol),
                },
            )
            logger.info(
                "TTS playing under interruption lease=%s: '%s...' at volume %s",
                lease_id, text[:50], vol,
            )
            await asyncio.sleep(max(2.0, len(text.split()) * 0.4 + 1.0))
            return True
        except Exception as exc:
            logger.error("TTS error: %s", exc, exc_info=True)
            return False
        finally:
            if lease_id is not None:
                restore_safe = False
                try:
                    if not self._shutdown:
                        restore_safe = await self._restore_owned_interruption(
                            lease_id=lease_id,
                            snapshot=snapshot,
                            preflight=preflight,
                            audio_url=audio_url,
                            tts_volume=vol,
                            play_succeeded=success,
                        )
                except asyncio.CancelledError:
                    # If restore itself is interrupted, physical provenance is
                    # unknown: retire the overlay and the owners beneath it.
                    restore_safe = False
                    raise
                except Exception:
                    restore_safe = False
                    logger.exception("TTS conditional restore failed")
                finally:
                    if await self._audio_ownership.is_valid(lease_id):
                        if restore_safe:
                            await self._audio_ownership.release(
                                lease_id,
                                reason="tts_complete",
                            )
                        else:
                            await self._audio_ownership.abandon_interruption(
                                lease_id,
                                reason=(
                                    "tts_shutdown_abandonment"
                                    if self._shutdown
                                    else "tts_restore_unproven"
                                ),
                            )
            self._schedule_cleanup(mp3_path)
            self._speaking = False

    async def _restore_owned_interruption(
        self,
        *,
        lease_id: str,
        snapshot: Any,
        preflight: dict[str, Any] | None,
        audio_url: str,
        tts_volume: int,
        play_succeeded: bool,
    ) -> bool:
        """Restore what is still owned and report whether provenance is safe."""
        if snapshot is None or preflight is None:
            return not play_succeeded

        if not play_succeeded:
            fresh = await self._sonos.get_playback_ownership_evidence()
            if fresh is None:
                return False
            # The conditional play can fail without issuing any device write.
            # In that case there is nothing to restore or invalidate.
            if self._same_preflight(preflight, fresh):
                return True

        # Restore rendering first so resumed audio never comes back at the
        # elevated announcement volume. Manual volume intent strips VOLUME and
        # therefore skips this branch while still allowing source restoration.
        if await self._audio_ownership.is_valid(lease_id, (VOLUME,)):
            async def _restore_volume() -> dict[str, Any]:
                return await self._sonos.restore_tts_snapshot_if_unchanged(
                    snapshot,
                    preflight=preflight,
                    tts_uri=audio_url,
                    tts_volume=tts_volume,
                    restore_source_transport=False,
                    restore_volume=True,
                    play_failed=not play_succeeded,
                )

            executed, result = await self._audio_ownership.run_if_valid(
                lease_id,
                (VOLUME,),
                _restore_volume,
            )
            if executed:
                if not result:
                    return False
                if not result.get("volume_restored"):
                    reason = str(result.get("volume_reason") or "")
                    if reason in {"volume_changed", "mute_changed"}:
                        await self._audio_ownership.invalidate_manual(
                            MANUAL_VOLUME_DIMENSIONS,
                            source="sonos_evidence",
                            reason=f"tts_external_{reason}",
                        )
                    else:
                        return False

        if not await self._audio_ownership.is_valid(
            lease_id, TTS_SOURCE_TRANSPORT_DIMENSIONS,
        ):
            # A newer manual source/transport action already won.
            return True

        async def _restore_source() -> dict[str, Any]:
            return await self._sonos.restore_tts_snapshot_if_unchanged(
                snapshot,
                preflight=preflight,
                tts_uri=audio_url,
                tts_volume=tts_volume,
                restore_source_transport=True,
                restore_volume=False,
                play_failed=not play_succeeded,
            )

        executed, result = await self._audio_ownership.run_if_valid(
            lease_id,
            TTS_SOURCE_TRANSPORT_DIMENSIONS,
            _restore_source,
        )
        if not executed:
            # Lease loss between the check and operation means newer manual
            # authority won under the central lock.
            return True
        if not result:
            return False
        if result.get("source_transport_restored"):
            return True

        reason = str(result.get("source_transport_reason") or "")
        if reason in {
            "source_changed",
            "queue_changed",
            "transport_paused",
            "transport_stopped_early",
        } or reason.startswith("transport_"):
            await self._audio_ownership.invalidate_manual(
                MANUAL_TRANSPORT_DIMENSIONS,
                source="sonos_evidence",
                reason=f"tts_external_{reason}",
            )
            return True

        # Unrestorable cloud queue, breaker/unavailable restore, or a
        # prepare/post-restore mismatch leaves physical provenance ambiguous.
        return False

    async def _generate_audio(self, text: str) -> Optional[Path]:
        """
        Generate an MP3 file from text.

        Tries edge-tts first, falls back to gTTS.
        """
        # Use text hash as filename to avoid regenerating identical audio
        text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
        timestamp = int(time.time())
        filename = f"tts_{text_hash}_{timestamp}.mp3"
        output_path = self._tts_dir / filename

        # Try edge-tts (preferred — async, natural voices)
        try:
            import edge_tts

            communicate = edge_tts.Communicate(text, self._voice)
            await communicate.save(str(output_path))
            logger.info(f"Generated TTS audio via edge-tts: {filename}")
            return output_path
        except ImportError:
            logger.warning("edge-tts not installed, trying gTTS fallback")
        except Exception as e:
            logger.warning(f"edge-tts failed: {e}, trying gTTS fallback")

        # Fallback: gTTS (synchronous, requires internet)
        try:
            from gtts import gTTS

            tts = gTTS(text=text, lang="en")
            await asyncio.to_thread(tts.save, str(output_path))
            logger.info(f"Generated TTS audio via gTTS: {filename}")
            return output_path
        except ImportError:
            logger.error("Neither edge-tts nor gTTS installed")
        except Exception as e:
            logger.error(f"gTTS failed: {e}")

        return None

    async def _cleanup_file(self, path: Path, delay: int = 60) -> None:
        """Delete a TTS file after a delay."""
        await asyncio.sleep(delay)
        try:
            if path.exists():
                path.unlink()
                logger.debug(f"Cleaned up TTS file: {path.name}")
        except Exception as e:
            logger.warning(f"Failed to clean up {path.name}: {e}")
