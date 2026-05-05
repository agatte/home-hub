"""
Guest endpoints — credentials and assets surfaced for the /guest landing
page and the home dashboard's GuestWifiWidget.
"""
import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

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
# Curated specifically for "guest at a party" — vibrant, dynamic palettes,
# nothing workspace-bright or sleep-quiet. Display order in the UI matches
# insertion order (CPython dict ordering is stable).
GUEST_SCENE_WHITELIST: dict[str, str] = {
    "party":  "house_party",
    "neon":   "neon_tokyo",
    "miami":  "miami_vice",
    "arcade": "arcade",
    "aurora": "northern_lights",
    "sunset": "sunset_strip",
}

# Global cooldown shared across all guests. Two visitors fighting over the
# lights still get rate-limited together; the goal is to prevent rapid
# strobing, not to track per-IP fairness.
GUEST_SCENE_COOLDOWN_SECONDS = 15
_last_guest_scene_at: float = 0.0

# Music vibe nudge — guests pick a vibe (hype/singalong/throwback), backend
# resolves to a Sonos favorite title and plays it. Mapping is configurable
# via app_settings["guest_vibe_playlists"]; if the key is unset we fall back
# to GUEST_VIBE_DEFAULTS which targets the favorites Anthony actually has.
# `label` is the visitor-facing tile name (Bebas-display style).
GUEST_VIBE_LABELS: dict[str, str] = {
    "hype":       "Hype",
    "singalong":  "Sing-along",
    "throwback":  "Throwback",
}
GUEST_VIBE_DEFAULTS: dict[str, str] = {
    "hype":       "It's Lit!",
    "singalong":  "2000s Hits Essentials",
    "throwback":  "Replay-all-time",
}
GUEST_VIBE_SETTINGS_KEY = "guest_vibe_playlists"
GUEST_VIBE_COOLDOWN_SECONDS = 15
_last_guest_vibe_at: float = 0.0

# Wave 2 in-scene tuning. Effects are layered on top of the active scene
# via Hue v2 set_effect_all (all-lights). Mutually exclusive on the frontend
# (tap +Sparkle while +Candle is active → sparkle replaces). Cooldown is
# separate from scene/vibe — guests should be able to layer an effect right
# after picking a scene.
GUEST_OVERLAY_EFFECTS = {"candle", "sparkle"}
GUEST_EFFECT_COOLDOWN_SECONDS = 3
_last_guest_effect_at: float = 0.0

# Brightness rocker bumps every on-light by ±10% multiplicatively, clamped
# to the per-mode ceiling (254 × mode_brightness_config[current_mode]).
# 800ms throttle keeps a hammered + button from queueing 20 PUTs to the
# bridge. Min-step floor of 20 ensures perceptible change even at low bri
# where pure 10% rounds to 3-4 units (invisible against ambient light).
GUEST_BRIGHTNESS_STEP = 1.10
GUEST_BRIGHTNESS_MIN_STEP = 20
GUEST_BRIGHTNESS_COOLDOWN_SECONDS = 0.8
_last_guest_brightness_at: float = 0.0

# Toast TTS — guests submit a short text, system speaks it through Sonos
# with a sparkle lighting flourish. Trust-the-room v1: no profanity filter,
# no host-approval gate. Just a length cap + global cooldown. Volume is
# hardcoded above the typical music level so the toast carries over a
# loud room; revisit if it's too aggressive in quieter contexts.
GUEST_TOAST_COOLDOWN_SECONDS = 60
GUEST_TOAST_MAX_CHARS = 120
GUEST_TOAST_MAX_NAME_CHARS = 30
GUEST_TOAST_VOLUME = 25
_last_guest_toast_at: float = 0.0


class ToastRequest(BaseModel):
    """Guest-submitted toast payload — short message, optional name."""

    message: str = Field(min_length=1, max_length=GUEST_TOAST_MAX_CHARS)
    name: Optional[str] = Field(default=None, max_length=GUEST_TOAST_MAX_NAME_CHARS)


async def _resolve_vibe_mapping() -> dict[str, str]:
    """Load the current vibe→favorite-title mapping from app_settings,
    falling back to GUEST_VIBE_DEFAULTS for any missing key. The settings
    table value is just a flat dict; future settings UI can edit it.
    """
    # Late import: avoids a startup-time circular with the routines module
    # which itself imports from backend.api.routes (via __init__).
    from backend.api.routes.routines import load_setting
    stored = await load_setting(GUEST_VIBE_SETTINGS_KEY)
    return {name: stored.get(name, default)
            for name, default in GUEST_VIBE_DEFAULTS.items()}


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


