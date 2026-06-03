"""
AgentHealthMonitor — Latitude-side watchdog for the desktop agent supervisor.

The desktop PC agent supervisor POSTs an agent-health heartbeat to
``/api/automation/agent-health`` every ~30s (per-agent status + heartbeat_age +
supervisor_uptime). Task #2 made the *supervisor* self-heal hung agent threads,
but it can't cover the case where the whole supervisor stops reporting — the
process crashed, the desktop slept or powered off, or the network dropped. On
2026-06-03 exactly that happened (the supervisor wedged at 13:42 and nothing
replaced it for hours) and the Latitude silently degraded to camera + process
signals with no alert.

This service closes that gap: it tracks the freshness of those heartbeats and
fires a NotifierService alert (desktop toast + ntfy phone push) when the
supervisor goes silent past a threshold, or when an individual agent stays
``stopped``/``hung`` long enough that the supervisor's own restart isn't
clearing it. Alerts are edge-triggered (one per incident, with a recovery
notice), DND-respecting (via ``emit_alert``), and suppressed while the desktop
is *expected* to be offline (sleeping mode, or the apartment-empty external-off
state).

Read-only w.r.t. apartment state — it only observes + notifies.
"""
import asyncio
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("home_hub.agent_health")

# How often the watchdog evaluates freshness.
CHECK_INTERVAL_S = 60.0
# Supervisor heartbeats arrive every ~30s; 5 min of silence = ~10 missed
# reports — unambiguously down, not a one-off dropped POST.
SUPERVISOR_SILENT_SECONDS = 300.0
# An individual agent reported stopped/hung for this long means the supervisor's
# own restart/recycle isn't clearing it — worth a heads-up.
AGENT_STUCK_SECONDS = 180.0
# Name of the desktop Scheduled Task, surfaced in the alert body as the fix.
RESPAWN_TASK_NAME = "Home Hub Agent Supervisor"
# Per-agent states that count as "bad".
_BAD_STATUSES = frozenset({"stopped", "hung"})


class AgentHealthMonitor:
    """Watches desktop agent-supervisor heartbeats; alerts on silence / stuck
    agents. Wire-up mirrors the other engine-driven services: construct in the
    bootstrap, register ``poll_loop`` in ``tasks``, and call ``record_report``
    from the agent-health route on each inbound POST."""

    def __init__(
        self,
        *,
        automation_engine: Any,
        notifier: Any,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._engine = automation_engine
        self._notifier = notifier
        self._clock = clock

        self._last_report_at: Optional[float] = None
        self._last_report: Optional[dict] = None
        self._ever_reported = False

        # Edge-trigger state so we alert once per incident, not every poll.
        self._supervisor_alerted = False
        self._agent_bad_since: dict[str, float] = {}
        self._agent_alerted: set[str] = set()

    # ------------------------------------------------------------------
    # Inbound — called by the agent-health route on each POST
    # ------------------------------------------------------------------

    async def record_report(self, body: dict) -> None:
        """Record an inbound supervisor heartbeat and reconcile per-agent
        bad-state timers. Fires a recovery notice if the supervisor was
        previously flagged silent."""
        now = self._clock()
        was_silent = self._supervisor_alerted

        self._last_report_at = now
        self._last_report = body or {}
        self._ever_reported = True

        agents = (self._last_report.get("agents") or {})
        for name, info in agents.items():
            status = (info or {}).get("status")
            if status in _BAD_STATUSES:
                self._agent_bad_since.setdefault(name, now)
            else:
                # Agent recovered — clear its timers/flags.
                self._agent_bad_since.pop(name, None)
                self._agent_alerted.discard(name)

        if was_silent:
            self._supervisor_alerted = False
            await self._safe_alert(
                title="Desktop agents back online",
                body="Agent supervisor is reporting again — desktop presence, "
                     "screen-sync and emotion capture recovered.",
                kind="recovery",
            )

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def poll_loop(self) -> None:
        while True:
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("agent_health check iteration failed")
            await asyncio.sleep(CHECK_INTERVAL_S)

    async def check(self) -> None:
        """One evaluation pass. Separated from the loop for testability."""
        now = self._clock()

        # ── 1. Supervisor silence ───────────────────────────────────────
        # Only meaningful once we've heard from it at least once — a fresh
        # backend boot with a desktop that's legitimately off shouldn't alarm.
        if self._ever_reported and self._last_report_at is not None:
            silent_for = now - self._last_report_at
            if silent_for > SUPERVISOR_SILENT_SECONDS:
                if self._expected_offline():
                    # Desktop is *meant* to be off (sleeping / apartment empty).
                    # Clear the alerted flag so we don't emit a spurious
                    # "recovered" when it legitimately wakes later.
                    self._supervisor_alerted = False
                    return
                if not self._supervisor_alerted:
                    self._supervisor_alerted = True
                    mins = int(silent_for // 60)
                    await self._safe_alert(
                        title="Desktop agents offline",
                        body=(
                            f"Agent supervisor silent for {mins}m — desktop "
                            f"presence, screen-sync and emotion capture are "
                            f"down. Restart: schtasks /run /tn "
                            f"\"{RESPAWN_TASK_NAME}\""
                        ),
                        kind="alert",
                    )
                # While silent the per-agent data is stale — skip section 2.
                return

        # ── 2. Per-agent stuck (supervisor is reporting fresh) ──────────
        for name, since in list(self._agent_bad_since.items()):
            if name in self._agent_alerted:
                continue
            if now - since > AGENT_STUCK_SECONDS:
                self._agent_alerted.add(name)
                status = self._agent_status(name)
                mins = int((now - since) // 60)
                await self._safe_alert(
                    title=f"Desktop agent stuck: {name}",
                    body=(
                        f"{name} has been {status} for {mins}m — the "
                        f"supervisor's restart isn't clearing it."
                    ),
                    kind="alert",
                )

    # ------------------------------------------------------------------
    # Observability snapshot (for GET /api/automation/agent-health + /health)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        silent_for = (
            round(now - self._last_report_at, 1)
            if self._last_report_at is not None
            else None
        )
        online = (
            self._last_report_at is not None
            and (now - self._last_report_at) <= SUPERVISOR_SILENT_SECONDS
        )
        return {
            "online": online,
            "ever_reported": self._ever_reported,
            "silent_for_seconds": silent_for,
            "silent_threshold_seconds": SUPERVISOR_SILENT_SECONDS,
            "expected_offline": self._expected_offline(),
            "supervisor_alerted": self._supervisor_alerted,
            "stuck_agents": sorted(self._agent_bad_since),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _expected_offline(self) -> bool:
        """True when the desktop is *meant* to be offline, so silence is not an
        anomaly: sleeping mode (PC suspends after sleep entry) or the
        apartment-empty external-off state."""
        if getattr(self._engine, "current_mode", None) == "sleeping":
            return True
        return bool(getattr(self._engine, "_external_off_detected", False))

    def _agent_status(self, name: str) -> str:
        agents = (self._last_report or {}).get("agents") or {}
        return (agents.get(name) or {}).get("status", "?")

    async def _safe_alert(self, *, title: str, body: str, kind: str) -> None:
        try:
            await self._notifier.emit_alert(title=title, body=body, kind=kind)
            logger.warning("agent_health alert: %s — %s", title, body)
        except Exception:
            logger.exception("agent_health alert dispatch failed: %s", title)
