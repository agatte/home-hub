"""
Rule engine endpoints — view, manage, and interact with learned rules.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.rules")

router = APIRouter(prefix="/api/rules", tags=["rules"])

# Valid `status` query values for GET /suggestions. Matches the
# RuleSuggestion.status vocabulary in models.py.
_VALID_SUGGESTION_STATUSES = {
    "pending", "accepted", "dismissed", "expired", "superseded",
}


def _get_service(request: Request):
    """Get RuleEngineService from app state."""
    return request.app.state.rule_engine


class RuleUpdate(BaseModel):
    enabled: bool


@router.get("/")
async def list_rules(request: Request) -> dict:
    """List all learned rules."""
    service = _get_service(request)
    rules = await service.get_rules()
    return {"rules": rules, "total": len(rules)}


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Current rule engine status and active suggestion."""
    service = _get_service(request)
    rules = await service.get_rules()
    enabled = sum(1 for r in rules if r["enabled"])
    return {
        "total_rules": len(rules),
        "enabled_rules": enabled,
        "last_suggestion": await service.get_latest_pending(),
    }


@router.get("/suggestions")
async def list_suggestions(
    request: Request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Recent rule-suggestion fires, newest first. Backs Settings history view."""
    if status is not None and status not in _VALID_SUGGESTION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(_VALID_SUGGESTION_STATUSES)}",
        )
    service = _get_service(request)
    suggestions = await service.get_suggestion_history(status=status, limit=limit)
    return {"suggestions": suggestions, "total": len(suggestions)}


@router.post("/regenerate", dependencies=[Depends(require_api_key)])
async def regenerate_rules(request: Request) -> dict:
    """Force rule regeneration from event data."""
    service = _get_service(request)
    stats = await service.regenerate_rules()
    return {"status": "ok", **stats}


@router.patch("/{rule_id}", dependencies=[Depends(require_api_key)])
async def update_rule(rule_id: int, body: RuleUpdate, request: Request) -> dict:
    """Enable or disable a learned rule."""
    service = _get_service(request)
    result = await service.update_rule(rule_id, body.enabled)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return result


@router.delete("/{rule_id}", dependencies=[Depends(require_api_key)])
async def delete_rule(rule_id: int, request: Request) -> dict:
    """Delete a learned rule."""
    service = _get_service(request)
    deleted = await service.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "ok"}


@router.post("/suggestion/accept", dependencies=[Depends(require_api_key)])
async def accept_suggestion(request: Request) -> dict:
    """Accept the latest pending mode suggestion and apply it.

    Returns 410 Gone when the pending row was auto-expired or
    superseded between WS broadcast and the click — UI handles
    silently (optimistic dismiss).
    """
    service = _get_service(request)
    remote = getattr(request.client, "host", None) or "unknown"
    suggestion = await service.accept_suggestion(remote=remote)
    if not suggestion:
        raise HTTPException(
            status_code=410, detail="suggestion no longer pending",
        )

    automation = request.app.state.automation
    # IMPORTANT: do NOT append suggestion_id to the source string. The exact
    # value `rule_suggestion_accept:<remote>` is what bypasses the
    # USER_CLEAR_AUTO_PUSH_COOLDOWN gate (automation_engine.py:97) and what
    # analytics LIKE-match against. The suggestion_id lives on the
    # rule_suggestions row's resolved_source column.
    await automation.set_manual_override(
        suggestion["predicted_mode"], source=f"rule_suggestion_accept:{remote}",
    )
    return {"status": "ok", "applied_mode": suggestion["predicted_mode"]}


@router.post("/suggestion/dismiss", dependencies=[Depends(require_api_key)])
async def dismiss_suggestion(request: Request) -> dict:
    """Dismiss the latest pending mode suggestion. Idempotent (200 on no-op)."""
    service = _get_service(request)
    remote = getattr(request.client, "host", None) or "unknown"
    await service.dismiss_suggestion(remote=remote)
    return {"status": "ok"}
