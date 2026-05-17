"""
Notification endpoints — verification + future settings surface.

Phase 1 ships a single ``POST /test`` endpoint that fires a synthetic
notification through the same dispatch path the autonomous triggers use
(WS broadcast + ntfy.sh push). Lets us verify end-to-end without waiting
for a real mode flip.

Phase 2/3 endpoints (silence-N-minutes, history, per-mode trigger rules)
land here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.auth import require_api_key

logger = logging.getLogger("home_hub.notification")

router = APIRouter(prefix="/api/notification", tags=["notification"])


@router.post("/test", dependencies=[Depends(require_api_key)])
async def fire_test_notification(request: Request) -> dict:
    """Fire a synthetic notification through the real dispatch path.

    Bypasses DND / coalesce / boot suppression so the test always fires.
    Returns the payload so the caller can verify the structure. The body
    can carry an optional ``{"title": "...", "body": "..."}`` to customize
    the message; missing keys fall back to defaults.
    """
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        raise HTTPException(
            status_code=503,
            detail="NotifierService not initialized",
        )

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        # Empty body / non-JSON is fine — fall back to defaults.
        pass

    title = (body or {}).get("title") or "Test notification"
    msg = (body or {}).get("body") or "Synthetic test fire"

    payload = await notifier.emit_synthetic(title=title, body=msg)
    return {"status": "ok", "payload": payload}
