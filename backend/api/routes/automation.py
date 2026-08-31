"""
Automation control endpoints — activity reporting, mode overrides, and config.

Receives activity reports from the PC agent (process detection) and ambient
monitor (Blue Yeti mic). Provides the frontend with current automation state
and manual override controls.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.api.auth import require_api_key, source_from_request
from backend.config import settings
from backend.rate_limit import limiter

from backend.api.routes.routines import load_setting, save_setting
from backend.api.schemas.automation import (
    ActivityReport,
    AutomationConfig,
    AutomationStatus,
    DNDRequest,
    LaptopLoopbackToggle,
    ManualOverride,
    MicCalibrationResult,
    ModeBrightnessConfig,
    ModeVolumeCurvesConfig,
    RustEventReport,
    ScreenColorReport,
    TimeScheduleConfig,
)
from backend.services.mode_volume_service import (
    MODE_VOLUME_CURVES_KEY,
    ModeVolumeService,
)
from backend.services.automation_constants import (
    # Canonical home is automation_constants (engine re-exports for back-compat).
    DND_STATE_KEY as DND_STATE_KEY,
    SCREEN_SYNC_MODES,
    SOURCE_STALE_SECONDS,
    DaySchedule,
    ScheduleConfig,
)
from backend.services.light_state_calculator import lux_to_multiplier
from backend.services.lux_channel import LUX_EMA_STALE_RESET_SECONDS
from backend.services.presence_fusion import PresenceReading
from backend.services.agent_health_monitor import SUPERVISOR_SILENT_SECONDS

SCHEDULE_CONFIG_KEY = "time_schedule_config"
BRIGHTNESS_CONFIG_KEY = "mode_brightness_config"
SCREEN_SYNC_LAPTOP_KEY = "screen_sync_laptop_enabled"
WATCHING_POSTURE_KEY = "watching_posture_config"
RUST_LIGHTING_KEY = "rust_lighting_config"
RUST_EVENT_CONFIG_KEY = "rust_event_config"
OVERRIDE_STATE_KEY = "override_state"

# Settings-page defaults for the watching-posture tuning knobs. The values
# here mirror the hardcoded fall-back in screen_sync.py and automation_engine
# so a fresh SQLite row reads back the same numbers the in-code defaults use.
WATCHING_POSTURE_DEFAULTS = {
    "reclined_sync_cap": 25,   # screen-sync max_bri when watching+bed+reclined
    "reclined_l1_night": 25,   # L1 ambient at night; evening/late_night scale
    "upright_sync_cap":  60,   # screen-sync max_bri when watching+bed+upright
}

logger = logging.getLogger("home_hub.automation")

router = APIRouter(prefix="/api/automation", tags=["automation"])

BEDROOM_SCREEN_SYNC_TARGETS = ("2", "5")
LIVING_ROOM_SCREEN_SYNC_TARGETS = ("1", "3", "4")
BEDROOM_LUX_HOLD_SECONDS = float(LUX_EMA_STALE_RESET_SECONDS)


def _factor_value(factors: list[dict] | None, key: str):
    for factor in factors or []:
        if isinstance(factor, dict) and factor.get("key") == key:
            return factor.get("value")
    return None


def _is_latitude_streaming_report(report: ActivityReport) -> bool:
    return (
        report.source == "process"
        and _factor_value(report.factors, "device") == "latitude"
        and _factor_value(report.factors, "playback_active") is not None
    )


async def _handle_latitude_streaming_side_effects(
    report: ActivityReport, request: Request, result: dict,
) -> None:
    if not _is_latitude_streaming_report(report):
        return

    engine = getattr(request.app.state, "automation", None)
    streaming_present = _latitude_owns_watching_context(report, result, engine)

    loopback = getattr(request.app.state, "laptop_loopback", None)
    if loopback is None:
        return

    auto_started = bool(getattr(
        request.app.state, "latitude_streaming_loopback_started", False,
    ))
    if streaming_present:
        if not loopback.running:
            start_task = getattr(
                request.app.state,
                "latitude_streaming_loopback_start_task",
                None,
            )
            if start_task is None or start_task.done():
                request.app.state.latitude_streaming_loopback_started = True
                start_task = asyncio.create_task(
                    loopback.start(),
                    name="latitude-streaming-loopback-start",
                )
                request.app.state.latitude_streaming_loopback_start_task = start_task

                def _start_done(task: asyncio.Task) -> None:
                    if getattr(
                        request.app.state,
                        "latitude_streaming_loopback_start_task",
                        None,
                    ) is task:
                        request.app.state.latitude_streaming_loopback_start_task = None
                    if task.cancelled():
                        return
                    error = task.exception()
                    if error is not None:
                        request.app.state.latitude_streaming_loopback_started = False
                        logger.warning(
                            "Latitude streaming loopback start failed: %s",
                            error,
                        )

                start_task.add_done_callback(_start_done)
        return

    start_task = getattr(
        request.app.state, "latitude_streaming_loopback_start_task", None,
    )
    if start_task is not None and not start_task.done():
        start_task.cancel()
    if auto_started and loopback.running:
        await loopback.stop()
    request.app.state.latitude_streaming_loopback_started = False


def _latitude_owns_watching_context(
    report: ActivityReport, result: dict, engine,
) -> bool:
    """True only for an accepted, fresh Latitude-owned Watching context.

    The raw detector report is deliberately insufficient: it may have lost
    engine arbitration to an active desktop session. Physical presence is not
    part of this media/source-ownership decision.
    """
    if not (
        report.mode == "watching"
        and bool(_factor_value(report.factors, "playback_active"))
        and result.get("semantic_disposition") == "accepted"
        and result.get("semantic_mode") == "watching"
        and result.get("authoritative_mode") == "watching"
    ):
        return False

    context_reader = getattr(engine, "get_activity_context", None)
    if not callable(context_reader):
        return False
    context = context_reader()
    return (
        context.get("current_activity") == "watching"
        and context.get("current_activity_fresh") is True
        and context.get("current_activity_source_key") == "process:latitude"
    )


def _screen_sync_target_lights(report: ScreenColorReport, sync) -> list[str]:
    available = set(sync.target_lights)
    if report.source == "laptop":
        targets = [lid for lid in LIVING_ROOM_SCREEN_SYNC_TARGETS if lid in available]
        if targets:
            return targets
    targets = [lid for lid in BEDROOM_SCREEN_SYNC_TARGETS if lid in available]
    return targets or sync.target_lights


def _reading_is_fresh(reading: PresenceReading | None, max_age_s: float) -> bool:
    if reading is None:
        return False
    captured_at = reading.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    age_s = (datetime.now(timezone.utc) - captured_at).total_seconds()
    return -2.0 <= age_s <= max_age_s


def _watching_screen_sync_authority(engine, presence) -> dict:
    """Resolve the only screen source allowed to write during Watching.

    Accepted device-qualified activity is the primary ownership signal:
    Latitude media owns laptop loopback colors, while desktop media owns the
    desktop capture. Physical desk/couch evidence is a fallback for an
    explicit/manual Watching mode. A legacy engine that cannot expose activity
    context retains the pre-audit behavior for compatibility adapters/tests.
    """
    if getattr(engine, "current_mode", None) != "watching":
        return {
            "enforced": False,
            "source": None,
            "reason": "mode_does_not_require_source_arbitration",
        }

    context_reader = getattr(engine, "get_activity_context", None)
    if not callable(context_reader):
        return {
            "enforced": False,
            "source": None,
            "reason": "activity_context_unavailable",
        }

    context = context_reader()
    source_key = context.get("current_activity_source_key")
    if (
        context.get("current_activity") == "watching"
        and context.get("current_activity_fresh") is True
    ):
        if source_key == "process:latitude":
            return {
                "enforced": True,
                "source": "laptop",
                "reason": "accepted_latitude_watching",
            }
        if source_key == "process:desktop":
            return {
                "enforced": True,
                "source": "desktop",
                "reason": "accepted_desktop_watching",
            }

    evidence = context.get("process_evidence_by_device") or {}
    watching_devices = {
        device
        for device, row in evidence.items()
        if row.get("committed_mode") == "watching"
        and isinstance(row.get("age_seconds"), (int, float))
        and -2.0 <= row["age_seconds"] <= SOURCE_STALE_SECONDS
    }
    if watching_devices == {"latitude"}:
        return {
            "enforced": True,
            "source": "laptop",
            "reason": "fresh_latitude_watching_evidence",
        }
    if watching_devices == {"desktop"}:
        return {
            "enforced": True,
            "source": "desktop",
            "reason": "fresh_desktop_watching_evidence",
        }

    if presence is not None:
        latest_zone = presence.latest_zone(max_age_s=8)
        if latest_zone == "desk":
            desktop = presence.get_source_reading("desktop")
            if (
                _reading_is_fresh(desktop, 8.0)
                and desktop.face_present is True
                and desktop.zone == "desk"
            ):
                return {
                    "enforced": True,
                    "source": "desktop",
                    "reason": "fresh_desktop_desk_presence",
                }

        if latest_zone == "couch":
            latitude = presence.get_source_reading("latitude")
            if (
                _reading_is_fresh(latitude, 8.0)
                and latitude.face_present is True
                and latitude.zone == "couch"
            ):
                return {
                    "enforced": True,
                    "source": "laptop",
                    "reason": "fresh_latitude_couch_presence",
                }
    return {
        "enforced": True,
        "source": None,
        "reason": "no_authoritative_watching_source",
    }


def _bedroom_lux_multiplier(channel) -> float:
    """Return the bedroom lux multiplier, holding through short agent gaps."""
    if channel is None:
        return 1.0
    ema_lux = channel.ema_lux
    baseline_lux = channel.baseline_lux
    last_update = getattr(channel, "last_lux_update", None)
    if ema_lux is None or baseline_lux is None or last_update is None:
        return 1.0
    if last_update.tzinfo is None:
        last_update = last_update.replace(tzinfo=timezone.utc)
    age_s = (datetime.now(timezone.utc) - last_update).total_seconds()
    if age_s > BEDROOM_LUX_HOLD_SECONDS:
        return 1.0
    return lux_to_multiplier(ema_lux, baseline_lux)


def _agent_health_origin(body: dict) -> str:
    origin = body.get("origin") if isinstance(body, dict) else None
    if isinstance(origin, str) and origin.strip():
        return origin.strip().lower()
    return "desktop"


def _agent_health_clock(request: Request) -> float:
    """Use an app-injected clock in route tests; production uses wall time."""
    clock = getattr(request.app.state, "agent_health_clock", time.time)
    return clock()


def _stored_agent_health_report(value: dict) -> tuple[dict, float | None]:
    """Read a receipt envelope, accepting pre-freshness raw reports on boot."""
    if "report" in value and "received_at" in value:
        report = value.get("report")
        return (report if isinstance(report, dict) else {}), value.get("received_at")
    return value, None


def _origin_is_fresh(received_at: float | None, now: float) -> tuple[float | None, bool]:
    """All current reporters post about every 30s, so share watchdog's 5m bound."""
    if received_at is None:
        return None, False
    age = max(0.0, now - received_at)
    return age, age <= SUPERVISOR_SILENT_SECONDS


