"""
Tests for lifespan-shutdown resilience.

The audit flagged that one teardown raising could block all subsequent ones.
We verify _safe_shutdown isolates failures and that Ambient uses its
no-device-mutation shutdown path.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def test_one_close_failing_does_not_block_others(caplog):
    """Patch hue_v2.close to raise; assert rec_service.close still ran."""
    rec_close = AsyncMock()
    hue_v2_close = AsyncMock(side_effect=RuntimeError("boom"))

    # We can't easily patch instance methods on services that aren't
    # instantiated yet, so we patch _safe_shutdown's behavior via the
    # close attributes after lifespan startup. Instead, patch on the class.
    from backend.services.hue_v2_service import HueV2Service
    from backend.services.recommendation_service import RecommendationService

    with patch.object(HueV2Service, "close", hue_v2_close), \
         patch.object(RecommendationService, "close", rec_close):
        with TestClient(app) as _client:
            pass  # context manager exit triggers shutdown

    hue_v2_close.assert_called()
    rec_close.assert_called()


def test_ambient_sound_and_tts_close_are_called_on_shutdown():
    """Verify both service closers with one complete, real app lifespan."""
    from backend.services.ambient_sound_service import AmbientSoundService
    from backend.services.tts_service import TTSService

    shutdown_mock = AsyncMock(return_value=None)
    close_mock = AsyncMock(return_value=None)
    with patch.object(AmbientSoundService, "shutdown", shutdown_mock), \
         patch.object(TTSService, "close", close_mock):
        with TestClient(app) as _client:
            pass

    shutdown_mock.assert_called()
    close_mock.assert_called()


def test_event_logger_retry_and_heartbeat_registry_during_lifespan():
    """Verify retry-task setup/teardown and poll-loop registration together.

    Both contracts use the same healthy startup and /health response; sharing
    that *one* real lifespan avoids redundant setup without bypassing it.
    The context manager exit still exercises task cancellation and shutdown.
    """
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()

        # The retry loop is registered and has an initially empty queue.
        assert "event_logger_drops" in body
        assert "event_logger_overflow" in body
        assert "event_logger_queue_depth" in body
        assert body["event_logger_queue_depth"] == 0

        # Always-on poll loops register before lifespan yields; camera is
        # opt-in and is covered separately. No Hue/Sonos connection required.
        names = {t["name"] for t in body["tasks"]}
        required = {
            "automation",
            "scheduler",
            "rule_engine",
            "transit_lighting",
            "event_logger_retry",
        }
        assert required.issubset(names), f"missing: {required - names}"
        assert body["status"] == "healthy"
        assert body["tasks_stale"] == []
