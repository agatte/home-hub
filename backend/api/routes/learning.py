"""ML learning endpoints — model status, decisions, and manual controls."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.ml")

router = APIRouter(prefix="/api/learning", tags=["learning"])


class AudioDecisionReport(BaseModel):
    """Payload from the ambient monitor's YAMNet classifier."""

    predicted_mode: str
    confidence: float
    applied: bool = False
    factors: Optional[dict] = None


def _get_model_manager(request: Request):
    """Get ModelManager from app state."""
    mgr = getattr(request.app.state, "model_manager", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="ML services not initialized")
    return mgr


def _get_ml_logger(request: Request):
    """Get MLDecisionLogger from app state."""
    ml_log = getattr(request.app.state, "ml_logger", None)
    if ml_log is None:
        raise HTTPException(status_code=503, detail="ML logger not initialized")
    return ml_log


def _get_lighting_learner(request: Request):
    """Get LightingPreferenceLearner from app state."""
    learner = getattr(request.app.state, "lighting_learner", None)
    if learner is None:
        raise HTTPException(status_code=503, detail="Lighting learner not initialized")
    return learner


# ------------------------------------------------------------------
# Status
# ------------------------------------------------------------------


@router.get("/status")
async def get_status(request: Request) -> dict:
    """Return health and status of all ML models."""
    mgr = _get_model_manager(request)
    lighting = getattr(request.app.state, "lighting_learner", None)
    predictor = getattr(request.app.state, "behavioral_predictor", None)
    bandit = getattr(request.app.state, "music_bandit", None)
    audio_clf = getattr(request.app.state, "audio_classifier", None)

    return {
        "status": "ok",
        "models": mgr.get_health(),
        "lighting_learner": lighting.get_status() if lighting else None,
        "behavioral_predictor": (
            predictor.get_status() if predictor and hasattr(predictor, "get_status") else None
        ),
        "music_bandit": bandit.get_status() if bandit else None,
        "audio_classifier": audio_clf.get_status() if audio_clf else None,
    }


# ------------------------------------------------------------------
# Decisions
# ------------------------------------------------------------------


@router.get("/decisions")
async def get_decisions(request: Request, limit: int = 20) -> dict:
    """Return recent ML decisions."""
    ml_log = _get_ml_logger(request)
    decisions = await ml_log.get_recent(limit=min(limit, 100))
    return {"status": "ok", "decisions": decisions, "total": len(decisions)}


@router.get("/accuracy")
async def get_accuracy(request: Request, days: int = 7) -> dict:
    """Return prediction accuracy over a time window."""
    ml_log = _get_ml_logger(request)
    accuracy = await ml_log.compute_accuracy(days=min(days, 90))
    return {"status": "ok", **accuracy}


@router.get("/compare")
async def compare_strategies(request: Request, days: int = 14) -> dict:
    """A/B comparison of fusion vs rule-engine vs process-priority accuracy.

    All three strategies are evaluated on the same fusion-decision row
    set (where ``actual_mode`` has been backfilled), so the comparison
    is apples-to-apples. Useful for deciding whether fusion actually
    beats the pre-fusion process-priority baseline.
    """
    ml_log = _get_ml_logger(request)
    window = max(1, min(days, 90))
    return {
        "status": "ok",
        "window_days": window,
        "strategies": await ml_log.compare_strategies(days=window),
    }


@router.get("/override-rate")
async def get_override_rate(
    request: Request, window_minutes: int = 5,
) -> dict:
    """Return user override rates at 7d and 30d windows.

    Phase 3 autonomy gate requires <2 overrides/day sustained 30 days.
    ``window_minutes`` defines how recent a preceding automation event
    must be for a manual switch to count as an "override" vs a cold
    manual choice.
    """
    ml_log = _get_ml_logger(request)
    window = max(1, min(window_minutes, 60))
    return {
        "status": "ok",
        "window_minutes": window,
        "7d": await ml_log.compute_override_rate(days=7, window_minutes=window),
        "30d": await ml_log.compute_override_rate(days=30, window_minutes=window),
    }


# ------------------------------------------------------------------
# Audio classifier (shadow mode logging)
# ------------------------------------------------------------------


@router.post("/audio-decision", dependencies=[Depends(require_api_key)])
async def log_audio_decision(body: AudioDecisionReport, request: Request) -> dict:
    """Log a YAMNet audio classification decision from the ambient monitor.

    Called by the standalone ambient_monitor.py process to record
    shadow-mode (or active-mode) classification results for accuracy
    comparison against the RMS-based detector.
    """
    ml_log = _get_ml_logger(request)
    await ml_log.log_decision(
        predicted_mode=body.predicted_mode,
        confidence=body.confidence,
        decision_source="audio_ml",
        factors=body.factors,
        applied=body.applied,
    )
    return {"status": "ok"}


# ------------------------------------------------------------------
# Lighting learner
# ------------------------------------------------------------------


@router.get("/lighting")
async def get_lighting_preferences(request: Request) -> dict:
    """Return current learned lighting preferences."""
    learner = _get_lighting_learner(request)
    return {
        "status": "ok",
        "preferences": learner._preferences,
        **learner.get_status(),
    }


