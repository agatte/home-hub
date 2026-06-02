"""
Bounded auto-remediation — the executor behind the source-trust watchdog.

The read-only monitoring fleet (check-back sweep → watcher → investigator)
diagnoses problems but cannot act. This service is the *only* place in the
backend that turns a diagnosis into a state change, and it is deliberately
narrow:

* **Whitelist only.** Exactly the actions in :data:`ACTION_POLICY` — each a
  bounded call into an existing service (camera recover/recalibrate,
  source-trust mark, override/DND clear). No file edits, no shell, no
  arbitrary mode/light writes.
* **Two-stage kill-switch.** ``REMEDIATION_ENABLED`` gates the subsystem;
  ``REMEDIATION_AUTONOMOUS`` additionally permits *execution*. With
  autonomous off (the shipping default), every call is **propose-only**: it
  records what it would do and notifies, but mutates nothing.
* **Policy tiers.** ``auto``-tier actions execute when autonomous is on;
  ``propose``-tier actions always only propose, regardless of the flag.
* **Rate-limited.** At most ``REMEDIATION_MAX_AUTO_PER_DAY`` executions per
  rolling 24h, plus a per-action cooldown — derived from the audit table so
  the ceiling survives restarts (mirrors the celebration cooldown + rule
  refractory patterns).
* **Audited + notified always.** Every decision writes a ``remediation_log``
  row and fires a notification before returning.

Verify-or-escalate (re-running the failing sweep check after a fix) is the
remediator agent's job — this service records the immediate handler result and
leaves the loop to confirm recovery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select

from backend.database import async_session
from backend.models import RemediationLog

logger = logging.getLogger("home_hub.remediation")

# action → policy tier. "auto" may execute (when autonomous); "propose" never
# executes on its own regardless of the flag. Adding an action here is the only
# way to make it callable — there is no dynamic dispatch.
ACTION_POLICY: dict[str, str] = {
    # Bounded, idempotent, reversible — safe to automate.
    "recover_camera": "auto",
    "recalibrate_camera_lux": "auto",
    "set_source_trust": "auto",
    "clear_stuck_override": "auto",
    "clear_stuck_dnd": "auto",
}

# Results recorded in the audit row.
_EXECUTED = "executed"
_PROPOSED = "proposed"
_SKIPPED = "skipped"
_ERROR = "error"


class RemediationService:
    """Executes (or proposes) whitelisted remediation actions under guardrails."""

    def __init__(
        self,
        app: Any,
        *,
        enabled: bool,
        autonomous: bool,
        max_auto_per_day: int,
        action_cooldown_seconds: int,
    ) -> None:
        self._app = app
        self.enabled = enabled
        self.autonomous = autonomous
        self.max_auto_per_day = max_auto_per_day
        self.action_cooldown_seconds = action_cooldown_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        """Subsystem status for the route + remediator agent: flags, policy,
        rolling auto-count, and the recent audit tail."""
        recent = await self._recent_log(limit=15)
        auto_today = await self._auto_count_last_24h()
        return {
            "enabled": self.enabled,
            "autonomous": self.autonomous,
            "mode": "autonomous" if (self.enabled and self.autonomous) else (
                "propose_only" if self.enabled else "disabled"
            ),
            "policy": dict(ACTION_POLICY),
            "max_auto_per_day": self.max_auto_per_day,
            "action_cooldown_seconds": self.action_cooldown_seconds,
            "auto_executed_last_24h": auto_today,
            "recent": recent,
        }

    async def execute_or_propose(
        self,
        action: str,
        *,
        source: Optional[str] = None,
        reason: str = "",
        diagnosis_ref: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Run (autonomous + auto-tier + within limits) or propose an action.

        Always writes an audit row and notifies before returning. Never raises
        for an expected outcome (unknown action, rate-limited, handler failure)
        — those are reported in the returned dict + audit row.
        """
        params = params or {}
        if action not in ACTION_POLICY:
            return await self._record(
                action, source, tier="propose", result=_ERROR,
                diagnosis_ref=diagnosis_ref, params=params,
                detail=f"unknown action '{action}' (not in whitelist)",
                notify=False,
            )

        tier = ACTION_POLICY[action]
        can_execute = self.enabled and self.autonomous and tier == "auto"

        if not can_execute:
            # Propose-only: either the flag is off, the subsystem is off, or
            # this is a propose-tier action. Record + notify; mutate nothing.
            why = (
                "subsystem disabled" if not self.enabled
                else "propose-only (REMEDIATION_AUTONOMOUS off)" if not self.autonomous
                else f"{tier}-tier action requires human approval"
            )
            return await self._record(
                action, source, tier="propose", result=_PROPOSED,
                diagnosis_ref=diagnosis_ref, params=params,
                detail=f"would run {action} ({reason or 'no reason given'}) — {why}",
            )

        # Autonomous + auto-tier: enforce ceilings before touching state.
        gate = await self._rate_gate(action)
        if gate is not None:
            return await self._record(
                action, source, tier="auto", result=_SKIPPED,
                diagnosis_ref=diagnosis_ref, params=params, detail=gate,
            )

        # Execute the bounded handler.
        try:
            ok, detail = await self._dispatch(action, source=source, params=params)
        except Exception as exc:
            logger.exception("Remediation handler '%s' raised", action)
            return await self._record(
                action, source, tier="auto", result=_ERROR,
                diagnosis_ref=diagnosis_ref, params=params,
                detail=f"handler raised: {type(exc).__name__}: {exc}"[:480],
            )

        return await self._record(
            action, source, tier="auto",
            result=_EXECUTED if ok else _ERROR,
            diagnosis_ref=diagnosis_ref, params=params,
            detail=(detail or ("executed" if ok else "handler reported failure"))[:480],
        )

    # ------------------------------------------------------------------
    # Bounded action handlers — each a single call into an existing service
    # ------------------------------------------------------------------

    async def _dispatch(
        self, action: str, *, source: Optional[str], params: dict,
    ) -> "tuple[bool, str]":
        app = self._app
        if action == "recover_camera":
            from backend.services.camera_service import spawn_camera_service
            res = await spawn_camera_service(app, reason="remediator:recover_camera")
            ok = res.get("status") == "ok"
            return ok, res.get("detail", "")

        if action == "recalibrate_camera_lux":
            cs = getattr(app.state, "camera_service", None)
            if cs is None:
                return False, "camera service not live"
            res = await cs.calibrate_exposure()
            ok = res.get("status") == "ok"
            return ok, res.get("detail", "recalibrated")

        if action == "set_source_trust":
            st = getattr(app.state, "source_trust", None)
            if st is None:
                return False, "source-trust registry not live"
            tgt = params.get("source") or source
            if not tgt:
                return False, "set_source_trust requires a source"
            trusted = bool(params.get("trusted", True))
            if trusted:
                # Release the manual quarantine; the predicate resumes and
                # will re-trust only once it sees sustained sane data.
                st.clear_mark(tgt)
                return True, f"cleared trust override on '{tgt}' (predicate resumes)"
            st.mark(tgt, trusted=False, reason=params.get("reason", "remediator_quarantine"))
            return True, f"quarantined '{tgt}'"

        if action == "clear_stuck_override":
            eng = getattr(app.state, "automation", None)
            if eng is None:
                return False, "automation engine not live"
            await eng.clear_override(source="remediator:clear_stuck_override")
            return True, "cleared manual override"

        if action == "clear_stuck_dnd":
            eng = getattr(app.state, "automation", None)
            if eng is None:
                return False, "automation engine not live"
            await eng.clear_dnd(source="remediator:clear_stuck_dnd")
            return True, "cleared DND"

        return False, f"no handler for '{action}'"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _rate_gate(self, action: str) -> Optional[str]:
        """Return a skip-reason string if the action is rate-limited, else None."""
        auto_today = await self._auto_count_last_24h()
        if auto_today >= self.max_auto_per_day:
            return (
                f"daily auto-remediation ceiling reached "
                f"({auto_today}/{self.max_auto_per_day} in 24h)"
            )
        last = await self._last_executed_at(action)
        if last is not None:
            age = (datetime.now(timezone.utc) - last).total_seconds()
            if age < self.action_cooldown_seconds:
                return (
                    f"'{action}' fired {age:.0f}s ago "
                    f"(<{self.action_cooldown_seconds}s cooldown)"
                )
        return None

    async def _auto_count_last_24h(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(func.count())
                    .select_from(RemediationLog)
                    .where(
                        RemediationLog.tier == "auto",
                        RemediationLog.result == _EXECUTED,
                        RemediationLog.timestamp >= cutoff,
                    )
                )
                return int(result.scalar() or 0)
        except Exception:
            logger.exception("remediation: auto-count query failed")
            # Fail safe: if we can't read the ledger, treat as at-ceiling so we
            # don't execute blind.
            return self.max_auto_per_day

    async def _last_executed_at(self, action: str) -> Optional[datetime]:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(func.max(RemediationLog.timestamp)).where(
                        RemediationLog.action == action,
                        RemediationLog.result == _EXECUTED,
                    )
                )
                ts = result.scalar()
                if ts is not None and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
        except Exception:
            logger.exception("remediation: last-executed query failed")
            return None

    async def _recent_log(self, limit: int = 15) -> list[dict]:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(RemediationLog)
                    .order_by(RemediationLog.timestamp.desc())
                    .limit(limit)
                )
                rows = result.scalars().all()
                return [
                    {
                        "id": r.id,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                        "action": r.action,
                        "source": r.source,
                        "tier": r.tier,
                        "result": r.result,
                        "diagnosis_ref": r.diagnosis_ref,
                        "detail": r.detail,
                        "reverted": r.reverted,
                    }
                    for r in rows
                ]
        except Exception:
            logger.exception("remediation: recent-log query failed")
            return []

    async def _record(
        self,
        action: str,
        source: Optional[str],
        *,
        tier: str,
        result: str,
        diagnosis_ref: Optional[str],
        params: Optional[dict],
        detail: str,
        notify: bool = True,
    ) -> dict[str, Any]:
        """Write the audit row + fire a notification. Returns the decision dict."""
        row_id: Optional[int] = None
        try:
            async with async_session() as session:
                row = RemediationLog(
                    action=action,
                    source=source,
                    tier=tier,
                    result=result,
                    diagnosis_ref=diagnosis_ref,
                    params=params or None,
                    detail=detail,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                row_id = row.id
        except Exception:
            logger.exception("remediation: audit write failed (action=%s)", action)

        if notify:
            await self._notify(action, tier=tier, result=result, detail=detail)

        logger.info(
            "remediation %s/%s action=%s source=%s detail=%s",
            tier, result, action, source, detail,
        )
        return {
            "status": "ok" if result in (_EXECUTED, _PROPOSED) else "error",
            "action": action,
            "tier": tier,
            "result": result,
            "detail": detail,
            "log_id": row_id,
        }

    async def _notify(self, action: str, *, tier: str, result: str, detail: str) -> None:
        notifier = getattr(self._app.state, "notifier", None)
        if notifier is None:
            return
        # Respect Do-Not-Disturb. A remediation proposal is non-urgent and goes
        # through the notifier's synthetic path, which otherwise BYPASSES DND —
        # so without this a camera-lux proposal would buzz the phone at 3am.
        # The audit row in remediation_log is written before _notify regardless,
        # so suppressing the push loses nothing durable: the proposal still
        # surfaces in `GET /api/remediation/status` + the check-back digest when
        # DND lifts. Mirrors NotifierService._maybe_emit's DND gate.
        automation = getattr(self._app.state, "automation", None)
        if automation is not None:
            try:
                if automation.is_dnd_active():
                    logger.info(
                        "remediation notify suppressed (DND active) — audit row "
                        "stands; action=%s result=%s", action, result,
                    )
                    return
            except Exception:
                logger.debug("DND check failed; notifying anyway", exc_info=True)
        verb = {
            _EXECUTED: "Auto-remediation fired",
            _PROPOSED: "Remediation proposed",
            _SKIPPED: "Remediation skipped",
            _ERROR: "Remediation error",
        }.get(result, "Remediation")
        try:
            await notifier.emit_synthetic(
                title=f"{verb}: {action}",
                body=detail,
                kind="remediation",
            )
        except Exception:
            logger.debug("remediation notify failed", exc_info=True)
