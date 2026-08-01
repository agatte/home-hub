"""
Home Hub MCP Server — Claude Code integration.

Exposes the Home Hub REST API as MCP tools so Claude can verify changes
against the live system without manual testing. Requires the main Home Hub
server to be running at http://localhost:8000.

Usage:
    python -m backend.mcp_server

Registered in .mcp.json as the "home-hub" MCP server.
"""
import logging
import os
import re
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("HOME_HUB_URL", "http://localhost:8000")
# Optional. When the backend has API-key auth enabled (HOME_HUB_API_KEY
# set in its .env), every write goes through `require_api_key`. The MCP
# usually runs from the dev desktop, which is on the trusted-LAN list,
# so this isn't strictly needed there — but injecting it costs nothing
# and makes the MCP work from any machine the dev sets HOME_HUB_API_KEY on.
API_KEY = os.environ.get("HOME_HUB_API_KEY", "")
mcp = FastMCP("home-hub", instructions=f"Tools for inspecting and controlling the live Home Hub system. The main server must be running at {BASE_URL}.")


def _client() -> httpx.AsyncClient:
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    return httpx.AsyncClient(base_url=BASE_URL, timeout=10.0, headers=headers)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_health() -> dict:
    """Check system health — Hue bridge + Sonos connectivity and WebSocket client count."""
    async with _client() as c:
        r = await c.get("/health")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_weather() -> dict:
    """Get current weather conditions (temperature, description, humidity, wind)."""
    async with _client() as c:
        r = await c.get("/api/weather")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Pi-hole
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_pihole_stats() -> dict:
    """Get Pi-hole DNS stats — total queries, blocked percentage, blocklist size, active clients."""
    async with _client() as c:
        r = await c.get("/api/pihole/stats")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_plant_status() -> dict:
    """Get aggregated plant status (total, needs water, overdue, next watering)."""
    async with _client() as c:
        r = await c.get("/api/plants/status")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_lights() -> list[dict]:
    """Get the current state of all Hue lights (id, name, on, bri, hue, sat, reachable)."""
    async with _client() as c:
        r = await c.get("/api/lights")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def set_light(
    light_id: str,
    on: Optional[bool] = None,
    bri: Optional[int] = None,
    hue: Optional[int] = None,
    sat: Optional[int] = None,
) -> dict:
    """
    Set the state of a single Hue light.

    Args:
        light_id: Light ID ("1"–"5" — see LIGHT_IDS in light_state_calculator)
        on: True to turn on, False to turn off
        bri: Brightness 1-254
        hue: Color hue 0-65535
        sat: Saturation 0-254
    """
    state: dict[str, Any] = {}
    if on is not None:
        state["on"] = on
    if bri is not None:
        state["bri"] = bri
    if hue is not None:
        state["hue"] = hue
    if sat is not None:
        state["sat"] = sat

    async with _client() as c:
        r = await c.put(f"/api/lights/{light_id}", json=state)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_automation_status() -> dict:
    """Get the current automation state: active mode, source, manual override status."""
    async with _client() as c:
        r = await c.get("/api/automation/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_camera_snapshot(annotate: bool = True, source: str = "latitude") -> Any:
    """Capture one JPEG frame from either the Latitude or the desktop webcam.

    Args:
        annotate: (Latitude only) overlay MediaPipe face box + lux readout.
        source: "latitude" (default) — capture from the Latitude camera in
            real time (living-room-mounted since 2026-05-27, framing the
            couch). "desktop" — request a fresh frame from the desktop
            pc_agent (used to diagnose the dual-camera arbitration).

    Latitude path: requires `camera_enabled`. Frames are never written to disk.
    Desktop path: marks a snapshot pending, polls /latest for up to 15s while
    the desktop pc_agent grabs and uploads the next frame from its 2s capture
    loop. Saved to `data/diagnostics/desktop_snapshot_<ts>.jpg` on the Latitude
    (gitignored — investigation artifact).

    Returns the JPEG to the agent, or a plain error string on failure.
    """
    from fastmcp.utilities.types import Image

    if source == "latitude":
        async with _client() as c:
            r = await c.get(f"/api/camera/snapshot?annotate={'true' if annotate else 'false'}")
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                return Image(data=r.content, format="jpeg")
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            return f"snapshot unavailable (HTTP {r.status_code}): {detail}"

    if source == "desktop":
        import asyncio

        async with _client() as c:
            # Capture the current latest_ts so we know when a fresh upload arrives.
            head = await c.get("/api/camera/desktop/snapshot/latest")
            prior_ts = head.headers.get("X-Snapshot-Ts") if head.status_code == 200 else None

            req = await c.post("/api/camera/desktop/snapshot/request")
            if req.status_code >= 400:
                try:
                    detail = req.json().get("detail", req.text)
                except Exception:
                    detail = req.text
                return f"desktop snapshot request failed (HTTP {req.status_code}): {detail}"

            # Poll /latest for up to 15s waiting for a new ts. Desktop capture
            # cadence is 2s, plus encode + upload — typical arrival 2–5s.
            deadline = 15.0
            interval = 0.75
            elapsed = 0.0
            while elapsed < deadline:
                await asyncio.sleep(interval)
                elapsed += interval
                latest = await c.get("/api/camera/desktop/snapshot/latest")
                if latest.status_code != 200:
                    continue
                ts = latest.headers.get("X-Snapshot-Ts")
                if ts and ts != prior_ts:
                    return Image(data=latest.content, format="jpeg")
            return (
                "desktop snapshot timed out after 15s — is the pc_agent supervisor "
                "running on 192.168.86.30 with desktop_presence_enabled=true?"
            )

    return f"unknown source '{source}' — expected 'latitude' or 'desktop'"


@mcp.tool()
async def set_mode(mode: str) -> dict:
    """
    Manually override the automation mode.

    Args:
        mode: One of gaming, watching, working, social, relax, cooking, idle, away, sleeping.
              Use "auto" to clear the override and return to time-based automation.
    """
    async with _client() as c:
        r = await c.post("/api/automation/override", json={"mode": mode})
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_schedule() -> dict:
    """Get the current time-based lighting schedule (weekday and weekend periods)."""
    async with _client() as c:
        r = await c.get("/api/automation/schedule")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_mode_brightness() -> dict:
    """Get per-mode brightness multipliers (0.3-1.5 range per mode)."""
    async with _client() as c:
        r = await c.get("/api/automation/mode-brightness")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Screen sync
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_screen_sync_status() -> dict:
    """
    Get current screen sync state.

    Returns whether the mode gate is open (current mode is in
    gaming/watching), when the last color was applied, what source
    posted it, and whether the laptop loopback is running.
    """
    async with _client() as c:
        r = await c.get("/api/automation/screen-sync/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def apply_screen_color(r: int, g: int, b: int) -> dict:
    """
    Manually post an RGB color to the screen sync receiver.

    Useful for testing — bypasses the desktop pc_agent. Will only update the
    bedroom lamp if the current automation mode is gaming or watching.

    Args:
        r: Red channel 0-255
        g: Green channel 0-255
        b: Blue channel 0-255
    """
    async with _client() as c:
        resp = await c.post(
            "/api/automation/screen-color",
            json={"r": r, "g": g, "b": b, "source": "mcp"},
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def set_laptop_screen_sync(enabled: bool) -> dict:
    """
    Toggle the in-process laptop screen capture loopback.

    This is the TV-on-laptop escape hatch. Default off; only flip on when
    the laptop is plugged into a TV and you want lights to follow it.

    Args:
        enabled: True to start the loopback, False to stop.
    """
    async with _client() as c:
        resp = await c.put(
            "/api/automation/screen-sync/laptop-enabled",
            json={"enabled": enabled},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Scenes & Effects
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_scenes() -> dict:
    """List all available scenes (built-in presets + native Hue bridge scenes)."""
    async with _client() as c:
        r = await c.get("/api/scenes")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def activate_scene(scene_id: str) -> dict:
    """
    Activate a scene by ID or preset name.

    Args:
        scene_id: Preset name (e.g. "movie_night", "relax") or Hue bridge scene UUID
    """
    async with _client() as c:
        r = await c.post(f"/api/scenes/{scene_id}/activate")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_effects() -> dict:
    """List available dynamic light effects (candlelight, fireplace, sparkle, etc.)."""
    async with _client() as c:
        r = await c.get("/api/scenes/effects")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def activate_effect(effect_name: str) -> dict:
    """
    Apply a dynamic effect to all lights.

    Args:
        effect_name: One of candle, fire, sparkle, prism, glisten, opal
    """
    async with _client() as c:
        r = await c.post(f"/api/scenes/effects/{effect_name}")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Sonos
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_sonos_status() -> dict:
    """Get current Sonos playback state (track, artist, volume, play state)."""
    async with _client() as c:
        r = await c.get("/api/sonos/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_play() -> dict:
    """Resume Sonos playback."""
    async with _client() as c:
        r = await c.post("/api/sonos/play")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_pause() -> dict:
    """Pause Sonos playback."""
    async with _client() as c:
        r = await c.post("/api/sonos/pause")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def sonos_volume(volume: int) -> dict:
    """
    Set Sonos volume.

    Args:
        volume: Volume level 0-100
    """
    async with _client() as c:
        r = await c.post("/api/sonos/volume", json={"volume": volume})
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_sonos_favorites() -> dict:
    """List all Sonos favorites and playlists."""
    async with _client() as c:
        r = await c.get("/api/sonos/favorites")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_mode_playlists() -> dict:
    """Get all mode-to-playlist mappings and available Sonos favorites."""
    async with _client() as c:
        r = await c.get("/api/music/mode-playlists")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Event summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_event_summary(days: int = 7) -> dict:
    """
    Summarize behavioral events over the last N days.

    Returns mode transition counts, most-adjusted lights, and most-played
    Sonos favorites. Useful for understanding usage patterns and debugging.

    Hits the live backend at HOME_HUB_URL — i.e. queries production data,
    not a stale local dev DB.

    Args:
        days: Number of days to look back (default 7).
    """
    async with _client() as c:
        r = await c.get("/api/debug/event-summary", params={"days": days})
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Routines
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_routines() -> dict:
    """Get all routine configs (morning routine, evening wind-down)."""
    async with _client() as c:
        r = await c.get("/api/routines")
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Database (read-only debug queries)
# ---------------------------------------------------------------------------


_QUERY_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_QUERY_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _is_read_only_sql(sql: str) -> bool:
    """Match the backend's debug.py validator: SELECT or WITH only.

    Strips line + block comments so a query that legitimately starts
    with a comment isn't rejected. The backend has its own copy of
    this check plus a read-only DB connection — this is just so we
    fail with a clear ValueError before the network round-trip.
    """
    if not sql or not sql.strip():
        return False
    stripped = _QUERY_BLOCK_COMMENT_RE.sub(" ", sql)
    stripped = _QUERY_LINE_COMMENT_RE.sub(" ", stripped).strip()
    if not stripped:
        return False
    return stripped.split(maxsplit=1)[0].upper() in {"SELECT", "WITH"}


@mcp.tool()
async def query_db(sql: str) -> list[dict]:
    """
    Run a read-only SQL query against the Home Hub SQLite database.
    Only SELECT (or WITH ... SELECT) statements are permitted.

    Hits the live backend at HOME_HUB_URL — i.e. queries production data,
    not a stale local dev DB. The backend opens the DB read-only, so even
    if a write somehow slipped past the validator the engine would refuse
    it. Results are capped at 1000 rows; the caller can re-query with a
    tighter WHERE / LIMIT if needed.

    Hot event-table schemas (column names matter — guessing produces
    OperationalError noise in Sentry):

      activity_events       id, timestamp, mode, previous_mode, source,
                            duration_seconds, zone, posture, audio_class, lux
      light_adjustments     id, timestamp, light_id, light_name,
                            bri_before, bri_after, hue_before, hue_after,
                            sat_before, sat_after, ct_before, ct_after,
                            mode_at_time, trigger
                            (NO on/off column — on/off lives implicit in bri)
      sonos_playback_events id, timestamp, event_type, favorite_title,
                            mode_at_time, volume, triggered_by, weather_class
      scene_activations     id, timestamp, scene_id, scene_name, source,
                            mode_at_time
      ml_decisions          id, timestamp, predicted_mode, actual_mode,
                            applied, confidence, decision_source, factors (JSON),
                            quarantined (0/1 — rows logged while the source was
                            untrusted; kept for forensics, excluded from training)
      remediation_log       id, timestamp, action, source, tier, result,
                            diagnosis_ref, params (JSON), detail, reverted
      ml_metrics            id, date, metric_name, value, extra (JSON)
                            (date is a Date, not DateTime — no time component)
      learned_rules         id, day_of_week, hour, predicted_mode, confidence,
                            sample_count, enabled, created_at, updated_at

    Timestamps are stored as SPACE-separated UTC -- ``'YYYY-MM-DD HH:MM:SS'``,
    NOT ISO-with-``T``. Comparing a column against a ``'...T...'`` literal
    silently mis-sorts (space 0x20 < 'T' 0x54) and returns wrong/empty rows --
    filter with space-format literals (``timestamp >= '2026-05-29 23:30:00'``)
    or ``datetime(timestamp,'localtime')`` for local-time windows. (None of this
    applies to ml_metrics.date, which is a bare Date.) ``light_adjustments.trigger``
    values: "ws" / "rest" / "scene" / "automation" / "all_lights" /
    "transit" / "celebration:<key>". Full schemas in backend/models.py.

    Args:
        sql: A SELECT query, e.g. "SELECT * FROM mode_playlists"

    Returns:
        List of rows as dicts.

    Raises:
        ValueError: If the query is not a read query.
    """
    if not _is_read_only_sql(sql):
        raise ValueError(
            "Only SELECT (or WITH ... SELECT) queries are permitted via this tool."
        )

    async with _client() as c:
        r = await c.get("/api/debug/query", params={"sql": sql})
        r.raise_for_status()
        return r.json()["result"]


# ---------------------------------------------------------------------------
# Live state snapshot — one JSON blob with everything Claude needs
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_live_state() -> dict:
    """
    Return a single JSON snapshot of every signal that shapes lighting behavior.

    Consolidates: automation mode + override + time period, per-light state
    (bri/hue/sat/ct/colormode/reachable), screen-sync status, camera zone /
    posture / lux, weather, brightness multipliers, health.

    Prefer this over calling several smaller tools when you need to reason
    about "what is the system doing right now" — one round-trip, full picture.
    Use the individual tools only when you already know the specific slice
    you need.

    Returns a flat dict with a ``timestamp`` field (UTC ISO8601) and a
    nested dict per subsystem. Missing subsystems (e.g. camera disabled)
    are included as ``null`` so keys are stable across calls.
    """
    import asyncio
    from datetime import datetime, timezone

    async def _safe_get(c: httpx.AsyncClient, path: str) -> Any:
        """Fetch and return JSON; on any error, return {'error': str}."""
        try:
            r = await c.get(path)
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    async with _client() as c:
        # All these endpoints are read-only, independent — fan out.
        results = await asyncio.gather(
            _safe_get(c, "/health"),
            _safe_get(c, "/api/automation/status"),
            _safe_get(c, "/api/lights"),
            _safe_get(c, "/api/automation/screen-sync/status"),
            _safe_get(c, "/api/camera/status"),
            _safe_get(c, "/api/weather"),
            _safe_get(c, "/api/automation/mode-brightness"),
            _safe_get(c, "/api/automation/watching-posture"),
        )
    health, automation, lights, screen_sync, camera, weather, bri_mult, posture_cfg = results

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health": health,
        "automation": automation,
        "lights": lights,
        "screen_sync": screen_sync,
        "camera": camera,
        "weather": weather,
        "brightness_multipliers": bri_mult,
        "watching_posture_config": posture_cfg,
    }


# ---------------------------------------------------------------------------
# State history — consolidated timeline from event tables
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_state_history(minutes: int = 30) -> dict:
    """
    Return a timeline of state changes over the last N minutes.

    Pulls from the event tables (activity_events, light_adjustments,
    scene_activations, sonos_playback_events) and returns one merged view
    sorted by timestamp descending (most recent first).

    Useful for "what changed recently" debugging: "why did the mode flip
    at 7pm?", "which light got dimmed?", "did a scene activate during
    watching?". Pairs with get_live_state() — snapshot + timeline = full
    debugging context.

    Args:
        minutes: Lookback window in minutes (default 30, max 1440 = 24h).

    Returns:
        dict with window_minutes, cutoff_utc, and four event lists:
        mode_transitions, light_adjustments, scene_activations, sonos_events.
    """
    minutes = max(1, min(1440, int(minutes)))
    # Use datetime('now', '-N minutes') in SQLite — server timestamps are UTC.
    cutoff_clause = f"timestamp >= datetime('now', '-{minutes} minutes')"

    async def _select(c: httpx.AsyncClient, sql: str) -> list[dict]:
        try:
            r = await c.get("/api/debug/query", params={"sql": sql})
            if r.status_code == 200:
                return r.json().get("result", [])
            return [{"error": f"HTTP {r.status_code}", "detail": r.text[:200]}]
        except Exception as e:
            return [{"error": str(e)}]

    import asyncio

    async with _client() as c:
        modes, lights, scenes, sonos_evts = await asyncio.gather(
            _select(
                c,
                f"SELECT timestamp, mode, previous_mode, source, duration_seconds "
                f"FROM activity_events WHERE {cutoff_clause} "
                f"ORDER BY timestamp DESC LIMIT 200"
            ),
            _select(
                c,
                f"SELECT timestamp, light_id, light_name, bri_before, bri_after, "
                f"hue_before, hue_after, sat_before, sat_after, ct_before, ct_after, "
                f"mode_at_time, trigger "
                f"FROM light_adjustments WHERE {cutoff_clause} "
                f"ORDER BY timestamp DESC LIMIT 500"
            ),
            _select(
                c,
                f"SELECT timestamp, scene_id, scene_name, source, mode_at_time "
                f"FROM scene_activations WHERE {cutoff_clause} "
                f"ORDER BY timestamp DESC LIMIT 100"
            ),
            _select(
                c,
                f"SELECT timestamp, event_type, favorite_title, mode_at_time, "
                f"volume, triggered_by "
                f"FROM sonos_playback_events WHERE {cutoff_clause} "
                f"ORDER BY timestamp DESC LIMIT 100"
            ),
        )

    return {
        "window_minutes": minutes,
        "mode_transitions": modes,
        "light_adjustments": lights,
        "scene_activations": scenes,
        "sonos_events": sonos_evts,
    }


# ---------------------------------------------------------------------------
# Bounded auto-remediation — the only MCP write into the remediation subsystem
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_remediation_status() -> dict:
    """
    Read the source-trust remediation subsystem state.

    Returns the kill-switch flags (enabled / autonomous / mode), the action
    policy map (action → auto|propose tier), the rolling 24h auto-execution
    count against the daily ceiling, and the recent audit-log tail. Read this
    BEFORE calling ``remediate`` so you know whether you're in autonomous or
    propose-only mode and which actions are even permitted.
    """
    async with _client() as c:
        r = await c.get("/api/remediation/status")
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def remediate(
    action: str,
    source: str | None = None,
    reason: str = "",
    diagnosis_ref: str | None = None,
    params: dict | None = None,
) -> dict:
    """
    Execute (or propose) a single whitelisted remediation action.

    This is the ONLY mutate path into the remediation subsystem and is
    deliberately narrow — it can do nothing the backend's ACTION_POLICY
    doesn't allow. The backend decides whether to actually run the action
    (autonomous + auto-tier + within rate limits) or merely record it as a
    proposal; either way it writes a remediation_log row and notifies. You
    cannot bypass the kill-switch or the rate ceiling from here.

    Whitelisted actions (confirm against get_remediation_status().policy):
      - recover_camera            — respawn the camera service (frees a stuck
                                    V4L2 handle).
      - recalibrate_camera_lux    — re-run lux calibration. Only when the room
                                    is at representative brightness.
      - set_source_trust          — params {"source": str, "trusted": bool,
                                    "reason"?: str}. trusted=true clears a
                                    quarantine (predicate resumes); false marks
                                    the source untrusted.
      - clear_stuck_override      — clear a wedged manual mode override.
      - clear_stuck_dnd           — clear a stuck Do-Not-Disturb.

    Args:
        action: One of the whitelisted action names above.
        source: The troubled source the action targets (e.g. "camera").
        reason: Short human-readable why — recorded in the audit row.
        diagnosis_ref: Pointer to the digest warn / diagnosis that triggered
            this (e.g. "2026-06-01#check-O").
        params: Action-specific parameters (see set_source_trust).

    Returns:
        The decision dict: {status, action, tier, result (executed|proposed|
        skipped|error), detail, log_id}.
    """
    body: dict[str, Any] = {"action": action, "reason": reason}
    if source is not None:
        body["source"] = source
    if diagnosis_ref is not None:
        body["diagnosis_ref"] = diagnosis_ref
    if params is not None:
        body["params"] = params
    async with _client() as c:
        r = await c.post("/api/remediation/action", json=body)
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    mcp.run()