def _agent_snapshot(info: dict, origin_age: float | None, *, current: bool) -> dict:
    """Label reporter-calculated age and, for current agents, estimate it now."""
    snapshot = dict(info or {})
    at_report = snapshot.get("heartbeat_age")
    snapshot["heartbeat_age_at_report"] = at_report
    if current and at_report is not None and origin_age is not None:
        snapshot["heartbeat_age"] = at_report + origin_age
    return snapshot


def _merge_agent_health_reports(reports: dict[str, dict], *, now: float | None = None) -> dict:
    """Expose only fresh origins as current while retaining their last reports.

    Receipt time is server-owned. Every current reporter has a ~30-second
    cadence, so this shares the desktop watchdog's five-minute silence bound.
    """
    if not reports:
        return {"status": "no_report", "agents": {}, "origins": {}}

    now = time.time() if now is None else now
    origins: dict[str, dict] = {}
    current_reports: dict[str, tuple[dict, float | None]] = {}
    agents: dict[str, dict] = {}
    for origin, stored in reports.items():
        report, received_at = _stored_agent_health_report(stored)
        origin_age, fresh = _origin_is_fresh(received_at, now)
        historical = dict(report)
        historical["agents"] = {
            name: _agent_snapshot(info, origin_age, current=False)
            for name, info in (report.get("agents") or {}).items()
        }
        historical.update({
            "server_received_at": received_at,
            "origin_age_seconds": origin_age,
            "fresh": fresh,
        })
        origins[origin] = historical
        if not fresh:
            continue
        current_reports[origin] = (report, origin_age)
        for name, info in (report.get("agents") or {}).items():
            current_info = _agent_snapshot(info, origin_age, current=True)
            if name in agents:
                agents[f"{origin}:{name}"] = current_info
            else:
                agents[name] = current_info

    desktop, _ = current_reports.get("desktop", ({}, None))
    merged = {
        key: value for key, value in desktop.items()
        if key not in {"agents", "origin"}
    }
    merged["agents"] = agents
    merged["origins"] = origins
    return merged


