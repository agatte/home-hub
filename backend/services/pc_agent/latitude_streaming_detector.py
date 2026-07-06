"""Latitude streaming detector.

Runs on the production Latitude and reports active living-room media playback as
``mode=watching`` through the existing automation activity endpoint. The detector
requires playback evidence (MPRIS Playing or a PipeWire media stream); a merely
open Stremio window is not enough.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

import httpx
import psutil

from backend.services.pc_agent.game_list import WATCHING_TITLE_KEYWORDS

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "latitude_streaming_detector.log"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("home_hub.latitude_streaming")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)
_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=2 * 1024 * 1024,
    backupCount=2,
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)

POLL_INTERVAL_SECONDS = 5.0
HEARTBEAT_INTERVAL_SECONDS = 15.0
HEALTH_INTERVAL_SECONDS = 30.0
STOP_DWELL_SECONDS = 20.0

MEDIA_PROCESS_HINTS = (
    "stremio",
    "vlc",
    "mpv",
    "firefox",
    "chrome",
    "chromium",
)
PIPEWIRE_STREAM_HINTS = (
    "stremio",
    "vlc",
    "mpv",
    "firefox",
    "chrome",
    "chromium",
    "qtwebengine",
)
BROWSER_PROCESS_HINTS = frozenset({"firefox", "chrome", "chromium"})


@dataclass
class PlaybackSnapshot:
    active: bool
    method: str = "none"
    player: str = "none"
    processes: list[str] = field(default_factory=list)
    detail: str = ""


class LatitudeStreamingDetector:
    """Detect active media playback on the Latitude."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        stop_dwell_seconds: float = STOP_DWELL_SECONDS,
    ) -> None:
        self._clock = clock
        self._stop_dwell_seconds = stop_dwell_seconds
        self._last_active_at: Optional[float] = None
        self._last_reported_mode: Optional[str] = None
        self._last_sent_at: float = 0.0

    def snapshot(self) -> PlaybackSnapshot:
        processes = self._running_media_processes()
        mpris = self._mpris_snapshot(processes)
        if mpris.active:
            return mpris
        pipewire = self._pipewire_snapshot(processes)
        if pipewire.active:
            return pipewire
        return PlaybackSnapshot(active=False, processes=processes)

    def mode_for_snapshot(self, snapshot: PlaybackSnapshot) -> Optional[str]:
        now = self._clock()
        if snapshot.active:
            self._last_active_at = now
            return "watching"

        if self._last_reported_mode != "watching" or self._last_active_at is None:
            return None
        if now - self._last_active_at < self._stop_dwell_seconds:
            return None
        return "idle"

    def should_send(self, mode: str) -> bool:
        now = self._clock()
        return (
            mode != self._last_reported_mode
            or now - self._last_sent_at >= HEARTBEAT_INTERVAL_SECONDS
        )

    def mark_sent(self, mode: str) -> None:
        self._last_reported_mode = mode
        self._last_sent_at = self._clock()

    def build_factors(self, snapshot: PlaybackSnapshot) -> list[dict]:
        return [
            {
                "key": "device",
                "label": "Device",
                "value": "latitude",
                "display": "latitude",
                "impact": 1.0,
            },
            {
                "key": "foreground_kind",
                "label": "Kind",
                "value": "media" if snapshot.active else "none",
                "display": "media" if snapshot.active else "none",
                "impact": 0.9 if snapshot.active else 0.2,
            },
            {
                "key": "foreground",
                "label": "Media",
                "value": snapshot.player,
                "display": snapshot.player,
                "impact": 0.9 if snapshot.active else 0.2,
            },
            {
                "key": "playback_active",
                "label": "Playback",
                "value": snapshot.active,
                "display": "playing" if snapshot.active else "stopped",
                "impact": 1.0 if snapshot.active else 0.1,
            },
            {
                "key": "detection_method",
                "label": "Method",
                "value": snapshot.method,
                "display": snapshot.method,
                "impact": 0.7,
            },
        ]

    def _running_media_processes(self) -> list[str]:
        seen: set[str] = set()
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            haystack = f"{name} {cmdline}"
            for hint in MEDIA_PROCESS_HINTS:
                if hint in haystack:
                    seen.add(hint)
        return sorted(seen)

    def _mpris_snapshot(self, processes: list[str]) -> PlaybackSnapshot:
        names = self._mpris_names()
        for name in names:
            status = self._mpris_playback_status(name)
            if status != "Playing":
                continue
            player = self._mpris_player_name(name)
            metadata = self._mpris_metadata(name)
            if self._browser_hint(name) and not self._looks_like_streaming_page(metadata):
                continue
            return PlaybackSnapshot(
                active=True,
                method="mpris",
                player=player,
                processes=processes,
                detail=metadata or name,
            )
        return PlaybackSnapshot(active=False, method="mpris", processes=processes)

    def _mpris_names(self) -> list[str]:
        result = self._run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.DBus",
                "--object-path",
                "/org/freedesktop/DBus",
                "--method",
                "org.freedesktop.DBus.ListNames",
            ]
        )
        if result.returncode != 0:
            return []
        return sorted(set(re.findall(r"org\.mpris\.MediaPlayer2[\w.:-]*", result.stdout)))

    def _mpris_playback_status(self, bus_name: str) -> Optional[str]:
        result = self._run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                bus_name,
                "--object-path",
                "/org/mpris/MediaPlayer2",
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.mpris.MediaPlayer2.Player",
                "PlaybackStatus",
            ]
        )
        if result.returncode != 0:
            return None
        for status in ("Playing", "Paused", "Stopped"):
            if status in result.stdout:
                return status
        return None

    def _mpris_metadata(self, bus_name: str) -> str:
        result = self._run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                bus_name,
                "--object-path",
                "/org/mpris/MediaPlayer2",
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.mpris.MediaPlayer2.Player",
                "Metadata",
            ]
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def _pipewire_snapshot(self, processes: list[str]) -> PlaybackSnapshot:
        result = self._run(["wpctl", "status"])
        if result.returncode != 0:
            return PlaybackSnapshot(active=False, method="pipewire", processes=processes)
        section = self._audio_streams_section(result.stdout).lower()
        active_title = self._active_window_title()
        for hint in PIPEWIRE_STREAM_HINTS:
            if hint not in section:
                continue
            if self._browser_hint(hint) and not self._looks_like_streaming_page(active_title):
                continue
            return PlaybackSnapshot(
                active=True,
                method="pipewire",
                player=hint,
                processes=processes,
                detail=active_title or hint,
            )
        return PlaybackSnapshot(active=False, method="pipewire", processes=processes)

    def _active_window_title(self) -> str:
        result = self._run(["xdotool", "getactivewindow", "getwindowname"])
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    @staticmethod
    def _mpris_player_name(bus_name: str) -> str:
        lowered = bus_name.lower()
        for hint in BROWSER_PROCESS_HINTS:
            if hint in lowered:
                return hint
        return bus_name.rsplit(".", 1)[-1].lower()

    @staticmethod
    def _browser_hint(value: str) -> bool:
        lowered = value.lower()
        return any(hint in lowered for hint in BROWSER_PROCESS_HINTS)

    @staticmethod
    def _looks_like_streaming_page(value: str) -> bool:
        lowered = value.lower()
        return any(keyword in lowered for keyword in WATCHING_TITLE_KEYWORDS)

    @staticmethod
    def _audio_streams_section(output: str) -> str:
        lines = output.splitlines()
        in_audio = False
        in_streams = False
        captured: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == "Audio":
                in_audio = True
                continue
            if stripped == "Video":
                break
            if not in_audio:
                continue
            if "Streams:" in stripped:
                in_streams = True
                continue
            if in_streams:
                if stripped.startswith("Settings"):
                    break
                captured.append(line)
        return "\n".join(captured)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(exc))


