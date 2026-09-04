"""Windows browser playback evidence for HomeHub desktop agents.

Uses Global System Media Transport Controls (GSMTC) only on Windows. Imports of
the modular PyWinRT projection stay inside the async read so Linux/server and
ordinary test environments do not need desktop-only packages.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional

from backend.services.pc_agent.game_list import (
    BROWSER_PROCESSES,
    WATCHING_TITLE_KEYWORDS,
)

logger = logging.getLogger("home_hub.windows_media_session")

MEDIA_SESSION_TIMEOUT_SECONDS = 1.0
MEDIA_SESSION_CACHE_SECONDS = 1.0
AUDIO_ONLY_BROWSER_TITLE_KEYWORDS = ("youtube music",)

# Do not use GSMTC playback_type as browser-video authority. A live Firefox
# YouTube probe on 2026-09-04 reported Music while genuine video was playing.
# Playback status is therefore combined with foreground video-site context.


def browser_title_looks_like_video(
    process_name: Optional[str], window_title: Optional[str],
) -> bool:
    """Return whether foreground browser chrome supports video intent."""
    if process_name not in BROWSER_PROCESSES or not window_title:
        return False
    title_lower = window_title.lower()
    if any(keyword in title_lower for keyword in AUDIO_ONLY_BROWSER_TITLE_KEYWORDS):
        return False
    return any(keyword in title_lower for keyword in WATCHING_TITLE_KEYWORDS)


class WindowsMediaSessionProbe:
    """Short-lived cached GSMTC observations for browser playback truth."""

    def __init__(self) -> None:
        self._cache_at = float("-inf")
        self._cache: list[tuple[str, str, str]] = []

    @staticmethod
    async def _read_sessions() -> list[tuple[str, str, str]]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )

        manager = await asyncio.wait_for(
            SessionManager.request_async(),
            timeout=MEDIA_SESSION_TIMEOUT_SECONDS,
        )
        observations: list[tuple[str, str, str]] = []
        for session in manager.get_sessions():
            source = (session.source_app_user_model_id or "").lower()
            status = session.get_playback_info().playback_status.name.lower()
            media_title = ""
            try:
                properties = await asyncio.wait_for(
                    session.try_get_media_properties_async(),
                    timeout=MEDIA_SESSION_TIMEOUT_SECONDS,
                )
                media_title = (properties.title or "").strip()
            except Exception:
                pass
            observations.append((source, status, media_title))
        return observations

    def sessions(self) -> list[tuple[str, str, str]]:
        """Return a cached GSMTC snapshot; missing support fails closed."""
        now = time.monotonic()
        if now - self._cache_at < MEDIA_SESSION_CACHE_SECONDS:
            return self._cache
        if sys.platform != "win32":
            return []
        try:
            observations = asyncio.run(self._read_sessions())
        except (ImportError, ModuleNotFoundError):
            observations = []
        except Exception as exc:
            logger.debug("Windows media-session probe failed: %s", exc)
            observations = []
        self._cache = observations
        self._cache_at = now
        return observations

    def browser_playback_status(
        self,
        process_name: Optional[str],
        window_title: Optional[str],
    ) -> str:
        """Resolve GSMTC state for the foreground browser video page."""
        if not browser_title_looks_like_video(process_name, window_title):
            return "not_applicable"
        assert process_name is not None
        process = process_name.lower()
        stem = process.removesuffix(".exe")
        title_lower = (window_title or "").lower()
        sessions = [
            observation
            for observation in self.sessions()
            if process in observation[0] or stem in observation[0]
        ]
        if not sessions:
            return "unavailable"

        title_matches = [
            observation
            for observation in sessions
            if observation[2] and observation[2].lower() in title_lower
        ]
        if title_matches:
            sessions = title_matches
        elif any(observation[2] for observation in sessions):
            # A different same-browser media tab is active/background. Do not
            # let its Playing state bless the foreground page.
            return "unmatched"
        elif len(sessions) > 1:
            return "ambiguous"

        priority = {"playing": 4, "paused": 3, "stopped": 2, "opened": 1}
        return max(
            sessions,
            key=lambda item: priority.get(item[1], 0),
        )[1]