@router.post("/activity", dependencies=[Depends(require_api_key)])
async def report_activity(report: ActivityReport, request: Request) -> dict:
    """
    Receive an activity report from the PC agent or ambient monitor.

    The automation engine decides whether to apply the mode change based on
    priority (gaming > social > watching > working > idle > away) and whether
    a manual override is active.
    """
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    engine_result = await engine.report_activity(
        report.mode, report.source, factors=report.factors,
    )
    # Third-party/legacy activity adapters returned None before #189. Keep the
    # route tolerant while the real engine now provides the richer contract.
    result = engine_result if isinstance(engine_result, dict) else {
        "reported_mode": report.mode,
        "semantic_disposition": "accepted",
        "reason": "legacy_engine",
        "semantic_mode": report.mode,
        "authoritative_mode": getattr(engine, "current_mode", report.mode),
        "included_in_fusion": False,
    }
    await _handle_latitude_streaming_side_effects(report, request, result)

    # Fan the report to the LoL champion service so a champion factor (set
    # only when League's Live Client Data API returned 200) can drive the
    # bedroom-lamp color. Service is gaming-mode-gated internally; non-LoL
    # reports are a cheap no-op.
    lol_service = getattr(request.app.state, "lol_champion_service", None)
    if lol_service is not None:
        await lol_service.on_activity_report(report, result)

    return {
        "status": "ok",
        "source": report.source,
        # Retained for clients that used the original response shape.  Unlike
        # the old echo, it now reflects the accepted semantic (or None for a
        # retraction/rejection) rather than the submitted detector output.
        "accepted_mode": result.get("semantic_mode"),
        **result,
    }


@router.get("/activity")
async def get_activity(request: Request) -> dict:
    """Get the current detected activity mode."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {"mode": "idle", "source": "none"}

    context = engine.get_activity_context()
    return {
        # Backward-compatible ``mode`` now reflects the user-facing effective
        # activity/lifecycle state.  Keep raw detector evidence explicit for
        # diagnostics and agent investigations.
        "mode": engine.effective_mode,
        "source": engine.effective_source,
        "house_state": engine.house_state,
        "activity": engine.activity,
        "detected_mode": context["current_activity"],
        "detected_source": context["current_activity_source"],
        "process_evidence_by_device": context["process_evidence_by_device"],
        "process_observations_by_device": (
            context["process_observations_by_device"]
        ),
        "gaming": context["gaming"],
    }


@router.post("/agent-health", dependencies=[Depends(require_api_key)])
async def report_agent_health(request: Request) -> dict:
    """Receive health heartbeats from desktop and Latitude agents."""
    body = await request.json()
    origin = _agent_health_origin(body)
    reports = getattr(request.app.state, "agent_health_reports", None)
    if not isinstance(reports, dict):
        reports = {}
    received_at = _agent_health_clock(request)
    reports[origin] = {"report": body, "received_at": received_at}
    request.app.state.agent_health_reports = reports
    request.app.state.agent_health = _merge_agent_health_reports(reports, now=received_at)

    # The watchdog is desktop-supervisor-specific. Latitude service health is
    # exposed in the merged payload but must not reset desktop silence timers.
    if origin == "desktop":
        monitor = getattr(request.app.state, "agent_health_monitor", None)
        if monitor is not None:
            await monitor.record_report(body, received_at=received_at)
    return {"status": "ok", "origin": origin}


@router.get("/agent-health")
async def get_agent_health(request: Request) -> dict:
    """Get latest agent health reports + desktop watchdog freshness."""
    reports = getattr(request.app.state, "agent_health_reports", None)
    if not isinstance(reports, dict):
        legacy = getattr(request.app.state, "agent_health", None)
        reports = {"desktop": legacy} if isinstance(legacy, dict) else {}
    now = _agent_health_clock(request)
    health = _merge_agent_health_reports(reports, now=now)
    monitor = getattr(request.app.state, "agent_health_monitor", None)
    watchdog = monitor.snapshot(now=now) if monitor is not None else None
    return {**health, "watchdog": watchdog}

@router.get("/status")
async def get_status(request: Request) -> AutomationStatus:
    """Get the full automation engine status."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return AutomationStatus()

    dnd = engine.dnd_status()
    return AutomationStatus(
        current_mode=engine.current_mode,
        mode_source=engine.mode_source,
        house_state=engine.house_state,
        activity=engine.activity,
        manual_override=engine.manual_override,
        override_mode=engine.override_mode,
        last_activity_change=(
            engine.last_activity_change.isoformat()
            if engine.last_activity_change
            else None
        ),
        automation_enabled=engine.enabled,
        manual_light_overrides=list(engine.manual_light_overrides),
        dnd_enabled=dnd["enabled"],
        dnd_expiry_utc=dnd["expiry_utc"],
        dnd_minutes_remaining=dnd["minutes_remaining"],
        time_period=engine.get_time_period(),
    )


