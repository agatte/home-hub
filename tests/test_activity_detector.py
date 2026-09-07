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
import psutil

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
    browser_playback_status: str = "unavailable",
) -> ActivityDetector:
    """Build a detector with environment fakes patched in."""
    d = ActivityDetector()
    d._get_running_process_names = lambda: processes  # type: ignore[method-assign]
    d._get_foreground_window = lambda: (fg_proc, fg_title)  # type: ignore[method-assign]
    d._get_foreground_process_identity = lambda: (  # type: ignore[method-assign]
        fg_proc,
        fg_title,
        None,
    )
    d._get_idle_seconds = lambda: idle_seconds  # type: ignore[method-assign]
    d._is_sleep_window = lambda: False  # type: ignore[method-assign]
    d._browser_playback_status = (  # type: ignore[method-assign]
        lambda _proc, _title: browser_playback_status
    )
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
        d._browser_playback_status = lambda _proc, _title: "playing"  # type: ignore[method-assign]

        assert d._classify() == "sleeping"
        assert calls["pause"] == 1

    def test_paused_firefox_youtube_does_not_toggle_media(self):
        d, calls = self._sleep_window_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="Lo-fi video - YouTube - Mozilla Firefox",
        )
        d._browser_playback_status = lambda _proc, _title: "paused"  # type: ignore[method-assign]

        assert d._classify() == "idle"
        assert calls["pause"] == 0

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
# Working intent — foreground work only, except existing late-night browser
# ---------------------------------------------------------------------------


class TestBrowserPlaybackIntent:
    def test_matching_playing_session_establishes_and_graces_pause(self):
        d = ActivityDetector()
        status = ["playing"]
        d._media_session_probe.browser_playback_status = (  # type: ignore[method-assign]
            lambda _proc, _title: status[0]
        )

        with patch(
            "backend.services.pc_agent.activity_detector.time.monotonic",
            return_value=100.0,
        ):
            assert d._browser_playback_status(
                "firefox.exe",
                "A video - YouTube - Mozilla Firefox",
            ) == "playing"

        status[0] = "paused"
        with patch(
            "backend.services.pc_agent.activity_detector.time.monotonic",
            return_value=150.0,
        ):
            assert d._browser_playback_status(
                "firefox.exe",
                "A video - YouTube - Mozilla Firefox",
            ) == "pause_grace"

    def test_pause_grace_does_not_transfer_to_a_different_video_title(self):
        d = ActivityDetector()
        status = ["playing"]
        d._media_session_probe.browser_playback_status = (  # type: ignore[method-assign]
            lambda _proc, _title: status[0]
        )

        with patch(
            "backend.services.pc_agent.activity_detector.time.monotonic",
            return_value=100.0,
        ):
            assert d._browser_playback_status(
                "firefox.exe",
                "Video A - YouTube - Mozilla Firefox",
            ) == "playing"

        status[0] = "paused"
        with patch(
            "backend.services.pc_agent.activity_detector.time.monotonic",
            return_value=120.0,
        ):
            assert d._browser_playback_status(
                "firefox.exe",
                "Video B - YouTube - Mozilla Firefox",
            ) == "paused"

    def test_cold_paused_session_does_not_establish_watching(self):
        d = ActivityDetector()
        d._media_session_probe.browser_playback_status = (  # type: ignore[method-assign]
            lambda _proc, _title: "paused"
        )

        assert d._browser_playback_status(
            "firefox.exe",
            "A video - YouTube - Mozilla Firefox",
        ) == "paused"

    def test_probe_abstention_does_not_establish_watching(self):
        d = ActivityDetector()
        d._media_session_probe.browser_playback_status = (  # type: ignore[method-assign]
            lambda _proc, _title: "unmatched"
        )

        assert d._browser_playback_status(
            "firefox.exe",
            "Current video - YouTube - Mozilla Firefox",
        ) == "unmatched"


