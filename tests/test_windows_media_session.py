"""Tests for Windows GSMTC browser-playback evidence."""
from __future__ import annotations

from unittest.mock import patch

from backend.services.pc_agent.windows_media_session import (
    WindowsMediaSessionProbe,
    browser_title_looks_like_video,
)


def test_browser_video_title_is_supporting_context_not_audio_surface() -> None:
    assert browser_title_looks_like_video(
        "firefox.exe", "Blue Planet - YouTube - Mozilla Firefox"
    )
    assert not browser_title_looks_like_video(
        "firefox.exe", "Track - YouTube Music - Mozilla Firefox"
    )
    assert not browser_title_looks_like_video(
        "firefox.exe", "ChatGPT - homehub - Mozilla Firefox"
    )


def test_matching_media_title_resolves_foreground_playback() -> None:
    probe = WindowsMediaSessionProbe()
    probe.sessions = lambda: [  # type: ignore[method-assign]
        ("firefox.exe", "playing", "Blue Planet"),
        ("firefox.exe", "paused", "Other video"),
    ]

    assert probe.browser_playback_status(
        "firefox.exe", "Blue Planet - YouTube - Mozilla Firefox"
    ) == "playing"


def test_background_same_browser_session_cannot_bless_foreground_video_page() -> None:
    probe = WindowsMediaSessionProbe()
    probe.sessions = lambda: [  # type: ignore[method-assign]
        ("firefox.exe", "playing", "Background video"),
    ]

    assert probe.browser_playback_status(
        "firefox.exe", "Different video - YouTube - Mozilla Firefox"
    ) == "unmatched"


def test_single_playing_session_without_metadata_can_still_support_video_page() -> None:
    probe = WindowsMediaSessionProbe()
    probe.sessions = lambda: [  # type: ignore[method-assign]
        ("firefox.exe", "playing", ""),
    ]

    assert probe.browser_playback_status(
        "firefox.exe", "Episode 4 - Netflix - Mozilla Firefox"
    ) == "playing"


def test_first_cache_read_runs_even_at_zero_monotonic_time() -> None:
    probe = WindowsMediaSessionProbe()

    async def fake_read() -> list[tuple[str, str, str]]:
        return [("firefox.exe", "paused", "Video")]

    probe._read_sessions = fake_read  # type: ignore[method-assign]
    with (
        patch("backend.services.pc_agent.windows_media_session.sys.platform", "win32"),
        patch("backend.services.pc_agent.windows_media_session.time.monotonic", return_value=0.0),
    ):
        assert probe.sessions() == [("firefox.exe", "paused", "Video")]
