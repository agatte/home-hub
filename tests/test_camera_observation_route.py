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
    automation = SimpleNamespace(
        notify_presence_observation=AsyncMock(),
        notify_camera_commit=AsyncMock(),
    )
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
    automation.notify_camera_commit.assert_awaited_once_with()
    away_manager.handle_presence_observation.assert_awaited_once_with(reading)


@pytest.mark.asyncio
async def test_steady_desktop_desk_heartbeat_does_not_recompose_twice():
    presence = PresenceFusion()
    automation = SimpleNamespace(
        notify_presence_observation=AsyncMock(),
        notify_camera_commit=AsyncMock(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            presence=presence, automation=automation, away_manager=None,
        ))
    )

    first = PresenceObservation(
        source="desktop", captured_at=datetime.now(timezone.utc),
        face_present=True, face_confidence=0.8, detection_source="face",
        zone="desk", posture="upright",
    )
    await post_observation(first, request)
    automation.notify_camera_commit.assert_awaited_once_with()
    automation.notify_camera_commit.reset_mock()

    second = first.model_copy(update={
        "captured_at": datetime.now(timezone.utc),
        "face_confidence": 0.9,
    })
    await post_observation(second, request)

    automation.notify_camera_commit.assert_not_awaited()

@pytest.mark.asyncio
async def test_new_desktop_context_always_requests_authoritative_recompose():
    presence = PresenceFusion()
    automation = SimpleNamespace(
        notify_presence_observation=AsyncMock(),
        notify_camera_commit=AsyncMock(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            presence=presence, automation=automation, away_manager=None,
        ))
    )
    payload = PresenceObservation(
        source="desktop", captured_at=datetime.now(timezone.utc),
        face_present=True, face_confidence=0.9, detection_source="face",
        zone="desk", posture="upright",
    )

    await post_observation(payload, request)

    reading = presence.get_source_reading("desktop")
    automation.notify_presence_observation.assert_awaited_once_with(reading)
    # The engine/light applicator owns serialization against transient writers;
    # the route must not make a non-atomic celebration-active decision.
    automation.notify_camera_commit.assert_awaited_once_with()
