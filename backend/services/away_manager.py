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
import asyncio
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


class HomeReconciliationError(RuntimeError):
    """Base error for the strict Return Home reconciliation contract."""


class HomeReconciliationRejected(HomeReconciliationError):
    """The Home write definitely did not commit and Travel can be restored."""


class HomeReconciliationIndeterminate(HomeReconciliationError):
    """The Home outcome is mixed or cannot be proved; keep RETURNING_HOME."""


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
        vibe_router_getter: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._engine = engine
        self._hue_getter = hue_getter
        self._sonos_getter = sonos_getter
        self._tts_getter = tts_getter
        self._notifier_getter = notifier_getter
        self._save_setting = save_setting
        self._load_setting = load_setting
        self._vibe_router_getter = vibe_router_getter or (lambda: None)

        self._away: bool = False
        self._since: Optional[datetime] = None
        self._last_event_source: Optional[str] = None
        self._last_home_reconciliation_id: Optional[str] = None
        self._pending_home_effects: dict[str, tuple[bool, Optional[int]]] = {}
        self._arrival_effect_tasks: set[asyncio.Task] = set()
        self._event_lock = asyncio.Lock()

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
            "host_return_hold": bool(
                getattr(self._engine, "host_return_hold_active", False)
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
        if not saved:
            return
        self._last_home_reconciliation_id = saved.get("home_reconciliation_id")
        if not saved.get("away"):
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

    def _state_payload(
        self,
        *,
        away: Optional[bool] = None,
        source: Optional[str] = None,
        reconciliation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        effective_away = self._away if away is None else away
        effective_since = self._since if effective_away else None
        effective_source = self._last_event_source if source is None else source
        effective_reconciliation_id = (
            self._last_home_reconciliation_id
            if reconciliation_id is None else reconciliation_id
        )
        payload = {
            "away": effective_away,
            "since_utc": (
                effective_since.astimezone(timezone.utc).isoformat()
                if effective_since else None
            ),
            "source": effective_source,
        }
        if effective_reconciliation_id is not None:
            payload["home_reconciliation_id"] = effective_reconciliation_id
        return payload

    async def _persist(self) -> None:
        payload = self._state_payload()
        try:
            await self._save_setting(AWAY_STATE_KEY, payload)
        except Exception as e:
            logger.error("Failed to persist away state: %s", e, exc_info=True)

    async def _persist_home_strict(
        self, *, source: str, reconciliation_id: str,
    ) -> None:
        payload = self._state_payload(
            away=False, source=source, reconciliation_id=reconciliation_id,
        )
        save_error: Optional[Exception] = None
        try:
            await self._save_setting(AWAY_STATE_KEY, payload)
            return
        except Exception as exc:
            save_error = exc
            logger.error(
                "Strict Home persistence raised for reconciliation %s: %s",
                reconciliation_id, exc, exc_info=True,
            )
        try:
            saved = await self._load_setting(AWAY_STATE_KEY)
        except Exception as load_exc:
            raise HomeReconciliationIndeterminate(
                "Home write failed and persisted state could not be read back"
            ) from load_exc
        if (
            isinstance(saved, dict)
            and saved.get("away") is False
            and saved.get("home_reconciliation_id") == reconciliation_id
        ):
            logger.warning(
                "Home reconciliation %s committed despite a write-path exception",
                reconciliation_id,
            )
            return
        if not saved or (isinstance(saved, dict) and saved.get("away") is True):
            raise HomeReconciliationRejected(
                "Home state did not persist; Away remains authoritative"
            ) from save_error
        raise HomeReconciliationIndeterminate(
            "Home write failed and read-back did not match this reconciliation"
        ) from save_error

    async def reconciliation_status(self, reconciliation_id: str) -> dict[str, Any]:
        try:
            saved = await self._load_setting(AWAY_STATE_KEY)
        except Exception as exc:
            raise HomeReconciliationIndeterminate(
                "Persisted away state could not be read"
            ) from exc
        same_transaction = (
            isinstance(saved, dict)
            and saved.get("home_reconciliation_id") == reconciliation_id
        )
        persisted_home = same_transaction and saved.get("away") is False
        superseded_by_away = same_transaction and saved.get("away") is True
        resolved = bool(persisted_home or superseded_by_away)
        runtime = self.status()
        return {
            "outcome": (
                "prepared_home" if persisted_home
                else "superseded_by_away" if superseded_by_away
                else "unresolved"
            ),
            "resolved": resolved,
            "committed": persisted_home,
            "superseded_by_away": superseded_by_away,
            "reconciliation_id": reconciliation_id,
            "persisted_home": persisted_home,
            "away": runtime["away"],
            "suppression_armed": runtime["suppression_armed"],
            "suppression_hold": runtime["suppression_hold"],
            "host_return_hold": runtime["host_return_hold"],
        }

    async def reconcile_home(
        self, *, source: str, reconciliation_id: str,
    ) -> dict[str, Any]:
        """Prepare durable Home while the host-owned RETURNING_HOME hold remains."""
        async with self._event_lock:
            try:
                saved = await self._load_setting(AWAY_STATE_KEY)
            except Exception as exc:
                raise HomeReconciliationIndeterminate(
                    "Persisted away state could not be read before reconciliation"
                ) from exc
            if (
                isinstance(saved, dict)
                and saved.get("home_reconciliation_id") == reconciliation_id
            ):
                if saved.get("away") is True:
                    return await self.reconciliation_status(reconciliation_id)
                self._away = False
                self._since = None
                self._last_event_source = saved.get("source") or source
                self._last_home_reconciliation_id = reconciliation_id
                return await self.reconciliation_status(reconciliation_id)
            was_away = self._away
            away_minutes = None
            if self._since is not None:
                away_minutes = int(
                    (datetime.now(timezone.utc) - self._since).total_seconds() // 60
                )
            try:
                await self._persist_home_strict(
                    source=source, reconciliation_id=reconciliation_id,
                )
            except HomeReconciliationRejected:
                self._away = True
                self._engine.arm_away_suppression(
                    f"home_reconciliation_failed:{source}"
                )
                raise
            self._away = False
            self._since = None
            self._last_event_source = source
            self._last_home_reconciliation_id = reconciliation_id
            self._pending_home_effects[reconciliation_id] = (was_away, away_minutes)
            proof = await self.reconciliation_status(reconciliation_id)
            if not proof["resolved"]:
                raise HomeReconciliationIndeterminate(
                    "Home reconciliation could not prove durable preparation"
                )
            logger.info(
                "HOME prepared (source=%s, transaction=%s)", source, reconciliation_id,
            )
            return proof

    async def activate_home_reconciliation(
        self, *, source: str, reconciliation_id: str,
    ) -> dict[str, Any]:
        """Release only the host-owned hold after hostctl has published HOME."""
        async with self._event_lock:
            proof = await self.reconciliation_status(reconciliation_id)
            if not proof["resolved"]:
                raise HomeReconciliationRejected(
                    "Home reconciliation is not durably resolved"
                )
            superseded = bool(proof["superseded_by_away"] or self._away)
            await self._engine.complete_host_return(
                f"home_reconciliation:{source}",
                release_away=not superseded,
            )
            changed, away_minutes = self._pending_home_effects.pop(
                reconciliation_id, (False, None)
            )
            runtime = self.status()
            if runtime["host_return_hold"]:
                raise HomeReconciliationIndeterminate(
                    "Host Return Home hold did not release"
                )
            if not superseded and (
                runtime["away"]
                or runtime["suppression_armed"]
                or runtime["suppression_hold"]
            ):
                raise HomeReconciliationIndeterminate(
                    "Prepared Home could not release Away suppression"
                )
            return {
                **proof,
                "activated": True,
                "changed": changed and not superseded,
                "effects_required": changed and not superseded,
                "away_minutes": away_minutes,
                "away": runtime["away"],
                "suppression_armed": runtime["suppression_armed"],
                "suppression_hold": runtime["suppression_hold"],
                "host_return_hold": runtime["host_return_hold"],
            }

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
        """Process a geofence event. ``event`` ∈ {"leave", "arrive"}."""
        arrival_minutes: Optional[int] = None
        async with self._event_lock:
            if event == "leave":
                if self._away:
                    return {"status": "ok", "away": True, "changed": False}
                await self._on_leave(source)
                return {"status": "ok", "away": True, "changed": True}
            if event == "arrive":
                if getattr(self._engine, "host_return_hold_active", False):
                    logger.info(
                        "Geofence arrive deferred while host is RETURNING_HOME (source=%s)",
                        source,
                    )
                    return {
                        "status": "deferred_returning_home",
                        "away": self._away,
                        "changed": False,
                    }
                await self._engine.signal_presence(f"geofence:{source}")
                if not self._away:
                    return {"status": "ok", "away": False, "changed": False}
                arrival_minutes = await self._on_arrive(source)
            else:
                return {"status": "error", "detail": f"unknown event: {event!r}"}
        await self.run_arrival_effects(source=source, away_minutes=arrival_minutes)
        return {"status": "ok", "away": False, "changed": True}

    # ── Leave ───────────────────────────────────────────────────────────

    async def _on_leave(self, source: str) -> None:
        self._away = True
        current = asyncio.current_task()
        for task in list(self._arrival_effect_tasks):
            if task is not current and not task.done():
                task.cancel()
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

    async def _on_arrive(self, source: str) -> Optional[int]:
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
        return away_minutes

    async def run_arrival_effects(
        self,
        *,
        source: str,
        away_minutes: Optional[int],
    ) -> None:
        """Run best-effort welcome effects; a newer LEAVE cancels this task."""
        task = asyncio.current_task()
        if task is not None:
            self._arrival_effect_tasks.add(task)
        try:
            if self._away:
                logger.info(
                    "ARRIVE effects skipped (source=%s) — apartment is Away again",
                    source,
                )
                return
            await self._run_arrival_effects_unlocked(
                source=source,
                away_minutes=away_minutes,
            )
        except asyncio.CancelledError:
            logger.info(
                "ARRIVE effects cancelled by newer occupancy event (source=%s)",
                source,
            )
            return
        finally:
            if task is not None:
                self._arrival_effect_tasks.discard(task)

    async def _run_arrival_effects_unlocked(
        self,
        *,
        source: str,
        away_minutes: Optional[int],
    ) -> None:
        """Run welcome effects without owning the occupancy event lock."""
        try:
            await self._engine.reapply_current_mode(force_resend=True)
        except Exception as e:
            logger.error("ARRIVE — light reapply failed: %s", e, exc_info=True)
        if self._away:
            return

        pending_vibe_applied = False
        try:
            vibe_router = self._vibe_router_getter()
            if vibe_router is not None:
                result = await vibe_router.apply_pending_arrival(
                    source=f"arrival:{source}",
                )
                pending_vibe_applied = bool(result)
        except Exception as e:
            logger.error("ARRIVE — pending vibe apply failed: %s", e, exc_info=True)
        if self._away:
            return

        cfg = await self._config()
        if self._away:
            return
        if cfg.get("welcome_tts", True) and self._welcome_tts_allowed():
            try:
                tts = self._tts_getter()
                if tts:
                    await tts.speak(str(cfg.get(
                        "welcome_tts_text", DEFAULT_CONFIG["welcome_tts_text"],
                    )))
            except Exception as e:
                logger.warning("ARRIVE — welcome TTS failed: %s", e)
        if self._away:
            return

        body = "Geofence arrive: lighting restored."
        if pending_vibe_applied:
            body = "Geofence arrive: staged vibe applied."
        if away_minutes is not None:
            body = f"Geofence arrive after {away_minutes} min away: lighting restored."
            if pending_vibe_applied:
                body = f"Geofence arrive after {away_minutes} min away: staged vibe applied."
        if self._away:
            return
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
