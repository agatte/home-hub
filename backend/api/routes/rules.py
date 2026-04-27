"""
Rule engine endpoints — view, manage, and interact with learned rules.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.rules")

router = APIRouter(prefix="/api/rules", tags=["rules"])


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
        "last_suggestion": service.last_suggestion,
    }


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
    """Accept the current mode suggestion and apply it."""
    service = _get_service(request)
    suggestion = await service.accept_suggestion()
    if not suggestion:
        raise HTTPException(status_code=404, detail="No active suggestion")

    automation = request.app.state.automation
    remote = getattr(request.client, "host", None) or "unknown"
    await automation.set_manual_override(
        suggestion["predicted_mode"], source=f"rule_suggestion_accept:{remote}",
    )
    return {"status": "ok", "applied_mode": suggestion["predicted_mode"]}


@router.post("/suggestion/dismiss", dependencies=[Depends(require_api_key)])
async def dismiss_suggestion(request: Request) -> dict:
    """Dismiss the current mode suggestion."""
    service = _get_service(request)
    await service.dismiss_suggestion()
    return {"status": "ok"}
