"""
Sonos speaker service — wraps SoCo for local UPnP control.
"""
import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("home_hub.sonos")


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

    @property
    def connected(self) -> bool:
        """Whether a Sonos speaker has been found."""
        return self._connected

    @property
    def device(self):
        """The underlying SoCo device object."""
        return self._device

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
            transport = await asyncio.to_thread(
                self._device.get_current_transport_info
            )
            track = await asyncio.to_thread(self._device.get_current_track_info)
            volume = await asyncio.to_thread(lambda: self._device.volume)
            mute = await asyncio.to_thread(lambda: self._device.mute)

            return {
                "state": transport.get("current_transport_state", "STOPPED"),
                "track": track.get("title", ""),
                "artist": track.get("artist", ""),
                "album": track.get("album", ""),
                "art_url": track.get("album_art", ""),
                "duration": track.get("duration", "0:00:00"),
                "position": track.get("position", "0:00:00"),
                "volume": volume,
                "mute": mute,
            }
        except Exception as e:
            logger.error(f"Error getting Sonos status: {e}")
            return {"state": "error", "error": str(e)}

    async def play(self) -> bool:
        """Resume playback."""
        if not self._connected or not self._device:
            return False
        try:
            await asyncio.to_thread(self._device.play)
            return True
        except Exception as e:
            logger.error(f"Sonos play error: {e}")
            return False

    async def pause(self) -> bool:
        """Pause playback."""
        if not self._connected or not self._device:
            return False
        try:
            await asyncio.to_thread(self._device.pause)
            return True
        except Exception as e:
            logger.error(f"Sonos pause error: {e}")
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
            await asyncio.to_thread(setattr, self._device, "volume", vol)
            return True
        except Exception as e:
            logger.error(f"Sonos volume error: {e}")
            return False

    async def next_track(self) -> bool:
        """Skip to next track."""
        if not self._connected or not self._device:
            return False
        try:
            await asyncio.to_thread(self._device.next)
            return True
        except Exception as e:
            logger.error(f"Sonos next error: {e}")
            return False

    async def previous_track(self) -> bool:
        """Go to previous track."""
        if not self._connected or not self._device:
            return False
        try:
            await asyncio.to_thread(self._device.previous)
            return True
        except Exception as e:
            logger.error(f"Sonos previous error: {e}")
            return False

    async def play_uri(self, uri: str, volume: Optional[int] = None) -> bool:
        """
        Play an audio file or stream from a URI.

        Args:
            uri: HTTP URL of the audio file to play.
            volume: If set, volume is applied atomically before playback starts.
        """
        if not self._connected or not self._device:
            return False
        try:
            def _play(device, uri, vol):
                if vol is not None:
                    device.volume = max(0, min(100, vol))
                    logger.info(f"Sonos volume set to {vol} before play_uri")
                logger.info(f"Sonos actual volume now: {device.volume}")
                device.play_uri(uri)
            await asyncio.to_thread(_play, self._device, uri, volume)
            return True
        except Exception as e:
            logger.error(f"Sonos play_uri error: {e}")
            return False

    async def get_current_playback_snapshot(self) -> Optional[dict]:
        """
        Capture current playback state for duck-and-resume.

        Returns:
            Snapshot dict or None if nothing is playing.
        """
        status = await self.get_status()
        if status.get("state") == "PLAYING":
            return {
                "uri": (await asyncio.to_thread(
                    self._device.get_current_track_info
                )).get("uri"),
                "position": status.get("position"),
                "volume": status.get("volume"),
            }
        return None

    async def restore_playback(self, snapshot: dict) -> None:
        """Restore playback from a snapshot taken by get_current_playback_snapshot."""
        if not snapshot:
            return
        try:
            uri = snapshot.get("uri")
            if uri:
                await asyncio.to_thread(self._device.play_uri, uri)
            volume = snapshot.get("volume")
            if volume is not None:
                await self.set_volume(volume)
        except Exception as e:
            logger.error(f"Error restoring playback: {e}")

    async def get_favorites(self) -> list[dict[str, str]]:
        """
        List Sonos favorites and Sonos playlists.

        Combines cloud-synced favorites with locally-created Sonos playlists
        (Era 100 / S2 firmware stores Apple Music items as playlists).

        Returns:
            List of dicts with title, uri, and source.
        """
        if not self._connected or not self._device:
            return []

        results = []

        # Cloud-synced favorites
        try:
            favorites = await asyncio.to_thread(
                self._device.music_library.get_sonos_favorites
            )
            for fav in favorites:
                uri = (
                    getattr(fav, "resources", [{}])[0].uri
                    if hasattr(fav, "resources") and fav.resources
                    else getattr(fav, "uri", "")
                )
                results.append({
                    "title": fav.title,
                    "uri": uri,
                    "source": "favorite",
                })
        except Exception as e:
            logger.error(f"Error getting Sonos favorites: {e}")

        # Sonos playlists (where Apple Music items typically land)
        try:
            playlists = await asyncio.to_thread(
                self._device.get_sonos_playlists
            )
            for pl in playlists:
                results.append({
                    "title": pl.title,
                    "uri": pl.get_uri() if hasattr(pl, "get_uri") else getattr(pl, "uri", ""),
                    "source": "playlist",
                })
        except Exception as e:
            logger.error(f"Error getting Sonos playlists: {e}")

        return results

    async def play_favorite(self, title: str) -> bool:
        """
        Play a Sonos favorite or playlist by title.

        Handles both cloud favorites (play_uri) and Sonos playlists
        (add_to_queue + play).

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
            playlists = await asyncio.to_thread(
                self._device.get_sonos_playlists
            )
            for pl in playlists:
                if pl.title.lower() == target:
                    await asyncio.to_thread(self._device.clear_queue)
                    await asyncio.to_thread(
                        self._device.add_to_queue, pl
                    )
                    await asyncio.to_thread(self._device.play_from_queue, 0)
                    logger.info(f"Playing Sonos playlist: {pl.title}")
                    return True
        except Exception as e:
            logger.error(f"Error searching Sonos playlists: {e}")

        # Fall back to cloud favorites
        favorites = await self.get_favorites()
        for fav in favorites:
            if fav["title"].lower() == target:
                uri = fav.get("uri", "")
                if uri:
                    return await self.play_uri(uri)

        available = [fav["title"] for fav in favorites]
        logger.warning(
            "Sonos favorite/playlist '%s' not found. Available: %s",
            title, available,
        )
        return False

    async def poll_state_loop(self, ws_manager) -> None:
        """
        Continuously poll Sonos state and broadcast changes via WebSocket.

        Runs as a background task. Detects track changes, play/pause,
        volume adjustments from the Sonos app or physical controls.
        """
        logger.info("Starting Sonos state polling")

        while True:
            try:
                status = await self.get_status()

                # Only broadcast if something changed
                if status != self._last_status:
                    self._last_status = status
                    await ws_manager.broadcast("sonos_update", status)

                await asyncio.sleep(2)
            except asyncio.CancelledError:
                logger.info("Sonos polling stopped")
                break
            except Exception as e:
                logger.error(f"Sonos polling error: {e}")
                await asyncio.sleep(5)
