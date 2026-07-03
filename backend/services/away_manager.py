"""
Away/home state + behaviors (D2 + D6, GH#107).

Owns the apartment's explicit ``away``/``home`` state, fed by the iOS
Shortcut geofence webhook at ``POST /api/presence/geofence`` (push-based
— the approach that sidesteps all three dead-ends that shelved away-mode
on 2026-05-21: Hue geofence REST/SSE gating and iPhone ARP deep-sleep;
see memory ``project_away_mode_shelved``).

Behaviors (locked in docs/PRESENCE_LIGHTING_SCENARIOS.md Part 7 #2/#6):

LEAVE — lights off + suppress autonomous setters + exactly ONE "away"
notification. Suppression reuses the engine's existing external-off
mechanism (``_check_external_off`` / ``signal_presence``): we arm the
same flag the Hue app's "Leaving home" recipe triggers, so the run_loop
skips every autonomous setter and the brightness-churn notification
spam stops at the root. Notifications are NOT blanket-muted — a genuine
event while away still notifies (Anthony values the visibility).

ARRIVE — the inverse: release suppression via ``signal_presence``,
re-apply the current mode's lighting with a forced resend (the dedup
cache still holds pre-departure values while the bridge is dark), and
optionally a short welcome TTS line (config-gated; suppressed during
DND / sleeping / late_night).

``away`` is deliberately NOT an automation mode — modes describe
activity; away is occupancy. State persists to
``app_settings["away_state"]`` so a backend restart while away doesn't
silently resume autonomous control of an empty apartment.

Idempotent in both directions: iOS geofence automations can re-fire on
region jitter; a duplicate leave/arrive is a no-op (changed=False).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("home_hub.away")

AWAY_STATE_KEY = "away_state"
AWAY_CONFIG_KEY = "away_config"

# Lights-off fade on leave (deciseconds): 3s — unhurried, not abrupt.
LEAVE_FADE_TRANSITIONTIME = 30

DEFAULT_CONFIG: dict[str, Any] = {
    # Welcome TTS on arrive. Suppressed during DND, sleeping mode, and
    # late_night regardless of this flag (a 1am welcome line is hostile).
    "welcome_tts": True,
    "welcome_tts_text": "Welcome home.",
    # Pause Sonos on leave when something is actually playing.
    "pause_music_on_leave": True,
}


class AwayManager:
    """Explicit away/home occupancy state + leave/arrive behaviors."""

    def __init__(
        self,
        *,
        engine: Any,
        hue_getter: Callable[[], Any],
        sonos_getter: Callable[[], Any],
        tts_getter: Callable[[], Any],
        notifier_getter: Callable[[], Any],
        save_setting: Callable[..., Any],
        load_setting: Callable[..., Any],
    ) -> None:
        self._engine = engine
        self._hue_getter = hue_getter
        self._sonos_getter = sonos_getter
        self._tts_getter = tts_getter
        self._notifier_getter = notifier_getter
        self._save_setting = save_setting
        self._load_setting = load_setting

        self._away: bool = False
        self._since: Optional[datetime] = None
        self._last_event_source: Optional[str] = None

    # ── State surface ───────────────────────────────────────────────────

    @property
    def away(self) -> bool:
        return self._away

    def status(self) -> dict[str, Any]:
        """JSON-serializable away state for API responses."""
        return {
            "away": self._away,
            "since_utc": (
                self._since.astimezone(timezone.utc).isoformat()
                if self._since else None
            ),
            "last_event_source": self._last_event_source,
            "suppression_armed": bool(
                getattr(self._engine, "_external_off_detected", False)
            ),
            # Hard hold = geofence-armed; residual process reports can't
            # clear it (only camera presence / geofence arrive can).
            "suppression_hold": bool(
                getattr(self._engine, "_away_hold", False)
            ),
        }

    async def load_state(self) -> None:
        """Restore persisted away state on startup.

        A restart while away must re-arm the run_loop suppression —
        otherwise the engine resumes autonomous control of an empty
        apartment and the churn-notification spam returns.
        """
        try:
            saved = await self._load_setting(AWAY_STATE_KEY)
        except Exception as e:
            logger.error("Failed to load away state: %s", e, exc_info=True)
            return
        if not saved or not saved.get("away"):
            return
        self._away = True
        self._last_event_source = saved.get("source")
        since_str = saved.get("since_utc")
        if since_str:
            try:
                self._since = datetime.fromisoformat(since_str)
            except (TypeError, ValueError):
                self._since = None
        self._engine.arm_away_suppression("away_manager:restore")
        logger.info(
            "Away state restored from app_settings (since=%s) — "
            "suppression re-armed", since_str,
        )

    async def _persist(self) -> None:
        payload = {
            "away": self._away,
            "since_utc": (
                self._since.astimezone(timezone.utc).isoformat()
                if self._since else None
            ),
            "source": self._last_event_source,
        }
        try:
            await self._save_setting(AWAY_STATE_KEY, payload)
        except Exception as e:
            logger.error("Failed to persist away state: %s", e, exc_info=True)

    async def _config(self) -> dict[str, Any]:
        try:
            saved = await self._load_setting(AWAY_CONFIG_KEY)
        except Exception:
            saved = None
        cfg = dict(DEFAULT_CONFIG)
        if isinstance(saved, dict):
            cfg.update(saved)
        return cfg

    # ── Event entry point ───────────────────────────────────────────────

    async def handle_event(self, event: str, source: str) -> dict[str, Any]:
        """Process a geofence event. ``event`` ∈ {"leave", "arrive"}.

        Idempotent: a repeat of the current state returns changed=False
        and performs no actuation (iOS automations re-fire on region
        jitter; the apartment shouldn't strobe on a GPS wobble).
        """
        if event == "leave":
            if self._away:
                logger.info("Geofence leave (source=%s) — already away, no-op", source)
                return {"status": "ok", "away": True, "changed": False}
            await self._on_leave(source)
            return {"status": "ok", "away": True, "changed": True}
        if event == "arrive":
            # Always release suppression (idempotent) — even if state was
            # lost, an arrive must never leave the apartment suppressed.
            await self._engine.signal_presence(f"geofence:{source}")
            if not self._away:
                logger.info("Geofence arrive (source=%s) — already home, no-op", source)
                return {"status": "ok", "away": False, "changed": False}
            await self._on_arrive(source)
            return {"status": "ok", "away": False, "changed": True}
        return {"status": "error", "detail": f"unknown event: {event!r}"}

    # ── Leave ───────────────────────────────────────────────────────────

    async def _on_leave(self, source: str) -> None:
        self._away = True
        self._since = datetime.now(timezone.utc)
        self._last_event_source = source
        await self._persist()
        logger.info("LEAVE (source=%s) — arming suppression, lights off", source)

        # 1. Suppress autonomous setters FIRST so no run_loop tick can
        #    re-light the apartment between our off-write and the next
        #    _check_external_off detection (up to 60s race otherwise).
        self._engine.arm_away_suppression(f"geofence:{source}")

        cfg = await self._config()

        # 2. Pause music if something is actually playing. Best-effort —
        #    a Sonos hiccup must not abort the lights-off.
        if cfg.get("pause_music_on_leave", True):
            try:
                sonos = self._sonos_getter()
                if sonos and sonos.connected:
                    status = await sonos.get_status()
                    if (status or {}).get("state") == "PLAYING":
                        await sonos.pause()
                        logger.info("LEAVE — paused Sonos playback")
            except Exception as e:
                logger.warning("LEAVE — Sonos pause failed: %s", e)

        # 3. All lights off, gentle fade.
        try:
            hue = self._hue_getter()
            if hue and hue.connected:
                await hue.set_all_lights(
                    {"on": False, "transitiontime": LEAVE_FADE_TRANSITIONTIME}
                )
        except Exception as e:
            logger.error("LEAVE — lights-off failed: %s", e, exc_info=True)

        # 4. Exactly ONE notification. DND-respecting (force=False) — the
        #    point of away mode is LESS noise, and the away state itself
        #    is visible on the dashboard regardless.
        await self._notify(
            title="Away — apartment idle",
            body="Geofence leave: lights off, music paused, autonomous "
                 "control suppressed until you're back.",
            kind="away",
        )

    # ── Arrive ──────────────────────────────────────────────────────────

    async def _on_arrive(self, source: str) -> None:
        away_minutes = None
        if self._since is not None:
            away_minutes = int(
                (datetime.now(timezone.utc) - self._since).total_seconds() // 60
            )
        self._away = False
        self._since = None
        self._last_event_source = source
        await self._persist()
        logger.info(
            "ARRIVE (source=%s, away %s min) — welcome-home sequence",
            source, away_minutes if away_minutes is not None else "?",
        )

        # Suppression was already released in handle_event (idempotent
        # signal_presence). Re-apply the current effective mode with a
        # forced resend: the dedup cache still holds pre-departure values
        # while the bridge is actually dark, so an un-forced apply would
        # dedup-skip and leave the lights off.
        try:
            await self._engine.reapply_current_mode(force_resend=True)
        except Exception as e:
            logger.error("ARRIVE — light reapply failed: %s", e, exc_info=True)

        cfg = await self._config()
        if cfg.get("welcome_tts", True) and self._welcome_tts_allowed():
            try:
                tts = self._tts_getter()
                if tts:
                    await tts.speak(str(cfg.get(
                        "welcome_tts_text", DEFAULT_CONFIG["welcome_tts_text"],
                    )))
            except Exception as e:
                logger.warning("ARRIVE — welcome TTS failed: %s", e)

        body = "Geofence arrive: lighting restored."
        if away_minutes is not None:
            body = f"Geofence arrive after {away_minutes} min away: lighting restored."
        await self._notify(
            title="Welcome home", body=body, kind="welcome_home",
        )

    def _welcome_tts_allowed(self) -> bool:
        """Quiet-hours + DND + sleeping gate for the welcome line."""
        try:
            if self._engine.is_dnd_active():
                return False
            if self._engine.current_mode == "sleeping":
                return False
            if self._engine._get_time_period() == "late_night":
                return False
        except Exception:
            return False
        return True

    # ── Notification helper ─────────────────────────────────────────────

    async def _notify(self, *, title: str, body: str, kind: str) -> None:
        try:
            notifier = self._notifier_getter()
            if notifier:
                await notifier.emit_alert(
                    title=title, body=body, kind=kind, force=False,
                )
        except Exception as e:
            logger.warning("Away notification (%s) failed: %s", kind, e)
