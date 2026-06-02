"""
Peripheral RGB agent — drives the desk peripherals' RGB (Keychron K10
keyboard + Glorious Model O mouse) to track the apartment's lighting.

Runs as a standalone agent on Anthony's Windows desktop (192.168.86.30),
managed by the pc_agent ``supervisor``. Talks to two endpoints:

  • Home Hub REST/WS on the Latitude (192.168.86.210:8000) — to read the
    live kitchen-pair color and to learn about League champions + Colts
    scoring plays.
  • A local OpenRGB SDK server (127.0.0.1:6742) — to actually set the
    LEDs. OpenRGB is the only software path that controls *both* devices
    (Glorious CORE dropped the V1 mouse; the Keychron has no desktop app).

Color policy (per Anthony, 2026-06-01):
  • Default: mirror the kitchen pair (Hue light id "3"). "Match the
    kitchen lights" is the resting behavior for every mode — we read the
    live bulb color and paint it onto both peripherals.
  • League override: while a *seeded* champion is active in gaming mode,
    use the champion's signature color instead (same color the bedroom
    lamps get via LoLChampionService). Pushed to us over the WS as a
    ``champion_color`` event; cleared when the match / gaming mode ends.
  • Game Day: a Colts scoring play (``gameday_play`` with
    ``scoring_team == "colts"``) fires a brief white↔Colts-navy pulse,
    then settles back to whatever the base color was.

Hardware constraint: neither device exposes a "Direct" (live-stream)
mode — only ``Static``. So we set solid colors and software-pace the
celebration pulse. No high-FPS screen-sync on these peripherals.

Pattern mirrors the other non-Qt agents (PID/stop_event, rotating log,
backoff WS reconnect). Entry point: ``run_agent(server_url, stop_event)``.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import logging
import math
import os
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import httpx

# Top-level import so the supervisor's ImportError guard cleanly skips
# this agent on a host without openrgb-python (e.g. the Latitude, which
# uses systemd and never runs the supervisor anyway).
from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, RGBColor

logger = logging.getLogger("home_hub.peripheral_rgb")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HTTP_SERVER = "http://192.168.86.210:8000"

# Local OpenRGB SDK server. The agent ensures it's running (launches
# ``OpenRGB.exe --server`` if the port is dead).
OPENRGB_HOST = "127.0.0.1"
OPENRGB_PORT = 6742
OPENRGB_EXE = os.environ.get(
    "HOMEHUB_OPENRGB_EXE", r"C:\Program Files\OpenRGB\OpenRGB.exe",
)

# Kitchen pair — L3/L4 share one color (kitchen-pair rule); reading L3 is
# sufficient. Hue light id, matching light_state_calculator's KITCHEN map.
KITCHEN_LIGHT_ID = "3"

# How often we re-read the kitchen color. Hue color (hue/sat/ct) changes
# ride the v1 5s poll on the backend and aren't reliably pushed over the
# WS, so we poll rather than rely on light_update events.
POLL_INTERVAL_S = 5.0

# Reconnect cadence — matches desktop_notifier / hue_v2_service.
RECONNECT_INITIAL_S = 1.0
RECONNECT_MAX_S = 30.0

# OpenRGB SDK reconnect cadence (separate, local, usually fast to recover).
SDK_RETRY_S = 3.0

# Celebration pulse — software-paced (no Direct mode). White↔Colts navy.
COLTS_NAVY = (0, 38, 84)
PULSE_FLASH = (255, 255, 255)
PULSE_CYCLES = 5
PULSE_HALF_PERIOD_S = 0.22

# Minimum per-channel delta before we bother issuing a write — avoids
# hammering the USB devices on sub-perceptual kitchen drift.
WRITE_EPSILON = 4

# Per-device color mode, in preference order. We need a mode that honors
# per-LED writes (``set_color`` writes the per-LED array): the Keychron's
# ``Custom`` is its per-key direct mode, while its ``Static`` is a single
# hardware mode-color that ignores per-LED data (keyboard reads back black).
# The Glorious mouse has only ``Static`` among these, and that does take a
# solid color. ``Direct`` (true streaming) isn't exposed by either device
# but is listed first in case a future device/firmware gains it.
COLOR_MODE_PREFERENCE = ("direct", "custom", "static")

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "peripheral_rgb.log"


def _configure_standalone_logging() -> None:
    """Attach file+console handlers when run directly (not via supervisor).

    The supervisor routes ``home_hub.peripheral_rgb`` through its own
    handlers, so we only add ours when no handler is present to avoid
    duplicate lines.
    """
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Color conversion — Hue bridge state → RGB
# ---------------------------------------------------------------------------

def _ct_to_rgb(mireds: int) -> tuple[int, int, int]:
    """Convert a Hue color temperature (mireds) to an approximate RGB.

    Mireds → Kelvin → RGB via the Tanner Helland approximation. Used for
    ct-mode bulbs (working whites, cooking, post-sunset warm states),
    which is what the kitchen pair sits in most of the time.
    """
    mireds = max(1, mireds)
    kelvin = 1_000_000 / mireds
    kelvin = max(1000.0, min(40000.0, kelvin))
    temp = kelvin / 100.0

    if temp <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(temp) - 161.1195681661
    else:
        red = 329.698727446 * ((temp - 60) ** -0.1332047592)
        green = 288.1221695283 * ((temp - 60) ** -0.0755148492)

    if temp >= 66:
        blue = 255.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temp - 10) - 305.0447927307

    return (
        int(max(0, min(255, red))),
        int(max(0, min(255, green))),
        int(max(0, min(255, blue))),
    )


def kitchen_rgb(light: dict[str, Any]) -> tuple[int, int, int]:
    """Derive an RGB color from a Hue light's reported state.

    Branches on ``colormode``: ct-mode bulbs convert via color temp,
    hs/xy-mode bulbs via hue+sat. Brightness scales the final value so a
    dim kitchen reads as a dim peripheral. ``on=False`` → off (black).
    """
    if not light.get("on"):
        return (0, 0, 0)

    bri = light.get("bri") or 0
    value = max(0.0, min(1.0, bri / 254.0))

    if light.get("colormode") == "ct":
        base = _ct_to_rgb(int(light.get("ct") or 366))
    else:
        h = (light.get("hue") or 0) / 65535.0
        s = max(0.0, min(1.0, (light.get("sat") or 0) / 254.0))
        rf, gf, bf = colorsys.hsv_to_rgb(h, s, 1.0)
        base = (int(rf * 255), int(gf * 255), int(bf * 255))

    return (
        int(base[0] * value),
        int(base[1] * value),
        int(base[2] * value),
    )


def _select_color_mode(device: Any) -> Optional[str]:
    """Pick the device's best mode for per-LED color writes.

    Walks COLOR_MODE_PREFERENCE and returns the first mode the device
    actually exposes (original-cased name for ``set_mode``), or None.
    """
    by_lower = {m.name.lower(): m.name for m in device.modes}
    for pref in COLOR_MODE_PREFERENCE:
        if pref in by_lower:
            return by_lower[pref]
    return None


# ---------------------------------------------------------------------------
# OpenRGB controller — wraps the SDK client + device targeting
# ---------------------------------------------------------------------------

class OpenRGBController:
    """Connects to the local OpenRGB SDK server and drives mouse+keyboard.

    All SDK access is serialized through ``_lock`` because the WS thread
    (champion / pulse) and the main poll thread both call in. The client
    is recreated on any error — OpenRGB drops the socket when its server
    restarts.
    """

    def __init__(self) -> None:
        self._client: Optional[OpenRGBClient] = None
        self._targets: list = []
        self._lock = threading.Lock()
        self._last_rgb: Optional[tuple[int, int, int]] = None

    # ---- connection lifecycle ----------------------------------------

    def _ensure_server(self) -> None:
        """Launch ``OpenRGB.exe --server`` if the SDK port isn't answering."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex((OPENRGB_HOST, OPENRGB_PORT)) == 0:
                return  # already up

        if not Path(OPENRGB_EXE).exists():
            logger.warning(
                "OpenRGB SDK down and exe not found at %s — cannot self-start",
                OPENRGB_EXE,
            )
            return

        logger.info("OpenRGB SDK not answering — launching %s --server", OPENRGB_EXE)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            subprocess.Popen(
                [OPENRGB_EXE, "--server", "--server-port", str(OPENRGB_PORT)],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            logger.exception("Failed to launch OpenRGB server")
            return
        time.sleep(4.0)  # give it a moment to detect devices + open the port

    def connect(self) -> bool:
        """(Re)establish the SDK client and resolve mouse+keyboard targets."""
        with self._lock:
            self._ensure_server()
            try:
                client = OpenRGBClient(
                    OPENRGB_HOST, OPENRGB_PORT, name="homehub-peripheral-rgb",
                )
            except Exception as e:
                logger.warning("OpenRGB SDK connect failed: %s", e)
                self._client = None
                return False

            targets = [
                d for d in client.devices
                if d.type in (DeviceType.MOUSE, DeviceType.KEYBOARD)
            ]
            if not targets:
                logger.warning("OpenRGB connected but no mouse/keyboard detected")
                self._client = client
                self._targets = []
                return False

            # Put each device on its best per-LED color mode once; thereafter
            # set_color is enough. Mode honoring per-LED writes differs per
            # device (see COLOR_MODE_PREFERENCE).
            for d in targets:
                mode = _select_color_mode(d)
                if mode is None:
                    logger.warning("%s exposes no settable color mode", d.name)
                    continue
                try:
                    d.set_mode(mode)
                    logger.info("%s -> color mode '%s'", d.name, mode)
                except Exception:
                    logger.debug("set_mode %s failed on %s", mode, d.name, exc_info=True)

            self._client = client
            self._targets = targets
            self._last_rgb = None
            logger.info(
                "OpenRGB connected — driving: %s",
                ", ".join(d.name for d in targets),
            )
            return True

    @property
    def ready(self) -> bool:
        return self._client is not None and bool(self._targets)

    # ---- writes -------------------------------------------------------

    def set_color(self, rgb: tuple[int, int, int], *, force: bool = False) -> None:
        """Set both peripherals to ``rgb``, skipping sub-epsilon no-ops.

        Raises on SDK failure so the caller can trigger a reconnect.
        """
        with self._lock:
            if not (self._client and self._targets):
                raise RuntimeError("controller not connected")
            if not force and self._last_rgb is not None:
                if all(abs(a - b) < WRITE_EPSILON for a, b in zip(rgb, self._last_rgb)):
                    return
            color = RGBColor(*rgb)
            for d in self._targets:
                d.set_color(color)
            self._last_rgb = rgb

    def pulse(self, base: tuple[int, int, int]) -> None:
        """Software-paced celebration flash, then settle to ``base``.

        Blocking (~2s); call from a dedicated thread so the WS recv loop
        keeps running.
        """
        try:
            for _ in range(PULSE_CYCLES):
                self.set_color(COLTS_NAVY, force=True)
                time.sleep(PULSE_HALF_PERIOD_S)
                self.set_color(PULSE_FLASH, force=True)
                time.sleep(PULSE_HALF_PERIOD_S)
            self.set_color(base, force=True)
        except Exception:
            logger.warning("pulse failed (will recover on next poll)", exc_info=True)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                self._targets = []


# ---------------------------------------------------------------------------
# Shared state between the WS thread and the poll loop
# ---------------------------------------------------------------------------

class SharedState:
    """Thread-safe holder for the champion override + pulse flag."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._champion_rgb: Optional[tuple[int, int, int]] = None
        self.pulsing = False
        self._last_base: tuple[int, int, int] = (0, 0, 0)

    def set_champion(self, rgb: Optional[tuple[int, int, int]]) -> None:
        with self._lock:
            self._champion_rgb = rgb

    @property
    def champion_rgb(self) -> Optional[tuple[int, int, int]]:
        with self._lock:
            return self._champion_rgb

    def remember_base(self, rgb: tuple[int, int, int]) -> None:
        with self._lock:
            self._last_base = rgb

    @property
    def last_base(self) -> tuple[int, int, int]:
        with self._lock:
            return self._last_base


# ---------------------------------------------------------------------------
# WebSocket worker — champion_color + gameday_play
# ---------------------------------------------------------------------------

class WsWorker(threading.Thread):
    """Listens for ``champion_color`` and ``gameday_play`` events."""

    def __init__(
        self,
        ws_url: str,
        state: SharedState,
        controller: OpenRGBController,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="peripheral-rgb-ws", daemon=True)
        self._url = ws_url
        self._state = state
        self._controller = controller
        self._stop = stop_event

    def run(self) -> None:
        import websockets
        import websockets.sync.client

        backoff = RECONNECT_INITIAL_S
        while not self._stop.is_set():
            try:
                with websockets.sync.client.connect(self._url, close_timeout=2.0) as ws:
                    logger.info("WS connected: %s", self._url)
                    backoff = RECONNECT_INITIAL_S
                    self._recv_loop(ws)
            except (OSError, websockets.exceptions.WebSocketException) as e:
                logger.warning("WS disconnect: %s (retry in %.1fs)", e, backoff)
            except Exception:
                logger.exception("WS worker unexpected error")
            finally:
                if self._stop.is_set():
                    return
                self._stop.wait(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_S)

    def _recv_loop(self, ws) -> None:
        while not self._stop.is_set():
            try:
                raw = ws.recv(timeout=5.0)
            except TimeoutError:
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            mtype = msg.get("type")
            data = msg.get("data") or {}
            if mtype == "champion_color":
                self._on_champion(data)
            elif mtype == "gameday_play":
                self._on_gameday_play(data)

    def _on_champion(self, data: dict[str, Any]) -> None:
        """Apply / clear the champion override.

        Only *seeded* champions (in champion_color_map) override the
        peripherals — a fallback-colored champion leaves us mirroring the
        kitchen, per the color policy.
        """
        seeded = bool(data.get("seeded"))
        rgb = data.get("rgb")
        if seeded and isinstance(rgb, (list, tuple)) and len(rgb) == 3:
            champ_rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            self._state.set_champion(champ_rgb)
            logger.info("Champion override: %s rgb=%s", data.get("champion"), champ_rgb)
            try:
                self._controller.set_color(champ_rgb, force=True)
            except Exception:
                logger.debug("champion apply failed (poll will retry)", exc_info=True)
        else:
            if self._state.champion_rgb is not None:
                logger.info("Champion override cleared — resuming kitchen mirror")
            self._state.set_champion(None)

    def _on_gameday_play(self, data: dict[str, Any]) -> None:
        """Fire a celebration pulse on Colts scoring plays only."""
        if data.get("scoring_team") != "colts":
            return
        if self._state.pulsing:
            return
        base = self._state.champion_rgb or self._state.last_base
        logger.info("Colts score (%s) — pulsing peripherals", data.get("play_type"))

        def _do_pulse() -> None:
            self._state.pulsing = True
            try:
                self._controller.pulse(base)
            finally:
                self._state.pulsing = False

        threading.Thread(target=_do_pulse, name="peripheral-rgb-pulse", daemon=True).start()


# ---------------------------------------------------------------------------
# Kitchen color polling
# ---------------------------------------------------------------------------

def _fetch_kitchen_light(client: httpx.Client, http_base: str) -> Optional[dict[str, Any]]:
    """GET /api/lights and return the kitchen-pair light dict, or None."""
    resp = client.get(f"{http_base}/api/lights", timeout=5.0)
    resp.raise_for_status()
    payload = resp.json()
    lights = payload.get("result") if isinstance(payload, dict) else payload
    if not isinstance(lights, list):
        return None
    for light in lights:
        if str(light.get("light_id")) == KITCHEN_LIGHT_ID:
            return light
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_agent(
    server_url: str = DEFAULT_HTTP_SERVER,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Run the peripheral RGB agent until ``stop_event`` is set.

    Args:
        server_url: Home Hub HTTP base (e.g. http://192.168.86.210:8000).
        stop_event: Optional shutdown signal (supplied by the supervisor).
    """
    _configure_standalone_logging()
    _stop = stop_event or threading.Event()

    http_base = server_url.rstrip("/")
    ws_url = http_base.replace("http://", "ws://").replace("https://", "wss://") + "/ws"

    state = SharedState()
    controller = OpenRGBController()
    controller.connect()

    ws_worker = WsWorker(ws_url, state, controller, _stop)
    ws_worker.start()

    logger.info("Peripheral RGB agent started — server=%s", http_base)

    with httpx.Client() as client:
        while not _stop.wait(POLL_INTERVAL_S):
            try:
                if not controller.ready:
                    controller.connect()
                    if not controller.ready:
                        _stop.wait(SDK_RETRY_S)
                        continue

                # Champion override and the celebration pulse own the LEDs
                # while active — skip the kitchen mirror so we don't fight.
                if state.champion_rgb is not None or state.pulsing:
                    continue

                light = _fetch_kitchen_light(client, http_base)
                if light is None:
                    continue
                rgb = kitchen_rgb(light)
                state.remember_base(rgb)
                controller.set_color(rgb)
            except (httpx.HTTPError, OSError) as e:
                logger.debug("kitchen poll transient error: %s", e)
            except RuntimeError:
                # Controller dropped — force a reconnect next tick.
                controller.close()
            except Exception:
                logger.exception("peripheral rgb loop error")

    ws_worker.join(timeout=3.0)
    controller.close()
    logger.info("Peripheral RGB agent stopped")


def main() -> int:
    parser = argparse.ArgumentParser(description="Home Hub Peripheral RGB Agent")
    parser.add_argument(
        "--server",
        default=DEFAULT_HTTP_SERVER,
        help=f"Home Hub HTTP base URL (default: {DEFAULT_HTTP_SERVER})",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    stop = threading.Event()
    try:
        run_agent(server_url=args.server, stop_event=stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