@router.post("/lighting/recalculate", dependencies=[Depends(require_api_key)])
async def recalculate_lighting(request: Request) -> dict:
    """Trigger immediate recalculation of lighting preferences."""
    learner = _get_lighting_learner(request)
    await learner.recalculate()
    return {"status": "ok", **learner.get_status()}


# ------------------------------------------------------------------
# Behavioral predictor
# ------------------------------------------------------------------


def _get_predictor(request: Request):
    """Get BehavioralPredictor from app state."""
    predictor = getattr(request.app.state, "behavioral_predictor", None)
    if predictor is None:
        raise HTTPException(status_code=503, detail="Behavioral predictor not initialized")
    return predictor


@router.post("/predictor/promote", dependencies=[Depends(require_api_key)])
async def promote_predictor(request: Request) -> dict:
    """Promote behavioral predictor from shadow to active."""
    predictor = _get_predictor(request)
    if predictor._status == "active":
        return {"status": "ok", "detail": "Already active", **predictor.get_status()}
    predictor.promote()
    return {"status": "ok", "detail": "Promoted to active", **predictor.get_status()}


@router.post("/predictor/demote", dependencies=[Depends(require_api_key)])
async def demote_predictor(request: Request) -> dict:
    """Demote behavioral predictor from active back to shadow."""
    predictor = _get_predictor(request)
    if predictor._status == "shadow":
        return {"status": "ok", "detail": "Already in shadow mode", **predictor.get_status()}
    predictor.demote()
    return {"status": "ok", "detail": "Demoted to shadow", **predictor.get_status()}


@router.get("/predictor")
async def get_predictor_status(request: Request) -> dict:
    """Return detailed behavioral predictor status."""
    predictor = _get_predictor(request)
    return {"status": "ok", **predictor.get_status()}


# ------------------------------------------------------------------
# Music bandit
# ------------------------------------------------------------------


def _get_bandit(request: Request):
    """Get MusicBandit from app state."""
    bandit = getattr(request.app.state, "music_bandit", None)
    if bandit is None:
        raise HTTPException(status_code=503, detail="Music bandit not initialized")
    return bandit


@router.get("/bandit")
async def get_bandit_status(request: Request) -> dict:
    """Return music bandit status — arm counts, top picks per mode."""
    bandit = _get_bandit(request)
    return {"status": "ok", **bandit.get_status()}


@router.delete("/bandit/reset", dependencies=[Depends(require_api_key)])
async def reset_bandit(request: Request) -> dict:
    """Wipe bandit arm data and restart from cold priors."""
    bandit = _get_bandit(request)
    bandit._arms = {}
    bandit._total_selections = 0
    bandit._save()
    return {"status": "ok", "detail": "Music bandit reset to cold start"}


# ------------------------------------------------------------------
# Retrain / reset
# ------------------------------------------------------------------


@router.post("/retrain", dependencies=[Depends(require_api_key)])
async def retrain_all(request: Request) -> dict:
    """Trigger immediate retrain of all ML models."""
    mgr = _get_model_manager(request)
    await mgr.retrain_all()
    return {"status": "ok", "models": mgr.get_health()}


@router.post("/retune-weights", dependencies=[Depends(require_api_key)])
async def retune_weights(request: Request) -> dict:
    """Manually trigger the fusion weight-tuning job.

    Normally runs nightly at 3:30 AM. This endpoint exposes the same path
    for validation — e.g. after shipping a change to the factors payload,
    call this to confirm weights update without waiting for the cron.
    """
    ml_logger = getattr(request.app.state, "ml_logger", None)
    fusion = getattr(request.app.state, "confidence_fusion", None)
    if not ml_logger or not fusion:
        raise HTTPException(
            status_code=503,
            detail="ml_logger or confidence_fusion not initialized",
        )

    before = dict(fusion.get_state()["weights"])
    acc = await ml_logger.compute_accuracy_by_source(days=14)
    if acc:
        fusion.update_weights_from_accuracy(acc)
    after = dict(fusion.get_state()["weights"])
    return {
        "status": "ok",
        "applied": bool(acc),
        "window_days": 14,
        "accuracy_by_source": acc,
        "weights_before": before,
        "weights_after": after,
    }


@router.delete("/reset", dependencies=[Depends(require_api_key)])
async def reset_ml(request: Request) -> dict:
    """Wipe all ML models and decision/metric tables.

    Deletes model files in data/models/, clears ml_decisions and
    ml_metrics tables.  Does NOT delete event tables (those are
    system data, not ML-specific).
    """
    from sqlalchemy import delete

    from backend.database import async_session
    from backend.models import MLDecision, MLMetric

    mgr = _get_model_manager(request)

    # Delete all tracked models
    for name in list(mgr._meta.keys()):
        mgr.delete_model(name)

    # Clear ML tables
    try:
        async with async_session() as session:
            await session.execute(delete(MLDecision))
            await session.execute(delete(MLMetric))
            await session.commit()
    except Exception as exc:
        logger.error("Failed to clear ML tables: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Reload learners from empty state
    lighting = getattr(request.app.state, "lighting_learner", None)
    if lighting:
        lighting._preferences = {}

    return {"status": "ok", "detail": "All ML data wiped"}
