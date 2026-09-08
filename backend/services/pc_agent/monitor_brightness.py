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
    --color-temp warm|neutral|cool   Smoke test the monitor-native color path
    --server URL    Home Hub base URL (default http://192.168.86.210:8000)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
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

DEFAULT_SERVER = "http://192.168.86.210:8000"

RECONCILE_INTERVAL_S = 30.0
LUX_POLL_INTERVAL_S = 30.0
SUN_POLL_INTERVAL_S = 30 * 60.0   # sunrise/sunset only change at midnight
# Consecutive sun-refresh failures before escalating from DEBUG to WARNING.
# A single blip (boot before weather warms, brief network hiccup) is noise;
# 3 straight failures (~60 min at the poll interval) means something is
# actually broken — wrong endpoint, sustained weather outage — and the agent
# has been silently flipping on the wall-clock fallback the whole time.
SUN_REFRESH_WARN_AFTER = 3
WS_RECONNECT_INITIAL_S = 1.0
WS_RECONNECT_MAX_S = 30.0

# Sun-aware period boundaries (offsets in seconds around sunrise/sunset).
# Rationale: ~30 min after sunrise the sun is unambiguously up; the evening
# offset targets golden-hour onset (sun ≈ +6°), which at Indianapolis's
# 39.8°N falls ~40 min before sunset (validated against solarwatch.app);
# 45 min lands the sun at ~+5–7° year-round (a fixed minute-offset is stable
# here — only ~2° elevation spread across seasons at this latitude).
# Astronomical-ish twilight is done ~90 min after sunset. The earlier 60 min
# fired while the sun was still ~9–10° up — a touch early — so it was tightened
# to 45 on 2026-05-30. Calibrated for the apartment's east-facing windows.
DAY_START_AFTER_SUNRISE_S   = 30 * 60
EVENING_START_BEFORE_SUNSET_S = 45 * 60
NIGHT_START_AFTER_SUNSET_S  = 90 * 60
# Hard late_night floor — on summer nights sunset can be 9pm+ which
# would push "night" past midnight without a wall-clock backstop.
LATE_NIGHT_HOUR = 23

# Hysteresis — DDC/CI writes are slow and panels can flicker on micro
# changes. Skip a write unless the delta exceeds this.
HYSTERESIS = 4

# HomeHub brightness is normalized 0..100, but some monitors expose a
# different native VCP luminance range (the Samsung G50F reports 0..50).
PRIMARY_DISPLAY_INDEX = 0
BRIGHTNESS_VERIFY_TOLERANCE_PERCENT = 2
BRIGHTNESS_VERIFY_ATTEMPTS = 3
BRIGHTNESS_VERIFY_DELAY_S = 0.15
COLOR_PRESET_MAX_FALLBACK_K = 1000

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

# Desk visual-comfort envelope. Time period owns the primary brightness
# target; Activity may only make a small bounded nudge inside that envelope.
# This prevents semantic flips from causing large contrast jumps.
TIME_PERIOD_BRIGHTNESS: dict[str, int] = {
    "day": 60,
    "evening": 45,
    "night": 30,
    "late_night": 20,
}
ACTIVITY_BRIGHTNESS_NUDGE: dict[str, int] = {
    "working": 5,
    "gaming": 5,
    "watching": -5,
    "relax": -5,
    "cooking": 5,
    "social": 0,
    "idle": 0,
    "general": 0,
}
SLEEPING_BRIGHTNESS = 5

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

# Preferred monitor-native warmth path on the Samsung G50F. The monitor
# advertises and read-backs standard RGB video-gain VCPs 0x16/0x18/0x1A
# at 50/100 neutral. Keep red fixed and progressively reduce green/blue.
# Values are normalized percentages of each VCP's advertised maximum.
RGB_GAIN_VCP_CODES: dict[str, int] = {"red": 0x16, "green": 0x18, "blue": 0x1A}
RGB_GAIN_PERIOD_PERCENT: dict[str, dict[str, int]] = {
    "day": {"red": 50, "green": 50, "blue": 50},
    "evening": {"red": 50, "green": 47, "blue": 43},
    "night": {"red": 50, "green": 44, "blue": 36},
    "late_night": {"red": 50, "green": 42, "blue": 32},
}
RGB_GAIN_VERIFY_TOLERANCE_PERCENT = 2

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
# DDC/CI display-control wrappers
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


def _raw_to_percent(value: int, maximum: int) -> int:
    """Normalize a monitor-native luminance value to HomeHub's 0..100 scale."""
    if maximum <= 0:
        raise ValueError("luminance maximum must be positive")
    return max(0, min(100, round(int(value) * 100 / int(maximum))))


def _percent_to_raw(percent: int, maximum: int) -> int:
    """Scale a HomeHub 0..100 target into the monitor's native VCP range."""
    if maximum <= 0:
        raise ValueError("luminance maximum must be positive")
    percent = max(0, min(100, int(percent)))
    return max(0, min(int(maximum), round(percent * int(maximum) / 100)))


_PRIMARY_LUMINANCE_MAX: Optional[int] = None


def _primary_luminance_max() -> int:
    """Return the primary display's VCP 0x10 maximum, falling back to 100."""
    global _PRIMARY_LUMINANCE_MAX
    if _PRIMARY_LUMINANCE_MAX is not None:
        return _PRIMARY_LUMINANCE_MAX
    maximum = 100
    if _HAS_MC:
        try:
            mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
            if mons:
                with mons[PRIMARY_DISPLAY_INDEX] as monitor:
                    _current, raw_max = monitor.vcp.get_vcp_feature(0x10)
                raw_max = int(raw_max)
                if raw_max > 0:
                    maximum = raw_max
        except Exception as e:
            logger.debug("luminance max probe failed; assuming 100: %s", e)
    _PRIMARY_LUMINANCE_MAX = maximum
    return maximum


def _read_primary_brightness_raw() -> Optional[int]:
    """Read the primary display's raw VCP luminance through SBC."""
    if not _HAS_SBC:
        return None
    try:
        vals = sbc.get_brightness(  # type: ignore[union-attr]
            display=PRIMARY_DISPLAY_INDEX,
        )
    except Exception as e:
        logger.debug("get_brightness failed: %s", e)
        return None
    if not vals:
        return None
    try:
        return int(vals[0])
    except (TypeError, ValueError, IndexError):
        return None


def get_current_brightness() -> Optional[int]:
    """Read primary-display brightness normalized to HomeHub's 0..100 scale."""
    raw = _read_primary_brightness_raw()
    if raw is None:
        return None
    return _raw_to_percent(raw, _primary_luminance_max())


def set_brightness(target: int) -> bool:
    """Apply and verify a normalized 0..100 target on the primary display."""
    if not _HAS_SBC:
        logger.warning("set_brightness skipped - screen-brightness-control missing")
        return False
    target = max(0, min(100, int(target)))
    maximum = _primary_luminance_max()
    raw_target = _percent_to_raw(target, maximum)
    try:
        sbc.set_brightness(  # type: ignore[union-attr]
            raw_target, display=PRIMARY_DISPLAY_INDEX,
        )
    except Exception as e:
        logger.warning("set_brightness(%d) failed: %s", target, e)
        return False

    raw: Optional[int] = None
    for attempt in range(BRIGHTNESS_VERIFY_ATTEMPTS):
        raw = _read_primary_brightness_raw()
        if raw is not None:
            actual = _raw_to_percent(raw, maximum)
            if abs(actual - target) <= BRIGHTNESS_VERIFY_TOLERANCE_PERCENT:
                return True
        if attempt + 1 < BRIGHTNESS_VERIFY_ATTEMPTS:
            time.sleep(BRIGHTNESS_VERIFY_DELAY_S)

    actual_text = "unreadable" if raw is None else str(_raw_to_percent(raw, maximum))
    logger.warning(
        "Brightness write did not verify (target=%d%% raw_target=%d/%d actual=%s%%)",
        target, raw_target, maximum, actual_text,
    )
    return False


def _parse_color_presets_from_raw_capabilities(raw: str) -> list[Any]:
    """Extract VCP 0x14 ColorPreset values from a raw MCCS capability string.

    Some Samsung capability strings include vendor tokens (for example
    ``mswhql(1)``) that older ``monitorcontrol`` parsers treat as hex and reject.
    This parses only the bounded 0x14 value list HomeHub needs.
    """
    if not raw or ColorPreset is None:
        return []
    match = re.search(r"(?:^|\s)14\(([^)]*)\)", raw)
    if match is None:
        return []
    presets: list[Any] = []
    for token in match.group(1).split():
        try:
            preset = ColorPreset(int(token, 16))
        except (ValueError, TypeError):
            continue
        if preset not in presets:
            presets.append(preset)
    return presets


def _read_primary_rgb_gains() -> Optional[dict[str, tuple[int, int]]]:
    """Read current/max standard RGB video gains from the primary display."""
    if not _HAS_MC:
        return None
    try:
        mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
        if not mons or PRIMARY_DISPLAY_INDEX >= len(mons):
            return None
        values: dict[str, tuple[int, int]] = {}
        with mons[PRIMARY_DISPLAY_INDEX] as monitor:
            for channel, code in RGB_GAIN_VCP_CODES.items():
                current, maximum = monitor.vcp.get_vcp_feature(code)
                current = int(current)
                maximum = int(maximum)
                if maximum <= 0:
                    return None
                values[channel] = (current, maximum)
        return values
    except Exception as e:
        logger.debug("RGB gain probe failed: %s", e)
        return None


def set_rgb_gain_warmth(period: str) -> bool:
    """Apply and verify the period's standard RGB-gain warmth target.

    Any partial failure rolls all three channels back to their pre-write values.
    """
    target = RGB_GAIN_PERIOD_PERCENT.get(period)
    if target is None or not _HAS_MC:
        return False
    try:
        mons = list(monitorcontrol.get_monitors())  # type: ignore[union-attr]
        if not mons or PRIMARY_DISPLAY_INDEX >= len(mons):
            return False
        with mons[PRIMARY_DISPLAY_INDEX] as monitor:
            original: dict[str, int] = {}
            raw_targets: dict[str, int] = {}
            for channel, code in RGB_GAIN_VCP_CODES.items():
                current, maximum = monitor.vcp.get_vcp_feature(code)
                current = int(current)
                maximum = int(maximum)
                if maximum <= 0:
                    return False
                original[channel] = current
                raw_targets[channel] = _percent_to_raw(target[channel], maximum)
            try:
                for channel, code in RGB_GAIN_VCP_CODES.items():
                    monitor.vcp.set_vcp_feature(code, raw_targets[channel])
                for channel, code in RGB_GAIN_VCP_CODES.items():
                    actual, maximum = monitor.vcp.get_vcp_feature(code)
                    actual_percent = _raw_to_percent(int(actual), int(maximum))
                    if abs(actual_percent - target[channel]) > RGB_GAIN_VERIFY_TOLERANCE_PERCENT:
                        raise RuntimeError(
                            f"{channel} gain did not verify: target={target[channel]} actual={actual_percent}"
                        )
            except Exception:
                for channel, code in RGB_GAIN_VCP_CODES.items():
                    try:
                        monitor.vcp.set_vcp_feature(code, original[channel])
                    except Exception:
                        logger.exception("RGB gain rollback failed for %s", channel)
                raise
        return True
    except Exception as e:
        logger.warning("RGB gain warmth failed for period=%s: %s", period, e)
        return False


# Cache of supported color presets, populated on first call. monitorcontrol
# opens a Windows DDC handle on every get_vcp_capabilities() call which is
# expensive (~300ms); cache so we only pay it once per process.
_SUPPORTED_COLOR_PRESETS: Optional[list[Any]] = None


def _supported_color_presets() -> list[Any]:
    """Return ColorPreset values supported by the primary monitor.

    Prefer ``monitorcontrol``'s structured parser, but fall back to the raw
    capability string when vendor extensions make the generic parser fail.
    """
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
        with mons[PRIMARY_DISPLAY_INDEX] as monitor:
            try:
                caps = monitor.get_vcp_capabilities()
                presets = caps.get("color_presets") or []
                parsed = [p for p in presets if isinstance(p, ColorPreset)]
            except Exception as e:
                logger.debug("structured color preset probe failed: %s", e)
                raw = monitor.vcp.get_vcp_capabilities()
                parsed = _parse_color_presets_from_raw_capabilities(raw)
        _SUPPORTED_COLOR_PRESETS = parsed
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
    if not by_distance:
        return None
    closest = by_distance[0]
    if abs(_kelvin(closest) - want_k) > COLOR_PRESET_MAX_FALLBACK_K:
        return None
    return closest


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
    if not mons or PRIMARY_DISPLAY_INDEX >= len(mons):
        return False
    monitor = mons[PRIMARY_DISPLAY_INDEX]
    try:
        with monitor:
            monitor.set_color_preset(target)
        return True
    except Exception as e:
        logger.debug("set_color_preset(%s) failed on primary monitor: %s", target, e)
        return False


def set_color_temperature(period: str) -> bool:
    """Apply monitor-native warmth, preferring verified standard RGB gains."""
    if _read_primary_rgb_gains() is not None:
        return set_rgb_gain_warmth(period)
    return set_color_preset(period)


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
    if mode == "sleeping":
        return SLEEPING_BRIGHTNESS

    base = TIME_PERIOD_BRIGHTNESS.get(period, TIME_PERIOD_BRIGHTNESS["day"])
    base += ACTIVITY_BRIGHTNESS_NUDGE.get(mode, 0)

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
    """Owns the last-applied brightness + monitor-native warmth state.

    Thread-safe: a lock guards each apply() call so the WS listener thread
    and the main reconcile loop can't race on a DDC/CI write.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_applied_brightness: Optional[int] = None
        self._last_applied_period_for_color: Optional[str] = None
        self._last_attempted_period_for_color: Optional[str] = None
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
                self._maybe_apply_color_temperature(period)
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

            self._maybe_apply_color_temperature(period)

    def _maybe_apply_color_temperature(self, period: str) -> None:
        """Apply the period's monitor-native color target once per period attempt.

        Failed/unsupported warmth remains observable and does not masquerade as
        an applied period. The same process will try again when the period changes.
        """
        if period == self._last_attempted_period_for_color:
            return
        self._last_attempted_period_for_color = period
        if set_color_temperature(period):
            logger.info(
                "Monitor color period %s -> %s",
                self._last_applied_period_for_color, period,
            )
            self._last_applied_period_for_color = period
            return
        logger.warning(
            "Monitor warmth unavailable for period=%s target=%s; leaving monitor color unchanged",
            period, COLOR_TEMP_PERIOD_PRESET.get(period),
        )


# ---------------------------------------------------------------------------
# Shared state — populated by WS listener, consumed by reconciler
# ---------------------------------------------------------------------------

# Indiana DST rules require an explicit tz on every datetime arithmetic
# call — system local could disagree on a non-Indiana host (e.g. someone
# running the supervisor on a laptop on the road).
_INDY_TZ = ZoneInfo("America/Indiana/Indianapolis")


# Wall-clock fallback for time_period when sun data is unavailable
# (weather endpoint down, fresh boot before first refresh). Matches the
# engine's default schedule (wake 7, evening 18, winddown 22, late_night 23).
def _wallclock_time_period() -> str:
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


def _sun_aware_time_period(
    sunrise_ts: Optional[float],
    sunset_ts: Optional[float],
    now_ts: Optional[float] = None,
) -> str:
    """Derive time_period from sun position. Falls back to wall-clock when sun data missing.

    Boundaries:
      day        — sunrise+30min → sunset-45min
      evening    — sunset-45min → min(sunset+90min, today's 23:00)
      night      — that boundary → today's 23:00
      late_night — 23:00 → next sunrise+30min

    Matters most in late spring/summer when sunset is ~9pm — wall-clock
    18:00 evening-flip dims the monitor 22 points while the apartment is
    still flooded with sun. See `project_monitor_brightness_sun_aware.md`.
    """
    if sunrise_ts is None or sunset_ts is None:
        return _wallclock_time_period()
    now_ts = now_ts if now_ts is not None else time.time()
    now_local = datetime.fromtimestamp(now_ts, tz=_INDY_TZ)
    late_night_floor_ts = now_local.replace(
        hour=LATE_NIGHT_HOUR, minute=0, second=0, microsecond=0,
    ).timestamp()

    day_start = sunrise_ts + DAY_START_AFTER_SUNRISE_S
    # Clamp evening_start >= day_start to keep the period sequence
    # monotone even on a corrupted/partial weather response (e.g. sunset
    # earlier than sunrise + 90min). Indianapolis at ~39.7°N never gets
    # close, but the clamp is one line of cheap insurance.
    evening_start = max(sunset_ts - EVENING_START_BEFORE_SUNSET_S, day_start)
    night_start = min(sunset_ts + NIGHT_START_AFTER_SUNSET_S, late_night_floor_ts)

    if now_ts < day_start:
        return "late_night"
    if now_ts < evening_start:
        return "day"
    if now_ts < night_start:
        return "evening"
    if now_ts < late_night_floor_ts:
        return "night"
    return "late_night"


class SharedState:
    """Latest known automation mode + sun-derived time period.

    The agent owns period derivation — backend `time_period` in WS
    payloads is intentionally ignored. Backend's period is wall-clock
    based and drives the lighting engine; the monitor agent uses the
    sun so a late-spring 6pm doesn't dim the screen while the sun is
    still high. See `project_monitor_brightness_sun_aware.md`.
    """

    def __init__(self, sun_provider: Optional["SunProvider"] = None) -> None:
        self._lock = threading.Lock()
        self.mode: str = "idle"
        self._sun = sun_provider
        self.period: str = self._derive_period_locked()

    def _derive_period_locked(self) -> str:
        """Caller must hold self._lock, except during __init__ when the
        object is not yet shared across threads.
        """
        if self._sun is None:
            return _wallclock_time_period()
        sunrise, sunset = self._sun.snapshot()
        return _sun_aware_time_period(sunrise, sunset)

    def update(self, mode: Optional[str], period: Optional[str]) -> bool:  # noqa: ARG002
        """Return True if mode changed or sun-derived period rolled over.

        `period` from the backend is accepted for signature compatibility
        with the WS payload but ignored — see class docstring.
        """
        changed = False
        with self._lock:
            if mode and mode != self.mode:
                self.mode = mode
                changed = True
            fresh = self._derive_period_locked()
            if fresh != self.period:
                self.period = fresh
                changed = True
        return changed

    def tick_period_if_stale(self) -> bool:
        """Refresh period from the sun. Called by the reconcile loop so a
        sun-boundary roll-over triggers a color preset change even when
        no WS event fires.
        """
        with self._lock:
            fresh = self._derive_period_locked()
            if fresh != self.period:
                self.period = fresh
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
# Sun provider — polls /api/weather/current for sunrise/sunset
# ---------------------------------------------------------------------------

class SunProvider:
    """Caches today's sunrise/sunset unix-epoch timestamps from weather.

    Refreshed every SUN_POLL_INTERVAL_S — sunrise/sunset only roll over
    at midnight, no need to hammer the endpoint.
    """

    def __init__(self, server_url: str) -> None:
        self._url = f"{server_url.rstrip('/')}/api/weather"
        self._lock = threading.Lock()
        self._sunrise: Optional[float] = None
        self._sunset: Optional[float] = None
        self._client = httpx.Client(timeout=5.0)
        self._consecutive_failures = 0

    def snapshot(self) -> tuple[Optional[float], Optional[float]]:
        with self._lock:
            return self._sunrise, self._sunset

    def refresh(self) -> None:
        # /api/weather shape: {"status":"ok","weather":{...sunrise,sunset...}}.
        # A 200 with the sun fields absent is treated as a failure too — that
        # path also strands derivation on the wall-clock fallback, so it must
        # escalate like a transport error rather than silently caching None.
        try:
            resp = self._client.get(self._url)
            resp.raise_for_status()
            body = resp.json()
            weather = body.get("weather") or body
            sunrise = weather.get("sunrise")
            sunset = weather.get("sunset")
            if sunrise is None or sunset is None:
                raise ValueError(
                    f"weather response missing sunrise/sunset "
                    f"(keys: {sorted(weather)})"
                )
            sunrise_f, sunset_f = float(sunrise), float(sunset)
        except Exception as e:
            self._note_failure(e)
            return
        with self._lock:
            self._sunrise = sunrise_f
            self._sunset = sunset_f
        if self._consecutive_failures:
            logger.info(
                "sun refresh recovered after %d failed attempt(s)",
                self._consecutive_failures,
            )
            self._consecutive_failures = 0

    def _note_failure(self, exc: Exception) -> None:
        """Log a sun-refresh failure, escalating to WARNING once the failure
        is persistent. Warns exactly on crossing the threshold (and again on
        each recurrence after a recovery) so a stuck endpoint surfaces without
        spamming the log every poll. Leaves cached sun values untouched."""
        self._consecutive_failures += 1
        if self._consecutive_failures == SUN_REFRESH_WARN_AFTER:
            logger.warning(
                "sun refresh failed %d× in a row (%s) — falling back to "
                "wall-clock time_period; check %s",
                self._consecutive_failures, exc, self._url,
            )
        else:
            logger.debug(
                "sun refresh failed (attempt %d): %s",
                self._consecutive_failures, exc,
            )

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
            "No DDC/CI-reachable monitors detected; display comfort writes "
            "will no-op. monitors=%s", monitors,
        )
    else:
        logger.info(
            "Monitors reachable: %s",
            [m.get("name") or m.get("model") for m in reachable],
        )

    sun = SunProvider(server_url)
    sun.refresh()
    shared = SharedState(sun_provider=sun)
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
    last_sun_refresh = time.time()  # refreshed above; track from now
    try:
        while not _stop.is_set():
            now = time.time()
            if now - last_lux_refresh >= LUX_POLL_INTERVAL_S:
                lux.refresh()
                last_lux_refresh = now
            if now - last_sun_refresh >= SUN_POLL_INTERVAL_S:
                sun.refresh()
                last_sun_refresh = now

            # Roll the sun-derived period forward (e.g. crossing sunset-60min).
            shared.tick_period_if_stale()

            mode, period = shared.snapshot()
            lux_val, baseline = lux.snapshot()
            reconciler.reconcile(mode, period, lux_val, baseline)

            _stop.wait(RECONCILE_INTERVAL_S)
    finally:
        lux.close()
        sun.close()


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
        help="Apply monitor-native color (warm=night target, neutral=day target; "
        "cool probes the optional 7500K preset fallback).",
    )
    args = parser.parse_args()

    if args.detect:
        monitors = detect_monitors()
        print(json.dumps(monitors, indent=2, default=str))
        if _HAS_MC:
            print("RGB gains:", _read_primary_rgb_gains())
            presets = _supported_color_presets()
            print("Supported color presets:", [p.name for p in presets])
        return 0

    if args.apply is not None:
        ok = set_brightness(args.apply)
        print(f"set_brightness({args.apply}) -> {'ok' if ok else 'failed'}")
        return 0 if ok else 1

    if args.color_temp is not None:
        # Map CLI shortcuts to the same period targets the agent uses.
        period = {"warm": "night", "neutral": "day", "cool": "day"}[args.color_temp]
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
                if not mons or PRIMARY_DISPLAY_INDEX >= len(mons):
                    print("primary monitor unavailable")
                    return 1
                with mons[PRIMARY_DISPLAY_INDEX] as monitor:
                    monitor.set_color_preset(target)
                print(f"set_color_preset({target.name}) -> ok")
                return 0
            except Exception as e:
                print(f"set_color_preset(cool) -> failed: {e}")
                return 1
        ok = set_color_temperature(period)
        print(f"set_color_temperature(period={period}) -> {'ok' if ok else 'failed'}")
        return 0 if ok else 1

    run_agent(args.server)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
