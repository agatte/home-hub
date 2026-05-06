"""
Home Hub — AWS Lambda handler for the Custom Alexa Skill.

Receives Alexa Skill events, maps intents → Home Hub REST endpoints, and
forwards the call through the public Cloudflare Tunnel
(home-hub.<domain>.com) into the local backend on the Latitude.

Deployment:
- Runtime: Python 3.11 (AWS Lambda built-in; zero deps beyond stdlib)
- Memory: 128 MB, timeout 5 s
- Trigger: Alexa Skills Kit (via the Skill ID configured in Alexa Console)
- Environment variables required:
    HOME_HUB_API_BASE   = https://home-hub.<your-domain>.com
    HOME_HUB_API_KEY    = same value as the Latitude .env
    HOME_HUB_SKILL_TOKEN= same value as the Latitude .env
- IAM role: basic Lambda execution role (logs only — no AWS resources)

Why urllib.request and not requests/httpx?
- Zero deps means zero zip-and-upload friction. `urllib` is in stdlib;
  the Lambda function fits in a single .py file you can paste into the
  AWS console editor.

Intent coverage:
- Phase 2: SetModeIntent, PlayMusicIntent, PauseMusicIntent,
  ReleaseOverrideIntent
- Phase 3: AdjustBrightnessIntent, SetEffectIntent, StopEffectIntent,
  ActivateSceneIntent, EnableDNDIntent, DisableDNDIntent
- Phase 3.5: AdjustVolumeIntent, NextTrackIntent, PreviousTrackIntent,
  WhatModeIntent, WhatsPlayingIntent
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Valid Home Hub modes — kept in sync with backend automation_engine.py.
# "auto" is intentionally NOT in this set: it's a pseudo-mode that
# releases the manual override, and Alexa NLU misroutes single-word
# slot values reliably enough that it gets its own dedicated intent
# (ReleaseOverrideIntent) instead of being a SetModeIntent slot value.
VALID_MODES = frozenset({
    "gaming", "working", "watching", "social",
    "relax", "cooking", "sleeping",
})

# Hue v2 dynamic effects exposed by the backend (`/api/scenes/effects`).
VALID_EFFECTS = frozenset({
    "candle", "fire", "sparkle", "prism", "glisten", "opal",
})

# Curated scene safelist — same six the /guest mini-app exposes. Slot IDs
# are the SCENE_PRESETS keys so we can pass them straight to
# `/api/scenes/{scene_id}/activate`. The display label (party, neon, ...)
# is what Alexa hears; the canonical ID is what the backend wants.
VALID_SCENE_IDS = frozenset({
    "house_party", "neon_tokyo", "miami_vice",
    "arcade", "northern_lights", "sunset_strip",
})

# Default DND window when the user doesn't specify one. Matches the
# backend's own default (DNDRequest.duration_minutes=120).
DEFAULT_DND_MINUTES = 120


def _env(name: str) -> str:
    """Read a required env var; raise loudly on miss so CloudWatch
    surfaces the misconfiguration."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Lambda env var {name} is not set")
    return val