@router.get("/scenes")
async def list_guest_scenes() -> dict:
    """Return the safelisted party scenes with per-light preset states.

    The frontend uses the per-light states to render a 4-dot color preview
    next to each scene name (via `lightStateToCSS` in
    `$lib/utils/lightColor.js`). No Python-side color math needed.
    """
    return {
        "scenes": [
            {
                "name": guest_name,
                "display_name": SCENE_PRESETS[preset_id]["display_name"],
                "lights": SCENE_PRESETS[preset_id]["lights"],
            }
            for guest_name, preset_id in GUEST_SCENE_WHITELIST.items()
            if preset_id in SCENE_PRESETS
        ]
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


@router.post("/scene/{name}/reset", dependencies=[Depends(require_api_key)])
async def reset_guest_scene(name: str, request: Request) -> dict:
    """Re-apply the baseline preset for an already-active guest scene.

    Skips the 15s scene cooldown — this isn't a new pick, it's a reset.
    Stops any v2 effect overlay the guest layered on top, then re-runs
    the same per-light + paired-effect flow as `/scene/{name}`.
    """
    if name not in GUEST_SCENE_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown guest scene '{name}'. Pick one of: "
                   f"{', '.join(sorted(GUEST_SCENE_WHITELIST))}",
        )

    preset_id = GUEST_SCENE_WHITELIST[name]
    preset = SCENE_PRESETS[preset_id]

    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    hue_v2 = getattr(request.app.state, "hue_v2", None)
    ws_manager = request.app.state.ws_manager

    # Stop overlay effect first — if the guest layered candle/sparkle on top
    # of the scene, reset means "back to baseline" which includes whatever
    # effect (if any) the preset itself specifies.
    if hue_v2:
        await hue_v2.stop_effect_all()
    await _activate_per_light(hue, preset["lights"])
    await _activate_effect_if_needed(hue_v2, preset.get("effect"))

    await asyncio.sleep(0.3)
    light_states = await hue.get_all_lights()
    for light in light_states:
        await ws_manager.broadcast("light_update", light)

    logger.info(
        "Guest reset scene '%s' from %s",
        name,
        request.client.host if request.client else "unknown",
    )
    return {"status": "ok", "scene": preset["display_name"]}


@router.get("/vibes")
async def list_guest_vibes() -> dict:
    """Return the guest music vibes with their current playlist mapping.

    The frontend renders one tile per vibe with the friendly label and a
    secondary line showing which Sonos favorite will play. Anthony can
    re-map any vibe by writing app_settings["guest_vibe_playlists"] —
    no UI for that yet, hand-edit the table.
    """
    mapping = await _resolve_vibe_mapping()
    return {
        "vibes": [
            {
                "name": name,
                "label": GUEST_VIBE_LABELS[name],
                "playlist_title": mapping[name],
            }
            for name in GUEST_VIBE_LABELS
        ]
    }


