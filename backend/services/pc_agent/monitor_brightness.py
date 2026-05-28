"""
Monitor Brightness Agent — standalone desktop process under the supervisor.

Drops the external monitor's backlight AND warms its color temperature
via DDC/CI on a curve indexed by ``mode × time_period``. Lux from the
desktop camera modulates the brightness curve ±10% so the actual room
conditions nudge the target. Runs only on the Windows desktop (the
Latitude has no attached display the user looks at).

Color temperature is driven through the monitor's own VCP color preset
(VCP code 0x14 via ``monitorcontrol``) rather than Windows Night Light —
the registry-edit approach to Night Light is unreliable because Windows
caches state in-memory and only reloads on specific session events.

Architecture inside the process:

  ┌───────────────────────────────────────────────────────────────────┐
  │ Main thread                                                       │
  │ ┌──────────────────┐                  ┌──────────────────────┐    │
  │ │ WsListener       │ ──mode update──> │ Reconciler           │    │
  │ │  (worker thread) │                  │  apply DDC + NL      │    │
  │ └──────────────────┘                  └──────────────────────┘    │
  │                                                ▲                  │
  │                                                │                  │
  │                              30s lux + 30s    │                  │
  │                              periodic re-sync  │                  │
  └────────────────────────────────────────────────┴──────────────────┘

The agent ALSO re-resolves the target every ``RECONCILE_INTERVAL_S`` (30s)
even when nothing changed — that covers (a) time_period rolling forward
on the wall clock without a mode flip, and (b) lux drift.

CLI:
    --detect        Enumerate monitors and try a brightness round-trip
    --apply N       Force-set brightness to N (smoke test, no backend)
    --color-temp warm|neutral|cool   Smoke test the color preset path
    --server URL    Home Hub base URL (default http://192.168.1.210:8000)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

try:
    import screen_brightness_control as sbc  # type: ignore[import-untyped]
    _HAS_SBC = True
except ImportError:
    sbc = None  # type: ignore[assignment]
    _HAS_SBC = False

try:
    import monitorcontrol  # type: ignore[import-untyped]
    from monitorcontrol import ColorPreset  # type: ignore[import-untyped]
    _HAS_MC = True
except ImportError:
    monitorcontrol = None  # type: ignore[assignment]
    ColorPreset = None  # type: ignore[assignment]
    _HAS_MC = False

try:
    import websockets  # type: ignore[import-untyped]
    import websockets.sync.client  # type: ignore[import-untyped]
    _HAS_WS = True
except ImportError:
    websockets = None  # type: ignore[assignment]
    _HAS_WS = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SERVER = "http://192.168.1.210:8000"

RECONCILE_INTERVAL_S = 30.0
LUX_POLL_INTERVAL_S = 30.0
WS_RECONNECT_INITIAL_S = 1.0
WS_RECONNECT_MAX_S = 30.0

# Hysteresis — DDC/CI writes are slow and panels can flicker on micro
# changes. Skip a write unless the delta exceeds this.
HYSTERESIS = 4

# Manual-override sentinel — if the user nudges their hardware brightness
# buttons (or anything else moves the backlight away from what we last set
# by more than this), back off so we don't fight them.
MANUAL_OVERRIDE_DELTA = 5
MANUAL_OVERRIDE_BACKOFF_S = 30 * 60   # 30 min

# If two reconcile() calls are separated by more than this, the agent was
# paused (Windows sleep, process restart, hung WS) — any drift from
# _last_applied_brightness can't be a user button-press because the agent
# wasn't around to set it. Resync silently instead of arming the backoff.
SUSPEND_GAP_THRESHOLD_S = RECONCILE_INTERVAL_S * 2

# Mode × time_period brightness curve. Defaults match the apartment
# lighting cadence — bright daytime, gentle wind-down at night.
BASE_BRIGHTNESS: dict[str, dict[str, int]] = {
    "working":  {"day": 100, "evening": 75, "night": 50, "late_night": 30},
    "gaming":   {"day":  90, "evening": 70, "night": 50, "late_night": 30},
    "watching": {"day":  60, "evening": 40, "night": 25, "late_night": 20},
    "relax":    {"day":  70, "evening": 40, "night": 25, "late_night": 20},
    "cooking":  {"day": 100, "evening": 80, "night": 60, "late_night": 50},
    "social":   {"day":  80, "evening": 55, "night": 35, "late_night": 25},
    "sleeping": {"day":  20, "evening": 15, "night": 10, "late_night":  5},
    "idle":     {"day":  80, "evening": 55, "night": 35, "late_night": 25},
}
# Modes not in the table fall back to the working curve.
DEFAULT_CURVE_MODE = "working"

# Color temperature target per time_period — independent of mode, since
# blue-light reduction is fundamentally about wall-clock time, not
# activity. Values are ``monitorcontrol.ColorPreset`` enum names; the
# resolver falls back to the closest supported preset if the monitor
# doesn't expose the named one.
COLOR_TEMP_PERIOD_PRESET: dict[str, str] = {
    "day":        "COLOR_TEMP_6500K",   # neutral
    "evening":    "COLOR_TEMP_5000K",   # mild warm
    "night":      "COLOR_TEMP_5000K",   # warm (often the warmest preset available)
    "late_night": "COLOR_TEMP_5000K",   # warm
}

# Lux modulation: brighter room → brighter screen, capped ±10%.
LUX_MOD_FRACTION = 0.10

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "home-hub" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "monitor_brightness.log"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("home_hub.monitor_brightness")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    _console = logging.StreamHandler()
    _console.setFormatter(_fmt)
    logger.addHandler(_console)
    _fh = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8",
    )
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)


# ---------------------------------------------------------------------------
# DDC/CI + Night Light wrappers
# ---------------------------------------------------------------------------

def detect_monitors() -> list[dict[str, Any]]:
    """Enumerate displays and probe each for DDC/CI brightness support."""
    if not _HAS_SBC:
        return [{"error": "screen-brightness-control not installed"}]
    out: list[dict[str, Any]] = []
    try:
        monitors = sbc.list_monitors_info()  # type: ignore[union-attr]
    except Exception as e:
        return [{"error": f"list_monitors_info failed: {e}"}]
    for m in monitors:
        info: dict[str, Any] = {
            "name": m.get("name"),
            "model": m.get("model"),
            "method": str(m.get("method")),
            "serial": m.get("serial"),
        }
        try:
            cur = sbc.get_brightness(display=m.get("index", 0))  # type: ignore[union-attr]
            info["brightness"] = cur
            info["supported"] = True
        except Exception as e:
            info["brightness"] = None
            info["supported"] = False
            info["error"] = str(e)
        out.append(info)
    return out


def get_current_brightness() -> Optional[int]:
    """Read brightness from the first display that answers. None if none do."""
    if not _HAS_SBC:
        return None
    try:
        vals = sbc.get_brightness()  # type: ignore[union-attr]
    except Exception as e:
        logger.debug("get_brightness failed: %s", e)
        return None
    if not vals:
        return None
    # vals is a list (one entry per display) — return the primary.
    try:
        return int(vals[0])
    except (TypeError, ValueError, IndexError):
        return None


def set_brightness(target: int) -> bool:
    """Apply ``target`` (0–100) to all DDC/CI-reachable displays. Returns success."""
    if not _HAS_SBC:
        logger.warning("set_brightness skipped — screen-brightness-control missing")
        return False
    target = max(0, min(100, int(target)))
    try:
        sbc.set_brightness(target)  # type: ignore[union-attr]
        return True
    except Exception as e:
        logger.warning("set_brightness(%d) failed: %s", target, e)
        return False


# Cache of supported color presets, populated on first call. monitorcontrol
# opens a Windows DDC handle on every get_vcp_capabilities() call which is
# expensive (~300ms); cache so we only pay it once per process.
_SUPPORTED_COLOR_PRESETS: Optional[list[Any]] = None


def _supported_color_presets() -> list[Any]:
    """Return the list of ColorPreset values the primary monitor supports."""
    global _SUPPORTED_COLOR_PRESETS
    if _SUPPORTED_COLOR_PRESETS is not None:
        return _SUPPORTED_COLOR_PRESETS
    if not _HAS_MC:
        _SUPPORTED_COLOR_PRESETS = []
        return _SUPPORTED_COLOR_PRESETS
    try:
        mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
        if not mons:
            _SUPPORTED_COLOR_PRESETS = []
            return _SUPPORTED_COLOR_PRESETS
        with mons[0] as m:
            caps = m.get_vcp_capabilities()
        presets = caps.get("color_presets") or []
        _SUPPORTED_COLOR_PRESETS = [p for p in presets if isinstance(p, ColorPreset)]
    except Exception as e:
        logger.debug("color preset probe failed: %s", e)
        _SUPPORTED_COLOR_PRESETS = []
    return _SUPPORTED_COLOR_PRESETS


def _resolve_preset(name: str) -> Optional[Any]:
    """Resolve a preset name like ``COLOR_TEMP_5000K`` to a supported ColorPreset.

    Falls back to the closest kelvin available — if 5000K isn't there, try
    4000K, then 6500K, etc. Returns None when no usable preset is found.
    """
    if not _HAS_MC:
        return None
    supported = _supported_color_presets()
    if not supported:
        return None
    target = getattr(ColorPreset, name, None)
    if target is not None and target in supported:
        return target
    # Fallback by kelvin proximity. ColorPreset enum values aren't kelvin
    # numbers directly; parse them from the name.
    def _kelvin(p: Any) -> int:
        n = p.name
        if n.startswith("COLOR_TEMP_") and n.endswith("K"):
            try:
                return int(n[len("COLOR_TEMP_"):-1])
            except ValueError:
                return 0
        return 0
    want_k = _kelvin(target) if target is not None else 5000
    by_distance = sorted(
        (p for p in supported if _kelvin(p) > 0),
        key=lambda p: abs(_kelvin(p) - want_k),
    )
    return by_distance[0] if by_distance else None


def set_color_preset(period: str) -> bool:
    """Apply the color preset for the given time period. Returns success."""
    if not _HAS_MC:
        logger.debug("set_color_preset skipped — monitorcontrol missing")
        return False
    target_name = COLOR_TEMP_PERIOD_PRESET.get(period)
    if not target_name:
        return False
    target = _resolve_preset(target_name)
    if target is None:
        logger.debug("no supported preset close to %s", target_name)
        return False
    try:
        mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
    except Exception as e:
        logger.warning("get_monitors failed: %s", e)
        return False
    if not mons:
        return False
    ok = False
    for m in mons:
        try:
            with m:
                m.set_color_preset(target)
            ok = True
        except Exception as e:
            logger.debug("set_color_preset(%s) failed on a monitor: %s", target, e)
    return ok


# ---------------------------------------------------------------------------
# Curve resolution
# ---------------------------------------------------------------------------

def resolve_target(
    mode: str,
    period: str,
    ema_lux: Optional[float],
    baseline_lux: Optional[float],
) -> int:
    """Compute the target brightness (0–100) for the given inputs."""
    curve = BASE_BRIGHTNESS.get(mode) or BASE_BRIGHTNESS[DEFAULT_CURVE_MODE]
    base = curve.get(period, curve["day"])

    factor = 0.0
    if ema_lux is not None and baseline_lux:
        ratio = (ema_lux / max(baseline_lux, 1.0)) - 1.0
        factor = max(-LUX_MOD_FRACTION, min(LUX_MOD_FRACTION, ratio * LUX_MOD_FRACTION))

    target = round(base * (1 + factor))
    return max(5, min(100, target))


# ---------------------------------------------------------------------------
# Reconciler — single source of truth that applies state
# ---------------------------------------------------------------------------

class Reconciler:
    """Owns the last-applied brightness + Night Light state.

    Thread-safe: a lock guards each apply() call so the WS listener thread
    and the main reconcile loop can't race on a DDC/CI write.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_applied_brightness: Optional[int] = None
        self._last_applied_period_for_color: Optional[str] = None
        self._manual_override_until: float = 0.0
        self._last_reconcile_at: float = 0.0

    def reconcile(
        self,
        mode: str,
        period: str,
        ema_lux: Optional[float],
        baseline_lux: Optional[float],
    ) -> None:
        with self._lock:
            now = time.time()
            gap = now - self._last_reconcile_at if self._last_reconcile_at else 0.0
            self._last_reconcile_at = now
            # gap=0 = first call this process; treat as "agent wasn't running"
            # so a cold start against a stale panel value silently resyncs.
            agent_was_running = 0 < gap <= SUSPEND_GAP_THRESHOLD_S

            # Manual-override sentinel — if the user moved the hardware
            # brightness, hold off until the timer expires. Only trip when
            # the agent was actively running between writes; large gaps mean
            # the drift happened while we were paused (Windows sleep, etc.).
            current = get_current_brightness()
            drifted = (
                self._last_applied_brightness is not None
                and current is not None
                and abs(current - self._last_applied_brightness) >= MANUAL_OVERRIDE_DELTA
            )
            if drifted and agent_was_running and now >= self._manual_override_until:
                logger.info(
                    "Manual brightness change detected (last=%d, current=%d) — "
                    "backing off for %ds",
                    self._last_applied_brightness, current, MANUAL_OVERRIDE_BACKOFF_S,
                )
                self._manual_override_until = now + MANUAL_OVERRIDE_BACKOFF_S
                # Also forget our last_applied so we don't keep tripping the
                # sentinel against a stale baseline.
                self._last_applied_brightness = current
                return
            if drifted and not agent_was_running:
                logger.info(
                    "Brightness drift across pause (last=%d current=%d gap=%.1fs) — "
                    "resyncing baseline, no backoff",
                    self._last_applied_brightness, current, gap,
                )
                self._last_applied_brightness = current

            if now < self._manual_override_until:
                # Still in cooldown — only re-engage the color preset, not
                # the brightness write.
                self._maybe_apply_color_preset(period)
                return

            target = resolve_target(mode, period, ema_lux, baseline_lux)

            if (
                self._last_applied_brightness is None
                or abs(target - self._last_applied_brightness) >= HYSTERESIS
            ):
                if set_brightness(target):
                    logger.info(
                        "Brightness %s -> %d (mode=%s period=%s lux=%s)",
                        self._last_applied_brightness, target, mode, period,
                        f"{ema_lux:.0f}" if ema_lux is not None else "n/a",
                    )
                    self._last_applied_brightness = target

            self._maybe_apply_color_preset(period)

    def _maybe_apply_color_preset(self, period: str) -> None:
        """Apply the period's DDC/CI color preset when the period changes.

        Only re-attempts on period transitions — DDC writes are slow and
        most monitors give a visible flicker when the preset switches.
        """
        if period == self._last_applied_period_for_color:
            return
        if set_color_preset(period):
            logger.info(
                "Color preset period %s -> %s",
                self._last_applied_period_for_color, period,
            )
        # Stamp the attempt either way so we don't hammer a monitor that
        # rejects the VCP write. The next period transition tries again.
        self._last_applied_period_for_color = period


