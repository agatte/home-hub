"""
Vital signs — aggregated kiosk health metrics for the always-visible strip.

One JSON-shaped GET that pulls from already-shipped surfaces (`hue.breaker`,
`sonos.breaker`, `automation._last_fusion_result`, `pihole_service.get_summary`,
`psutil`) and tags each metric with `status: ok | warn | error`. The
``VitalStrip.svelte`` component polls every 30s and renders one chip per
metric, colored by status.

No new sensors — this is purely a re-projection of state the backend
already exposes for a denser, kiosk-glanceable readout.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request

logger = logging.getLogger("home_hub.vitals")

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


# Threshold tuples: (warn_at, error_at). Direction is metric-specific —
# memory/disk/temp warn when *high*; fusion confidence warns when *low*.
_MEMORY_WARN, _MEMORY_ERROR = 85, 95
_DISK_WARN, _DISK_ERROR = 80, 90
_CPU_TEMP_WARN, _CPU_TEMP_ERROR = 70, 85  # Celsius
_FUSION_WARN, _FUSION_ERROR = 0.6, 0.3    # confidence (lower = worse)


def _classify_high(value: float, warn: float, error: float) -> str:
    """Classify a metric where higher means worse (e.g., temperature)."""
    if value >= error:
        return "error"
    if value >= warn:
        return "warn"
    return "ok"


def _classify_low(value: float, warn: float, error: float) -> str:
    """Classify a metric where lower means worse (e.g., confidence)."""
    if value <= error:
        return "error"
    if value <= warn:
        return "warn"
    return "ok"


def _device_status(connected: bool, breaker: Optional[dict]) -> str:
    if not connected:
        return "error"
    if breaker and breaker.get("state") == "open":
        return "error"
    if breaker and (breaker.get("consecutive_failures") or 0) > 0:
        return "warn"
    return "ok"


def _read_psutil_metrics() -> dict[str, Any]:
    """Best-effort psutil readout. Skips fields that aren't supported."""
    out: dict[str, Any] = {}
    try:
        import psutil
    except ImportError:
        return out

    try:
        mem = psutil.virtual_memory()
        out["memory"] = {
            "percent": round(mem.percent, 1),
            "status": _classify_high(mem.percent, _MEMORY_WARN, _MEMORY_ERROR),
        }
    except Exception:
        pass

    try:
        disk = psutil.disk_usage("/")
        out["disk"] = {
            "percent": round(disk.percent, 1),
            "status": _classify_high(disk.percent, _DISK_WARN, _DISK_ERROR),
        }
    except Exception:
        pass

    # CPU temp: Linux only (Latitude is Ubuntu). Windows / macOS quietly
    # fall through with no key — the strip just hides that chip.
    try:
        temps = getattr(psutil, "sensors_temperatures", lambda: {})()
        if temps:
            # Try the well-known keys in order of usefulness.
            for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
                readings = temps.get(key)
                if readings:
                    current = readings[0].current
                    out["cpu_temp"] = {
                        "celsius": round(current, 1),
                        "status": _classify_high(
                            current, _CPU_TEMP_WARN, _CPU_TEMP_ERROR,
                        ),
                    }
                    break
    except Exception:
        pass

    return out


@router.get("")
async def get_vitals(request: Request) -> dict[str, Any]:
    """One-shot aggregator for the kiosk vitals strip."""
    app = request.app
    metrics: dict[str, Any] = {}

    # Hue
    hue = getattr(app.state, "hue", None)
    if hue is not None:
        breaker = hue.breaker.snapshot() if hasattr(hue, "breaker") else None
        metrics["hue"] = {
            "connected": bool(getattr(hue, "connected", False)),
            "breaker_state": (breaker or {}).get("state", "unknown"),
            "status": _device_status(getattr(hue, "connected", False), breaker),
        }

    # Sonos
    sonos = getattr(app.state, "sonos", None)
    if sonos is not None:
        breaker = sonos.breaker.snapshot() if hasattr(sonos, "breaker") else None
        metrics["sonos"] = {
            "connected": bool(getattr(sonos, "connected", False)),
            "breaker_state": (breaker or {}).get("state", "unknown"),
            "status": _device_status(getattr(sonos, "connected", False), breaker),
        }

    # Fusion confidence — last computed result on AutomationEngine. The
    # field can be None for the first ~60s after boot before the loop has
    # ticked once.
    automation = getattr(app.state, "automation", None)
    if automation is not None:
        fusion_result = getattr(automation, "_last_fusion_result", None)
        if fusion_result:
            fc = float(fusion_result.get("fused_confidence", 0.0))
            metrics["fusion"] = {
                "confidence": round(fc, 3),
                "mode": fusion_result.get("fused_mode"),
                "agreement": round(
                    float(fusion_result.get("agreement", 0.0)), 3,
                ),
                "status": _classify_low(fc, _FUSION_WARN, _FUSION_ERROR),
            }
        else:
            metrics["fusion"] = {
                "confidence": None,
                "mode": None,
                "agreement": None,
                "status": "warn",
            }

    # Pi-hole
    pihole = getattr(app.state, "pihole_service", None)
    if pihole is not None:
        try:
            summary = await pihole.get_summary()
            if summary:
                metrics["pihole"] = {
                    "blocked": int(summary.get("blocked", 0)),
                    "percent_blocked": float(
                        summary.get("percent_blocked", 0.0)
                    ),
                    "active_clients": int(summary.get("active_clients", 0)),
                    "status": "ok",
                }
            else:
                metrics["pihole"] = {"status": "error"}
        except Exception as e:
            logger.warning("vitals: pihole summary failed: %s", e)
            metrics["pihole"] = {"status": "error"}

    # System metrics (psutil)
    metrics.update(_read_psutil_metrics())

    # WebSocket clients
    ws_manager = getattr(app.state, "ws_manager", None)
    if ws_manager is not None:
        metrics["websocket_clients"] = ws_manager.connection_count

    # Roll-up status — error wins, then warn, else ok. Non-status values
    # (websocket_clients, etc.) are skipped.
    statuses = [
        m.get("status")
        for m in metrics.values()
        if isinstance(m, dict) and m.get("status")
    ]
    if "error" in statuses:
        overall = "error"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"

    return {"status": overall, "metrics": metrics}