class TestForegroundWorkIntent:
    """Background developer tools cannot assert active work intent."""

    @staticmethod
    def _at_hour(hour: int):
        return patch("backend.services.pc_agent.activity_detector.datetime")

    @pytest.mark.parametrize(
        ("processes", "fg_proc"),
        [
            ({"firefox.exe", "windowsterminal.exe"}, "firefox.exe"),
            ({"explorer.exe", "code.exe"}, "explorer.exe"),
            ({"lockapp.exe", "powershell.exe"}, "lockapp.exe"),
        ],
    )
    def test_background_work_processes_fall_back_to_idle(
        self, processes, fg_proc,
    ):
        d = _make_detector(processes=processes, fg_proc=fg_proc)

        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 10, 15, 0)
            assert d._classify() == "idle"

        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "fallback_idle"

    @pytest.mark.parametrize("fg_proc", ["windowsterminal.exe", "code.exe"])
    def test_foreground_work_process_is_working(self, fg_proc):
        d = _make_detector(processes={fg_proc}, fg_proc=fg_proc)

        assert d._classify() == "working"
        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "foreground_work"

    def test_foreground_browser_media_beats_background_terminal(self):
        d = _make_detector(
            processes={"firefox.exe", "windowsterminal.exe"},
            fg_proc="firefox.exe",
            fg_title="A video - YouTube - Mozilla Firefox",
            browser_playback_status="playing",
        )

        assert d._classify() == "watching"
        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "foreground_browser_playing"

    def test_established_browser_pause_grace_remains_watching(self):
        d = _make_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="A video - YouTube - Mozilla Firefox",
            browser_playback_status="pause_grace",
        )

        assert d._classify() == "watching"
        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "foreground_browser_pause_grace"

    def test_playing_browser_survives_global_input_idle(self):
        d = _make_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="A video - YouTube - Mozilla Firefox",
            idle_seconds=601,
            browser_playback_status="playing",
        )

        assert d._classify() == "watching"
        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "foreground_browser_playing"

    def test_stopped_foreground_youtube_is_not_watching(self):
        d = _make_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="A video - YouTube - Mozilla Firefox",
            browser_playback_status="paused",
        )

        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 4, 15, 0)
            assert d._classify() == "idle"

        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "fallback_idle"
        assert d._last_classification.browser_playback_status == "paused"

    def test_youtube_music_playing_is_not_video_watching(self):
        d = _make_detector(
            processes={"firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="Track - YouTube Music - Mozilla Firefox",
            browser_playback_status="playing",
        )

        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 4, 15, 0)
            assert d._classify() == "idle"

    def test_background_stremio_process_does_not_assert_watching(self):
        d = _make_detector(
            processes={"stremio service.exe", "explorer.exe"},
            fg_proc="explorer.exe",
        )

        with self._at_hour(15) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 4, 15, 0)
            assert d._classify() == "idle"

        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "fallback_idle"

    def test_late_night_browser_remains_working(self):
        d = _make_detector(processes={"firefox.exe"}, fg_proc="firefox.exe")

        with self._at_hour(22) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 10, 22, 0)
            assert d._classify() == "working"

        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "late_night_browser"


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

    def test_runelite_executable_commits_gaming(self):
        d = _make_detector(
            processes={"runelite.exe"},
            fg_proc="runelite.exe",
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

    def test_red_dead_redemption_2_foreground_commits_gaming(self):
        d = _make_detector(
            processes={"rdr2.exe"},
            fg_proc="rdr2.exe",
            idle_seconds=0,
        )
        assert "rdr2.exe" in GAME_PROCESSES
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
        assert d._last_classification is not None
        assert d._last_classification.gaming_qualification == "background_game_idle"

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


class TestForegroundRuneLiteJava:
    """Only a foreground Java client with three RuneLite signals is gaming."""

    def _detector(
        self,
        *,
        process_name: str = "java.exe",
        title: str = "RuneLite - Photochalupa",
        processes: set[str] | None = None,
    ) -> ActivityDetector:
        detector = _make_detector(
            processes=processes or {process_name},
            fg_proc=process_name,
            fg_title=title,
        )
        detector._get_foreground_process_identity = lambda: (  # type: ignore[method-assign]
            process_name,
            title,
            1376,
        )
        return detector

    @pytest.mark.parametrize(
        ("process_name", "title", "command_line"),
        [
            (
                "java.exe",
                "RuneLite - Photochalupa",
                r"net.runelite\client-1.12.35.jar --developer-mode --debug",
            ),
            ("javaw.exe", "RuneLite", "net.runelite/client-1.12.35.jar"),
            ("java.exe", "RuneLite – Photochalupa", "net.runelite/client.jar"),
            ("java.exe", "rUnElItE — Photochalupa", "net.runelite/client.jar"),
        ],
    )
    def test_foreground_runelite_java_commits_gaming(
        self, process_name, title, command_line
    ):
        detector = self._detector(process_name=process_name, title=title)
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.Process"
        ) as process:
            process.return_value.cmdline.return_value = command_line.split()
            assert detector._classify() == "gaming"

    def test_runelite_looking_java_without_client_marker_does_not_use_background_work(self):
        detector = self._detector(processes={"java.exe", "code.exe"})
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.Process"
        ) as process:
            process.return_value.cmdline.return_value = ["java", "other-app.jar"]
            assert detector._classify() == "idle"

    def test_runelite_client_marker_with_unrelated_title_is_not_gaming(self):
        detector = self._detector(title="Photochalupa Companion")
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.Process"
        ) as process:
            process.return_value.cmdline.return_value = ["net.runelite/client.jar"]
            assert detector._classify() == "idle"

    @pytest.mark.parametrize(
        "title, command_line",
        [
            ("Gradle Daemon", ["gradle", "daemon"]),
            ("IntelliJ IDEA", ["idea", "jbr"]),
            ("My Java Tool", ["java", "custom-gui.jar"]),
        ],
    )
    def test_non_runelite_java_apps_are_not_gaming(self, title, command_line):
        detector = self._detector(title=title)
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.Process"
        ) as process:
            process.return_value.cmdline.return_value = command_line
            assert detector._classify() == "idle"

    def test_command_line_access_denied_fails_closed(self):
        detector = self._detector()
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.Process"
        ) as process:
            process.return_value.cmdline.side_effect = psutil.AccessDenied(pid=1376)
            assert detector._classify() == "idle"

    def test_background_runelite_java_with_recent_input_preserves_gaming(self):
        detector = _make_detector(
            processes={"java.exe", "firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="Old School RuneScape Wiki - Mozilla Firefox",
            idle_seconds=GAMING_IDLE_THRESHOLD - 30,
        )
        detector._find_running_runelite_java_pid = lambda: 1376  # type: ignore[method-assign]

        assert detector._classify() == "gaming"
        assert detector._last_classification is not None
        assert detector._last_classification.candidate_reason == "recent_input_game_hold"
        assert detector._last_classification.matched_game_process == "runelite-java"
        assert (
            detector._last_classification.gaming_qualification
            == "recent_input_runelite_java_hold"
        )

    def test_background_runelite_java_releases_after_input_hold_expires(self):
        detector = _make_detector(
            processes={"java.exe", "firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="Old School RuneScape Wiki - Mozilla Firefox",
            idle_seconds=GAMING_IDLE_THRESHOLD,
        )
        detector._find_running_runelite_java_pid = lambda: 1376  # type: ignore[method-assign]

        assert detector._classify() != "gaming"
        assert detector._last_classification is not None
        assert (
            detector._last_classification.gaming_qualification
            == "background_runelite_java_idle"
        )

    def test_background_unverified_java_does_not_promote_gaming(self):
        detector = _make_detector(
            processes={"java.exe", "firefox.exe"},
            fg_proc="firefox.exe",
            fg_title="GitHub - Mozilla Firefox",
            idle_seconds=0,
        )
        detector._find_running_runelite_java_pid = lambda: None  # type: ignore[method-assign]

        assert detector._classify() != "gaming"
        assert detector._last_classification is not None
        assert detector._last_classification.matched_game_process is None
        assert detector._last_classification.gaming_qualification is None


class TestRunningRuneLiteJavaIdentity:
    """Background Java qualification requires RuneLite's classpath marker."""

    class _Proc:
        def __init__(self, pid: int, name: str, command_line):
            self.info = {"pid": pid, "name": name}
            self._command_line = command_line

        def cmdline(self):
            if isinstance(self._command_line, BaseException):
                raise self._command_line
            return self._command_line

    def test_finds_runelite_among_multiple_java_processes(self):
        detector = ActivityDetector()
        processes = [
            self._Proc(100, "java.exe", ["java", "org.gradle.launcher.daemon.bootstrap.GradleDaemon"]),
            self._Proc(200, "javaw.exe", [r"C:\Java\bin\javaw.exe", r"net.runelite\client\1.12.35\client-1.12.35.jar"]),
            self._Proc(300, "java.exe", ["java", "custom-tool.jar"]),
        ]
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.process_iter",
            return_value=iter(processes),
        ):
            assert detector._find_running_runelite_java_pid() == 200

    def test_gradle_and_unrelated_java_do_not_qualify(self):
        detector = ActivityDetector()
        processes = [
            self._Proc(100, "java.exe", ["java", "org.gradle.launcher.daemon.bootstrap.GradleDaemon"]),
            self._Proc(300, "javaw.exe", ["javaw", "custom-tool.jar"]),
        ]
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.process_iter",
            return_value=iter(processes),
        ):
            assert detector._find_running_runelite_java_pid() is None

    def test_access_denied_java_fails_closed(self):
        detector = ActivityDetector()
        processes = [
            self._Proc(100, "java.exe", psutil.AccessDenied(pid=100)),
        ]
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.process_iter",
            return_value=iter(processes),
        ):
            assert detector._find_running_runelite_java_pid() is None

    def test_non_java_process_with_marker_does_not_qualify(self):
        detector = ActivityDetector()
        processes = [
            self._Proc(400, "python.exe", [r"net.runelite\client\client.jar"]),
        ]
        with patch(
            "backend.services.pc_agent.activity_detector.psutil.process_iter",
            return_value=iter(processes),
        ):
            assert detector._find_running_runelite_java_pid() is None


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

    def test_watching_sticky_hold_stays_intact_for_terminal_alt_tab(self):
        """The existing night watching hold still absorbs a brief terminal peek."""
        d = _make_detector(
            processes={"stremio.exe", "windowsterminal.exe"},
            fg_proc="stremio.exe",
        )
        with patch(
            "backend.services.pc_agent.activity_detector.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 8, 10, 22, 0)
            with self._patch_time(0.0):
                assert d.detect() == "watching"

            d._get_foreground_window = lambda: (  # type: ignore[method-assign]
                "windowsterminal.exe", "",
            )
            d._get_foreground_process_identity = lambda: (  # type: ignore[method-assign]
                "windowsterminal.exe", "", None,
            )
            with self._patch_time(30.0):
                assert d.detect() == "watching"

        assert d._last_classification is not None
        assert d._last_classification.candidate_reason == "watching_sticky_hold"


# ---------------------------------------------------------------------------
# Factor payload — source/device context for backend ownership policy
# ---------------------------------------------------------------------------


def test_input_idle_validity_tracks_win32_probe_success(monkeypatch):
    d = ActivityDetector()
    monkeypatch.setattr(d, "_read_last_input", lambda: None)
    assert d._get_idle_seconds() == 0
    assert d._input_idle_valid is False

    monkeypatch.setattr(d, "_read_last_input", lambda: (10_000, 9_000))
    assert d._get_idle_seconds() == 1
    assert d._input_idle_valid is True


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
    factor_values = {factor["key"]: factor["value"] for factor in factors}
    assert factor_values["input_idle_valid"] is False
    assert len(factors) <= 15
    assert "foreground_title" not in {factor["key"] for factor in factors}


def test_classifier_factors_capture_candidate_and_pending_dwell():
    d = _make_detector(
        processes={"code.exe"},
        fg_proc="code.exe",
        idle_seconds=12,
    )
    with patch("backend.services.pc_agent.activity_detector.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 10, 15, 0)
        with patch(
            "backend.services.pc_agent.activity_detector.time.time", return_value=0.0,
        ):
            assert d.detect() == "working"

        d._get_running_process_names = lambda: {  # type: ignore[method-assign]
            "firefox.exe", "windowsterminal.exe",
        }
        d._get_foreground_window = lambda: (  # type: ignore[method-assign]
            "firefox.exe", "Mozilla Firefox",
        )
        d._get_foreground_process_identity = lambda: (  # type: ignore[method-assign]
            "firefox.exe", "Mozilla Firefox", None,
        )
        with patch(
            "backend.services.pc_agent.activity_detector.time.time", return_value=10.0,
        ):
            assert d.detect() == "working"

    factors = {factor["key"]: factor["value"] for factor in d.build_factors()}
    assert factors["candidate_mode"] == "idle"
    assert factors["classified_mode"] == "working"
    assert factors["candidate_reason"] == "fallback_idle"
    assert factors["foreground"] == "firefox.exe"
    assert factors["foreground_kind"] == "browser"
    assert factors["matched_work_processes"] == ["windowsterminal.exe"]
    assert factors["idle"] == 12
    assert factors["pending_mode"] == "idle"
    assert factors["pending_dwell_age"] == 0.0


def test_watching_factors_expose_playback_reason_without_page_title():
    d = _make_detector(
        processes={"firefox.exe"},
        fg_proc="firefox.exe",
        fg_title="Blue Planet - YouTube - Mozilla Firefox",
        browser_playback_status="playing",
    )

    assert d._classify() == "watching"
    factors = {factor["key"]: factor["value"] for factor in d.build_factors()}

    assert factors["candidate_reason"] == "foreground_browser_playing"
    assert factors["browser_playback"] == "playing"
    assert "foreground_title" not in factors


def test_classifier_factors_capture_foreground_game_qualification():
    d = _make_detector(processes={"planetzoo.exe"}, fg_proc="planetzoo.exe")

    assert d.detect() == "gaming"

    factors = {factor["key"]: factor["value"] for factor in d.build_factors()}
    assert factors["candidate_mode"] == "gaming"
    assert factors["classified_mode"] == "gaming"
    assert factors["candidate_reason"] == "foreground_game"
    assert factors["matched_game_process"] == "planetzoo.exe"
    assert factors["gaming_qualification"] == "foreground_game"


def test_foreground_game_telemetry_uses_qualifying_snapshot():
    d = _make_detector(processes={"planetzoo.exe", "code.exe"}, fg_proc=None)
    d._get_foreground_process_identity = lambda: (  # type: ignore[method-assign]
        "planetzoo.exe",
        "Planet Zoo",
        42,
    )
    # A rapid focus change would make a later independent lookup disagree.
    # Classification must retain the snapshot that qualified foreground gaming.
    d._get_foreground_window = lambda: (  # type: ignore[method-assign]
        "code.exe",
        "Home Hub - Visual Studio Code",
    )

    assert d._classify() == "gaming"

    factors = {factor["key"]: factor["value"] for factor in d.build_factors()}
    assert factors["candidate_reason"] == "foreground_game"
    assert factors["foreground"] == "planetzoo.exe"
    assert factors["foreground_kind"] == "game"
    assert factors["matched_game_process"] == "planetzoo.exe"
    assert factors["gaming_qualification"] == "foreground_game"

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
