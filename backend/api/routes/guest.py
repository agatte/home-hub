"""
Guest endpoints — credentials and assets surfaced for the /guest landing
page and the home dashboard's GuestWifiWidget.
"""
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key
from backend.api.routes.scenes import (
    SCENE_PRESETS,
    _activate_effect_if_needed,
    _activate_per_light,
    _log_scene_activation,
)
from backend.config import settings

logger = logging.getLogger("home_hub.guest")

router = APIRouter(prefix="/api/guest", tags=["guest"])

# Curated scenes safelisted for guest activation. Map short guest-facing
# names → curated SCENE_PRESETS keys. Anything not in this map is rejected
# even if it's a valid scene — guests do not get the full scene browser.
GUEST_SCENE_WHITELIST: dict[str, str] = {
    "party":  "house_party",
    "neon":   "neon_tokyo",
    "sunset": "sunset_strip",
    "chill":  "candlelit",
}

# Global cooldown shared across all guests. Two visitors fighting over the
# lights still get rate-limited together; the goal is to prevent rapid
# strobing, not to track per-IP fairness.
GUEST_SCENE_COOLDOWN_SECONDS = 60
_last_guest_scene_at: float = 0.0


_WIFI_ESCAPE = str.maketrans({
    "\\": "\\\\",
    ";": "\\;",
    ",": "\\,",
    '"': '\\"',
    ":": "\\:",
})


def _wifi_uri(ssid: str, password: str, security: str) -> str:
    """Build the WIFI: URI per the de-facto QR spec.

    Special chars (`\\;,":`) must be escaped inside SSID/password fields.
    """
    return (
        f"WIFI:T:{security};"
        f"S:{ssid.translate(_WIFI_ESCAPE)};"
        f"P:{password.translate(_WIFI_ESCAPE)};"
        f"H:false;;"
    )


@router.get("/wifi")
async def get_guest_wifi() -> dict:
    """Return the guest WiFi QR payload + display fields.

    Returns `{configured: false}` if SSID/password aren't set, so the
    frontend can render a quiet "not configured" state instead of erroring.
    Password never leaves the LAN — same trust boundary as every other GET.
    """
    ssid = settings.GUEST_WIFI_SSID
    password = settings.GUEST_WIFI_PASSWORD
    security = settings.GUEST_WIFI_SECURITY or "WPA"

    if not ssid or not password:
        return {"status": "ok", "configured": False}

    return {
        "status": "ok",
        "configured": True,
        "ssid": ssid,
        "password": password,
        "security": security,
        "qr_payload": _wifi_uri(ssid, password, security),
    }


@router.post("/scene/{name}", dependencies=[Depends(require_api_key)])
async def activate_guest_scene(name: str, request: Request) -> dict:
    """Activate one of a small set of guest-safelisted curated scenes.

    Validates `name` against `GUEST_SCENE_WHITELIST`, enforces a global
    cooldown, applies the matching curated preset, and sets a manual
    override on the automation engine tagged source="guest" so the next
    automation tick doesn't immediately revert.

    Returns 400 for unknown names, 429 (with Retry-After) when the
    cooldown is still active, 503 when the Hue bridge is offline.
    """
    global _last_guest_scene_at

    if name not in GUEST_SCENE_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown guest scene '{name}'. Pick one of: "
                   f"{', '.join(sorted(GUEST_SCENE_WHITELIST))}",
        )

    now = time.monotonic()
    elapsed = now - _last_guest_scene_at
    if elapsed < GUEST_SCENE_COOLDOWN_SECONDS:
        retry_after = int(GUEST_SCENE_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Cooling down — try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    preset_id = GUEST_SCENE_WHITELIST[name]
    preset = SCENE_PRESETS[preset_id]

    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    hue_v2 = getattr(request.app.state, "hue_v2", None)
    ws_manager = request.app.state.ws_manager
    automation = getattr(request.app.state, "automation", None)

    # Apply lights, then any paired effect. Mirrors scenes.py:activate_scene
    # but without the require_api_key gate around scene_id (guests don't
    # get to pick arbitrary scene IDs — only the safelist).
    await _activate_per_light(hue, preset["lights"])
    await _activate_effect_if_needed(hue_v2, preset.get("effect"))

    await asyncio.sleep(0.3)
    light_states = await hue.get_all_lights()
    for light in light_states:
        await ws_manager.broadcast("light_update", light)

    # Tag the override so journalctl shows guest-driven mode flips
    # (per project_override_caller_telemetry memory). Map party → social,
    # everything else → relax — best-fit existing modes for the lighting
    # vibe each preset establishes.
    if automation:
        target_mode = "social" if name == "party" else "relax"
        await automation.set_manual_override(target_mode, source="guest")

    await _log_scene_activation(
        request, preset_id, preset.get("display_name"), "guest"
    )

    _last_guest_scene_at = now
    logger.info(
        "Guest activated scene '%s' (preset=%s) from %s",
        name, preset_id,
        request.client.host if request.client else "unknown",
    )

    return {
        "status": "ok",
        "scene": preset["display_name"],
        "cooldown_seconds": GUEST_SCENE_COOLDOWN_SECONDS,
    }