@router.get("/dnd")
async def get_dnd_status(request: Request) -> dict:
    """Get current Do Not Disturb state."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {
            "enabled": False,
            "expiry_utc": None,
            "minutes_remaining": 0,
            "duration_minutes": 0,
        }
    return engine.dnd_status()


@router.post("/dnd", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def enable_dnd_route(req: DNDRequest, request: Request) -> dict:
    """Activate Do Not Disturb for the given duration (default 2h)."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    state = await engine.enable_dnd(req.duration_minutes, source=caller)
    return {"status": "ok", **state}


@router.delete("/dnd", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def clear_dnd_route(request: Request) -> dict:
    """Clear Do Not Disturb immediately."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    state = await engine.clear_dnd(source=caller)
    return {"status": "ok", **state}


@router.get("/pipeline")
async def get_pipeline(request: Request) -> dict:
    """Get the current decision pipeline state and recent history."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return {
            "current": None,
            "history": [],
            "living_room_context": None,
        }
    gate = getattr(request.app.state, "living_room_decision_gate", None)
    living_room_context = gate.current_envelope() if gate is not None else None
    if living_room_context is not None:
        living_room_context = {
            **living_room_context,
            "atmosphere": engine.get_living_room_atmosphere_status(),
        }
    return {
        "current": engine._build_pipeline_state(),
        "history": list(engine.pipeline_history),
        "living_room_context": living_room_context,
    }


@router.get(
    "/living-room-context",
    dependencies=[Depends(require_api_key)],
)
async def get_living_room_context(request: Request) -> dict:
    """Return the exact already-evaluated shadow decision envelope."""
    gate = getattr(request.app.state, "living_room_decision_gate", None)
    if gate is None:
        raise HTTPException(
            status_code=503,
            detail="Living-room decision gate not initialized",
        )
    engine = getattr(request.app.state, "automation", None)
    return {
        **gate.current_status(),
        "atmosphere": (
            engine.get_living_room_atmosphere_status()
            if engine is not None else None
        ),
    }


