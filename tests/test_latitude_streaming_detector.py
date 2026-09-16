"""Tests for the Latitude streaming detector."""

from __future__ import annotations

import subprocess

import pytest

from backend.services.pc_agent.latitude_streaming_detector import (
    LatitudeStreamingDetector,
    PlaybackSnapshot,
)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeDetector(LatitudeStreamingDetector):
    def __init__(self, *, outputs: dict[tuple[str, ...], str] | None = None, clock=None):
        super().__init__(clock=clock or (lambda: 0.0), stop_dwell_seconds=20.0)
        self.outputs = outputs or {}
        self.processes = []

    def _running_media_processes(self) -> list[str]:
        return self.processes

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        stdout = self.outputs.get(tuple(args), "")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def test_open_stremio_without_playback_does_not_report_watching():
    detector = FakeDetector(
        outputs={
            (
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ): "([],)"
        }
    )
    detector.processes = ["stremio"]

    snapshot = detector.snapshot()

    assert snapshot.active is False
    assert detector.mode_for_snapshot(snapshot) is None


def test_mpris_playing_reports_watching():
    list_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    status_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.mpris.MediaPlayer2.stremio",
        "--object-path",
        "/org/mpris/MediaPlayer2",
        "--method",
        "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
    )
    detector = FakeDetector(
        outputs={
            list_cmd: "(['org.mpris.MediaPlayer2.stremio'],)",
            status_cmd: "(<('Playing',)>,)",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is True
    assert snapshot.method == "mpris"
    assert detector.mode_for_snapshot(snapshot) == "watching"


def test_pipewire_media_stream_reports_watching():
    detector = FakeDetector(
        outputs={
            (
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ): "([],)",
            ("wpctl", "status"): """
Audio
 └─ Streams:
        99. Stremio
             100. output_FL > Built-in Audio
Video
""",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is True
    assert snapshot.method == "pipewire"
    assert snapshot.player == "stremio"


def test_stop_dwell_delays_idle_report():
    clock = FakeClock()
    detector = LatitudeStreamingDetector(clock=clock, stop_dwell_seconds=20.0)

    assert detector.mode_for_snapshot(PlaybackSnapshot(active=True, player="stremio")) == "watching"
    detector.mark_sent("watching")

    clock.now = 10.0
    assert detector.mode_for_snapshot(PlaybackSnapshot(active=False)) is None

    clock.now = 21.0
    assert detector.mode_for_snapshot(PlaybackSnapshot(active=False)) == "idle"


def test_build_factors_include_latitude_device_and_playback_state():
    detector = LatitudeStreamingDetector()
    factors = detector.build_factors(
        PlaybackSnapshot(
            active=True, method="mpris", player="firefox", service="hulu",
            position_seconds=123.0, length_seconds=987.0,
        ),
    )

    assert factors[0]["key"] == "device"
    assert factors[0]["value"] == "latitude"
    by_key = {factor["key"]: factor["value"] for factor in factors}
    assert by_key["playback_active"] is True
    assert by_key["detection_method"] == "mpris"
    assert by_key["streaming_service"] == "hulu"


def test_mpris_browser_streaming_page_reports_watching():
    list_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    status_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.mpris.MediaPlayer2.firefox.instance42",
        "--object-path",
        "/org/mpris/MediaPlayer2",
        "--method",
        "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
    )
    metadata_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.mpris.MediaPlayer2.firefox.instance42",
        "--object-path",
        "/org/mpris/MediaPlayer2",
        "--method",
        "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player",
        "Metadata",
    )
    position_cmd = (
        "gdbus", "call", "--session", "--dest",
        "org.mpris.MediaPlayer2.firefox.instance42",
        "--object-path", "/org/mpris/MediaPlayer2",
        "--method", "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player", "Position",
    )
    detector = FakeDetector(
        outputs={
            list_cmd: "(['org.mpris.MediaPlayer2.firefox.instance42'],)",
            status_cmd: "(<('Playing',)>,)",
            metadata_cmd: "{'xesam:url': <'https://www.hulu.com/watch/abc'>, 'xesam:title': <'Hulu'>, 'mpris:length': <int64 987000000>}",
            position_cmd: "(<int64 123000000>,)",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is True
    assert snapshot.method == "mpris"
    assert snapshot.player == "firefox"
    assert snapshot.service == "hulu"
    assert snapshot.position_seconds == 123.0
    assert snapshot.length_seconds == 987.0
    assert snapshot.length_minus_position_seconds == 864.0


def test_mpris_browser_non_streaming_page_does_not_report_watching():
    list_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    status_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.mpris.MediaPlayer2.firefox.instance42",
        "--object-path",
        "/org/mpris/MediaPlayer2",
        "--method",
        "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
    )
    metadata_cmd = (
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.mpris.MediaPlayer2.firefox.instance42",
        "--object-path",
        "/org/mpris/MediaPlayer2",
        "--method",
        "org.freedesktop.DBus.Properties.Get",
        "org.mpris.MediaPlayer2.Player",
        "Metadata",
    )
    detector = FakeDetector(
        outputs={
            list_cmd: "(['org.mpris.MediaPlayer2.firefox.instance42'],)",
            status_cmd: "(<('Playing',)>,)",
            metadata_cmd: "{'xesam:url': <'https://example.com'>, 'xesam:title': <'Example'>}",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is False


def test_pipewire_browser_streaming_title_reports_watching():
    detector = FakeDetector(
        outputs={
            (
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ): "([],)",
            ("wpctl", "status"): """
Audio
 └─ Streams:
        99. Firefox
             100. output_FL > Built-in Audio
Video
""",
            ("xdotool", "getactivewindow", "getwindowname"): "YouTube - Firefox",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is True
    assert snapshot.method == "pipewire"
    assert snapshot.player == "firefox"


def test_pipewire_browser_audio_without_streaming_title_does_not_report_watching():
    detector = FakeDetector(
        outputs={
            (
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ): "([],)",
            ("wpctl", "status"): """
Audio
 └─ Streams:
        99. Firefox
             100. output_FL > Built-in Audio
Video
""",
            ("xdotool", "getactivewindow", "getwindowname"): "Docs - Firefox",
        }
    )

    snapshot = detector.snapshot()

    assert snapshot.active is False


def test_chromium_live_length_sentinel_is_unknown():
    metadata = (
        "{'xesam:title': <'Hulu | Live TV'>, "
        "'mpris:length': <int64 9223372036854775807>}"
    )
    assert LatitudeStreamingDetector._mpris_length_us(metadata) is None


def test_viewer_clock_snapshot_prefers_chromium_hulu_and_keeps_pause():
    firefox = "org.mpris.MediaPlayer2.firefox.instance42"
    chromium = "org.mpris.MediaPlayer2.chromium.instance99"
    list_cmd = (
        "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
        "--object-path", "/org/freedesktop/DBus", "--method",
        "org.freedesktop.DBus.ListNames",
    )

    def prop_cmd(name: str, prop: str) -> tuple[str, ...]:
        return (
            "gdbus", "call", "--session", "--dest", name,
            "--object-path", "/org/mpris/MediaPlayer2", "--method",
            "org.freedesktop.DBus.Properties.Get",
            "org.mpris.MediaPlayer2.Player", prop,
        )
    detector = FakeDetector(outputs={
        list_cmd: f"(['{firefox}', '{chromium}'],)",
        prop_cmd(firefox, "Metadata"): "{'xesam:title': <'Hulu | Live TV'>}",
        prop_cmd(firefox, "PlaybackStatus"): "(<('Playing',)>,)",
        prop_cmd(firefox, "Position"): "(<int64 1789501000000000>,)",
        prop_cmd(chromium, "Metadata"): "{'xesam:title': <'Hulu | Live TV'>}",
        prop_cmd(chromium, "PlaybackStatus"): "(<('Paused',)>,)",
        prop_cmd(chromium, "Position"): "(<int64 1789502000500000>,)",
    })

    snapshot = detector.viewer_clock_snapshot()

    assert snapshot is not None
    assert snapshot.player == "chromium"
    assert snapshot.service == "hulu"
    assert snapshot.playback_status == "Paused"
    assert snapshot.media_timestamp == pytest.approx(1789502000.5)
