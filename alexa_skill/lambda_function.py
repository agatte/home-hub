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

Phase 2 scope: SetModeIntent + PauseMusicIntent + PlayMusicIntent. The
plan adds more intents in Phase 3.
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
# "auto" is the dashboard's "release manual override" pseudo-mode.
VALID_MODES = frozenset({
    "gaming", "working", "watching", "social",
    "relax", "cooking", "sleeping", "auto",
})


def _env(name: str) -> str:
    """Read a required env var; raise loudly on miss so CloudWatch
    surfaces the misconfiguration."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Lambda env var {name} is not set")
    return val


def _post_to_homehub(path: str, body: dict | None) -> tuple[int, str]:
    """POST a JSON payload (or empty body) to the Home Hub backend through
    the Cloudflare Tunnel. Returns (status_code, response_body_text)."""
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
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            logger.info("Home Hub %s -> %d (%d bytes)", path, resp.status, len(text))
            return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        # First 200 chars only — body may include the bridge token in
        # rare error paths; trim to avoid surprising leaks in CloudWatch.
        logger.warning(
            "Home Hub %s -> HTTP %d body=%r", path, e.code, text[:200]
        )
        return e.code, text
    except urllib.error.URLError as e:
        # Backend down, DNS failed, TLS issue.
        logger.error("Home Hub %s URL error: %s", path, e)
        return 0, str(e)
    except Exception as e:
        logger.exception("Home Hub %s call unexpectedly failed", path)
        return 0, str(e)


def _speak(text: str, end_session: bool = True) -> dict:
    """Build the Alexa response envelope with a single TTS line."""
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session,
        },
    }


def _slot_value(slots: dict, name: str) -> str | None:
    """Pull the resolved (or raw) slot value, lowercased.

    Alexa returns slot values nested. Prefer the resolved authority value
    (the canonical one matching our slot type); fall back to the raw user
    utterance if no resolution exists.
    """
    slot = slots.get(name)
    if not slot:
        return None
    res = (
        slot.get("resolutions", {})
            .get("resolutionsPerAuthority", [])
    )
    for authority in res:
        status = authority.get("status", {}).get("code")
        values = authority.get("values", [])
        if status == "ER_SUCCESS_MATCH" and values:
            return values[0]["value"]["name"].strip().lower()
    raw = slot.get("value")
    return raw.strip().lower() if isinstance(raw, str) else None


# ---- Intent handlers ----

def _handle_set_mode(slots: dict) -> dict:
    mode = _slot_value(slots, "Mode")
    if not mode:
        return _speak("Which mode? You can say gaming, working, relax, "
                      "watching, social, cooking, sleeping, or auto.")
    if mode not in VALID_MODES:
        return _speak(f"I don't know the mode {mode}.")
    status, _ = _post_to_homehub("/api/automation/override", {"mode": mode})
    if 200 <= status < 300:
        if mode == "auto":
            return _speak("Releasing manual override.")
        return _speak(f"Setting {mode} mode.")
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


INTENT_HANDLERS = {
    "SetModeIntent": _handle_set_mode,
    "PlayMusicIntent": _handle_play_music,
    "PauseMusicIntent": _handle_pause_music,
}


# ---- Built-in intent / request type handlers ----

def _handle_launch() -> dict:
    """No-arg invocation: 'Alexa, open Home Hub.' Stay in session so the
    next utterance can land an intent without re-saying the wake word."""
    return _speak(
        "Home Hub is ready. You can say things like set gaming mode, "
        "or pause the music.",
        end_session=False,
    )


def _handle_help() -> dict:
    return _speak(
        "Try saying: set relax mode. Pause the music. Or set the apartment "
        "to working.",
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
