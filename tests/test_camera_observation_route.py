"""Focused tests for off-host physical presence ingestion."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.camera import PresenceObservation, post_observation
from backend.services.presence_fusion import PresenceFusion


@pytest.mark.asyncio
async def test_desktop_observation_reaches_occupancy_owner_after_fusion_ingest():
    presence = PresenceFusion()
    automation = SimpleNamespace(notify_presence_observation=AsyncMock())
    away_manager = SimpleNamespace(handle_presence_observation=AsyncMock())
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                presence=presence,
                automation=automation,
                away_manager=away_manager,
            )
        )
    )
    captured_at = datetime.now(timezone.utc)
    payload = PresenceObservation(
        source="desktop",
        captured_at=captured_at,
        face_present=True,
        face_confidence=0.8,
        detection_source="face",
        zone="desk",
    )

    result = await post_observation(payload, request)

    assert result == {"status": "ok"}
    reading = presence.get_source_reading("desktop")
    assert reading is not None
    automation.notify_presence_observation.assert_awaited_once_with(reading)
    away_manager.handle_presence_observation.assert_awaited_once_with(reading)
