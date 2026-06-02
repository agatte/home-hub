"""Bounded auto-remediation endpoints — status + action dispatch.

The remediator agent (and a human at the kiosk) reach the source-trust
remediation subsystem through here. ``GET /status`` is read-only; ``POST
/action`` is the single mutate path, gated by ``require_api_key`` and the
two-stage ``REMEDIATION_ENABLED`` / ``REMEDIATION_AUTONOMOUS`` kill-switch in
``RemediationService``. Every call writes a ``remediation_log`` row regardless
of outcome.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.auth import require_api_key, source_from_request

logger = logging.getLogger("home_hub.remediation")

router = APIRouter(prefix="/api/remediation", tags=["remediation"])


class RemediationAction(BaseModel):
    """Request body for POST /api/remediation/action."""

    action: str = Field(..., description="Whitelisted action name (see /status policy)")
    source: Optional[str] = Field(None, description="Target source, e.g. 'camera'")
    reason: str = Field("", description="Why this action — surfaced in the audit row")
    diagnosis_ref: Optional[str] = Field(
        None, description="Pointer to the digest warn / diagnosis that triggered this"
    )
    params: Optional[dict] = Field(None, description="Action-specific parameters")


@router.get("/status")
async def get_status(request: Request) -> dict[str, Any]:
    """Subsystem flags, policy, rolling auto-count, and recent audit tail."""
    svc = getattr(request.app.state, "remediation", None)
    if svc is None:
        return {"enabled": False, "autonomous": False, "mode": "disabled", "recent": []}
    return await svc.status()


@router.post("/action", dependencies=[Depends(require_api_key)])
async def post_action(body: RemediationAction, request: Request) -> dict[str, Any]:
    """Execute (autonomous + auto-tier) or propose a whitelisted action.

    503 when the subsystem is disabled — there is nothing to propose against.
    Otherwise always returns 200 with the decision (executed / proposed /
    skipped / error); the audit row + notification are written by the service.
    """
    svc = getattr(request.app.state, "remediation", None)
    if svc is None or not svc.enabled:
        raise HTTPException(
            status_code=503,
            detail="Remediation subsystem disabled (set REMEDIATION_ENABLED)",
        )
    # Stamp caller identity onto the diagnosis_ref trail when absent so the
    # audit row records who asked (remediator agent vs kiosk vs API).
    caller = source_from_request(request, fallback="api")
    return await svc.execute_or_propose(
        body.action,
        source=body.source,
        reason=body.reason,
        diagnosis_ref=body.diagnosis_ref or f"caller:{caller}",
        params=body.params,
    )