# ---------------------------------------------------------------------------
# Shared state — populated by WS listener, consumed by reconciler
# ---------------------------------------------------------------------------

# Indiana DST rules require an explicit tz on every datetime arithmetic
# call — system local could disagree on a non-Indiana host (e.g. someone
# running the supervisor on a laptop on the road).
_INDY_TZ = ZoneInfo("America/Indiana/Indianapolis")


# Local fallback for time_period when the backend doesn't report it (pre-
# deploy of the get_time_period() route addition). Matches the engine's
# default schedule (wake 7, evening 18, winddown 22, late_night 23) — if
# the user has customized their schedule via the dashboard, the API will
# eventually carry an authoritative value and overwrite this default.
def _local_time_period() -> str:
    hour = datetime.now(tz=_INDY_TZ).hour
    if hour < 7:
        return "late_night"
    if hour < 18:
        return "day"
    if hour < 22:
        return "evening"
    if hour < 23:
        return "night"
    return "late_night"


class SharedState:
    """Latest known automation mode + time period. Mutated from WS thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.mode: str = "idle"
        self.period: str = _local_time_period()
        # Tracks whether the backend has supplied an authoritative period.
        # When False, the reconcile loop re-derives period locally each
        # tick so the wall-clock rolling forward across boundaries (e.g.
        # 23:00 -> late_night) still triggers a color preset change.
        self._period_from_backend: bool = False

    def update(self, mode: Optional[str], period: Optional[str]) -> bool:
        """Return True if either field changed."""
        changed = False
        with self._lock:
            if mode and mode != self.mode:
                self.mode = mode
                changed = True
            if period:
                self._period_from_backend = True
                if period != self.period:
                    self.period = period
                    changed = True
            elif not self._period_from_backend:
                # Backend isn't carrying time_period yet (pre-deploy).
                # Re-derive locally so we still follow the wall clock.
                local = _local_time_period()
                if local != self.period:
                    self.period = local
                    changed = True
        return changed

    def tick_period_if_stale(self) -> bool:
        """Refresh period from the wall clock if backend hasn't supplied one.

        Called by the reconcile loop so a wall-clock roll-over (e.g.
        22:59 -> 23:00) triggers a color preset change even when no WS
        event fires.
        """
        with self._lock:
            if self._period_from_backend:
                return False
            local = _local_time_period()
            if local != self.period:
                self.period = local
                return True
            return False

    def snapshot(self) -> tuple[str, str]:
        with self._lock:
            return self.mode, self.period


# ---------------------------------------------------------------------------
# WS listener — subscribes for mode_update events
# ---------------------------------------------------------------------------

class WsListener(threading.Thread):
    """Connects to /ws and pushes mode_update events into SharedState.

    Triggers an immediate reconcile() on every change so the user sees
    monitor brightness move in lockstep with the dashboard mode flip.
    """

    def __init__(
        self,
        ws_url: str,
        state: SharedState,
        reconciler: Reconciler,
        lux_provider: "LuxProvider",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="ws-listener", daemon=True)
        self._url = ws_url
        self._state = state
        self._reconciler = reconciler
        self._lux = lux_provider
        self._stop = stop_event

    def run(self) -> None:
        if not _HAS_WS:
            logger.warning("websockets library missing — WS listener disabled")
            return
        backoff = WS_RECONNECT_INITIAL_S
        while not self._stop.is_set():
            try:
                logger.info("Connecting to %s", self._url)
                with websockets.sync.client.connect(  # type: ignore[union-attr]
                    self._url, close_timeout=2.0,
                ) as ws:
                    logger.info("WS connected")
                    backoff = WS_RECONNECT_INITIAL_S
                    self._recv_loop(ws)
            except Exception as e:
                logger.warning(
                    "WS disconnect: %s (reconnecting in %.1fs)", e, backoff,
                )
            finally:
                if self._stop.is_set():
                    return
                self._stop.wait(backoff)
                backoff = min(backoff * 2, WS_RECONNECT_MAX_S)

    def _recv_loop(self, ws: Any) -> None:
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
            if msg.get("type") != "mode_update":
                continue
            data = msg.get("data") or {}
            mode = data.get("mode")
            period = data.get("time_period")
            if self._state.update(mode, period):
                m, p = self._state.snapshot()
                lux, baseline = self._lux.snapshot()
                self._reconciler.reconcile(m, p, lux, baseline)


# ---------------------------------------------------------------------------
# Lux provider — polls /api/camera/status
# ---------------------------------------------------------------------------

class LuxProvider:
    """Caches the latest lux reading; refreshed by a poll thread."""

    def __init__(self, server_url: str) -> None:
        self._url = f"{server_url.rstrip('/')}/api/camera/status"
        self._lock = threading.Lock()
        self._lux: Optional[float] = None
        self._baseline: Optional[float] = None
        self._client = httpx.Client(timeout=5.0)

    def snapshot(self) -> tuple[Optional[float], Optional[float]]:
        with self._lock:
            return self._lux, self._baseline

    def refresh(self) -> None:
        try:
            resp = self._client.get(self._url)
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            logger.debug("lux refresh failed: %s", e)
            return
        with self._lock:
            ema = body.get("ema_lux")
            baseline = body.get("baseline_lux")
            self._lux = float(ema) if ema is not None else None
            self._baseline = float(baseline) if baseline is not None else None

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Bootstrap — fetch initial mode / period via REST in case WS is slow
# ---------------------------------------------------------------------------

def _bootstrap_state(server_url: str, state: SharedState) -> None:
    """One-shot REST fetch so we don't sit on stale defaults until WS connects."""
    url = f"{server_url.rstrip('/')}/api/automation/status"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        logger.warning("bootstrap status fetch failed: %s", e)
        return
    state.update(body.get("current_mode"), body.get("time_period"))


