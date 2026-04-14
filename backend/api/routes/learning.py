"""ML learning endpoints — model status, decisions, and manual controls."""

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("home_hub.ml")

router = APIRouter(prefix="/api/learning", tags=["learning"])


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

    return {
        "status": "ok",
        "models": mgr.get_health(),
        "lighting_learner": lighting.get_status() if lighting else None,
        "behavioral_predictor": (
            predictor.get_status() if predictor and hasattr(predictor, "get_status") else None
        ),
        "music_bandit": bandit.get_status() if bandit else None,
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


@router.post("/lighting/recalculate")
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


@router.post("/predictor/promote")
async def promote_predictor(request: Request) -> dict:
    """Promote behavioral predictor from shadow to active."""
    predictor = _get_predictor(request)
    if predictor._status == "active":
        return {"status": "ok", "detail": "Already active", **predictor.get_status()}
    predictor.promote()
    return {"status": "ok", "detail": "Promoted to active", **predictor.get_status()}


@router.post("/predictor/demote")
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


@router.delete("/bandit/reset")
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


@router.post("/retrain")
async def retrain_all(request: Request) -> dict:
    """Trigger immediate retrain of all ML models."""
    mgr = _get_model_manager(request)
    await mgr.retrain_all()
    return {"status": "ok", "models": mgr.get_health()}


@router.delete("/reset")
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