@router.get(
    "/living-room-context/history",
    dependencies=[Depends(require_api_key)],
)
async def get_living_room_context_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Return bounded persisted decisions, newest first."""
    gate = getattr(request.app.state, "living_room_decision_gate", None)
    if gate is None:
        raise HTTPException(
            status_code=503,
            detail="Living-room decision gate not initialized",
        )
    engine = getattr(request.app.state, "automation", None)
    return {
        "limit": limit,
        "records": await gate.history(limit),
        "atmosphere_records": (
            await engine.get_living_room_atmosphere_history(limit)
            if engine is not None else []
        ),
    }


@router.post("/override", dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def set_override(override: ManualOverride, request: Request) -> dict:
    """
    Manually override the current automation mode.

    Set mode to 'auto' to clear the override and return to automatic detection.
    """
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    # Caller-context label for telemetry — answers "who flipped the override"
    # in journalctl after the fact. Includes the route's own client IP so we
    # can distinguish kiosk dashboard from dev desktop from external scripts.
    # The X-Source header (set by the Alexa lambda) overrides the IP-based
    # default so voice actions surface as `alexa:<intent>` instead of
    # `api:127.0.0.1` (the tunnel proxy's loopback).
    remote = getattr(request.client, "host", None) or "unknown"
    caller = source_from_request(request, fallback=f"api:{remote}")
    if override.mode == "auto":
        await engine.clear_override(
            source=caller,
            user_requested_auto=True,
        )
        return {"status": "ok", "message": "Override cleared — returning to auto"}

    await engine.set_manual_override(override.mode, source=caller)
    return {"status": "ok", "mode": override.mode, "source": "manual"}


@router.post("/screen-color", dependencies=[Depends(require_api_key)])
async def receive_screen_color(report: ScreenColorReport, request: Request) -> dict:
    """
    Receive a screen color sample from the desktop pc_agent or laptop loopback.

    The current automation mode gates application: colors only reach lights
    if the mode is in SCREEN_SYNC_MODES (gaming, watching). Off-mode colors
    are accepted (so the agent doesn't error) but dropped silently — the
    response distinguishes via the ``applied`` field.

    Mirror dispatch: the single ``{r, g, b}`` is fan-out to the route-selected
    lamp set. Desktop/Rust stays on bedroom L2+L5; Latitude laptop watching
    uses L1+L3+L4 so the room around the TV responds. Per-light EMA,
    brightness caps, and luma compensation still differentiate output — the
    input color is shared, the on-bridge state isn't.
    """
    engine = getattr(request.app.state, "automation", None)
    sync = getattr(request.app.state, "screen_sync", None)
    if not engine or not sync:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    clear_watching_hold = getattr(sync, "clear_watching_hold", None)
    if (
        report.source == "desktop"
        and engine.current_mode != "watching"
        and callable(clear_watching_hold)
    ):
        clear_watching_hold(report.source)

    if engine.current_mode not in SCREEN_SYNC_MODES:
        return {"status": "ok", "applied": False}

    # Away/external-off: a game/video left running keeps streaming colors
    # after a departure — while the apartment is suppressed, accept the
    # report but never re-light the sync target lamps with it.
    if getattr(engine, "_external_off_detected", False):
        return {"status": "ok", "applied": False}

    # Laptop frames originate solely from the Latitude loopback, whose valid
    # automatic ownership is Latitude Watching.  Reject them before the
    # generic Gaming/Rust paths so a rejected/stale Latitude report cannot
    # inject color or Rust luma into a desktop-owned game session.
    if engine.current_mode == "gaming" and report.source == "laptop":
        return {
            "status": "ok",
            "applied": False,
            "reason": "laptop_source_requires_latitude_watching",
            "reported_source": report.source,
            "authoritative_source": "desktop",
            "authority_reason": "desktop_gaming",
        }

    presence = getattr(request.app.state, "presence", None)
    source_authority = _watching_screen_sync_authority(engine, presence)
    authoritative_source = source_authority["source"]
    if (
        source_authority["enforced"]
        and report.source != authoritative_source
    ):
        if report.source == "desktop" and callable(clear_watching_hold):
            clear_watching_hold(report.source)
        return {
            "status": "ok",
            "applied": False,
            "reason": "non_authoritative_source",
            "reported_source": report.source,
            "authoritative_source": authoritative_source,
            "authority_reason": source_authority["reason"],
        }

    # Watching mode intentionally has long dwell at night, but screen color
    # ownership should not inherit that stickiness. When the desktop reports
    # explicit non-media foreground content (for example ChatGPT after pausing
    # YouTube), hold the last valid media color until media returns or the mode
    # itself transitions. None remains fail-open for older/indeterminate agents.
    if engine.current_mode == "watching" and report.source == "desktop":
        targets = _screen_sync_target_lights(report, sync)
        if report.foreground_media is False:
            refresh_hold = getattr(sync, "refresh_watching_hold", None)
            if callable(refresh_hold):
                refresh_hold(report.source, targets)
            return {
                "status": "ok",
                "applied": False,
                "reason": "watching_foreground_not_media",
                "reported_source": report.source,
            }
        if report.foreground_media is True and callable(clear_watching_hold):
            clear_watching_hold(report.source, targets)

    # Pull zone + posture so the sync cap can differ between watching-at-desk
    # (brighter bias, L2 cap 180) and the dim couch/reclined variants. Source
    # from PresenceFusion, NOT the raw Latitude camera: since the 2026-05-27
    # living-room move the Latitude sees the COUCH (its ``zone`` is null when
    # nobody's there), so reading it directly hid the ``desk`` zone the desktop
    # pc_agent owns — the watching-desk L2 cap silently stopped firing for
    # screen-sync while the user watches at the desk. ``latest_zone()`` fuses
    # both physical sources: close-face desktop observations can resolve Desk,
    # calibrated distant desktop pose can resolve Bed, and weak Latitude face
    # evidence cannot claim Couch. Falls back to the raw camera if fusion isn't
    # wired (boot / tests). Bed-variant caps still require a posture signal.
    camera = getattr(request.app.state, "camera_service", None)
    if presence is not None:
        zone = presence.latest_zone()
        posture = presence.latest_posture()
    else:
        zone = getattr(camera, "zone", None) if camera else None
        posture = getattr(camera, "posture", None) if camera else None

    # Time period drives the per-period cap/floor envelope so the lamps
    # dim alongside the room as evening rolls into night.
    period = engine._get_time_period()

    # Rust profile: hold a fixed ember color and drive the bedroom lamps'
    # BRIGHTNESS from the screen's whole-frame luma, so the room dims as Rust's
    # day/night cycle goes dark (the user's "dark in game → dimmer room" ask).
    # Color is NOT synced — Rust has no coherent ambient color. Both L2 and L5
    # are luma-driven on per-light envelopes (L5 subordinate, ~50-55% of L2) so
    # the clear-housing accent dims WITH L2 instead of towering over it when L2
    # floors out (the glare-pop the curator flagged + live feedback confirmed
    # 2026-06-08). Other games use the stable canonical gaming state below.
    if getattr(engine, "current_game", None) == "rust":
        luma = report.luma
        if luma is None:
            # Transitional fallback for an agent that predates the `luma` field
            # — derive it from the dominant color (a worse signal than real
            # frame luma, but keeps the path live until the desktop agent
            # restart ships it).
            luma = int(0.299 * report.r + 0.587 * report.g + 0.114 * report.b)
        # Under-fire glow (Phase 2): while RustEventService says the player is
        # taking sustained damage, tint the ember toward danger-red instead of
        # re-flashing. None = normal ember.
        rust_event = getattr(request.app.state, "rust_event", None)
        tint = rust_event.tint_for("2") if (
            rust_event is not None and rust_event.under_fire
        ) else None

        applied_rust: list[str] = []
        skipped_rust: dict[str, str] = {}
        for target in BEDROOM_SCREEN_SYNC_TARGETS:
            if target not in sync.target_lights:
                skipped_rust[target] = "no_target"
                continue
            if target in engine.manual_light_overrides:
                skipped_rust[target] = "manual_override"
                continue
            await sync.apply_rust_brightness(
                target, luma, period=period, source=report.source, tint=tint,
            )
            applied_rust.append(target)
        resp: dict = {
            "status": "ok", "applied": bool(applied_rust),
            "lights": applied_rust, "profile": "rust",
        }
        if skipped_rust:
            resp["skipped"] = skipped_rust
        return resp

    # Watching ambient lift: lux + weather scale the cap+floor so dim content
    # in a dim room doesn't drag L2 to eye-strain dimness. Generic gaming
    # bypasses this dynamic envelope and holds its canonical base; watching
    # retains the existing per-light cap/floor scaling below.
    #
    # D4 Part E: source the lux from the BEDROOM desktop-webcam channel, NOT
    # the living-room Latitude camera — L2/L5 are bedroom lamps, and a bright
    # living room must not dim them (the cross-room contamination that got
    # gaming dropped from LUX_MODES; bit us live 2026-06-02, living-room
    # mult 0.897 was throttling the bedroom gaming floors). Falls back to
    # neutral 1.0 only when the channel is uncalibrated, never updated,
    # or stale past the LuxChannel stale-reset window. Short desktop-agent gaps
    # keep the last EMA value so L2 does not pulse between lifted and neutral.
    bedroom_lux = getattr(request.app.state, "bedroom_lux", None)
    lux_mult = _bedroom_lux_multiplier(bedroom_lux)
    weather_condition = engine._get_current_weather_condition()

    # Per-light skip gate. A lamp may sit out a frame because the user
    # dragged its slider (manual_light_overrides) or because the LoL
    # champion service owns it mid-match.
    lol_service = getattr(request.app.state, "lol_champion_service", None)
    applied: list[str] = []
    skipped: list[str] = []
    skip_reasons: dict[str, str] = {}
    for light_id in _screen_sync_target_lights(report, sync):
        if light_id in engine.manual_light_overrides:
            skipped.append(light_id)
            skip_reasons[light_id] = "manual_override"
            continue
        if lol_service is not None and lol_service.is_owning(light_id):
            skipped.append(light_id)
            skip_reasons[light_id] = "lol_champion"
            continue
        accepted = await sync.apply_color(
            light_id,
            report.r,
            report.g,
            report.b,
            mode=engine.current_mode,
            source=report.source,
            zone=zone,
            posture=posture,
            period=period,
            lux_multiplier=lux_mult,
            weather_condition=weather_condition,
        )
        if accepted is not False:
            applied.append(light_id)

    response: dict = {
        "status": "ok",
        "applied": bool(applied),
        "lights": applied,
    }
    if source_authority["enforced"]:
        response["authoritative_source"] = authoritative_source
        response["authority_reason"] = source_authority["reason"]
    if skipped:
        response["skipped"] = skipped
        response["skip_reasons"] = skip_reasons
        # ``reason`` retained for back-compat; reports the first skip's reason.
        response["reason"] = skip_reasons[skipped[0]]
    return response


@router.get("/screen-sync/status")
async def get_screen_sync_status(request: Request) -> dict:
    """
    Current screen sync state — whether the mode gate is open, when the
    last color arrived, what posted it, and whether the laptop loopback is on.
    """
    engine = getattr(request.app.state, "automation", None)
    sync = getattr(request.app.state, "screen_sync", None)
    loopback = getattr(request.app.state, "laptop_loopback", None)

    enabled_mode = (
        engine.current_mode in SCREEN_SYNC_MODES if engine else False
    )
    last_color_at = (
        sync.last_color_at.isoformat()
        if sync and sync.last_color_at
        else None
    )
    last_source = sync.last_source if sync else None
    laptop_loopback_running = loopback.running if loopback else False
    source_authority = (
        _watching_screen_sync_authority(engine, getattr(
            request.app.state, "presence", None,
        ))
        if engine is not None
        else {
            "enforced": False,
            "source": None,
            "reason": "automation_unavailable",
        }
    )
    authoritative_source = source_authority["source"]
    authoritative_targets = None
    if sync is not None and authoritative_source in {"desktop", "laptop"}:
        authoritative_targets = _screen_sync_target_lights(
            ScreenColorReport(r=0, g=0, b=0, source=authoritative_source),
            sync,
        )

    return {
        "enabled_mode": enabled_mode,
        "current_mode": engine.current_mode if engine else None,
        "last_color_at": last_color_at,
        "last_source": last_source,
        "laptop_loopback_enabled": laptop_loopback_running,
        "laptop_loopback_delivery": (
            loopback.delivery_health if loopback is not None else None
        ),
        "source_authority_enforced": source_authority["enforced"],
        "authoritative_source": authoritative_source,
        "authority_reason": source_authority["reason"],
        "authoritative_targets": authoritative_targets,
        "last_source_authoritative": (
            last_source == authoritative_source
            if authoritative_source is not None and last_source is not None
            else None
        ),
    }


@router.put("/screen-sync/laptop-enabled", dependencies=[Depends(require_api_key)])
async def set_laptop_loopback(
    toggle: LaptopLoopbackToggle, request: Request
) -> dict:
    """
    Toggle the in-process laptop screen capture loopback.

    This is the escape hatch for the rare TV-on-laptop scenario. Default off.
    Persists across restarts via the `screen_sync_laptop_enabled` app_setting.
    """
    loopback = getattr(request.app.state, "laptop_loopback", None)
    if loopback is None:
        raise HTTPException(
            status_code=503, detail="Laptop loopback not initialized"
        )

    if toggle.enabled:
        await loopback.start()
    else:
        await loopback.stop()

    await save_setting(SCREEN_SYNC_LAPTOP_KEY, {"enabled": toggle.enabled})
    logger.info(f"Laptop screen sync loopback set to enabled={toggle.enabled}")

    return {"status": "ok", "enabled": toggle.enabled}


@router.post("/mic/calibrate", dependencies=[Depends(require_api_key)])
async def calibrate_mic(request: Request) -> MicCalibrationResult:
    """
    Calibrate the ambient noise baseline.

    Measures background noise for 5 seconds and sets the detection threshold
    to 2x the average (to avoid false positives from normal room noise).
    """
    # This endpoint is a placeholder — actual calibration runs on the
    # ambient_monitor script. The server stores the threshold for reference.
    return MicCalibrationResult(threshold=800, avg_floor=400.0)


@router.get("/config")
async def get_config(request: Request) -> AutomationConfig:
    """Get current automation configuration."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return AutomationConfig()

    return AutomationConfig(
        enabled=engine.enabled,
        override_timeout_hours=engine.override_timeout_hours,
        gaming_effect=engine.gaming_effect,
    )


@router.put("/config", dependencies=[Depends(require_api_key)])
async def update_config(config: AutomationConfig, request: Request) -> dict:
    """Update automation configuration."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    engine.enabled = config.enabled
    engine.override_timeout_hours = config.override_timeout_hours
    engine.gaming_effect = config.gaming_effect

    logger.info(f"Automation config updated: enabled={config.enabled}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Schedule config
# ---------------------------------------------------------------------------

def _dict_to_schedule_config(data: dict) -> ScheduleConfig:
    """Convert saved JSON dict to ScheduleConfig dataclass."""
    import dataclasses
    valid_fields = {f.name for f in dataclasses.fields(DaySchedule)}

    config = ScheduleConfig()
    if "weekday" in data:
        filtered = {k: v for k, v in data["weekday"].items() if k in valid_fields}
        config.weekday = DaySchedule(**filtered)
    if "weekend" in data:
        filtered = {k: v for k, v in data["weekend"].items() if k in valid_fields}
        config.weekend = DaySchedule(**filtered)
    return config


@router.get("/schedule")
async def get_schedule(request: Request) -> dict:
    """Get the current time-based lighting schedule."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return TimeScheduleConfig().model_dump()

    sc = engine.schedule_config
    return {
        "weekday": {
            "wake_hour": sc.weekday.wake_hour,
            "wake_brightness": sc.weekday.wake_brightness,
            "ramp_start_hour": sc.weekday.ramp_start_hour,
            "ramp_duration_minutes": sc.weekday.ramp_duration_minutes,
            "evening_start_hour": sc.weekday.evening_start_hour,
            "winddown_start_hour": sc.weekday.winddown_start_hour,
            "late_night_start_hour": sc.weekday.late_night_start_hour,
        },
        "weekend": {
            "wake_hour": sc.weekend.wake_hour,
            "wake_brightness": sc.weekend.wake_brightness,
            "ramp_start_hour": sc.weekend.ramp_start_hour,
            "ramp_duration_minutes": sc.weekend.ramp_duration_minutes,
            "evening_start_hour": sc.weekend.evening_start_hour,
            "winddown_start_hour": sc.weekend.winddown_start_hour,
            "late_night_start_hour": sc.weekend.late_night_start_hour,
        },
    }


@router.put("/schedule", dependencies=[Depends(require_api_key)])
async def update_schedule(config: TimeScheduleConfig, request: Request) -> dict:
    """Update the time-based lighting schedule."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    # Convert to engine dataclass
    schedule = ScheduleConfig(
        weekday=DaySchedule(**config.weekday.model_dump()),
        weekend=DaySchedule(**config.weekend.model_dump()),
    )
    engine.update_schedule_config(schedule)

    # Persist to database
    await save_setting(SCHEDULE_CONFIG_KEY, config.model_dump())

    logger.info("Time schedule updated")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Mode brightness
# ---------------------------------------------------------------------------

@router.get("/mode-brightness")
async def get_mode_brightness(request: Request) -> dict:
    """Get per-mode brightness multipliers."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        return ModeBrightnessConfig().model_dump()

    return engine.mode_brightness


@router.put("/mode-brightness", dependencies=[Depends(require_api_key)])
async def update_mode_brightness(
    config: ModeBrightnessConfig, request: Request
) -> dict:
    """Update per-mode brightness multipliers."""
    engine = getattr(request.app.state, "automation", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Automation engine not initialized")

    brightness = config.model_dump()
    engine.update_mode_brightness(brightness)

    # Persist to database
    await save_setting(BRIGHTNESS_CONFIG_KEY, brightness)

    logger.info(f"Mode brightness updated: {brightness}")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Mode volume curves (GH#17 — per-mode Sonos volume targets + fade)
# ---------------------------------------------------------------------------

@router.get("/mode-volume")
async def get_mode_volume() -> dict:
    """Return the merged per-mode volume curves (defaults + persisted overrides)."""
    persisted = await load_setting(MODE_VOLUME_CURVES_KEY)
    return ModeVolumeService.merged_config(persisted)


@router.put("/mode-volume", dependencies=[Depends(require_api_key)])
async def update_mode_volume(
    config: ModeVolumeCurvesConfig, request: Request
) -> dict:
    """Update per-mode Sonos volume curves.

    Partial updates supported — any mode set to None is left at its
    previous persisted value (or the default if no persisted value exists).
    """
    src = source_from_request(request, fallback="api:automation")
    incoming = config.model_dump(exclude_none=True)
    existing = await load_setting(MODE_VOLUME_CURVES_KEY) or {}
    # Merge: incoming overrides existing per-mode, but preserves other modes.
    merged: dict[str, dict[str, int]] = {**existing, **incoming}
    await save_setting(MODE_VOLUME_CURVES_KEY, merged)
    logger.info("Mode volume curves updated by %s: %s", src, list(incoming.keys()))
    return {"status": "ok", "config": merged}


# ---------------------------------------------------------------------------
# Watching posture tuning — runtime knobs for projector-in-bed brightness.
# Desktop bedroom localization can now produce zone="bed", but these knobs are
# still posture-specific. They remain inactive unless a trustworthy bed posture
# (reclined/upright) is available; Bed location alone is not posture evidence.
# ---------------------------------------------------------------------------

@router.get("/watching-posture")
async def get_watching_posture() -> dict:
    """Return the current watching-posture tuning values.

    Reads from persisted storage if present, otherwise returns the defaults
    that match the in-code fallback in screen_sync.py and automation_engine.
    """
    saved = await load_setting(WATCHING_POSTURE_KEY)
    return {**WATCHING_POSTURE_DEFAULTS, **(saved or {})}


@router.put("/watching-posture", dependencies=[Depends(require_api_key)])
async def update_watching_posture(config: dict, request: Request) -> dict:
    """Update the watching-posture tuning values.

    Accepts any subset of the three keys; each value is clamped to 1..100.
    Writes through to the live screen_sync + automation engine so the change
    takes effect on the next reconciliation without a restart.
    """
    cleaned: dict[str, int] = {}
    for key in WATCHING_POSTURE_DEFAULTS:
        if key in config and config[key] is not None:
            cleaned[key] = max(1, min(100, int(config[key])))

    if not cleaned:
        raise HTTPException(status_code=400, detail="No valid keys provided")

    saved = await load_setting(WATCHING_POSTURE_KEY) or {}
    merged = {**WATCHING_POSTURE_DEFAULTS, **saved, **cleaned}
    await save_setting(WATCHING_POSTURE_KEY, merged)

    sync = getattr(request.app.state, "screen_sync", None)
    engine = getattr(request.app.state, "automation", None)
    if sync is not None:
        sync.set_cap_override("watching", "bed", "reclined", merged["reclined_sync_cap"])
        sync.set_cap_override("watching", "bed", "upright",  merged["upright_sync_cap"])
    if engine is not None:
        engine.set_bed_reclined_l1_night(merged["reclined_l1_night"])

    logger.info(f"Watching posture tuning updated: {cleaned}")
    return {"status": "ok", "config": merged}


@router.get("/rust-lighting")
async def get_rust_lighting(request: Request) -> dict:
    """Return the live Rust luma-brightness config (envelope + ember + luma).

    Reads from the live screen_sync service so it reflects defaults merged with
    any persisted tweaks. Shape matches the PUT body. 503 if screen_sync isn't
    wired (boot/tests)."""
    sync = getattr(request.app.state, "screen_sync", None)
    if sync is None:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")
    return {"status": "ok", "config": sync.get_rust_config()}


@router.put("/rust-lighting", dependencies=[Depends(require_api_key)])
async def update_rust_lighting(config: dict, request: Request) -> dict:
    """Live-tune the Rust luma-brightness profile WITHOUT a redeploy.

    Accepts a full or partial config — e.g. ``{"envelope": {"2": {"night":
    [50, 170]}}}`` bumps only L2's night range. The service validates/clamps,
    applies it to the live knobs (effective on the next screen-color frame,
    ~2.5s), and the full resolved config is persisted to app_settings so it
    survives restarts. This is the no-deploy tuning loop for "a tad dimmer /
    brighter" feedback."""
    sync = getattr(request.app.state, "screen_sync", None)
    if sync is None:
        raise HTTPException(status_code=503, detail="Screen sync not initialized")

    merged = sync.apply_rust_config(config)
    await save_setting(RUST_LIGHTING_KEY, merged)
    logger.info("Rust lighting config updated: %s", config)
    return {"status": "ok", "config": merged}


@router.post("/rust-event", dependencies=[Depends(require_api_key)])
async def receive_rust_event(report: RustEventReport, request: Request) -> dict:
    """Ingest a Rust in-game event from the desktop screen agent (Phase 2).

    Damage pings drive the L2/L5 flinch + under-fire glow. Cheaply gated to
    gaming+rust (the agent only posts during Rust anyway); off-context pings
    are accepted and dropped so the agent never errors."""
    rust_event = getattr(request.app.state, "rust_event", None)
    engine = getattr(request.app.state, "automation", None)
    if rust_event is None or engine is None:
        raise HTTPException(status_code=503, detail="Rust event service not initialized")

    if engine.current_mode != "gaming" or getattr(engine, "current_game", None) != "rust":
        return {"status": "ok", "reaction": "not_rust"}
    if report.type != "damage":
        return {"status": "ok", "reaction": "ignored_type"}

    result = await rust_event.report_damage(report.score, period=engine._get_time_period())
    return {"status": "ok", **result}


@router.get("/rust-event-config")
async def get_rust_event_config(request: Request) -> dict:
    """Return the live Rust event-reaction config (flinch/tint/cooldown knobs)."""
    svc = getattr(request.app.state, "rust_event", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Rust event service not initialized")
    return {"status": "ok", "config": svc.get_config()}


@router.put("/rust-event-config", dependencies=[Depends(require_api_key)])
async def update_rust_event_config(config: dict, request: Request) -> dict:
    """Live-tune the damage reaction (cooldown, release, threshold, flinch +
    tint colors) WITHOUT a redeploy. Partial-merge + validate + persist, same
    no-deploy loop as the brightness envelope. Applies to the next event."""
    svc = getattr(request.app.state, "rust_event", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Rust event service not initialized")
    merged = svc.apply_config(config)
    await save_setting(RUST_EVENT_CONFIG_KEY, merged)
    logger.info("Rust event config updated: %s", config)
    return {"status": "ok", "config": merged}


# ---------------------------------------------------------------------------
# Mode → Scene overrides (use Hue scenes instead of hardcoded light states)
# ---------------------------------------------------------------------------

VALID_MODES = {"gaming", "working", "watching", "relax", "cooking", "social"}
VALID_PERIODS = {"day", "evening", "night"}


@router.get("/mode-scenes")
async def get_mode_scene_overrides(request: Request) -> dict:
    """List all mode → scene overrides."""
    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(ModeSceneOverride))
        overrides = result.scalars().all()

    return {
        "overrides": [
            {
                "mode": o.mode,
                "time_period": o.time_period,
                "scene_id": o.scene_id,
                "scene_source": o.scene_source,
                "scene_name": o.scene_name,
            }
            for o in overrides
        ]
    }


@router.put("/mode-scenes/{mode}/{time_period}", dependencies=[Depends(require_api_key)])
async def set_mode_scene_override(
    mode: str, time_period: str, request: Request
) -> dict:
    """Map a scene to a mode + time period, overriding default light states."""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    if time_period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period: {time_period}")

    body = await request.json()
    scene_id = body.get("scene_id")
    scene_source = body.get("scene_source", "bridge")
    scene_name = body.get("scene_name", "")

    if not scene_id:
        raise HTTPException(status_code=400, detail="scene_id is required")

    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(ModeSceneOverride).where(
                ModeSceneOverride.mode == mode,
                ModeSceneOverride.time_period == time_period,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.scene_id = scene_id
            existing.scene_source = scene_source
            existing.scene_name = scene_name
        else:
            session.add(ModeSceneOverride(
                mode=mode,
                time_period=time_period,
                scene_id=scene_id,
                scene_source=scene_source,
                scene_name=scene_name,
            ))
        await session.commit()

    # Reload overrides cache in the automation engine
    engine = getattr(request.app.state, "automation", None)
    if engine:
        await engine.load_scene_overrides()

    logger.info("Mode scene override set: %s/%s → %s (%s)", mode, time_period, scene_name, scene_source)
    return {"status": "ok"}


@router.delete("/mode-scenes/{mode}/{time_period}", dependencies=[Depends(require_api_key)])
async def delete_mode_scene_override(
    mode: str, time_period: str, request: Request
) -> dict:
    """Remove a mode → scene override, reverting to default light states."""
    from backend.database import async_session
    from backend.models import ModeSceneOverride
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(ModeSceneOverride).where(
                ModeSceneOverride.mode == mode,
                ModeSceneOverride.time_period == time_period,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            await session.delete(existing)
            await session.commit()

    # Reload overrides cache
    engine = getattr(request.app.state, "automation", None)
    if engine:
        await engine.load_scene_overrides()

    logger.info("Mode scene override removed: %s/%s", mode, time_period)
    return {"status": "ok"}


# Phone-presence detection (WiFi/ARP/iPhone Shortcut webhooks) was retired
# 2026-04-27 — iOS Shortcut flap was unfixable, BLE-on-iPhone is impractical
# without a custom app, and camera + activity signals already cover "is
# someone here?". Hue native geofencing handles arrival/departure lighting.