@router.post("/vibe/{name}", dependencies=[Depends(require_api_key)])
async def activate_guest_vibe(name: str, request: Request) -> dict:
    """Switch Sonos to the favorite mapped to this guest vibe.

    Validates `name` against GUEST_VIBE_LABELS, enforces a separate
    cooldown from the scene picker (lights and music are independent
    visitor controls), resolves the favorite title via _resolve_vibe_mapping,
    and calls SonosService.play_favorite. Sets a "social" manual override
    tagged source="guest" so the engine doesn't immediately roll the mode
    back to whatever was detected.

    Returns 400 for unknown names, 429 (with Retry-After) when the
    cooldown is still active, 502 if Sonos can't find the favorite, 503
    when Sonos isn't connected.
    """
    global _last_guest_vibe_at

    if name not in GUEST_VIBE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown guest vibe '{name}'. Pick one of: "
                   f"{', '.join(sorted(GUEST_VIBE_LABELS))}",
        )

    now = time.monotonic()
    elapsed = now - _last_guest_vibe_at
    if elapsed < GUEST_VIBE_COOLDOWN_SECONDS:
        retry_after = int(GUEST_VIBE_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Cooling down — try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    sonos = getattr(request.app.state, "sonos", None)
    if not sonos or not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")

    mapping = await _resolve_vibe_mapping()
    favorite_title = mapping[name]

    started = await sonos.play_favorite(favorite_title)
    if not started:
        raise HTTPException(
            status_code=502,
            detail=f"Couldn't start '{favorite_title}' — favorite missing or unplayable",
        )

    automation = getattr(request.app.state, "automation", None)
    if automation:
        await automation.set_manual_override("social", source="guest")

    _last_guest_vibe_at = now
    logger.info(
        "Guest activated vibe '%s' → favorite '%s' from %s",
        name, favorite_title,
        request.client.host if request.client else "unknown",
    )

    return {
        "status": "ok",
        "vibe": GUEST_VIBE_LABELS[name],
        "playlist": favorite_title,
        "cooldown_seconds": GUEST_VIBE_COOLDOWN_SECONDS,
    }


@router.post("/handback", dependencies=[Depends(require_api_key)])
async def guest_handback(request: Request) -> dict:
    """Clear any guest-set manual override and return to host's automation.

    No cooldown — pressing twice is a harmless no-op on an already-cleared
    override. Tagged source="guest_handback" so journalctl distinguishes
    "guest pressed Hand It Back" from "host pressed Auto on the kiosk"
    (which lands as source=`api:<LAN-IP>`).
    """
    automation = getattr(request.app.state, "automation", None)
    if not automation:
        raise HTTPException(
            status_code=503, detail="Automation engine not initialized"
        )
    await automation.clear_override(source="guest_handback")
    logger.info(
        "Guest handed control back from %s",
        request.client.host if request.client else "unknown",
    )
    return {"status": "ok"}


@router.post("/effect/{name}", dependencies=[Depends(require_api_key)])
async def activate_guest_effect(name: str, request: Request) -> dict:
    """Layer a v2 effect overlay on the active scene, or stop it.

    `name` ∈ {candle, sparkle, stop}. All-lights only (per the v2 service
    today). Mutual exclusivity is enforced client-side: tapping the active
    chip again sends 'stop'; switching effects sends the new name (which
    replaces).
    """
    global _last_guest_effect_at

    if name != "stop" and name not in GUEST_OVERLAY_EFFECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown overlay effect '{name}'. Pick one of: "
                   f"{', '.join(sorted(GUEST_OVERLAY_EFFECTS))} or 'stop'",
        )

    now = time.monotonic()
    elapsed = now - _last_guest_effect_at
    if elapsed < GUEST_EFFECT_COOLDOWN_SECONDS:
        retry_after = int(GUEST_EFFECT_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Cooling down — try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    hue_v2 = getattr(request.app.state, "hue_v2", None)
    if not hue_v2:
        raise HTTPException(status_code=503, detail="Hue v2 service not available")

    if name == "stop":
        await hue_v2.stop_effect_all()
    else:
        await hue_v2.set_effect_all(name)

    _last_guest_effect_at = now
    logger.info(
        "Guest set overlay effect '%s' from %s",
        name,
        request.client.host if request.client else "unknown",
    )
    return {
        "status": "ok",
        "effect": name,
        "cooldown_seconds": GUEST_EFFECT_COOLDOWN_SECONDS,
    }


@router.post("/brightness/{direction}", dependencies=[Depends(require_api_key)])
async def adjust_guest_brightness(direction: str, request: Request) -> dict:
    """Bump every on-light's brightness ±10%, clamped to the mode ceiling.

    `direction` ∈ {up, down}. Multiplicative — each tap is `bri × 1.10` or
    `bri / 1.10`. Ceiling = `min(254, floor(254 × mode_multiplier))` where
    multiplier comes from `mode_brightness_config[current_mode]` (default 1.0).
    Off-lights are skipped — guests don't get to turn lights ON via this knob.
    """
    global _last_guest_brightness_at

    if direction not in {"up", "down"}:
        raise HTTPException(
            status_code=400,
            detail="Direction must be 'up' or 'down'",
        )

    now = time.monotonic()
    elapsed = now - _last_guest_brightness_at
    if elapsed < GUEST_BRIGHTNESS_COOLDOWN_SECONDS:
        retry_after = max(1, int(GUEST_BRIGHTNESS_COOLDOWN_SECONDS - elapsed) + 1)
        raise HTTPException(
            status_code=429,
            detail="Slow down a sec",
            headers={"Retry-After": str(retry_after)},
        )

    hue = request.app.state.hue
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")

    automation = getattr(request.app.state, "automation", None)
    mode_mult = 1.0
    if automation:
        mode_mult = automation._mode_brightness.get(automation.current_mode, 1.0)
    ceiling = max(1, min(254, int(254 * mode_mult)))

    sign = 1 if direction == "up" else -1
    multiplicative_delta = GUEST_BRIGHTNESS_STEP - 1.0  # 0.10

    lights = await hue.get_all_lights()
    updated: list[dict] = []
    for light in lights:
        if not light.get("on") or "bri" not in light:
            continue
        current = light["bri"]
        # Floor the step at GUEST_BRIGHTNESS_MIN_STEP so a tap is always
        # visible. Pure 10% on bri=40 = 4 units — invisible against an
        # already-lit room. floor=20 ensures every tap is a real change.
        delta = max(GUEST_BRIGHTNESS_MIN_STEP, round(current * multiplicative_delta))
        new_bri = max(1, min(ceiling, current + sign * delta))
        if new_bri == current:
            continue
        light_id = light["light_id"]
        await hue.set_light(light_id, {"bri": new_bri})
        # Stamp manual override so the engine's next 60s tick doesn't
        # revert the tweak. The guest's existing override (set when they
        # picked the scene) keeps the mode pinned; this stamp keeps the
        # specific bri value pinned.
        if automation:
            automation.mark_light_manual(light_id)
        updated.append({"id": light_id, "bri": new_bri})

    _last_guest_brightness_at = now
    logger.info(
        "Guest brightness %s on %d lights (ceiling=%d) from %s",
        direction,
        len(updated),
        ceiling,
        request.client.host if request.client else "unknown",
    )
    return {
        "status": "ok",
        "direction": direction,
        "updated": updated,
        "ceiling": ceiling,
    }


@router.post("/toast", dependencies=[Depends(require_api_key)])
async def speak_guest_toast(body: ToastRequest, request: Request) -> dict:
    """Speak a guest-submitted toast through Sonos with a sparkle flourish.

    Composes "From {name}: {message}" if a name was provided, otherwise
    speaks the bare message. Wraps `TTSService.speak()` which already
    handles Sonos duck-and-resume. Sparkle runs concurrently for the
    duration of the speech to give a real "everyone listen" moment;
    if a guest had +Sparkle as a scene overlay before the toast, that
    overlay will end with the toast (re-tap +Sparkle to restore it).

    Returns 429 (with Retry-After) when the cooldown is still active,
    503 when TTS or Sonos can't run.
    """
    global _last_guest_toast_at

    now = time.monotonic()
    elapsed = now - _last_guest_toast_at
    if elapsed < GUEST_TOAST_COOLDOWN_SECONDS:
        retry_after = int(GUEST_TOAST_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Cooling down — try again in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    message = body.message.strip()
    name = body.name.strip() if body.name else None
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    text = f"From {name}: {message}" if name else message

    tts = getattr(request.app.state, "tts", None)
    if not tts:
        raise HTTPException(status_code=503, detail="TTS service not initialized")

    hue_v2 = getattr(request.app.state, "hue_v2", None)

    # Sparkle flourish — set it for the toast, stop it after. Done directly
    # against hue_v2 to mirror the existing /effect/{name} pattern (which
    # also bypasses the EffectManager). Edge case: if a guest had +Sparkle
    # as a scene overlay, this stop will end their overlay too. Acceptable
    # v1 limitation; toasts are rare and re-tapping +Sparkle costs a second.
    if hue_v2:
        try:
            await hue_v2.set_effect_all("sparkle")
        except Exception:
            logger.warning("Couldn't start sparkle for toast", exc_info=True)

    try:
        spoken = await tts.speak(text, volume=GUEST_TOAST_VOLUME)
    finally:
        if hue_v2:
            try:
                await hue_v2.stop_effect_all()
            except Exception:
                logger.warning("Couldn't stop sparkle after toast", exc_info=True)

    if not spoken:
        raise HTTPException(
            status_code=503, detail="Sonos couldn't play the toast — try again"
        )

    _last_guest_toast_at = now
    logger.info(
        "Guest toast '%s' (name=%s, %d chars) spoken from %s",
        message[:60], name or "-", len(message),
        request.client.host if request.client else "unknown",
    )
    return {
        "status": "ok",
        "spoken": text,
        "cooldown_seconds": GUEST_TOAST_COOLDOWN_SECONDS,
    }
