"""
Notifier service — pushes "what just changed and why" to desktop + phone.

The apartment makes autonomous decisions all day (late-night rescue,
zone+posture rule, fusion lane reweighting, watching-sleep-guard, camera
lux multiplier shifts) that the user can't see from across the room.
This service watches the automation engine's effective output and pushes
a structured notification on threshold-crossing changes:

    Trigger:  mode flip
              OR average per-light brightness shift |Δ| / last >= 0.15

    Suppress: DND active
              OR within 10s of the previous emit (coalesce burst events)
              OR within 30s of backend startup (skip boot noise)
              OR mode flip whose source is user-initiated (api:* / manual
                 / alexa:* / guest:*) — the user caused it

Two surfaces consume each notification:
  * WebSocket broadcast "notification" → desktop_notifier toast widget.
  * httpx POST https://ntfy.sh/{NTFY_TOPIC} → ntfy iOS app native push.

Top-3 "why" factors come from ``automation._last_fusion_result.signals[]
.factors[]``, flattened across lanes and re-sorted by impact desc. No
new reasoning logic — every factor was already being computed by the
fusion lanes; the notifier is just the surface that puts it in front
of a human.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.notifier")

# How long after backend boot to suppress notifications. Fusion settles
# in the first ~10s and the very first mode-change callback also fires
# as services come online; 30s leaves margin without delaying the user's
# first real notification noticeably.
BOOT_SUPPRESS_S = 30.0

# Coalesce window — collapse bursts (mode-flip + brightness-shift cascade)
# into a single notification. 10s matches the "good night" + sleeping-mode
# cascade where ambient brightness and mode shift within a few seconds.
COALESCE_WINDOW_S = 10.0

# Brightness shift threshold (relative). 15% is roughly one slider notch
# in the mode_brightness settings UI — small enough to catch camera-lux
# multiplier moves, large enough to not fire on every IES reconcile.
BRIGHTNESS_DELTA_THRESHOLD = 0.15

# How often the poll loop walks the engine state checking for shifts.
# Mode changes fire immediately via the callback hook; this poll only
# catches brightness drift between mode changes (camera lux, posture).
POLL_INTERVAL_S = 5.0

# Sources for which a mode change is "the user did it" and shouldn't fire
# a notification. Autonomous sources (process, camera, fusion, predictor,
# late_night_rescue, zone_posture_rule, watching_sleep_guard, schedule,
# rule_suggestion_accept, ambient, scene_drift) all DO fire.
USER_INITIATED_SOURCE_PREFIXES = ("api:", "alexa:", "guest:")
USER_INITIATED_SOURCES = frozenset({"manual"})


@dataclass(slots=True)
class _State:
    """Per-emit state we remember between fires."""
    last_mode: Optional[str] = None
    last_brightness: Optional[float] = None
    last_emit_at: float = 0.0
    boot_at: float = field(default_factory=time.time)


class NotifierService:
    """Push apartment-state-change notifications to desktop + phone.

    Construction takes the existing collaborators (ws_manager, automation
    engine, optional camera_service) plus the ntfy.sh config. The service
    runs as a poll loop that the bootstrap registers in ``tasks`` and
    cancels on shutdown — pattern identical to the other engine-driven
    services.
    """

    def __init__(
        self,
        ws_manager,
        automation_engine,
        ntfy_topic: Optional[str],
        ntfy_server: str = "https://ntfy.sh",
    ) -> None:
        self._ws = ws_manager
        self._engine = automation_engine
        self._ntfy_topic = (ntfy_topic or "").strip() or None
        self._ntfy_server = ntfy_server.rstrip("/")
        self._state = _State()
        self._http: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        if not self._ntfy_topic:
            logger.info(
                "NotifierService initialized (ntfy.sh push DISABLED — "
                "NTFY_TOPIC unset; WS broadcast still active)",
            )
        else:
            # Topic deliberately omitted — it's the auth secret on hosted
            # ntfy.sh and must not land in journalctl (this fires every boot).
            logger.info(
                "NotifierService initialized (ntfy.sh push enabled at %s)",
                self._ntfy_server,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Lazy-build the httpx client. Called from bootstrap before poll_loop."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=5.0)

    async def close(self) -> None:
        """Release the httpx client. Called from bootstrap teardown."""
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                logger.debug("NotifierService.close: httpx aclose failed", exc_info=True)
            self._http = None

    async def poll_loop(self) -> None:
        """Periodic brightness-shift check. Mode flips fire via callback."""
        while True:
            try:
                await self._maybe_emit(reason="poll")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("notifier poll iteration failed")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def on_mode_change(self, new_mode: str, **_kwargs: Any) -> None:
        """Callback registered with AutomationEngine.register_on_mode_change."""
        try:
            await self._maybe_emit(reason="mode_change")
        except Exception:
            logger.exception("notifier on_mode_change failed")

    # ------------------------------------------------------------------
    # Core emit decision
    # ------------------------------------------------------------------

    async def _maybe_emit(self, reason: str) -> None:
        """Decide whether to fire a notification; fire it if so."""
        async with self._lock:
            now = time.time()

            if now - self._state.boot_at < BOOT_SUPPRESS_S:
                return

            if self._engine.is_dnd_active():
                # Refresh the snapshot so the first post-DND poll compares
                # against the now-baseline, not the pre-DND values. Without
                # this, any brightness drift during the DND window crosses
                # the shift threshold on lift and fires a spurious notification.
                self._state.last_mode = self._engine.current_mode
                self._state.last_brightness = self._effective_brightness()
                return

            mode = self._engine.current_mode
            brightness = self._effective_brightness()

            # First observation seeds the snapshot without firing.
            if self._state.last_mode is None:
                self._state.last_mode = mode
                self._state.last_brightness = brightness
                return

            mode_changed = mode != self._state.last_mode
            brightness_shifted = self._is_brightness_shift(
                self._state.last_brightness, brightness,
            )

            if not (mode_changed or brightness_shifted):
                # Update the snapshot so the next check compares against
                # the latest observation, not a stale baseline. Without
                # this, slow drift accumulates across many polls and
                # eventually crosses the 15% threshold even though no
                # rapid change happened (false-positive shift notification).
                # Narrows the threshold semantics to "shift since last
                # poll (~5s)," which is what the docstring describes.
                self._state.last_mode = mode
                self._state.last_brightness = brightness
                return

            # Brightness-only changes are too noisy for push/desktop surfaces.
            # Learned brightness preference prompts still go through
            # emit_suggestion(), which bypasses this generic state-change path.
            if brightness_shifted and not mode_changed:
                self._state.last_mode = mode
                self._state.last_brightness = brightness
                return

            # Coalesce burst events. A mode flip + brightness shift within
            # the same poll cycle are one "change" — fire once.
            if now - self._state.last_emit_at < COALESCE_WINDOW_S:
                # Update tracking so the *next* fire compares against the
                # latest values, not the pre-burst snapshot.
                self._state.last_mode = mode
                self._state.last_brightness = brightness
                return

            # User-initiated mode flips don't get notified — Anthony pressed
            # the button; he doesn't need a toast telling him what he just did.
            if mode_changed:
                source = (self._engine.mode_source or "").strip()
                if (
                    source in USER_INITIATED_SOURCES
                    or any(source.startswith(p) for p in USER_INITIATED_SOURCE_PREFIXES)
                ):
                    self._state.last_mode = mode
                    self._state.last_brightness = brightness
                    self._state.last_emit_at = now
                    return

            payload = self._build_payload(
                old_mode=self._state.last_mode,
                new_mode=mode,
                old_brightness=self._state.last_brightness,
                new_brightness=brightness,
                mode_changed=mode_changed,
                brightness_shifted=brightness_shifted,
            )

            self._state.last_mode = mode
            self._state.last_brightness = brightness
            self._state.last_emit_at = now

        # Fan out to surfaces OUTSIDE the lock so a slow ntfy.sh round-trip
        # doesn't hold up the next on_mode_change callback.
        await self._dispatch(payload)

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------

    def _effective_brightness(self) -> float:
        """Average ``bri`` across the engine's last-applied per-light state.

        Returns 0.0..1.0. Captures all sources of brightness change in one
        signal: mode_brightness slider, camera lux multiplier, watching-
        posture overlay, zone overrides, per-light overrides. Off lights
        count as zero. An empty state returns 0.0.
        """
        applied = getattr(self._engine, "_last_applied_per_light", None) or {}
        if not applied:
            return 0.0
        total = 0.0
        count = 0
        for state in applied.values():
            if not isinstance(state, dict):
                continue
            count += 1
            if state.get("on", True) is False:
                continue
            bri = state.get("bri", 0) or 0
            total += min(max(int(bri), 0), 254) / 254.0
        return total / count if count else 0.0

    @staticmethod
    def _is_brightness_shift(old: Optional[float], new: float) -> bool:
        if old is None:
            return False
        denom = max(old, 0.01)
        return abs(new - old) / denom >= BRIGHTNESS_DELTA_THRESHOLD

    def _collect_top_factors(self, limit: int = 3) -> list[dict[str, Any]]:
        """Flatten fusion.signals[].factors[], sort by impact desc, take top N."""
        fusion = getattr(self._engine, "_last_fusion_result", None)
        if not isinstance(fusion, dict):
            return []
        signals = fusion.get("signals") or {}
        flattened: list[dict[str, Any]] = []
        for lane_name, lane in signals.items():
            if not isinstance(lane, dict):
                continue
            for factor in lane.get("factors") or []:
                if not isinstance(factor, dict):
                    continue
                label = factor.get("label") or factor.get("key") or lane_name
                value = factor.get("display") or factor.get("value")
                if value is None:
                    continue
                flattened.append({
                    "lane": lane_name,
                    "label": str(label),
                    "value": str(value),
                    "impact": float(factor.get("impact") or 0.0),
                })
        flattened.sort(key=lambda f: f["impact"], reverse=True)
        return flattened[:limit]

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        *,
        old_mode: str,
        new_mode: str,
        old_brightness: Optional[float],
        new_brightness: float,
        mode_changed: bool,
        brightness_shifted: bool,
    ) -> dict[str, Any]:
        # Title is the headline — what the user sees on the lock screen.
        if mode_changed:
            title = f"{old_mode} → {new_mode}"
        else:
            denom = max(old_brightness or 0.01, 0.01)
            pct = int(round((new_brightness - denom) / denom * 100))
            direction = "brighter" if pct > 0 else "dimmer"
            title = f"{new_mode}: {direction} ({pct:+d}%)"

        subtitle = self._engine.override_source or self._engine.mode_source or ""

        factors = self._collect_top_factors()

        output_delta = self._describe_output_delta(
            old_brightness, new_brightness, brightness_shifted,
        )

        return {
            "title": title,
            "subtitle": subtitle,
            "factors": factors,
            "output_delta": output_delta,
            "mode_changed": mode_changed,
            "brightness_shifted": brightness_shifted,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        }

    @staticmethod
    def _describe_output_delta(
        old: Optional[float], new: float, shifted: bool,
    ) -> Optional[str]:
        if not shifted or old is None:
            return None
        return f"avg bri {old * 100:.0f}% → {new * 100:.0f}%"

    # ------------------------------------------------------------------
    # Dispatch surfaces
    # ------------------------------------------------------------------

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        """Fan out the payload to all surfaces."""
        # WS first — desktop is the latency-sensitive surface.
        try:
            await self._ws.broadcast("notification", payload)
        except Exception:
            logger.exception("notification WS broadcast failed")

        # ntfy.sh is best-effort and runs in the background. Avoid blocking
        # the next mode-change callback on a slow phone-push round-trip.
        if self._ntfy_topic and self._http is not None:
            asyncio.create_task(self._send_ntfy(payload))

    async def _send_ntfy(self, payload: dict[str, Any]) -> None:
        """POST a single notification to ntfy.sh.

        ntfy.sh's hosted server treats the topic name as the "auth" boundary
        (anyone subscribed to the topic gets the message). Keep NTFY_TOPIC
        secret like an API key — that's why it's an env var, not a setting.

        When ``payload["actions"]`` is non-empty, ntfy.sh's ``Actions``
        header carries http-action buttons that POST to the supplied URLs
        when the user taps them in the iOS app. Per-action headers (e.g.
        ``X-API-Key``) get sent verbatim and ARE visible to the ntfy.sh
        server in cleartext — single-user system, NTFY_TOPIC already
        treated as a shared secret, but worth knowing the trade-off.
        """
        if not self._ntfy_topic or self._http is None:
            return
        body = " | ".join(
            f"{f['label']}: {f['value']}" for f in payload.get("factors") or []
        )
        if payload.get("output_delta"):
            sep = "  •  " if body else ""
            body = f"{body}{sep}{payload['output_delta']}"
        if not body:
            body = payload.get("subtitle") or "Apartment state changed"

        url = f"{self._ntfy_server}/{self._ntfy_topic}"
        title = self._ascii_safe_header(payload.get("title", "Home Hub"))[:200]
        headers = {
            "Title": title,
            "Priority": "low",
            "Tags": "house",
            "X-Correlation-Id": self._ascii_safe_header(payload.get("correlation_id", "")),
        }
        actions_header = self._format_actions_header(payload.get("actions") or [])
        if actions_header:
            headers["Actions"] = self._ascii_safe_header(actions_header)
        # Click header — when set, tapping the phone notification opens this
        # URL directly (no button required). Used by calibration_nudge so the
        # phone push deep-links into /personality on tap.
        click_url = payload.get("click_url")
        if click_url:
            headers["Click"] = self._ascii_safe_header(str(click_url))
        try:
            resp = await self._http.post(
                url, content=body.encode("utf-8"), headers=headers,
            )
            if resp.status_code >= 400:
                # Never log the topic — on hosted ntfy.sh the topic name IS the
                # auth (anyone who reads it can publish/subscribe), so it must
                # not leak into journalctl. The server is single-topic, so the
                # value adds no diagnostic signal anyway.
                logger.warning(
                    "ntfy.sh push returned %d: %s",
                    resp.status_code, resp.text[:200],
                )
            else:
                logger.debug(
                    "ntfy.sh push ok (correlation=%s)",
                    payload.get("correlation_id"),
                )
        except Exception:
            # Topic deliberately omitted — it's the auth secret (see above).
            logger.exception("ntfy.sh push failed")

    # ntfy.sh sends headers as latin-1 over HTTP/1.1; any UTF-8 char that
    # isn't representable (→, •, …, em-dash, curly quotes) raises
    # UnicodeEncodeError inside httpx before the request goes out. Map the
    # typographic chars we actually emit (mode-flip arrows, factor bullets)
    # to ASCII equivalents, then fall back to latin-1 errors='replace' for
    # anything else.
    _HEADER_CHAR_MAP = str.maketrans({
        "→": "->",   # →  rightwards arrow (mode flips)
        "←": "<-",   # ←
        "↔": "<->",  # ↔
        "•": "*",    # •  bullet (factor separator)
        "…": "...",  # …  horizontal ellipsis
        "—": "--",   # —  em dash
        "–": "-",    # –  en dash
        "‘": "'",    # ‘
        "’": "'",    # ’
        "“": '"',    # “
        "”": '"',    # ”
        "°": " deg", # °
    })

    @classmethod
    def _ascii_safe_header(cls, value: str) -> str:
        """Make an HTTP header value safe to send to ntfy.sh.

        httpx encodes headers as latin-1; non-representable chars raise
        UnicodeEncodeError pre-send. First substitute the typographic
        chars we deliberately emit (arrows, bullets, ellipses, dashes,
        smart quotes); then encode/decode latin-1 with 'replace' to
        scrub anything we didn't anticipate without crashing.
        """
        if not value:
            return ""
        mapped = str(value).translate(cls._HEADER_CHAR_MAP)
        return mapped.encode("latin-1", errors="replace").decode("latin-1")

    @staticmethod
    def _format_actions_header(
        actions: list[dict[str, Any]],
    ) -> Optional[str]:
        """Render the WS-side actions list into ntfy.sh's Actions header.

        Format per ntfy.sh action-button spec:
            http, <label>, <url>, method=<METHOD>, headers.<key>=<value>
        Each per-action header is its own ``headers.<key>=<value>`` token;
        the legacy ``headers="K: v,K: v"`` form returns HTTP 400 with
        ``key 'headers' unknown``. Multiple actions joined by ``; ``.
        Empty list → None (header omitted).
        """
        if not actions:
            return None
        parts: list[str] = []
        for action in actions:
            label = action.get("label", "Action")
            url = action.get("url")
            if not url:
                continue
            # ntfy.sh action types: "http" (POSTs/GETs to a URL with optional
            # headers) and "view" (opens the URL in the user's browser). view
            # actions don't take method= or headers.* fields — adding them
            # would be silently ignored by ntfy.sh but the spec is cleaner if
            # we omit them entirely.
            action_type = (action.get("type") or "http").lower()
            if action_type == "view":
                parts.append(f"view, {label}, {url}")
                continue
            method = action.get("method", "POST")
            piece = f"http, {label}, {url}, method={method}"
            for hk, hv in (action.get("headers") or {}).items():
                value = str(hv)
                if any(c in value for c in (",", ";", "=", '"')):
                    value = '"' + value.replace('"', '\\"') + '"'
                piece += f", headers.{hk}={value}"
            parts.append(piece)
        return "; ".join(parts) if parts else None

    async def emit_suggestion(
        self,
        *,
        suggestion_id: int,
        title: str,
        body: str,
        accept_url: str,
        dismiss_url: str,
        api_key: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Fire a notification with Accept / Dismiss action buttons.

        Bypasses the mode-change / brightness-shift decision logic — the
        caller (RuleEngineService.emit_brightness_suggestion) has already
        decided the user should see this. Goes through the same WS +
        ntfy.sh fan-out as the auto path so the desktop notifier + iOS
        app render identical action-button rows.
        """
        action_headers: dict[str, str] = {}
        if api_key:
            action_headers["X-API-Key"] = api_key

        payload: dict[str, Any] = {
            "title": title,
            "subtitle": body,
            "body": body,
            "factors": [],
            "output_delta": None,
            "actions": [
                {"label": "Accept", "url": accept_url, "method": "POST",
                 "headers": action_headers},
                {"label": "Dismiss", "url": dismiss_url, "method": "POST",
                 "headers": action_headers},
            ],
            "suggestion_id": suggestion_id,
            "kind": "suggestion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        }
        if extra:
            payload.update(extra)
        await self._dispatch(payload)

    # ------------------------------------------------------------------
    # Calibration nudge path
    # ------------------------------------------------------------------

    async def emit_calibration_nudge(self, payload: dict[str, Any]) -> None:
        """Fire a calibration-nudge notification through the dispatch path.

        Caller (CalibrationNudgeService) has already decided this should fire
        and built the full payload — bypasses every NotifierService gate
        (boot suppress, DND, coalesce). The nudge service runs its own gating
        upstream and shouldn't be silently swallowed here.
        """
        await self._dispatch(payload)

    # ------------------------------------------------------------------
    # Synthetic / test path
    # ------------------------------------------------------------------

    async def emit_synthetic(
        self, title: str = "Test notification",
        body: str = "Synthetic test fire",
        kind: str = "test",
    ) -> dict[str, Any]:
        """Fire a synthetic notification through the real dispatch path.

        Used by POST /api/notification/test to verify both surfaces end-to-end
        without waiting for a real mode flip. Bypasses DND + coalesce + boot
        suppression so the test always fires.

        ``kind="suggestion"`` switches to a suggestion-style payload with
        empty factors + Accept/Dismiss action buttons (URLs are no-op
        echo endpoints) so the desktop toast's action-button render path
        can be exercised without waiting for the next brightness scan.
        """
        if kind == "suggestion":
            # No-op URL — buttons just need to render for the toast verify;
            # click-through is best-effort (handler ignores bad URLs).
            stub_url = f"{self._ntfy_server.replace('https://ntfy.sh', 'http://localhost:8000')}/api/notification/test"
            payload: dict[str, Any] = {
                "title": title,
                "subtitle": body,
                "body": body,
                "factors": [],
                "output_delta": None,
                "actions": [
                    {"label": "Accept", "url": stub_url,
                     "method": "POST", "headers": {}},
                    {"label": "Dismiss", "url": stub_url,
                     "method": "POST", "headers": {}},
                ],
                "kind": "suggestion",
                "suggestion_id": -1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "correlation_id": str(uuid.uuid4()),
            }
        else:
            payload = {
                "title": title,
                "subtitle": "test",
                "factors": [
                    {"lane": "test", "label": "synthetic", "value": body, "impact": 1.0},
                ],
                "output_delta": None,
                "mode_changed": False,
                "brightness_shifted": False,
                "old_mode": self._engine.current_mode,
                "new_mode": self._engine.current_mode,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "correlation_id": str(uuid.uuid4()),
            }
        await self._dispatch(payload)
        return payload

    async def emit_alert(
        self,
        *,
        title: str,
        body: str,
        kind: str = "alert",
        force: bool = False,
    ) -> bool:
        """Fire an operational alert (watchdog / health) through the real
        dispatch path — desktop toast (WS) + ntfy.sh phone push.

        Unlike :meth:`emit_synthetic` (a test fire that bypasses every gate),
        this is for real autonomous alerts, so it honors DND: a silenced
        apartment shouldn't buzz the phone at 3am. Returns True if dispatched,
        False if suppressed by DND. Callers own the higher-level policy
        (dedup / edge-triggering / domain suppression) — this is the transport.
        """
        if not force and self._engine.is_dnd_active():
            logger.info("Alert suppressed by DND: %s", title)
            return False
        mode = self._engine.current_mode
        payload = {
            "title": title,
            "subtitle": body,
            "body": body,
            "factors": [
                {"lane": "watchdog", "label": kind, "value": body, "impact": 1.0},
            ],
            "output_delta": None,
            "mode_changed": False,
            "brightness_shifted": False,
            "kind": kind,
            "old_mode": mode,
            "new_mode": mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(uuid.uuid4()),
        }
        await self._dispatch(payload)
        return True
