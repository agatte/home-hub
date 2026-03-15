"""
Music mapper — maps activity modes to Sonos favorites/playlists.

When the automation engine changes modes, the music mapper can auto-play
or suggest the mapped playlist for that mode.
"""
import logging
from typing import Optional

logger = logging.getLogger("home_hub.music")

# Default mode → playlist mapping (user configures via API)
DEFAULT_MAPPING: dict[str, dict] = {
    "gaming": {"favorite_title": "", "auto_play": False},
    "working": {"favorite_title": "", "auto_play": False},
    "watching": {"favorite_title": "", "auto_play": False},
    "social": {"favorite_title": "", "auto_play": False},
    "relax": {"favorite_title": "", "auto_play": False},
}


class MusicMapper:
    """
    Maps activity modes to Sonos favorites for automatic playlist playback.

    The user sets up playlists in Apple Music, adds them to Sonos favorites,
    then maps each mode to a favorite name via the API. When a mode change
    occurs, the mapper either auto-plays or suggests the mapped playlist.
    """

    def __init__(self, sonos_service) -> None:
        self._sonos = sonos_service
        self._mapping: dict[str, dict] = DEFAULT_MAPPING.copy()

    @property
    def mapping(self) -> dict[str, dict]:
        """Current mode-to-playlist mapping."""
        return self._mapping.copy()

    def set_mapping(self, mode: str, favorite_title: str, auto_play: bool = False) -> None:
        """
        Set or update a mode-to-playlist mapping.

        Args:
            mode: Activity mode (gaming, working, watching, social, relax).
            favorite_title: Name of the Sonos favorite to play.
            auto_play: Whether to automatically start playback on mode change.
        """
        self._mapping[mode] = {
            "favorite_title": favorite_title,
            "auto_play": auto_play,
        }
        logger.info(
            f"Music mapping updated: {mode} → '{favorite_title}' "
            f"(auto_play={auto_play})"
        )

    def get_playlist_for_mode(self, mode: str) -> Optional[str]:
        """
        Get the mapped playlist title for a given mode.

        Returns:
            Sonos favorite title, or None if no mapping exists.
        """
        entry = self._mapping.get(mode, {})
        title = entry.get("favorite_title", "")
        return title if title else None

    def should_auto_play(self, mode: str) -> bool:
        """Check if the mapped playlist should auto-play for this mode."""
        entry = self._mapping.get(mode, {})
        return entry.get("auto_play", False)

    async def on_mode_change(self, mode: str) -> Optional[str]:
        """
        Handle a mode change — auto-play the mapped playlist if configured.

        Args:
            mode: The new activity mode.

        Returns:
            The playlist title that was played, or None.
        """
        title = self.get_playlist_for_mode(mode)
        if not title:
            return None

        if self.should_auto_play(mode):
            success = await self._sonos.play_favorite(title)
            if success:
                logger.info(f"Auto-playing '{title}' for mode '{mode}'")
                return title
            else:
                logger.warning(f"Failed to auto-play '{title}' for mode '{mode}'")

        return None
