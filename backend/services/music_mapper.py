"""
Music mapper — maps activity modes to Sonos favorites/playlists.

When the automation engine changes modes, the music mapper can auto-play
or suggest the mapped playlist for that mode. Mappings persist to SQLite.
"""
import logging
from typing import Optional

from sqlalchemy import delete, select

from backend.database import async_session
from backend.models import ModePlaylist

logger = logging.getLogger("home_hub.music")

SUPPORTED_MODES = ("gaming", "working", "watching", "social", "relax", "movie")


class MusicMapper:
    """
    Maps activity modes to Sonos favorites for automatic playlist playback.

    The user sets up playlists in Apple Music, adds them to Sonos favorites,
    then maps each mode to a favorite name via the API. When a mode change
    occurs, the mapper either auto-plays (if Sonos is idle) or broadcasts
    a suggestion via WebSocket.
    """

    def __init__(self, sonos_service, ws_manager) -> None:
        self._sonos = sonos_service
        self._ws_manager = ws_manager
        # In-memory cache: mode -> {favorite_title, auto_play, priority}
        self._cache: dict[str, dict] = {}

    async def load_from_db(self) -> None:
        """Load all mode-playlist mappings from the database into cache."""
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).order_by(ModePlaylist.priority.desc())
            )
            rows = result.scalars().all()

        self._cache.clear()
        for row in rows:
            self._cache[row.mode] = {
                "favorite_title": row.favorite_title,
                "auto_play": row.auto_play,
                "priority": row.priority,
            }

        logger.info(f"Loaded {len(self._cache)} mode-playlist mappings from DB")

    @property
    def mapping(self) -> dict[str, dict]:
        """Current mode-to-playlist mapping (includes empty modes)."""
        result = {}
        for mode in SUPPORTED_MODES:
            if mode in self._cache:
                result[mode] = self._cache[mode].copy()
            else:
                result[mode] = {"favorite_title": "", "auto_play": False}
        return result

    async def set_mapping(
        self, mode: str, favorite_title: str, auto_play: bool = False
    ) -> None:
        """
        Set or update a mode-to-playlist mapping. Persists to database.

        Args:
            mode: Activity mode (gaming, working, watching, social, relax, movie).
            favorite_title: Name of the Sonos favorite to play.
            auto_play: Whether to automatically start playback on mode change.
        """
        async with async_session() as session:
            # Upsert: delete existing mapping for this mode, then insert
            await session.execute(
                delete(ModePlaylist).where(ModePlaylist.mode == mode)
            )
            session.add(ModePlaylist(
                mode=mode,
                favorite_title=favorite_title,
                auto_play=auto_play,
            ))
            await session.commit()

        # Update cache
        self._cache[mode] = {
            "favorite_title": favorite_title,
            "auto_play": auto_play,
            "priority": 0,
        }
        logger.info(
            f"Music mapping updated: {mode} -> '{favorite_title}' "
            f"(auto_play={auto_play})"
        )

    async def remove_mapping(self, mode: str) -> bool:
        """
        Remove the playlist mapping for a mode.

        Returns:
            True if a mapping was removed, False if none existed.
        """
        async with async_session() as session:
            result = await session.execute(
                delete(ModePlaylist).where(ModePlaylist.mode == mode)
            )
            await session.commit()
            removed = result.rowcount > 0

        self._cache.pop(mode, None)
        if removed:
            logger.info(f"Music mapping removed for mode: {mode}")
        return removed

    def get_playlist_for_mode(self, mode: str) -> Optional[str]:
        """
        Get the mapped playlist title for a given mode.

        Returns:
            Sonos favorite title, or None if no mapping exists.
        """
        entry = self._cache.get(mode, {})
        title = entry.get("favorite_title", "")
        return title if title else None

    def should_auto_play(self, mode: str) -> bool:
        """Check if the mapped playlist should auto-play for this mode."""
        entry = self._cache.get(mode, {})
        return entry.get("auto_play", False)

    async def on_mode_change(self, mode: str) -> Optional[dict]:
        """
        Handle a mode change — smart auto-play based on Sonos state.

        If Sonos is idle and auto_play is enabled, starts the mapped playlist.
        If Sonos is already playing, broadcasts a suggestion via WebSocket
        so the user can choose to switch.

        Args:
            mode: The new activity mode.

        Returns:
            Dict with action taken, or None if no mapping exists.
        """
        title = self.get_playlist_for_mode(mode)
        if not title:
            return None

        if not self.should_auto_play(mode):
            return None

        if not self._sonos.connected:
            logger.warning("Sonos not connected — skipping music auto-play")
            return None

        try:
            status = await self._sonos.get_status()
            sonos_state = status.get("state", "STOPPED")

            if sonos_state in ("STOPPED", "PAUSED_PLAYBACK"):
                # Sonos is idle — auto-play
                success = await self._sonos.play_favorite(title)
                if success:
                    logger.info(f"Auto-playing '{title}' for mode '{mode}'")
                    await self._ws_manager.broadcast("music_auto_played", {
                        "mode": mode,
                        "title": title,
                    })
                    return {"action": "auto_played", "title": title}
                else:
                    logger.warning(
                        f"Failed to auto-play '{title}' for mode '{mode}'"
                    )
                    return None
            else:
                # Sonos is busy — suggest instead of interrupting
                logger.info(
                    f"Sonos playing — suggesting '{title}' for mode '{mode}'"
                )
                await self._ws_manager.broadcast("music_suggestion", {
                    "mode": mode,
                    "title": title,
                    "message": f"Play '{title}' for {mode} mode?",
                })
                return {"action": "suggested", "title": title}

        except Exception as e:
            logger.error(f"Error during music auto-play: {e}", exc_info=True)
            return None

    async def on_mode_change_wrapper(self, mode: str) -> None:
        """
        Thin callback wrapper for AutomationEngine.register_on_mode_change.

        The automation engine calls this with just the mode string.
        """
        await self.on_mode_change(mode)