# ---------------------------------------------------------------------------
# Supervisor entrypoint
# ---------------------------------------------------------------------------

def run_agent(
    server_url: str = DEFAULT_SERVER,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Main agent loop — supervisor-compatible signature."""
    if not _HAS_SBC:
        logger.error(
            "screen-brightness-control not installed — install it on the "
            "desktop (`pip install screen-brightness-control`) and restart "
            "the supervisor.",
        )
        return

    _stop = stop_event or threading.Event()

    # Confirm at least one monitor responds. If none, log and continue —
    # the agent will still drive Night Light, which doesn't depend on DDC.
    monitors = detect_monitors()
    reachable = [m for m in monitors if m.get("supported")]
    if not reachable:
        logger.warning(
            "No DDC/CI-reachable monitors detected. Brightness writes will "
            "no-op; Night Light still active. monitors=%s", monitors,
        )
    else:
        logger.info(
            "Monitors reachable: %s",
            [m.get("name") or m.get("model") for m in reachable],
        )

    shared = SharedState()
    reconciler = Reconciler()
    lux = LuxProvider(server_url)

    _bootstrap_state(server_url, shared)
    lux.refresh()

    # WS URL derived from REST URL by swapping the scheme.
    ws_url = server_url.rstrip("/").replace("http://", "ws://", 1).replace(
        "https://", "wss://", 1,
    ) + "/ws"
    listener = WsListener(ws_url, shared, reconciler, lux, _stop)
    listener.start()

    logger.info(
        "Monitor brightness agent started — server=%s ws=%s",
        server_url, ws_url,
    )

    last_lux_refresh = 0.0
    try:
        while not _stop.is_set():
            now = time.time()
            if now - last_lux_refresh >= LUX_POLL_INTERVAL_S:
                lux.refresh()
                last_lux_refresh = now

            # Roll the wall-clock period forward if backend isn't carrying
            # time_period yet (pre-deploy of the schema change).
            shared.tick_period_if_stale()

            mode, period = shared.snapshot()
            lux_val, baseline = lux.snapshot()
            reconciler.reconcile(mode, period, lux_val, baseline)

            _stop.wait(RECONCILE_INTERVAL_S)
    finally:
        lux.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> int:
    parser = argparse.ArgumentParser(description="Home Hub Monitor Brightness Agent")
    parser.add_argument(
        "--server", default=DEFAULT_SERVER,
        help=f"Home Hub base URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--detect", action="store_true",
        help="List monitors and probe DDC/CI brightness, then exit.",
    )
    parser.add_argument(
        "--apply", type=int, default=None, metavar="N",
        help="Force-set brightness to N (0-100) and exit. Smoke test.",
    )
    parser.add_argument(
        "--color-temp", choices=("warm", "neutral", "cool"), default=None,
        help="Apply a color preset (warm=5000K, neutral=6500K, cool=7500K). "
        "Smoke test the DDC/CI color path.",
    )
    args = parser.parse_args()

    if args.detect:
        monitors = detect_monitors()
        print(json.dumps(monitors, indent=2, default=str))
        if _HAS_MC:
            presets = _supported_color_presets()
            print("Supported color presets:", [p.name for p in presets])
        return 0

    if args.apply is not None:
        ok = set_brightness(args.apply)
        print(f"set_brightness({args.apply}) -> {'ok' if ok else 'failed'}")
        return 0 if ok else 1

    if args.color_temp is not None:
        # Map CLI shortcuts to the same time_period table for consistency.
        period = {"warm": "late_night", "neutral": "day", "cool": "day"}[args.color_temp]
        # cool just reuses neutral's preset on this monitor — we don't
        # explicitly run cooler than 6500K via the period table, but the
        # CLI keeps the option for testing cooler presets directly.
        if args.color_temp == "cool":
            target = _resolve_preset("COLOR_TEMP_7500K")
            if target is None or not _HAS_MC:
                print("cool preset unavailable")
                return 1
            try:
                mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
                for m in mons:
                    with m:
                        m.set_color_preset(target)
                print(f"set_color_preset({target.name}) -> ok")
                return 0
            except Exception as e:
                print(f"set_color_preset(cool) -> failed: {e}")
                return 1
        ok = set_color_preset(period)
        print(f"set_color_preset(period={period}) -> {'ok' if ok else 'failed'}")
        return 0 if ok else 1

    run_agent(args.server)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
