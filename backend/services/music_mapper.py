"""
Music mapper — maps activity modes to Sonos favorites/playlists.

Supports multiple favorites per mode, each optionally tagged with a vibe
(energetic, mellow, focus, background, hype). On mode change, the mapper
picks the best-matching vibe based on time of day, then auto-plays or
broadcasts a suggestion via WebSocket. Mappings persist to SQLite.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.database import async_session
from backend.models import ModePlaylist

logger = logging.getLogger("home_hub.music")

TZ = ZoneInfo("America/Indiana/Indianapolis")

SUPPORTED_MODES = ("gaming", "working", "watching", "social", "relax", "movie")
VALID_VIBES = ("energetic", "mellow", "focus", "background", "hype")

# Time-of-day → preferred vibe order (first match wins)
_TIME_VIBE_PREFERENCE: dict[str, list[str]] = {
    "morning": ["focus", "mellow", "background", "energetic", "hype"],   # 5-10
    "day": ["energetic", "focus", "background", "mellow", "hype"],        # 10-18
    "evening": ["mellow", "background", "focus", "energetic", "hype"],    # 18-22
    "night": ["mellow", "background", "focus", "energetic", "hype"],      # 22-5
}

# Weather condition → preferred vibe order. Only precipitation/storms
# warrant a music suggestion; clouds and golden hour don't.
_WEATHER_VIBE_OVERRIDE: dict[str, list[str]] = {
    "thunderstorm": ["background", "mellow", "focus", "energetic", "hype"],
    "rain": ["mellow", "background", "focus", "energetic", "hype"],
    "snow": ["mellow", "focus", "background", "energetic", "hype"],
}

# Modes that skip weather music suggestions (party/sleep have their own thing)
_WEATHER_MUSIC_SKIP_MODES = frozenset(("social", "sleeping"))


def _time_period(hour: int) -> str:
    if 5 <= hour < 10:
        return "morning"
    if 10 <= hour < 18:
        return "day"
    if 18 <= hour < 22:
        return "evening"
    return "night"


class MusicMapper:
    """
    Maps activity modes to Sonos favorites for automatic playlist playback.

    Supports multiple favorites per mode via vibe tags. On mode change,
    picks the best vibe for the current time of day. Mappings persist
    to the mode_playlists SQLite table.
    """

    def __init__(self, sonos_service, ws_manager, event_logger=None) -> None:
        self._sonos = sonos_service
        self._ws_manager = ws_manager
        self._event_logger = event_logger
        self._music_bandit = None  # Set by main.py if ML is available
        # Cache: mode -> list[{id, favorite_title, vibe, auto_play, priority}]
        self._cache: dict[str, list[dict]] = {m: [] for m in SUPPORTED_MODES}
        # Tracks the most recent mode requested — used to skip stale auto-plays
        self._last_requested_mode: Optional[str] = None

    async def load_from_db(self) -> None:
        """Load all mode-playlist mappings from the database into cache."""
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).order_by(ModePlaylist.priority.desc())
            )
            rows = result.scalars().all()

        self._cache = {m: [] for m in SUPPORTED_MODES}
        for row in rows:
            if row.mode in self._cache:
                self._cache[row.mode].append({
                    "id": row.id,
                    "favorite_title": row.favorite_title,
                    "vibe": row.vibe,
                    "auto_play": row.auto_play,
                    "priority": row.priority,
                })

        total = sum(len(v) for v in self._cache.values())
        logger.info(f"Loaded {total} mode-playlist mappings from DB")

    @property
    def mapping(self) -> dict[str, list[dict]]:
        """Current mode-to-playlist mappings, all modes included."""
        return {mode: list(entries) for mode, entries in self._cache.items()}

    def pick_playlist(self, mode: str, vibe: Optional[str] = None) -> Optional[dict]:
        """
        Select the best playlist entry for a mode.

        If vibe is specified, filters to that vibe (falls back to any entry
        if none match). If vibe is None, uses the Thompson sampling bandit
        (if available) or falls back to the time-of-day heuristic.

        Returns:
            Entry dict {id, favorite_title, vibe, auto_play, priority}, or None.
        """
        entries = self._cache.get(mode, [])
        if not entries:
            return None

        if vibe:
            match = next((e for e in entries if e["vibe"] == vibe), None)
            return match or entries[0]

        hour = datetime.now(tz=TZ).hour
        period = _time_period(hour)
        preference = _TIME_VIBE_PREFERENCE[period]

        # Try Thompson sampling bandit first
        if self._music_bandit and len(entries) > 1:
            pick = self._music_bandit.select(
                mode=mode,
                period=period,
                candidates=entries,
                preferred_vibes=preference,
            )
            if pick:
                return pick

        # Fallback: time-of-day vibe heuristic
        for preferred_vibe in preference:
            match = next((e for e in entries if e["vibe"] == preferred_vibe), None)
            if match:
                return match

        # Fallback: highest priority entry
        return entries[0]

    async def add_mapping(
        self,
        mode: str,
        favorite_title: str,
        vibe: Optional[str] = None,
        auto_play: bool = False,
        priority: int = 0,
    ) -> int:
        """
        Add or update a mode-to-playlist mapping. Persists to database.

        If the same (mode, favorite_title) already exists, updates its vibe,
        auto_play, and priority in place.

        Args:
            mode: Activity mode.
            favorite_title: Sonos favorite name.
            vibe: Optional vibe tag (energetic/mellow/focus/background/hype).
            auto_play: Whether to auto-play on mode change.
            priority: Higher priority entries are preferred (default 0).

        Returns:
            Database ID of the created or updated row.
        """
        existing_row = None
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).where(
                    ModePlaylist.mode == mode,
                    ModePlaylist.favorite_title == favorite_title,
                )
            )
            existing_row = result.scalar_one_or_none()

            if existing_row:
                existing_row.vibe = vibe
                existing_row.auto_play = auto_play
                existing_row.priority = priority
                row_id = existing_row.id
            else:
                row = ModePlaylist(
                    mode=mode,
                    favorite_title=favorite_title,
                    vibe=vibe,
                    auto_play=auto_play,
                    priority=priority,
                )
                session.add(row)
                await session.flush()
                row_id = row.id

            await session.commit()

        await self._reload_mode(mode)
        action = "updated" if existing_row else "added"
        logger.info(
            f"Music mapping {action}: {mode} -> '{favorite_title}' "
            f"vibe={vibe} auto_play={auto_play}"
        )
        return row_id

    async def remove_mapping_by_id(self, mapping_id: int) -> bool:
        """
        Remove a specific mapping by database ID.

        Returns:
            True if removed, False if not found.
        """
        mode = None
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).where(ModePlaylist.id == mapping_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False
            mode = row.mode
            await session.delete(row)
            await session.commit()

        await self._reload_mode(mode)
        logger.info(f"Music mapping {mapping_id} removed")
        return True

    async def remove_all_for_mode(self, mode: str) -> int:
        """Remove all mappings for a mode. Returns count removed."""
        async with async_session() as session:
            result = await session.execute(
                delete(ModePlaylist).where(ModePlaylist.mode == mode)
            )
            await session.commit()
            count = result.rowcount

        self._cache[mode] = []
        if count:
            logger.info(f"Removed {count} mappings for mode '{mode}'")
        return count

    async def _reload_mode(self, mode: str) -> None:
        """Refresh the cache for a single mode from the database."""
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist)
                .where(ModePlaylist.mode == mode)
                .order_by(ModePlaylist.priority.desc())
            )
            rows = result.scalars().all()

        self._cache[mode] = [
            {
                "id": row.id,
                "favorite_title": row.favorite_title,
                "vibe": row.vibe,
                "auto_play": row.auto_play,
                "priority": row.priority,
            }
            for row in rows
        ]

    async def on_mode_change(self, mode: str) -> Optional[dict]:
        """
        Handle a mode change — smart auto-play based on Sonos state.

        Uses time-of-day vibe heuristic to pick the best playlist.
        If Sonos is idle and auto_play is set, starts the playlist.
        If Sonos is busy, broadcasts a suggestion via WebSocket.

        Args:
            mode: The new activity mode.

        Returns:
            Dict describing the action taken, or None.
        """
        self._last_requested_mode = mode

        entry = self.pick_playlist(mode)
        if not entry or not entry.get("auto_play"):
            return None

        title = entry["favorite_title"]
        vibe = entry.get("vibe")

        if not self._sonos.connected:
            logger.warning("Sonos not connected — skipping music auto-play")
            return None

        try:
            try:
                status = await asyncio.wait_for(
                    self._sonos.get_status(), timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("Sonos get_status timed out (5s) — skipping auto-play")
                return None
            sonos_state = status.get("state", "STOPPED")

            if sonos_state in ("STOPPED", "PAUSED_PLAYBACK"):
                if self._last_requested_mode != mode:
                    logger.info(
                        "Mode changed during auto-play setup ('%s' → '%s'), skipping.",
                        mode, self._last_requested_mode,
                    )
                    return None
                try:
                    success = await asyncio.wait_for(
                        self._sonos.play_favorite(title), timeout=6.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Sonos play_favorite timed out (6s) for '%s'", title
                    )
                    return None
                if success:
                    logger.info(
                        f"Auto-playing '{title}' (vibe={vibe}) for mode '{mode}'"
                    )
                    await self._ws_manager.broadcast("music_auto_played", {
                        "mode": mode,
                        "title": title,
                        "vibe": vibe,
                    })
                    if self._event_logger:
                        await self._event_logger.log_sonos_event(
                            event_type="auto_play",
                            favorite_title=title,
                            mode_at_time=mode,
                            triggered_by="auto",
                        )
                    return {"action": "auto_played", "title": title, "vibe": vibe}
                logger.warning(f"Failed to auto-play '{title}' for mode '{mode}'")
                await self._ws_manager.broadcast("music_auto_play_failed", {
                    "mode": mode,
                    "title": title,
                    "error": "Favorite not found or playback failed",
                })
                return None
            else:
                logger.info(
                    f"Sonos playing — suggesting '{title}' for mode '{mode}'"
                )
                await self._ws_manager.broadcast("music_suggestion", {
                    "mode": mode,
                    "title": title,
                    "vibe": vibe,
                    "message": f"Play '{title}' for {mode} mode?",
                })
                if self._event_logger:
                    await self._event_logger.log_sonos_event(
                        event_type="suggestion",
                        favorite_title=title,
                        mode_at_time=mode,
                        triggered_by="auto",
                    )
                return {"action": "suggested", "title": title, "vibe": vibe}

        except Exception as e:
            logger.error(f"Error during music auto-play: {e}", exc_info=True)
            return None

    async def on_mode_change_wrapper(self, mode: str) -> None:
        """Thin callback wrapper for AutomationEngine.register_on_mode_change."""
        await self.on_mode_change(mode)

    async def on_weather_change(
        self, condition: str, mode: str,
    ) -> Optional[dict]:
        """Suggest a weather-appropriate playlist when weather changes.

        Called by the automation engine when weather condition shifts (e.g.
        clear → rain). Never auto-plays — only broadcasts a WebSocket
        suggestion so the user can choose to switch.

        Args:
            condition: Classified weather (thunderstorm, rain, snow).
            mode: Current activity mode.

        Returns:
            Dict describing the suggestion, or None.
        """
        if mode in _WEATHER_MUSIC_SKIP_MODES:
            return None

        preference = _WEATHER_VIBE_OVERRIDE.get(condition)
        if not preference:
            return None

        entries = self._cache.get(mode, [])
        if not entries:
            return None

        # Pick best playlist using weather vibe preference
        pick = None
        for preferred_vibe in preference:
            match = next((e for e in entries if e["vibe"] == preferred_vibe), None)
            if match:
                pick = match
                break
        if not pick:
            pick = entries[0]

        title = pick["favorite_title"]
        vibe = pick.get("vibe")

        # Check if Sonos is already playing this
        if self._sonos.connected:
            try:
                status = await asyncio.wait_for(
                    self._sonos.get_status(), timeout=5.0,
                )
                current_track = status.get("title") or status.get("track") or ""
                if title.lower() in current_track.lower():
                    logger.debug(
                        "Weather suggestion '%s' already playing, skipping", title,
                    )
                    return None
            except (asyncio.TimeoutError, Exception):
                pass  # Suggest anyway if we can't check

        _WEATHER_LABELS = {
            "thunderstorm": "Stormy",
            "rain": "Rainy",
            "snow": "Snowy",
        }
        weather_label = _WEATHER_LABELS.get(condition, condition.title())

        logger.info(
            "Weather music suggestion: '%s' (vibe=%s) for %s weather in %s mode",
            title, vibe, condition, mode,
        )
        await self._ws_manager.broadcast("music_weather_suggestion", {
            "mode": mode,
            "title": title,
            "vibe": vibe,
            "weather": condition,
            "message": f"{weather_label} outside — try '{title}'?",
        })
        if self._event_logger:
            await self._event_logger.log_sonos_event(
                event_type="weather_suggestion",
                favorite_title=title,
                mode_at_time=mode,
                triggered_by="weather",
            )
        return {"action": "weather_suggested", "title": title, "vibe": vibe}

    # ------------------------------------------------------------------
    # Legacy helpers — used by older code paths
    # ------------------------------------------------------------------

    def get_playlist_for_mode(self, mode: str) -> Optional[str]:
        """Return the best-match favorite title for a mode (legacy helper)."""
        entry = self.pick_playlist(mode)
        return entry["favorite_title"] if entry else None

    def should_auto_play(self, mode: str) -> bool:
        """Return True if any mapping for this mode has auto_play enabled."""
        return any(e["auto_play"] for e in self._cache.get(mode, []))
