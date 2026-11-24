"""
Rule engine endpoints — view, manage, and interact with learned rules.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key
from backend.services.light_state_calculator import ALL_LIGHT_IDS
from backend.services.ws_manual_light_guard import dispatch_manual_light

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


def _brightness_targets(payload: dict) -> dict[str, int]:
    """Validate the entire suggestion before saving or dispatching any target."""
    if not isinstance(payload, dict):
        raise ValueError("invalid brightness payload")
    raw = payload.get("light_targets")
    if raw is None:
        raw = {str(payload["light_id"]): payload["suggested_bri"]} if (
            "light_id" in payload and "suggested_bri" in payload
        ) else {}
    if not isinstance(raw, dict) or not raw:
        raise ValueError("missing brightness targets")
    if any(
        type(light_id) is not str or light_id not in ALL_LIGHT_IDS
        or type(bri) is not int or not 1 <= bri <= 254
        for light_id, bri in raw.items()
    ):
        raise ValueError("invalid brightness target")
    if any(not isinstance(payload.get(key), str) or not payload[key]
           for key in ("mode", "period", "weather_class")):
        raise ValueError("missing brightness context")
    return dict(raw)


async def _apply_brightness_targets_now(
    request: Request,
    targets: dict[str, int],
    context_valid,
) -> dict:
    """Reuse the manual writer, including its final lease and owner fences."""
    hue = getattr(request.app.state, "hue", None)
    automation = getattr(request.app.state, "automation", None)
    event_logger = getattr(request.app.state, "event_logger", None)
    applied: list[dict] = []
    blocked: list[str] = []
    unavailable: list[str] = []
    uncertain: list[str] = []
    for light_id, bri in targets.items():
        state = {"bri": bri}
        try:
            result = await dispatch_manual_light(
                automation, hue, light_id, state, context_valid=context_valid,
            )
        except Exception:
            # An unexpected failure must not invite retry of a possibly sent write.
            logger.exception("Brightness suggestion dispatch outcome unknown")
            uncertain.append(light_id)
            continue
        if result.status != "acknowledged":
            if result.status == "denied":
                blocked.append(light_id)
            elif result.status == "unavailable":
                unavailable.append(light_id)
            else:
                uncertain.append(light_id)
            continue
        applied.append({"light_id": light_id, "bri": bri})
        if event_logger:
            before = result.before or {}
            try:
                await event_logger.log_light_adjustment(
                    light_id=light_id,
                    light_name=before.get("name"),
                    bri_before=before.get("bri"),
                    bri_after=bri,
                    mode_at_time=automation.current_mode if automation else None,
                    trigger="brightness_suggestion_accept",
                )
            except Exception:
                logger.warning("Brightness suggestion event log unavailable")
    return {"applied_now": applied, "blocked": blocked,
            "unavailable": unavailable, "uncertain": uncertain}


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


# ---------------------------------------------------------------------------

@router.post("/suggestion/accept/{sid}", dependencies=[Depends(require_api_key)])
async def accept_suggestion_by_id(sid: int, request: Request) -> dict:
    """Accept a specific pending mode suggestion and apply it."""
    service = _get_service(request)
    remote = getattr(request.client, "host", None) or "unknown"
    suggestion = await service.accept_suggestion_by_id(sid, remote=remote)
    if not suggestion:
        raise HTTPException(
            status_code=410, detail="suggestion no longer pending",
        )

    automation = request.app.state.automation
    await automation.set_manual_override(
        suggestion["predicted_mode"], source=f"rule_suggestion_accept:{remote}",
    )
    return {"status": "ok", "applied_mode": suggestion["predicted_mode"]}


@router.post("/suggestion/dismiss/{sid}", dependencies=[Depends(require_api_key)])
async def dismiss_suggestion_by_id(sid: int, request: Request) -> dict:
    """Dismiss a specific pending mode suggestion. Idempotent for callers."""
    service = _get_service(request)
    remote = getattr(request.client, "host", None) or "unknown"
    await service.dismiss_suggestion_by_id(sid, remote=remote)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Brightness-kind suggestions — addressable by id (ntfy.sh action targets
# need a stable URL per suggestion, can't always read "latest pending").
# ---------------------------------------------------------------------------


@router.post(
    "/brightness-suggestion/accept/{sid}",
    dependencies=[Depends(require_api_key)],
)
async def accept_brightness_suggestion(sid: int, request: Request) -> dict:
    """Accept a brightness suggestion. Writes a learned pref into the
    LightingLearner for the suggested bucket so the heuristic stops
    applying there and the learned value takes over.

    Returns 410 Gone when the row was auto-expired, superseded, or
    already-resolved between push and click — UI handles silently.
    """
    service = _get_service(request)
    learner = getattr(request.app.state, "lighting_learner", None)
    if learner is None:
        raise HTTPException(status_code=503, detail="Lighting learner unavailable")
    remote = getattr(request.client, "host", None) or "unknown"
    resolved = await service.accept_brightness_suggestion(
        suggestion_id=sid, remote=remote,
    )
    if not resolved:
        raise HTTPException(status_code=410, detail="suggestion no longer pending")
    if resolved.get("status") != "accepted":
        raise HTTPException(status_code=410, detail="suggestion context no longer active")

    payload = resolved.get("payload", {})
    try:
        targets = _brightness_targets(payload)
    except (TypeError, ValueError):
        # The suggestion has already been resolved. Do not retry or learn
        # a partial invalid target list.
        raise HTTPException(status_code=409, detail="Resolved suggestion has invalid targets; no lighting request sent") from None

    saved: list[str] = []
    preference_uncertain: list[str] = []
    preference_not_attempted: list[str] = []
    for light_id, bri in targets.items():
        if preference_uncertain:
            preference_not_attempted.append(light_id)
            continue
        try:
            await learner.write_learned_pref(
                light_id=light_id, mode=payload["mode"],
                time_period=payload["period"], weather_class=payload["weather_class"],
                bri=bri, zone_at_time=payload.get("zone_at_time"),
            )
            saved.append(light_id)
        except Exception:
            # Persistence can fail after a partial disk/in-memory change.
            # The resolved row is not retryable; stop and report uncertainty.
            logger.exception("Brightness suggestion preference write uncertain")
            preference_uncertain.append(light_id)

    if preference_uncertain:
        return {
            "status": "partial_failure", "applied": payload, "applied_now": [],
            "blocked": [], "unavailable": [], "uncertain": [],
            "not_attempted": list(targets),
            "preference_saved": saved, "preference_uncertain": preference_uncertain,
            "preference_not_attempted": preference_not_attempted,
        }

    result = await _apply_brightness_targets_now(
        request, targets, lambda: service.brightness_context_matches(payload),
    )
    partial = any(result[key] for key in ("blocked", "unavailable", "uncertain"))
    return {
        "status": "partial_failure" if partial else "ok",
        "applied": payload, **result, "not_attempted": [],
        "preference_saved": saved, "preference_uncertain": [],
        "preference_not_attempted": [],
    }


@router.post(
    "/brightness-suggestion/dismiss/{sid}",
    dependencies=[Depends(require_api_key)],
)
async def dismiss_brightness_suggestion(sid: int, request: Request) -> dict:
    """Dismiss a brightness suggestion by id. Idempotent (200 on no-op)."""
    service = _get_service(request)
    remote = getattr(request.client, "host", None) or "unknown"
    await service.dismiss_brightness_suggestion(
        suggestion_id=sid, remote=remote,
    )
    return {"status": "ok"}
