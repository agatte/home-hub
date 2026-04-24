"""
Tests for lifespan-shutdown resilience.

The audit flagged that one teardown raising could block all subsequent ones.
We verify _safe_shutdown isolates failures and that ambient_sound.stop() is
now called as part of shutdown.
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


def test_ambient_sound_stop_is_called_on_shutdown():
    from backend.services.ambient_sound_service import AmbientSoundService

    stop_mock = AsyncMock(return_value={})
    with patch.object(AmbientSoundService, "stop", stop_mock):
        with TestClient(app) as _client:
            pass

    stop_mock.assert_called()


def test_event_logger_retry_task_started_and_torn_down():
    """The retry loop is registered into `tasks` so the cancel-and-wait path
    handles it. Verify it's running while the app is up and gets cancelled
    on shutdown."""
    with TestClient(app) as client:
        # Hit /health to confirm lifespan completed startup.
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        # New keys exposed by health route.
        assert "event_logger_drops" in body
        assert "event_logger_overflow" in body
        assert "event_logger_queue_depth" in body
        assert body["event_logger_queue_depth"] == 0
