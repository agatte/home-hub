"""
Health check endpoints.

Two surfaces:

- ``/health`` — full diagnostic blob (device connectivity, breaker
  state, ML lane health, scheduler tasks, build_id). Intended for the
  kiosk, dev tools, and internal monitoring. NOT in the public tunnel
  allowlist — the response is reconnaissance gold for an attacker.

- ``/api/ping`` — minimal liveness probe for external uptime monitors
  (UptimeRobot / Uptime Kuma / Cloudflare zone health). Returns just
  ``{"ok": true}`` with no internal state. Allowlisted on the public
  tunnel so the off-LAN probe path keeps working.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/ping")
async def ping() -> dict:
    """Tiny public liveness probe — fixed shape, no app state."""
    return {"ok": True}

# Predictors we surface in the /health ml block. Each tuple is
# (state_attribute_name, display_name) — the attribute is the name on
# app.state where the predictor lives. We tolerate missing attributes
# (some predictors are gated by optional dependencies, e.g.
# behavioral_predictor needs lightgbm; audio_classifier lives in the
# ambient_monitor process).
_ML_PREDICTORS = (
    ("behavioral_predictor", "behavioral_predictor"),
    ("lighting_learner", "lighting_learner"),
    ("music_bandit", "music_bandit"),
    ("rule_engine", "rule_engine"),
    ("confidence_fusion", "confidence_fusion"),
    ("audio_classifier", "audio_classifier"),
)


@router.get("/health")
async def health_check(request: Request) -> dict:
    """
    Returns service status for all connected devices.

    Useful for monitoring and debugging connectivity issues.
    """
    app = request.app

    hue_connected = False
    sonos_connected = False

    if hasattr(app.state, "hue"):
        hue_connected = app.state.hue.connected

    if hasattr(app.state, "sonos"):
        sonos_connected = app.state.sonos.connected

    pihole_connected = False
    if hasattr(app.state, "pihole_service"):
        pihole_connected = app.state.pihole_service.connected

    fauxmo_enabled = False
    fauxmo_connected = False
    if hasattr(app.state, "fauxmo"):
        fauxmo_enabled = app.state.fauxmo.enabled
        fauxmo_connected = app.state.fauxmo.connected
    fauxmo_status = (
        "disabled"
        if not fauxmo_enabled
        else "healthy" if fauxmo_connected else "unhealthy"
    )
    ws_count = 0
    if hasattr(app.state, "ws_manager"):
        ws_count = app.state.ws_manager.connection_count

    event_logger_drops: dict = {}
    event_logger_overflow: dict = {}
    event_logger_queue_depth = 0
    if hasattr(app.state, "event_logger"):
        el = app.state.event_logger
        event_logger_drops = el.get_drop_counts()
        event_logger_overflow = el.get_overflow_counts()
        event_logger_queue_depth = el.get_queue_depth()

    # Background-task heartbeats. Each long-running poll loop publishes
    # last_tick via HeartbeatRegistry; a task is "stale" if its age
    # exceeds 2x its expected interval. /health stays HTTP 200 even when
    # degraded so external probes (Uptime Kuma) keep working — the
    # status field is the signal to act on.
    tasks: list[dict] = []
    tasks_stale: list[str] = []
    status = "healthy"
    details: dict[str, str] = {}
    if hasattr(app.state, "heartbeats"):
        tasks = app.state.heartbeats.snapshot()
        tasks_stale = [t["name"] for t in tasks if t["stale"]]
        if tasks_stale:
            status = "degraded"

    # Camera-specific degraded check: when camera_enabled=true in
    # app_settings but the camera service is missing entirely (boot
    # start failed, half-dead after a crashed poll_loop). The
    # tasks_stale path above only catches the heartbeat-registered case
    # — a never-registered camera looks healthy to the tasks block
    # despite being the documented 12h blind spot from 2026-05-20.
    #
    # Skipped entirely during sleeping mode: a cold/paused camera there
    # is the intended privacy state, not a degradation. Without this
    # gate, /health would flap to "degraded" every night when the camera
    # legitimately stands down — and the kiosk vital strip would turn
    # yellow during sleep, which is the inverse of what we want.
    try:
        automation = getattr(app.state, "automation", None)
        in_sleeping_mode = (
            automation is not None and automation.current_mode == "sleeping"
        )
        from backend.api.routes.routines import load_setting as _load_setting
        camera_setting = await _load_setting("camera_enabled")
        if (
            camera_setting
            and camera_setting.get("enabled", False)
            and not in_sleeping_mode
        ):
            service = getattr(app.state, "camera_service", None)
            heartbeat_present = any(t["name"] == "camera" for t in tasks)
            if service is None:
                status = "degraded"
                details["camera"] = (
                    "camera_enabled=true but no service is live "
                    "(watchdog will respawn within 5 min)"
                )
            elif not getattr(service, "enabled", False) and not getattr(
                service, "_paused", False
            ):
                status = "degraded"
                details["camera"] = (
                    "service present but disabled "
                    "(watchdog will respawn within 5 min)"
                )
            elif not heartbeat_present and not getattr(
                service, "_paused", False
            ):
                status = "degraded"
                details["camera"] = (
                    "service enabled but no heartbeat registered "
                    "(watchdog will respawn within 5 min)"
                )
    except Exception as exc:
        # The camera health probe is best-effort — don't let it break
        # /health for everything else.
        details["camera_probe_error"] = repr(exc)[:200]

    # Circuit breakers protecting calls into Hue / Sonos. When a breaker
    # is open, calls fail fast (raising CircuitBreakerOpen) instead of
    # wedging on a slow bridge — the heartbeat surface above tells you
    # the loop is still ticking, this surface tells you why it's failing.
    circuit_breakers: dict = {}
    if hasattr(app.state, "hue") and hasattr(app.state.hue, "breaker"):
        circuit_breakers["hue"] = app.state.hue.breaker.snapshot()
    if hasattr(app.state, "sonos") and hasattr(app.state.sonos, "breaker"):
        circuit_breakers["sonos"] = app.state.sonos.breaker.snapshot()
    if any(b.get("state") == "open" for b in circuit_breakers.values()):
        status = "degraded"

    # ML predictor health. Each predictor exposes its own health() with
    # status ∈ {"healthy", "shadow", "idle", "unhealthy"}. "shadow" and
    # "idle" never trigger degraded — shadow is intentional non-voting
    # (behavioral pre-promotion, rule_engine data-gated), idle is the
    # boot transient before the first inference. Only "unhealthy"
    # propagates: model failed to load, or N consecutive failures.
    ml: dict = {}
    for attr, display_name in _ML_PREDICTORS:
        predictor = getattr(app.state, attr, None)
        if predictor is None or not hasattr(predictor, "health"):
            continue
        try:
            ml[display_name] = predictor.health()
        except Exception as exc:
            # A health() that itself throws is itself a failure surface.
            ml[display_name] = {
                "status": "unhealthy",
                "model_loaded": False,
                "last_predict_at": None,
                "consecutive_failures": 0,
                "last_failure": f"health() raised: {exc}"[:200],
            }
    if any(p.get("status") == "unhealthy" for p in ml.values()):
        status = "degraded"

    # Per-source data-validity ("sanity") verdicts. The heartbeat surface
    # above says a source is *ticking*; this says whether the data it produces
    # is *trustworthy*. A live-but-garbage source (the 2026-05-27 camera lux
    # pin held for five days while the heartbeat stayed green) degrades
    # /health here and gates ML learning via the quarantine path in
    # ml_logger. Liveness + breaker state for Hue/Sonos already live in
    # `tasks` / `circuit_breakers`; this block is the sanity layer.
    sources: list[dict] = []
    sources_untrusted: list[str] = []
    if hasattr(app.state, "source_trust"):
        sources = app.state.source_trust.snapshot()
        sources_untrusted = [s["name"] for s in sources if not s["trusted"]]
        if sources_untrusted:
            status = "degraded"

    scheduler_tasks: list[dict] = []
    if hasattr(app.state, "scheduler"):
        scheduler_tasks = app.state.scheduler.get_tasks()

    # Engine weather/lux state — lets the stateful Check K verifier read the
    # last weather class + settled lux multiplier directly, instead of
    # recomputing statelessly and false-flagging a correct within-epsilon
    # steady state (GH #67). Purely informational — never flips `status`.
    automation_block: dict = {}
    _automation = getattr(app.state, "automation", None)
    if _automation is not None:
        automation_block = {
            "current_mode": _automation.current_mode,
            "last_weather_class": _automation.last_weather_class,
            "last_lux_multiplier": round(_automation.last_lux_multiplier, 4),
        }

    return {
        "status": status,
        "service": "Home Hub",
        "build_id": getattr(app.state, "build_id", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "devices": {
            "hue_bridge": hue_connected,
            "sonos": sonos_connected,
            "pihole": pihole_connected,
            "fauxmo": {
                "enabled": fauxmo_enabled,
                "connected": fauxmo_connected,
                "status": fauxmo_status,
            },
        },
        "websocket_clients": ws_count,
        "event_logger_drops": event_logger_drops,
        "event_logger_overflow": event_logger_overflow,
        "event_logger_queue_depth": event_logger_queue_depth,
        "tasks": tasks,
        "tasks_stale": tasks_stale,
        "scheduler_tasks": scheduler_tasks,
        "circuit_breakers": circuit_breakers,
        "ml": ml,
        "automation": automation_block,
        "sources": sources,
        "sources_untrusted": sources_untrusted,
        "details": details,
    }
