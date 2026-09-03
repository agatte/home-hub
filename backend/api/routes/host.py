"""Local host-lifecycle controls for the portable Latitude.

Travel is deliberately above House State/Activity.  The kiosk may arm Travel
only from loopback; a detached user-systemd helper then persists the marker and
stops HomeHub after the HTTP acknowledgement has reached the browser.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import subprocess
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import is_direct_localhost, require_localhost
from backend.config import PROJECT_ROOT

logger = logging.getLogger("home_hub.api.host")
router = APIRouter(prefix="/api/host", tags=["host"])

STATE_FILE = Path.home() / ".local" / "state" / "home-hub" / "travel-mode"
RETURNING_HOME_STATE_FILE = (
    Path.home() / ".local" / "state" / "home-hub" / "returning-home"
)
HOSTCTL = PROJECT_ROOT / "scripts" / "homehub-hostctl.sh"
DNS_WARNING = (
    "Apartment DNS may still depend on the Latitude while #145 is open. "
    "Travel Mode does not reconfigure Google/Nest Wifi DNS."
)


def _status_payload(*, can_control: bool = False) -> dict:
    travel_marker = STATE_FILE.exists()
    returning_home_marker = RETURNING_HOME_STATE_FILE.exists()
    active_marker = RETURNING_HOME_STATE_FILE if returning_home_marker else STATE_FILE
    entered_at = None
    if returning_home_marker or travel_marker:
        try:
            entered_at = active_marker.read_text(encoding="utf-8").strip() or None
        except OSError:
            entered_at = None
    if returning_home_marker:
        mode = "RETURNING_HOME"
    elif travel_marker:
        mode = "TRAVEL"
    else:
        mode = "HOME"
    return {
        "mode": mode,
        "travel_marker": travel_marker,
        "returning_home_marker": returning_home_marker,
        "entered_at": entered_at,
        "dns_warning": DNS_WARNING,
        "return_launcher": "HomeHub Return Home",
        "can_control": can_control,
    }


def _schedule_travel(delay_seconds: float = 5.0) -> str:
    if not HOSTCTL.exists():
        raise FileNotFoundError(f"host control helper missing: {HOSTCTL}")
    unit = f"home-hub-travel-enter-{time.time_ns()}"
    command = [
        "systemd-run", "--user", f"--unit={unit}", "--collect", "--no-block",
        "/bin/bash", str(HOSTCTL), "travel", "--delay", str(delay_seconds),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
    return unit


@router.get("/status")
async def host_status(request: Request) -> dict:
    return _status_payload(can_control=is_direct_localhost(request))


@router.post("/travel", dependencies=[Depends(require_localhost)])
async def enter_travel(request: Request) -> dict:
    """Acknowledge Travel, then detach the actual host shutdown from FastAPI."""
    if RETURNING_HOME_STATE_FILE.exists():
        return {
            "status": "already_returning_home",
            **_status_payload(can_control=True),
        }
    if STATE_FILE.exists():
        return {"status": "already_travel", **_status_payload(can_control=True)}

    try:
        unit = _schedule_travel()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.exception("Could not arm Travel host helper")
        raise HTTPException(status_code=500, detail="Could not arm Travel Mode") from exc

    departure = {"attempted": False, "ok": False, "detail": "not available"}
    # Drop live Latitude physical authority before the delayed host stop.
    # PresenceFusion is in-memory and starts empty on the later HOME boot;
    # this closes the acknowledgement window too.
    presence = getattr(request.app.state, "presence", None)
    if presence is not None:
        presence.invalidate_source("latitude")

    away_manager = getattr(request.app.state, "away_manager", None)
    if away_manager is not None:
        departure["attempted"] = True
        try:
            result = await asyncio.wait_for(
                away_manager.handle_event("leave", "travel:kiosk"),
                timeout=3.0,
            )
            departure.update(ok=True, detail=result)
        except Exception as exc:  # Travel must fail safe when Hue/Away is degraded.
            logger.warning("Travel graceful departure degraded: %s", exc)
            departure["detail"] = str(exc)


    return {
        "status": "arming",
        "mode": "TRAVEL",
        "message": "Travel Mode armed — HomeHub is shutting down.",
        "helper_unit": unit,
        "departure": departure,
        "dns_warning": DNS_WARNING,
        "return_launcher": "HomeHub Return Home",
    }
