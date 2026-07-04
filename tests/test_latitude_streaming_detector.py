"""Tests for the Latitude streaming detector."""
from __future__ import annotations

import subprocess

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
    detector = FakeDetector(outputs={
        (
            "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
            "--object-path", "/org/freedesktop/DBus", "--method",
            "org.freedesktop.DBus.ListNames",
        ): "([],)"
    })
    detector.processes = ["stremio"]

    snapshot = detector.snapshot()

    assert snapshot.active is False
    assert detector.mode_for_snapshot(snapshot) is None


def test_mpris_playing_reports_watching():
    list_cmd = (
        "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
        "--object-path", "/org/freedesktop/DBus", "--method",
        "org.freedesktop.DBus.ListNames",
    )
    status_cmd = (
        "gdbus", "call", "--session", "--dest", "org.mpris.MediaPlayer2.stremio",
        "--object-path", "/org/mpris/MediaPlayer2", "--method",
        "org.freedesktop.DBus.Properties.Get", "org.mpris.MediaPlayer2.Player",
        "PlaybackStatus",
    )
    detector = FakeDetector(outputs={
        list_cmd: "(['org.mpris.MediaPlayer2.stremio'],)",
        status_cmd: "(<('Playing',)>,)",
    })

    snapshot = detector.snapshot()

    assert snapshot.active is True
    assert snapshot.method == "mpris"
    assert detector.mode_for_snapshot(snapshot) == "watching"


def test_pipewire_media_stream_reports_watching():
    detector = FakeDetector(outputs={
        (
            "gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
            "--object-path", "/org/freedesktop/DBus", "--method",
            "org.freedesktop.DBus.ListNames",
        ): "([],)",
        ("wpctl", "status"): """
Audio
 └─ Streams:
        99. Stremio
             100. output_FL > Built-in Audio
Video
""",
    })

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
        PlaybackSnapshot(active=True, method="mpris", player="stremio"),
    )

    assert factors[0]["key"] == "device"
    assert factors[0]["value"] == "latitude"
    assert {f["key"] for f in factors} >= {"playback_active", "detection_method"}