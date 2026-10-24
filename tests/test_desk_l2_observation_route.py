"""#370 real producer read-only diagnostics; no light write or ownership mint."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from backend.api.auth import require_api_key_strict
from backend.api.routes.camera import (
    get_desktop_l2_observation_readiness as _read_route,
    router,
)
from backend.services.lux_channel import LuxChannel
from backend.services.presence_fusion import PresenceFusion, PresenceReading


async def get_desktop_l2_observation_readiness(request):
    response = Response()
    result = await _read_route(request, response)
    assert response.headers["Cache-Control"] == "no-store"
    return result


def request(*, presence=None, lux=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(presence=presence, bedroom_lux=lux))
    )


def reading(source, zone, *, age_s=0, detection_source="face"):
    return PresenceReading(
        source=source,
        zone=zone,
        face_present=True,
        detection_source=detection_source,
        captured_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )


def bedroom(*, room="bedroom", baseline=80.0, age_s=0):
    sample = LuxChannel(room, baseline_lux=baseline)
    sample.update(
        42.0,
        captured_at=datetime.now(timezone.utc) - timedelta(seconds=age_s),
    )
    return sample


def test_endpoint_requires_the_existing_protected_camera_auth():
    route = next(
        r
        for r in router.routes
        if getattr(r, "path", None) == "/api/camera/desktop/l2-observation-readiness"
    )
    assert "GET" in route.methods
    assert any(d.call is require_api_key_strict for d in route.dependant.dependencies)


@pytest.mark.asyncio
async def test_missing_sources_fail_closed_without_exposing_private_data():
    result = await get_desktop_l2_observation_readiness(request())
    assert result == {
        "status": "ok",
        "scope": "advisory_observation_only",
        "desktop_observation_ready": False,
        "bedroom_sample_ready": False,
        "reasons": ["desktop_unqualified", "bedroom_lux_unqualified"],
        "lighting_authorized": False,
    }
    assert "face" not in str(result)
    assert "lux" not in result


@pytest.mark.asyncio
async def test_actual_named_source_producers_visible_but_never_authorize_write():
    presence = PresenceFusion()
    desk = reading("desktop", "desk")
    presence.on_observation(desk)
    lux = bedroom()
    before = (presence.get_source_reading("desktop"), lux.status())

    result = await get_desktop_l2_observation_readiness(request(presence=presence, lux=lux))

    assert result["desktop_observation_ready"] is True
    assert result["bedroom_sample_ready"] is True
    assert result["reasons"] == []
    assert result["lighting_authorized"] is False
    assert (presence.get_source_reading("desktop"), lux.status()) == before


@pytest.mark.asyncio
async def test_strong_latitude_couch_conflict_drops_desktop_without_dropping_lux():
    presence = PresenceFusion()
    presence.on_observation(reading("desktop", "desk"))
    presence.on_observation(reading("latitude", "couch", detection_source="yolo"))
    result = await get_desktop_l2_observation_readiness(request(presence=presence, lux=bedroom()))
    assert result["desktop_observation_ready"] is False
    assert result["bedroom_sample_ready"] is True
    assert result["reasons"] == ["opposing_physical_presence"]
    assert result["lighting_authorized"] is False


@pytest.mark.asyncio
async def test_stale_desktop_and_wrong_room_lux_abstain():
    presence = PresenceFusion()
    presence.on_observation(reading("desktop", "desk", age_s=25))
    result = await get_desktop_l2_observation_readiness(
        request(presence=presence, lux=bedroom(room="living-room"))
    )
    assert result["reasons"] == ["desktop_unqualified", "bedroom_lux_unqualified"]
    assert result["lighting_authorized"] is False


@pytest.mark.asyncio
async def test_future_timestamp_or_uncalibrated_lux_abstain():
    presence = PresenceFusion()
    presence.on_observation(reading("desktop", "desk", age_s=-30))
    result = await get_desktop_l2_observation_readiness(
        request(presence=presence, lux=bedroom(baseline=None))
    )
    assert result["reasons"] == ["desktop_unqualified", "bedroom_lux_unqualified"]


@pytest.mark.asyncio
async def test_unexpected_store_types_do_not_bypass_source_qualification():
    fake = SimpleNamespace(get_source_reading=lambda _source: reading("desktop", "desk"))
    fake_lux = SimpleNamespace(room="bedroom", calibrated=True)
    result = await get_desktop_l2_observation_readiness(request(presence=fake, lux=fake_lux))
    assert result["desktop_observation_ready"] is False
    assert result["bedroom_sample_ready"] is False
    assert result["lighting_authorized"] is False


@pytest.mark.asyncio
async def test_private_lan_http_access_is_key_gated_without_source_leak(monkeypatch):
    from backend.api import auth

    # Synthetic in-memory key only; no real secrets or configuration writes.
    monkeypatch.setattr(auth.settings, "HOME_HUB_API_KEY", "test-only-l2-key")
    app = FastAPI()
    app.include_router(router)
    app.state.presence = PresenceFusion()
    app.state.bedroom_lux = bedroom()
    app.state.presence.on_observation(reading("desktop", "desk"))

    transport = ASGITransport(app=app, client=("192.168.86.88", 41811))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/api/camera/desktop/l2-observation-readiness")
        assert unauthorized.status_code == 401
        assert "desktop_observation_ready" not in unauthorized.text
        assert "bedroom_sample_ready" not in unauthorized.text

        allowed = await client.get(
            "/api/camera/desktop/l2-observation-readiness",
            headers={"X-API-Key": "test-only-l2-key"},
        )
        assert allowed.status_code == 200
        assert allowed.headers.get("Cache-Control") == "no-store"
        assert allowed.json()["desktop_observation_ready"] is True
        assert allowed.json()["bedroom_sample_ready"] is True
        assert allowed.json()["lighting_authorized"] is False