def _call_homehub(
    path: str, body: dict | None = None, method: str = "POST",
) -> tuple[int, str]:
    """Send a request to the Home Hub backend through the Cloudflare Tunnel.

    Returns (status_code, response_body_text). Default method is POST to
    preserve Phase-2 callers; DND clear uses DELETE.
    """
    api_base = _env("HOME_HUB_API_BASE")
    api_key = _env("HOME_HUB_API_KEY")
    skill_token = _env("HOME_HUB_SKILL_TOKEN")

    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(
        url=api_base.rstrip("/") + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Skill-Token": skill_token,
            # Cloudflare's bot-fight blocks "Python-urllib/X.Y" with
            # error 1010 ("banned based on browser's signature").
            # Identify ourselves clearly and don't masquerade as a
            # browser; the X-Skill-Token already proves auth.
            "User-Agent": "HomeHub-AlexaSkill/1.0 (+aws-lambda)",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            logger.info(
                "Home Hub %s %s -> %d (%d bytes)",
                method, path, resp.status, len(text),
            )
            return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        # First 200 chars only — body may include the bridge token in
        # rare error paths; trim to avoid surprising leaks in CloudWatch.
        logger.warning(
            "Home Hub %s %s -> HTTP %d body=%r",
            method, path, e.code, text[:200],
        )
        return e.code, text
    except urllib.error.URLError as e:
        # Backend down, DNS failed, TLS issue.
        logger.error("Home Hub %s %s URL error: %s", method, path, e)
        return 0, str(e)
    except Exception:
        logger.exception("Home Hub %s %s call unexpectedly failed", method, path)
        return 0, "unexpected"


def _post_to_homehub(path: str, body: dict | None) -> tuple[int, str]:
    """Backwards-compatible POST wrapper."""
    return _call_homehub(path, body, method="POST")


def _speak(text: str, end_session: bool = True) -> dict:
    """Build the Alexa response envelope with a single TTS line."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session,
        },
    }


def _resolved_slot(slots: dict, name: str) -> tuple[str | None, str | None]:
    """Pull the resolved (id, value name) tuple for a slot, lowercased.

    Returns (id, value) on a successful match, (None, raw) when the user
    said something the slot type doesn't know, or (None, None) when the
    slot is missing entirely. The id is what the backend wants for slot
    types where the spoken word and the canonical key differ (e.g.,
    HOMEHUB_SCENE: spoken "party" → id "house_party"). The value is the
    canonical display string ("party") and is used for TTS.
    """
    slot = slots.get(name)
    if not slot:
        return None, None
    res = (
        slot.get("resolutions", {})
            .get("resolutionsPerAuthority", [])
    )
    for authority in res:
        status = authority.get("status", {}).get("code")
        values = authority.get("values", [])
        if status == "ER_SUCCESS_MATCH" and values:
            entry = values[0]["value"]
            return (
                str(entry.get("id", "")).strip().lower() or None,
                entry["name"].strip().lower(),
            )
    raw = slot.get("value")
    return None, (raw.strip().lower() if isinstance(raw, str) else None)


def _slot_value(slots: dict, name: str) -> str | None:
    """Resolved canonical name, or raw user utterance if no resolution.

    For slot types where id == value name (HOMEHUB_MODE, HOMEHUB_EFFECT,
    HOMEHUB_DIRECTION) this is exactly what callers want. Use
    _resolved_slot() directly when the id and value diverge.
    """
    _id, value = _resolved_slot(slots, name)
    return value


# ---- Intent handlers ----

def _handle_set_mode(slots: dict) -> dict:
    mode = _slot_value(slots, "Mode")
    if not mode:
        return _speak("Which mode? You can say gaming, working, relax, "
                      "watching, social, cooking, or sleeping. "
                      "For automatic, just say auto.")
    if mode not in VALID_MODES:
        return _speak(f"I don't know the mode {mode}.")
    status, _ = _post_to_homehub("/api/automation/override", {"mode": mode})
    if 200 <= status < 300:
        return _speak(f"Setting {mode} mode.")
    if status == 401:
        return _speak("Home Hub rejected the request. Check the skill token.")
    return _speak("Home Hub didn't respond.")


def _handle_release_override(_slots: dict) -> dict:
    """Dedicated handler for the auto / release-override pseudo-mode.

    Carved out of SetModeIntent because Alexa NLU misroutes "tell home
    hub to set auto" — single-token slot values fall under the
    confidence threshold and Alexa fallback-routes to smart-home,
    where the most-recently-used Hue scene name wins.
    """
    status, _ = _post_to_homehub("/api/automation/override", {"mode": "auto"})
    if 200 <= status < 300:
        return _speak("Releasing manual override.")
    if status == 401:
        return _speak("Home Hub rejected the request. Check the skill token.")
    return _speak("Home Hub didn't respond.")


def _handle_play_music(_slots: dict) -> dict:
    status, _ = _post_to_homehub("/api/sonos/smart-play", None)
    if 200 <= status < 300:
        return _speak("Playing.")
    return _speak("Couldn't start the music.")


def _handle_pause_music(_slots: dict) -> dict:
    status, _ = _post_to_homehub("/api/sonos/pause", None)
    if 200 <= status < 300:
        return _speak("Paused.")
    return _speak("Couldn't pause the music.")


def _handle_adjust_brightness(slots: dict) -> dict:
    direction = _slot_value(slots, "Direction")
    if direction not in {"up", "down"}:
        return _speak("Say brighter or dimmer.")
    status, _ = _post_to_homehub(
        f"/api/lights/brightness/{direction}", None,
    )
    if 200 <= status < 300:
        return _speak("Brighter." if direction == "up" else "Dimmer.")
    return _speak("Couldn't adjust the lights.")


def _handle_set_effect(slots: dict) -> dict:
    effect = _slot_value(slots, "Effect")
    if not effect:
        return _speak(
            "Which effect? Try candle, fire, sparkle, prism, "
            "glisten, or opal.",
        )
    if effect not in VALID_EFFECTS:
        return _speak(f"I don't have an effect called {effect}.")
    status, _ = _post_to_homehub(f"/api/scenes/effects/{effect}", None)
    if 200 <= status < 300:
        return _speak(f"{effect.capitalize()} effect on.")
    if status == 503:
        return _speak("The Hue bridge isn't ready for effects right now.")
    return _speak("Couldn't start the effect.")


def _handle_stop_effect(_slots: dict) -> dict:
    status, _ = _post_to_homehub("/api/scenes/effects/stop", None)
    if 200 <= status < 300:
        return _speak("Effect stopped.")
    if status == 503:
        return _speak("The Hue bridge isn't ready right now.")
    return _speak("Couldn't stop the effect.")


def _handle_activate_scene(slots: dict) -> dict:
    scene_id, spoken = _resolved_slot(slots, "Scene")
    if scene_id is None:
        # Either no slot at all or the user said something off-list.
        if spoken:
            return _speak(f"I don't have a scene called {spoken}.")
        return _speak(
            "Which scene? Try party, neon, miami, arcade, aurora, "
            "or sunset.",
        )
    if scene_id not in VALID_SCENE_IDS:
        return _speak(f"I don't have a scene called {spoken or scene_id}.")
    status, _ = _post_to_homehub(f"/api/scenes/{scene_id}/activate", None)
    if 200 <= status < 300:
        return _speak(f"Setting the {spoken or scene_id} scene.")
    return _speak("Couldn't activate that scene.")


def _handle_enable_dnd(_slots: dict) -> dict:
    status, _ = _post_to_homehub(
        "/api/automation/dnd",
        {"duration_minutes": DEFAULT_DND_MINUTES},
    )
    if 200 <= status < 300:
        hours = DEFAULT_DND_MINUTES // 60
        return _speak(f"Do not disturb on for {hours} hours.")
    return _speak("Couldn't enable do not disturb.")


def _handle_disable_dnd(_slots: dict) -> dict:
    status, _ = _call_homehub("/api/automation/dnd", None, method="DELETE")
    if 200 <= status < 300:
        return _speak("Do not disturb off.")
    return _speak("Couldn't clear do not disturb.")


def _handle_adjust_volume(slots: dict) -> dict:
    direction = _slot_value(slots, "VolumeDirection")
    if direction not in {"up", "down"}:
        return _speak("Say louder or quieter.")
    status, _ = _post_to_homehub(
        f"/api/sonos/volume/{direction}", None,
    )
    if 200 <= status < 300:
        return _speak("Louder." if direction == "up" else "Quieter.")
    if status == 503:
        return _speak("Sonos isn't connected.")
    return _speak("Couldn't change the volume.")


def _handle_next_track(_slots: dict) -> dict:
    status, _ = _post_to_homehub("/api/sonos/next", None)
    if 200 <= status < 300:
        return _speak("Skipping.")
    if status == 503:
        return _speak("Sonos isn't connected.")
    return _speak("Couldn't skip the track.")


def _handle_previous_track(_slots: dict) -> dict:
    status, _ = _post_to_homehub("/api/sonos/previous", None)
    if 200 <= status < 300:
        return _speak("Going back.")
    if status == 503:
        return _speak("Sonos isn't connected.")
    return _speak("Couldn't go back a track.")


def _handle_what_mode(_slots: dict) -> dict:
    status, body = _call_homehub("/api/automation/status", None, method="GET")
    if not (200 <= status < 300):
        return _speak("Couldn't read the current mode.")
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return _speak("Couldn't read the current mode.")
    mode = data.get("current_mode")
    if not mode:
        return _speak("No mode is set right now.")
    if data.get("manual_override"):
        return _speak(f"{mode} mode, manually set.")
    return _speak(f"{mode} mode.")


def _handle_whats_playing(_slots: dict) -> dict:
    status, body = _call_homehub("/api/sonos/status", None, method="GET")
    if status == 503:
        return _speak("Sonos isn't connected.")
    if not (200 <= status < 300):
        return _speak("Couldn't read what's playing.")
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return _speak("Couldn't read what's playing.")

    state = (data.get("state") or "").upper()
    track = data.get("track") or ""
    artist = data.get("artist") or ""

    if not track:
        return _speak("Nothing's playing.")

    # Sonos states: PLAYING, PAUSED_PLAYBACK, STOPPED, TRANSITIONING.
    track_phrase = f"{track} by {artist}" if artist else track
    if state == "PLAYING":
        return _speak(f"Playing {track_phrase}.")
    if state.startswith("PAUSED"):
        return _speak(f"Paused on {track_phrase}.")
    return _speak(f"{track_phrase} is loaded but not playing.")


INTENT_HANDLERS = {
    "SetModeIntent": _handle_set_mode,
    "ReleaseOverrideIntent": _handle_release_override,
    "PlayMusicIntent": _handle_play_music,
    "PauseMusicIntent": _handle_pause_music,
    "AdjustBrightnessIntent": _handle_adjust_brightness,
    "SetEffectIntent": _handle_set_effect,
    "StopEffectIntent": _handle_stop_effect,
    "ActivateSceneIntent": _handle_activate_scene,
    "EnableDNDIntent": _handle_enable_dnd,
    "DisableDNDIntent": _handle_disable_dnd,
    "AdjustVolumeIntent": _handle_adjust_volume,
    "NextTrackIntent": _handle_next_track,
    "PreviousTrackIntent": _handle_previous_track,
    "WhatModeIntent": _handle_what_mode,
    "WhatsPlayingIntent": _handle_whats_playing,
}


# ---- Built-in intent / request type handlers ----

def _handle_launch() -> dict:
    """No-arg invocation: 'Alexa, open Home Hub.' Stay in session so the
    next utterance can land an intent without re-saying the wake word."""
    return _speak(
        "Home Hub is ready. You can set a mode, run a scene, change the "
        "volume, or ask what's playing.",
        end_session=False,
    )


def _handle_help() -> dict:
    return _speak(
        "Try: set relax mode. Louder. Skip this song. What mode am I in. "
        "Run the party scene. Or enable do not disturb.",
        end_session=False,
    )


def _handle_stop() -> dict:
    return _speak("Goodbye.")


# ---- Top-level entry point ----

def lambda_handler(event: dict, _context) -> dict:
    """Alexa Skills Kit entry point. Always returns a valid response
    envelope — Alexa surfaces uncaught exceptions as a generic skill
    error which is unhelpful in production."""
    try:
        request = event.get("request", {})
        request_type = request.get("type")
        logger.info("Alexa request type=%s", request_type)

        if request_type == "LaunchRequest":
            return _handle_launch()

        if request_type == "SessionEndedRequest":
            # No response needed for SessionEndedRequest, but Alexa is
            # tolerant — return an empty envelope.
            return {"version": "1.0", "response": {}}

        if request_type == "IntentRequest":
            intent = request.get("intent", {})
            name = intent.get("name")
            slots = intent.get("slots", {})
            logger.info("Intent: %s slots=%s", name, list(slots.keys()))

            # Built-in intents Alexa reserves
            if name in ("AMAZON.HelpIntent",):
                return _handle_help()
            if name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
                return _handle_stop()

            handler = INTENT_HANDLERS.get(name)
            if handler is None:
                return _speak(f"I don't have a handler for {name}.")
            return handler(slots)

        return _speak(f"Unsupported request type {request_type}.")

    except Exception:
        logger.exception("lambda_handler crashed")
        return _speak("Home Hub had an error. Check the logs.")