def _post_health(
    client: httpx.Client,
    endpoint: str,
    *,
    started_at: float,
    last_error: Optional[str],
) -> None:
    now = time.time()
    try:
        client.post(
            endpoint,
            json={
                "origin": "latitude",
                "agents": {
                    "latitude_streaming_detector": {
                        "status": "running",
                        "uptime": int(now - started_at),
                        "restarts": 0,
                        "last_error": last_error,
                        "heartbeat_age": 0,
                    },
                },
                "service_uptime": int(now - started_at),
            },
        )
    except Exception:
        logger.debug("latitude streaming health POST failed", exc_info=True)


def run_agent(
    server_url: str,
    stop_event: Optional[threading.Event] = None,
    heartbeat: Optional[Callable[[], None]] = None,
) -> None:
    base_url = server_url.rstrip("/")
    activity_endpoint = f"{base_url}/api/automation/activity"
    health_endpoint = f"{base_url}/api/automation/agent-health"
    detector = LatitudeStreamingDetector()
    stop = stop_event or threading.Event()
    started_at = time.time()
    last_health_at = 0.0
    last_error: Optional[str] = None

    logger.info("Latitude streaming detector started - reporting to %s", activity_endpoint)

    with httpx.Client(timeout=5.0) as client:
        while not stop.is_set():
            if heartbeat is not None:
                heartbeat()
            try:
                snapshot = detector.snapshot()
                mode = detector.mode_for_snapshot(snapshot)
                if mode is not None and detector.should_send(mode):
                    payload = {
                        "mode": mode,
                        "source": "process",
                        "detected_at": datetime.now().isoformat(),
                        "factors": detector.build_factors(snapshot),
                    }
                    resp = client.post(activity_endpoint, json=payload)
                    resp.raise_for_status()
                    detector.mark_sent(mode)
                    logger.info(
                        "Reported latitude streaming mode=%s active=%s method=%s player=%s",
                        mode,
                        snapshot.active,
                        snapshot.method,
                        snapshot.player,
                    )
                last_error = None
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Latitude streaming iteration failed: %s", exc)

            now = time.time()
            if now - last_health_at >= HEALTH_INTERVAL_SECONDS:
                _post_health(
                    client,
                    health_endpoint,
                    started_at=started_at,
                    last_error=last_error,
                )
                last_health_at = now

            stop.wait(POLL_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Home Hub Latitude streaming detector")
    parser.add_argument("--server", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        run_agent(args.server)
    except KeyboardInterrupt:
        logger.info("Latitude streaming detector stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
