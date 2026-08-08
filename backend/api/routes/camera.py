"""Camera presence detection endpoints — status, enable/disable, calibrate."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from backend.api._guards import clamp_client_timestamp
from backend.api.auth import require_api_key, require_api_key_strict
from backend.config import DATA_DIR
from backend.services.presence_fusion import KNOWN_SOURCES, PresenceReading

logger = logging.getLogger("home_hub.camera")

router = APIRouter(prefix="/api/camera", tags=["camera"])

# Desktop snapshot diagnostic — pending-flag TTL. The pc_agent polls
# /desktop/snapshot/pending every ~2s (capture cadence). If no upload
# arrives within this window we assume the desktop is offline or the
# webcam is shuttered, clear the flag, and stop holding the request.
DESKTOP_SNAPSHOT_TTL_S = 60.0
DESKTOP_SNAPSHOT_DIR = DATA_DIR / "diagnostics"
# Hard cap on uploaded JPEG size. A typical 640×480 JPEG at quality 85 is
# ~30–80 KB; 2 MB leaves headroom for higher-resolution future captures
# without exposing the route to an OOM-by-upload attack. LAN-only path,
# but defense-in-depth.
DESKTOP_SNAPSHOT_MAX_BYTES = 2_000_000


class CameraToggle(BaseModel):
    """Request body for enabling/disabling the camera."""

    enabled: bool


class PresenceObservation(BaseModel):
    """One presence reading from an off-host source (currently desktop pc_agent).

    Fields mirror ``PresenceReading`` — the route builds the dataclass
    from this body and hands it to ``app.state.presence``.
    """

    source: Literal["desktop", "latitude_streaming"] = "desktop"
    captured_at: Optional[datetime] = None
    face_present: Optional[bool] = None
    face_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    detection_source: Optional[Literal["face", "pose"]] = None
    zone: Optional[Literal["desk", "bed", "couch"]] = None
    posture: Optional[Literal["upright", "reclined", "slouched"]] = None
    posture_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pose_visible_landmarks: Optional[int] = Field(default=None, ge=0)


class DesktopLuxReading(BaseModel):
    """One ambient-lux sample from the desktop pc_agent's bedroom webcam (D4).

    The agent flips to its calibrated fixed exposure, averages ``gray.mean()``
    over a few frames, restores auto-exposure, and POSTs the value here. Range
    is 0–255 (8-bit grayscale mean), matching CameraService's lux scale.
    """

    ambient_lux: float = Field(ge=0.0, le=255.0)
    captured_at: Optional[datetime] = None


class DesktopLuxCalibration(BaseModel):
    """Result of a desktop bedroom-lux calibration run (D4).

    Mirrors CameraService's lux calibration: the agent binary-searches
    exposure until ``gray.mean()`` hits ``target_lux`` under comfortable-bright
    bedroom light, then reports the settled fixed ``exposure`` + measured
    ``baseline_lux``. The agent pins ``exposure`` for every future sample.
    """

    exposure: float
    baseline_lux: float = Field(gt=0.0, le=255.0)
    target_lux: float = Field(default=100.0, gt=0.0, le=255.0)


def _current_multiplier(service) -> float:
    """Current lux multiplier for the UI readout (1.0 if uncalibrated / stale)."""
    from backend.services.automation_engine import LUX_STALE_SECONDS, lux_to_multiplier

    ema = getattr(service, "ema_lux", None)
    if ema is None:
        return 1.0
    last = getattr(service, "last_lux_update", None)
    if last is None:
        return 1.0
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age > LUX_STALE_SECONDS:
        return 1.0
    baseline = getattr(service, "baseline_lux", None)
    return lux_to_multiplier(float(ema), float(baseline) if baseline else 90.0)


@router.get("/status", dependencies=[Depends(require_api_key)])
async def get_status(request: Request) -> dict:
    """Return camera service status (includes lux calibration + current multiplier).

    Gated even though it's a GET — the response leaks zone, posture, lux,
    and the calibration baseline, all of which are useful reconnaissance
    for a public-tunnel attacker. LAN dashboards keep working via the
    RFC1918 bypass in `require_api_key`.
    """
    service = getattr(request.app.state, "camera_service", None)
    presence = getattr(request.app.state, "presence", None)
    presence_block = presence.get_status() if presence is not None else None

    if service is None:
        return {
            "status": "ok",
            "enabled": False,
            "available": False,
            "presence": presence_block,
        }
    return {
        "status": "ok",
        **service.get_status(),
        "current_multiplier": _current_multiplier(service),
        "presence": presence_block,
    }


@router.post("/observation", dependencies=[Depends(require_api_key)])
async def post_observation(
    payload: PresenceObservation, request: Request,
) -> dict:
    """Ingest a presence reading from an off-host source (desktop pc_agent).

    The desktop emotion_capture POSTs here after each FaceLandmarker tick
    when ``desktop_presence_enabled`` is on. The Latitude camera reaches
    PresenceFusion directly via in-process callback; this endpoint is
    the network boundary for everything else.

    LAN-bypass at ``auth.py:90`` covers the 192.168.86.30 desktop. The
    ``require_api_key`` dependency stays for shape consistency and for
    future tunnel-origin sources (e.g. a phone-camera companion app).
    """
    if payload.source not in KNOWN_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"unknown source: {payload.source}",
        )

    presence = getattr(request.app.state, "presence", None)
    if presence is None:
        # Service hasn't started (early-boot race, or unit-test). Don't
        # error — silent drops here are safer than 503s that retry-storm
        # an agent during startup. Logged for observability.
        logger.debug(
            "presence observation dropped — PresenceFusion not initialized"
        )
        return {"status": "ok", "detail": "presence service unavailable"}

    reading = PresenceReading(
        source=payload.source,
        # Server clock wins on forward skew — a future-stamped reading
        # would wedge PresenceFusion's out-of-order guard (see
        # clamp_client_timestamp docstring).
        captured_at=clamp_client_timestamp(
            payload.captured_at, source=f"{payload.source}:observation",
        ),
        face_present=payload.face_present,
        face_confidence=payload.face_confidence,
        detection_source=payload.detection_source,
        zone=payload.zone,
        posture=payload.posture,
        posture_confidence=payload.posture_confidence,
        pose_visible_landmarks=payload.pose_visible_landmarks,
    )
    presence.on_observation(reading)
    return {"status": "ok"}


@router.get("/snapshot", dependencies=[Depends(require_api_key_strict)])
async def get_snapshot(request: Request, annotate: bool = False) -> Response:
    """Return a single JPEG frame from the webcam.

    Opt-in: requires ``camera_enabled``. The frame is captured through the
    running camera service (shares the existing ``cv2.VideoCapture`` handle)
    and is never written to disk or cached server-side. When ``annotate`` is
    true, the response overlays the face bounding box and the current lux +
    multiplier readout for framing / calibration verification.

    **Auth-gated** (defense in depth — the tunnel allowlist already
    excludes this path, but the gate ensures any future remote-app path
    that bypasses the allowlist still can't pull JPEGs of the apartment).
    """
    service = getattr(request.app.state, "camera_service", None)
    if service is None or not service.enabled:
        raise HTTPException(status_code=409, detail="camera is not enabled")
    if getattr(service, "_paused", False):
        raise HTTPException(status_code=503, detail="camera paused (sleeping mode)")
    jpeg = await service.capture_snapshot(annotate=annotate)
    if jpeg is None:
        raise HTTPException(status_code=503, detail="capture failed")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/calibrate", dependencies=[Depends(require_api_key)])
async def calibrate_exposure(request: Request) -> dict:
    """Calibrate fixed exposure so gray.mean() ≈ 100 under current room light.

    Must be called with the camera enabled and during lighting representative
    of your typical usage (normal evening room light works well). Binary-
    searches ``CAP_PROP_EXPOSURE`` until the calibration target is hit, then
    persists the result to ``app_settings`` so future restarts re-apply it.
    """
    service = getattr(request.app.state, "camera_service", None)
    if service is None or not service.enabled:
        raise HTTPException(status_code=409, detail="camera is not enabled")
    result = await service.calibrate_exposure()
    if result.get("status") != "ok":
        raise HTTPException(status_code=500, detail=result.get("detail", "calibration failed"))
    return result


@router.post("/enable", dependencies=[Depends(require_api_key)])
async def toggle_camera(body: CameraToggle, request: Request) -> dict:
    """Enable or disable camera presence detection.

    When enabling: initializes the camera service if not already running.
    When disabling: stops the camera and releases resources.
    """
    from backend.api.routes.routines import save_setting

    await save_setting("camera_enabled", {"enabled": body.enabled})
    request.app.state.latitude_camera_configured = body.enabled

    if body.enabled:
        try:
            from backend.services.camera_service import spawn_camera_service
            result = await spawn_camera_service(request.app, reason="api_toggle")
        except ImportError as exc:
            logger.warning("Cannot enable camera — missing dependency: %s", exc)
            return {
                "status": "error",
                "detail": f"Missing dependency: {exc}",
            }
        return result

    # Disable path. Tear down any existing service; tolerate a half-dead
    # one (close() is idempotent and releases V4L2 even when _enabled is
    # already False from a crashed poll_loop).
    service = getattr(request.app.state, "camera_service", None)
    if service is not None:
        try:
            await service.close()
        except Exception:
            logger.exception("Camera close() raised during disable — continuing")
        request.app.state.camera_service = None
        automation = request.app.state.automation
        automation.set_camera_service(None)
        logger.info("Camera service stopped via API toggle")
    return {"status": "ok", "detail": "Camera disabled"}


# spawn_camera_service lives in backend.services.camera_service so the
# watchdog loop (also in that module) can share it without creating an
# api → service → api import cycle. The route imports it lazily inside
# the handler above.


# ---------------------------------------------------------------------------
# Desktop snapshot diagnostic — request / poll / upload / fetch
# ---------------------------------------------------------------------------
#
# The desktop pc_agent (emotion_capture.py) holds the only handle to the
# desktop webcam. To compare what the two cameras see for the dual-camera
# arbitration design, we need to pull a single JPEG from the desktop on
# demand. This is a four-route pull-then-push: backend marks a snapshot
# pending, desktop polls the flag on its next capture tick, encodes the
# current frame, POSTs it back. Latency is bounded by the 2s capture
# cadence + http round trip.
#
# Snapshots land in data/diagnostics/desktop_snapshot_{ts}.jpg. The
# directory is gitignored along with the rest of data/. These are
# investigation artifacts — not part of normal operation. There is no
# automatic cleanup; manual prune after each diagnostic session.


def _snapshot_state(app: Any) -> dict:
    """Lazily initialize app.state.desktop_snapshot.

    Holds: ``pending`` (bool), ``requested_at`` (datetime|None),
    ``latest_path`` (Path|None), ``latest_ts`` (datetime|None).
    """
    state = getattr(app.state, "desktop_snapshot", None)
    if state is None:
        state = {
            "pending": False,
            "requested_at": None,
            "latest_path": None,
            "latest_ts": None,
        }
        app.state.desktop_snapshot = state
    return state


def _expire_pending_if_stale(state: dict) -> None:
    """Clear the pending flag once it's past the TTL (desktop is offline)."""
    if not state["pending"] or state["requested_at"] is None:
        return
    age = (datetime.now(timezone.utc) - state["requested_at"]).total_seconds()
    if age > DESKTOP_SNAPSHOT_TTL_S:
        logger.info(
            "Desktop snapshot request expired after %.0fs without upload", age,
        )
        state["pending"] = False
        state["requested_at"] = None


@router.post("/desktop/snapshot/request", dependencies=[Depends(require_api_key)])
async def request_desktop_snapshot(request: Request) -> dict:
    """Mark a desktop-camera snapshot as pending.

    The desktop pc_agent will see the flag on its next capture tick
    (within ~2s) and POST the frame back to /desktop/snapshot/upload.
    Use /desktop/snapshot/latest to retrieve the result.

    Idempotent — multiple calls before an upload arrives don't queue
    extra captures; they just refresh ``requested_at`` so the TTL clock
    starts over.
    """
    state = _snapshot_state(request.app)
    now = datetime.now(timezone.utc)
    state["pending"] = True
    state["requested_at"] = now
    logger.info("Desktop snapshot requested (ttl=%ds)", int(DESKTOP_SNAPSHOT_TTL_S))
    return {
        "status": "ok",
        "pending": True,
        "requested_at": now.isoformat(),
        "ttl_seconds": DESKTOP_SNAPSHOT_TTL_S,
    }


@router.get("/desktop/snapshot/pending", dependencies=[Depends(require_api_key)])
async def get_desktop_snapshot_pending(request: Request) -> dict:
    """Polled by the desktop pc_agent to check whether to capture.

    Auth-gated; the desktop already has API-key bypass via RFC1918. The
    response is intentionally tiny — this is called every 2s during
    normal capture, and the desktop short-circuits on ``pending=False``.
    """
    state = _snapshot_state(request.app)
    _expire_pending_if_stale(state)
    return {
        "pending": state["pending"],
        "requested_at": (
            state["requested_at"].isoformat()
            if state["requested_at"] is not None
            else None
        ),
    }


@router.post("/desktop/snapshot/upload", dependencies=[Depends(require_api_key)])
async def upload_desktop_snapshot(
    request: Request,
    image: UploadFile = File(...),
    captured_at: Optional[str] = Form(default=None),
    face_present: Optional[str] = Form(default=None),
    face_confidence: Optional[str] = Form(default=None),
) -> dict:
    """Receive a JPEG frame from the desktop pc_agent.

    Writes the image to ``data/diagnostics/desktop_snapshot_{ts}.jpg``
    and a sidecar ``.json`` with the matching presence reading. Clears
    the pending flag so the desktop stops capturing on subsequent polls.

    The form fields (captured_at / face_present / face_confidence) are
    optional strings so the desktop doesn't have to re-parse the
    PresenceReading shape — they're written verbatim to the sidecar.
    """
    state = _snapshot_state(request.app)
    if not state["pending"]:
        # Late upload after TTL expiry, or unsolicited POST. Still save
        # it — the diagnostic value isn't conditional on the flag still
        # being set — but log so a misbehaving agent is visible.
        logger.warning(
            "Desktop snapshot upload received with no pending request"
        )

    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"expected image/* content-type, got {image.content_type}",
        )

    # Early-reject oversized uploads — header-based check before we
    # allocate the bytes. Body is then bounded by the explicit cap below.
    declared_len = request.headers.get("content-length")
    if declared_len and declared_len.isdigit() and int(declared_len) > DESKTOP_SNAPSHOT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"snapshot exceeds {DESKTOP_SNAPSHOT_MAX_BYTES} byte cap",
        )

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image body")
    if len(data) > DESKTOP_SNAPSHOT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"snapshot exceeds {DESKTOP_SNAPSHOT_MAX_BYTES} byte cap",
        )

    DESKTOP_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    ts_compact = ts.strftime("%Y%m%dT%H%M%SZ")
    img_path = DESKTOP_SNAPSHOT_DIR / f"desktop_snapshot_{ts_compact}.jpg"
    sidecar_path = DESKTOP_SNAPSHOT_DIR / f"desktop_snapshot_{ts_compact}.json"

    img_path.write_bytes(data)
    sidecar = {
        "captured_at": captured_at,
        "face_present": face_present,
        "face_confidence": face_confidence,
        "uploaded_at": ts.isoformat(),
        "byte_size": len(data),
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    state["pending"] = False
    state["requested_at"] = None
    state["latest_path"] = img_path
    state["latest_ts"] = ts
    logger.info(
        "Desktop snapshot saved: %s (%d bytes)", img_path.name, len(data),
    )
    return {
        "status": "ok",
        "path": str(img_path),
        "ts": ts.isoformat(),
        "byte_size": len(data),
    }


@router.get("/desktop/snapshot/latest", dependencies=[Depends(require_api_key)])
async def get_desktop_snapshot_latest(request: Request) -> Response:
    """Return the most recently uploaded desktop snapshot."""
    state = _snapshot_state(request.app)
    latest: Optional[Path] = state.get("latest_path")
    if latest is None or not latest.exists():
        raise HTTPException(
            status_code=404,
            detail="no desktop snapshot uploaded yet — call /desktop/snapshot/request first",
        )
    headers = {"Cache-Control": "no-store"}
    if state.get("latest_ts") is not None:
        headers["X-Snapshot-Ts"] = state["latest_ts"].isoformat()
    return Response(
        content=latest.read_bytes(),
        media_type="image/jpeg",
        headers=headers,
    )


# ── Bedroom lux channel (D4) ────────────────────────────────────────────
# The desktop pc_agent's bedroom webcam reports its own ambient lux here so
# bedroom modes (gaming / working / watching) can adapt brightness against a
# room-correct baseline — the living-room Latitude camera can't see the
# bedroom. ``app.state.bedroom_lux`` is a ``LuxChannel`` wired in main.py.
# Part C is store-only: nothing consumes the channel yet (Part D does).


@router.post("/desktop/lux", dependencies=[Depends(require_api_key)])
async def post_desktop_lux(payload: DesktopLuxReading, request: Request) -> dict:
    """Ingest one ambient-lux sample from the desktop bedroom webcam.

    Best-effort like ``/observation``: if the channel isn't wired yet
    (early boot / unit test) we drop silently rather than 503 an agent that
    POSTs every ~25s. LAN-bypass in ``auth.py`` covers the desktop.
    """
    channel = getattr(request.app.state, "bedroom_lux", None)
    if channel is None:
        logger.debug("bedroom lux dropped — channel not initialized")
        return {"status": "ok", "detail": "bedroom lux channel unavailable"}
    channel.update(
        float(payload.ambient_lux),
        # Server clock wins on forward skew — LuxChannel's out-of-order
        # guard wedges on a future-stamped sample otherwise.
        captured_at=clamp_client_timestamp(
            payload.captured_at, source="desktop:lux",
        ),
    )
    return {"status": "ok"}


@router.get("/desktop/lux", dependencies=[Depends(require_api_key)])
async def get_desktop_lux(request: Request) -> dict:
    """Bedroom lux channel snapshot (ema / baseline / freshness).

    Gated like ``/status`` — the baseline + readings are reconnaissance.
    Used for shadow-logging the bedroom readings before Part D consumes them.
    """
    channel = getattr(request.app.state, "bedroom_lux", None)
    if channel is None:
        raise HTTPException(status_code=503, detail="bedroom lux channel not initialized")
    return {"status": "ok", **channel.status()}


@router.post("/desktop/lux/calibrate/request", dependencies=[Depends(require_api_key)])
async def request_desktop_lux_calibration(request: Request) -> dict:
    """Flag a bedroom-lux calibration for the desktop agent to run (D4 Part B).

    The desktop pc_agent polls ``/desktop/lux/calibrate/pending`` on its 30s
    settings cadence; when this flag is set it runs the exposure sweep (at
    comfortable-bright bedroom light) on its capture thread and POSTs the
    result to ``/desktop/lux/calibration``, which clears the flag. Persisted
    in ``app_settings`` so the request survives a backend restart.
    """
    from backend.api.routes.routines import save_setting

    await save_setting("desktop_lux_calibrate_requested", {"requested": True})
    logger.info("Bedroom lux calibration requested — agent will run on next poll")
    return {"status": "ok", "pending": True}


@router.get("/desktop/lux/calibrate/pending", dependencies=[Depends(require_api_key)])
async def get_desktop_lux_calibrate_pending(request: Request) -> dict:
    """Polled by the desktop agent — runs calibration when ``pending`` is true."""
    from backend.api.routes.routines import load_setting

    cfg = await load_setting("desktop_lux_calibrate_requested") or {}
    return {"pending": bool(cfg.get("requested"))}


@router.get("/desktop/lux/calibration", dependencies=[Depends(require_api_key)])
async def get_desktop_lux_calibration(request: Request) -> dict:
    """Return the persisted bedroom-lux calibration config (D4 Part A).

    The desktop agent loads ``exposure`` from here to pin its periodic lux
    samples, so a calibration survives an agent restart. Empty dict when the
    bedroom webcam hasn't been calibrated yet.
    """
    from backend.api.routes.routines import load_setting

    return await load_setting("desktop_lux_calibration_config") or {}


@router.post("/desktop/lux/calibration", dependencies=[Depends(require_api_key)])
async def post_desktop_lux_calibration(
    payload: DesktopLuxCalibration, request: Request,
) -> dict:
    """Persist a bedroom-lux calibration result + apply it to the live channel.

    Saves ``desktop_lux_calibration_config`` (the agent reloads ``exposure``
    to pin every future sample), sets the live channel's baseline so the
    multiplier is centered immediately, and clears the calibrate-request flag.
    """
    from backend.api.routes.routines import save_setting

    config = {
        "exposure": payload.exposure,
        "baseline_lux": payload.baseline_lux,
        "target_lux": payload.target_lux,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
    await save_setting("desktop_lux_calibration_config", config)
    # Clear the request flag (Part B sets it; harmless no-op until then).
    await save_setting("desktop_lux_calibrate_requested", {"requested": False})
    channel = getattr(request.app.state, "bedroom_lux", None)
    if channel is not None:
        channel.set_baseline(float(payload.baseline_lux))
    logger.info(
        "bedroom lux calibrated: exposure=%.2f baseline_lux=%.1f",
        payload.exposure, payload.baseline_lux,
    )
    return {"status": "ok", "config": config}
