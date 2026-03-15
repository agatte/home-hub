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
from typing import Optional

logger = logging.getLogger("home_hub.tts")


class TTSService:
    """
    Converts text to speech and plays it on the Sonos speaker.

    Flow: text → edge-tts generates MP3 → save to static/tts/ →
          FastAPI serves the file → SoCo play_uri() → Sonos plays it.

    Implements duck-and-resume: if music is playing, saves state,
    lowers volume, plays TTS, then restores playback.
    """

    def __init__(
        self,
        sonos_service,
        static_dir: Path,
        local_ip: str,
        voice: str = "en-US-GuyNeural",
        default_volume: int = 80,
        server_port: int = 8000,
    ) -> None:
        self._sonos = sonos_service
        self._tts_dir = static_dir / "tts"
        self._local_ip = local_ip
        self._voice = voice
        self._default_volume = default_volume
        self._server_port = server_port
        self._tts_dir.mkdir(parents=True, exist_ok=True)

    async def speak(
        self,
        text: str,
        volume: Optional[int] = None,
    ) -> bool:
        """
        Generate TTS audio and play it on the Sonos speaker.

        Args:
            text: The text to speak.
            volume: Playback volume (0-100). Uses default if not set.

        Returns:
            True if the audio was played successfully.
        """
        if not text.strip():
            return False

        if not self._sonos.connected:
            logger.warning("Cannot speak — Sonos not connected")
            return False

        vol = volume or self._default_volume

        try:
            # Generate MP3
            mp3_path = await self._generate_audio(text)
            if not mp3_path:
                return False

            # Build URL that Sonos can fetch from our FastAPI server
            filename = mp3_path.name
            audio_url = (
                f"http://{self._local_ip}:{self._server_port}"
                f"/static/tts/{filename}"
            )

            # Duck-and-resume: save current playback state
            snapshot = await self._sonos.get_current_playback_snapshot()

            # Set volume for TTS
            original_volume = (await self._sonos.get_status()).get("volume", vol)
            await self._sonos.set_volume(vol)

            # Play the TTS audio
            success = await self._sonos.play_uri(audio_url)

            if success:
                logger.info(f"TTS playing: '{text[:50]}...' at volume {vol}")

                # Wait for TTS to finish (estimate ~100ms per word + buffer)
                word_count = len(text.split())
                wait_time = max(2.0, word_count * 0.4 + 1.0)
                await asyncio.sleep(wait_time)

                # Restore previous playback
                if snapshot:
                    await self._sonos.set_volume(original_volume)
                    await self._sonos.restore_playback(snapshot)
                else:
                    await self._sonos.set_volume(original_volume)

            # Schedule cleanup
            asyncio.create_task(self._cleanup_file(mp3_path, delay=60))

            return success

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
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
