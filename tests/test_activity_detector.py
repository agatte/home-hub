"""Tests for ``backend.services.pc_agent.activity_detector``.

Covers the two flap-suppression layers that previously let
``watching ↔ working`` cycle the kitchen lights at night and let an
abandoned ``leagueclient.exe`` launcher lock mode to ``gaming``:

1. ``_classify`` gaming gate — game process running is *necessary* but
   not *sufficient*; foreground OR recent input is also required.
2. ``_dwell_threshold`` — symmetric 5-min stickiness at night for the
   ``watching ↔ working`` pair so quick alt-tabs can't churn modes.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from backend.services.pc_agent.activity_detector import (
    ActivityDetector,
    DWELL_DEFAULT,
    DWELL_LEAVE_WATCHING_DAY,
    DWELL_LEAVE_WATCHING_NIGHT,
    DWELL_LEAVE_WORKING_NIGHT,
    GAMING_IDLE_THRESHOLD,
)
from backend.services.pc_agent.game_list import (
    GAME_PROCESSES,
    _steam_game_processes_from_library,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detector(
    *,
    processes: set[str],
    fg_proc: str | None,
    fg_title: str = "",
    idle_seconds: int = 0,
) -> ActivityDetector:
    """Build a detector with environment fakes patched in."""
    d = ActivityDetector()
    d._get_running_process_names = lambda: processes  # type: ignore[method-assign]
    d._get_foreground_window = lambda: (fg_proc, fg_title)  # type: ignore[method-assign]
    d._get_idle_seconds = lambda: idle_seconds  # type: ignore[method-assign]
    d._is_sleep_window = lambda: False  # type: ignore[method-assign]
    return d



# ---------------------------------------------------------------------------
# Sleep auto-pause — only foreground media counts as intent
# ---------------------------------------------------------------------------


class TestSleepAutoPauseGate:
    """Background browser/media must not receive the global media key."""

    def _sleep_window_detector(
        self,
        *,
        processes: set[str],
        fg_proc: str | None,
        fg_title: str = "",
    ) -> tuple[ActivityDetector, dict[str, int]]:
        d = _make_detector(
            processes=processes,
            fg_proc=fg_proc,
            fg_title=fg_title,
            idle_seconds=901,
        )
        d._is_sleep_window = lambda: True  # type: ignore[method-assign]
        calls = {"pause": 0}

        def fake_pause() -> None:
            calls["pause"] += 1

        d._pause_media = fake_pause  # type: ignore[method-assign]
        return d, calls

    def test_firefox_non_media_selected_tab_does_not_pause(self):
        d, calls = self._sleep_window_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="GitHub - Mozilla Firefox",
        )

        assert d._classify() == "idle"
        assert calls["pause"] == 0

    def test_firefox_youtube_selected_tab_pauses(self):
        d, calls = self._sleep_window_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="Lo-fi video - YouTube - Mozilla Firefox",
        )

        assert d._classify() == "sleeping"
        assert calls["pause"] == 1

    def test_background_media_player_does_not_pause(self):
        d, calls = self._sleep_window_detector(
            processes={"stremio.exe", "code.exe"},
            fg_proc="code.exe",
            fg_title="activity_detector.py - home-hub",
        )

        assert d._classify() == "idle"
        assert calls["pause"] == 0

    def test_foreground_media_player_pauses(self):
        d, calls = self._sleep_window_detector(
            processes={"stremio.exe"},
            fg_proc="stremio.exe",
        )

        assert d._classify() == "sleeping"
        assert calls["pause"] == 1

# ---------------------------------------------------------------------------
# Gaming gate — leagueclient.exe-style launcher persistence
# ---------------------------------------------------------------------------


class TestGamingGate:
    """Game process running alone must NOT commit gaming."""

    def test_foreground_game_commits_gaming(self):
        d = _make_detector(
            processes={"leagueclient.exe"},
            fg_proc="leagueclient.exe",
            idle_seconds=0,
        )
        assert d._classify() == "gaming"

    def test_active_input_with_game_running_commits_gaming(self):
        # Alt-tab to wiki: foreground is the browser, but input is active
        # (scrolling). Stay in gaming.
        d = _make_detector(
            processes={"leagueclient.exe", "firefox.exe"},
            fg_proc="firefox.exe",
            idle_seconds=GAMING_IDLE_THRESHOLD - 30,
        )
        assert d._classify() == "gaming"


    def test_planet_zoo_foreground_commits_gaming(self):
        d = _make_detector(
            processes={"planetzoo.exe"},
            fg_proc="planetzoo.exe",
            idle_seconds=0,
        )
        assert "planetzoo.exe" in GAME_PROCESSES
        assert d._classify() == "gaming"

    def test_discovered_steam_game_commits_gaming(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.pc_agent.activity_detector.get_game_processes",
            lambda: GAME_PROCESSES | {"futuregame.exe"},
        )
        d = _make_detector(
            processes={"futuregame.exe"},
            fg_proc="futuregame.exe",
            idle_seconds=0,
        )
        assert d._classify() == "gaming"

    def test_unfocused_idle_launcher_does_not_lock_gaming(self):
        # The bug: walked away from PC, leagueclient.exe still in tray.
        # Old behavior locked mode to "gaming". New behavior falls through.
        d = _make_detector(
            processes={"leagueclient.exe"},
            fg_proc=None,
            idle_seconds=GAMING_IDLE_THRESHOLD + 60,
        )
        assert d._classify() != "gaming"

    def test_unfocused_idle_launcher_with_browser_falls_to_working_at_night(self):
        # 9pm+, browser running, launcher in tray, walked away → not gaming.
        # Late-night browser-only path picks "working".
        d = _make_detector(
            processes={"leagueclient.exe", "firefox.exe"},
            fg_proc=None,
            idle_seconds=GAMING_IDLE_THRESHOLD + 60,
        )
        with patch(
            "backend.services.pc_agent.activity_detector.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert d._classify() == "working"


# ---------------------------------------------------------------------------
# Dwell — watching ↔ working symmetric stickiness at night
# ---------------------------------------------------------------------------


class TestDwellThreshold:
    """Symmetric 5-min stickiness on the watching↔working pair at night."""

    @pytest.fixture
    def detector(self) -> ActivityDetector:
        # _dwell_threshold consults _foreground_is_media() for the new
        # explicit-media bypass. Force it False so the legacy dwell tests
        # exercise the non-media-foreground path (the case the 300s night
        # sticky was added for). Tests that need the bypass path mock it
        # to True explicitly.
        d = ActivityDetector()
        d._foreground_is_media = lambda: False  # type: ignore[method-assign]
        return d

    def _at_hour(self, hour: int):
        """Patch datetime.now() inside the activity_detector module."""
        return patch(
            "backend.services.pc_agent.activity_detector.datetime"
        )

    def test_default_transition_uses_default_dwell(self, detector):
        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 15, 0)
            assert detector._dwell_threshold("idle", "working") == DWELL_DEFAULT

    def test_leave_watching_day_responsive(self, detector):
        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 15, 0)
            assert (
                detector._dwell_threshold("watching", "working")
                == DWELL_LEAVE_WATCHING_DAY
            )

    def test_leave_watching_night_sticky(self, detector):
        with self._at_hour(22) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert (
                detector._dwell_threshold("watching", "working")
                == DWELL_LEAVE_WATCHING_NIGHT
            )

    def test_leave_working_to_watching_night_sticky(self, detector):
        # The new case: previously 30s, now 300s. Prevents alt-tab to
        # Stremio from flipping mode while genuinely coding at night.
        with self._at_hour(22) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert (
                detector._dwell_threshold("working", "watching")
                == DWELL_LEAVE_WORKING_NIGHT
            )

    def test_leave_working_to_watching_day_responsive(self, detector):
        # Daytime stays snappy in both directions.
        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 15, 0)
            assert (
                detector._dwell_threshold("working", "watching")
                == DWELL_DEFAULT
            )

    def test_leave_working_to_idle_night_uses_default(self, detector):
        # Only the working→watching pairing gets the night sticky bump.
        # Other transitions out of working stay on the default dwell.
        with self._at_hour(22) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert (
                detector._dwell_threshold("working", "idle") == DWELL_DEFAULT
            )

    def test_default_dwell_is_60_seconds(self):
        # Bumped from 30s → 60s: catches longer alt-tab peeks (e.g. 45s
        # at YouTube, 50s in a terminal mid-video).
        assert DWELL_DEFAULT == 60.0

    def test_foreground_media_bypasses_night_sticky(self):
        """An explicit foreground media window (YouTube tab front-most,
        Stremio focused, …) commits to watching on DWELL_DEFAULT even at
        night. Background-tab cases still get the 300s gate — see the
        non-bypass test above that patches _foreground_is_media to False."""
        d = ActivityDetector()
        d._foreground_is_media = lambda: True  # type: ignore[method-assign]
        with patch(
            "backend.services.pc_agent.activity_detector.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert d._dwell_threshold("working", "watching") == DWELL_DEFAULT
            # Idle → watching also fast-paths when media is foregrounded
            assert d._dwell_threshold("idle", "watching") == DWELL_DEFAULT

    def test_foreground_media_does_not_bypass_leaving_watching(self):
        """The bypass only fires for transitions INTO watching. Leaving
        watching at night still gets the 300s stickiness — a video tab
        being foregrounded doesn't change the fact that briefly tabbing
        away shouldn't flip lights."""
        d = ActivityDetector()
        d._foreground_is_media = lambda: True  # type: ignore[method-assign]
        with patch(
            "backend.services.pc_agent.activity_detector.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 22, 0)
            assert (
                d._dwell_threshold("watching", "working")
                == DWELL_LEAVE_WATCHING_NIGHT
            )


# ---------------------------------------------------------------------------
# Detect — end-to-end hysteresis path with the new dwells
# ---------------------------------------------------------------------------


class TestDetectHysteresis:
    """Wire the dwell logic through ``detect()`` to verify integration."""

    def _patch_time(self, t: float):
        return patch(
            "backend.services.pc_agent.activity_detector.time.time",
            return_value=t,
        )

    def test_45_second_peek_does_not_flip_mode(self):
        """A 45s alt-tab to media is shorter than DWELL_DEFAULT (60s),
        so the committed mode should not change."""
        d = _make_detector(
            processes={"code.exe"},
            fg_proc="code.exe",
            idle_seconds=0,
        )
        with self._patch_time(0.0):
            d.detect()  # First poll commits "working".
        assert d._last_mode == "working"

        # Stremio appears in foreground for 45s.
        d._get_running_process_names = lambda: {  # type: ignore[method-assign]
            "code.exe", "stremio.exe",
        }
        d._get_foreground_window = lambda: (  # type: ignore[method-assign]
            "stremio.exe", "",
        )

        # Patch daytime so we use DWELL_DEFAULT (60s), not the night sticky.
        with patch(
            "backend.services.pc_agent.activity_detector.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 26, 15, 0)
            with self._patch_time(45.0):
                committed = d.detect()

        assert committed == "working", (
            f"45s peek should not commit a new mode under 60s default dwell, "
            f"got {committed}"
        )


# ---------------------------------------------------------------------------
# Factor payload — source/device context for backend ownership policy
# ---------------------------------------------------------------------------


def test_build_factors_includes_configured_device_role(monkeypatch):
    monkeypatch.setenv("HOME_HUB_AGENT_DEVICE", "latitude")
    d = _make_detector(
        processes={"stremio.exe"},
        fg_proc="stremio.exe",
        idle_seconds=0,
    )

    factors = d.build_factors()

    assert factors[0]["key"] == "device"
    assert factors[0]["value"] == "latitude"
    assert len(factors) <= 8

# ---------------------------------------------------------------------------
# Steam discovery — installed Steam games auto-join generic gaming detection
# ---------------------------------------------------------------------------


def test_steam_library_manifest_discovers_game_exe(tmp_path):
    steamapps = tmp_path / "steamapps"
    app_dir = steamapps / "common" / "Future Game"
    app_dir.mkdir(parents=True)
    (app_dir / "FutureGame.exe").write_text("", encoding="utf-8")
    (app_dir / "UnityCrashHandler64.exe").write_text("", encoding="utf-8")
    redist = app_dir / "_CommonRedist" / "vcredist"
    redist.mkdir(parents=True)
    (redist / "setup.exe").write_text("", encoding="utf-8")
    (steamapps / "appmanifest_999.acf").write_text(
        """"AppState"
{
    "appid" "999"
    "name" "Future Game"
    "installdir" "Future Game"
}
""",
        encoding="utf-8",
    )

    assert _steam_game_processes_from_library(tmp_path) == {"futuregame.exe"}


def test_steam_library_manifest_skips_redistributable_apps(tmp_path):
    steamapps = tmp_path / "steamapps"
    app_dir = steamapps / "common" / "Steamworks Shared"
    app_dir.mkdir(parents=True)
    (app_dir / "helper.exe").write_text("", encoding="utf-8")
    (steamapps / "appmanifest_228980.acf").write_text(
        """"AppState"
{
    "appid" "228980"
    "name" "Steamworks Common Redistributables"
    "installdir" "Steamworks Shared"
}
""",
        encoding="utf-8",
    )

    assert _steam_game_processes_from_library(tmp_path) == set()
