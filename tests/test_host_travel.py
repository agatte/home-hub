from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.api import auth
from backend.api.routes import host
from backend.main import app


def _request(hostname: str, *, tunnel: bool = False) -> Request:
    headers = [(b"x-tunnel-origin", b"cloudflare")] if tunnel else []
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/host/travel",
        "headers": headers,
        "client": (hostname, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


def test_require_localhost_rejects_lan_and_tunnel_loopback():
    asyncio.run(auth.require_localhost(_request("127.0.0.1")))
    with pytest.raises(HTTPException) as lan:
        asyncio.run(auth.require_localhost(_request("192.168.86.30")))
    assert lan.value.status_code == 403
    with pytest.raises(HTTPException) as tunnel:
        asyncio.run(auth.require_localhost(_request("127.0.0.1", tunnel=True)))
    assert tunnel.value.status_code == 403


def test_host_status_reads_persistent_marker(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    with TestClient(app) as client:
        response = client.get("/api/host/status")
        assert response.status_code == 200
        assert response.json()["mode"] == "HOME"

        marker.write_text("2026-09-02T13:00:00-04:00 source=test\n", encoding="utf-8")
        response = client.get("/api/host/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "TRAVEL"
        assert payload["travel_marker"] is True
        assert "2026-09-02" in payload["entered_at"]


def test_enter_travel_acknowledges_before_detached_shutdown(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    monkeypatch.setattr(host, "_schedule_travel", lambda delay_seconds=1.5: "travel-test.service")

    invalidated = []
    fake_presence = SimpleNamespace(invalidate_source=lambda source: invalidated.append(source))
    with TestClient(app) as client:
        app.state.presence = fake_presence
        app.state.away_manager = None
        response = client.post("/api/host/travel")
    assert response.status_code == 200
    assert invalidated == ["latitude"]
    payload = response.json()
    assert payload["status"] == "arming"
    assert payload["mode"] == "TRAVEL"
    assert payload["helper_unit"] == "travel-test.service"
    assert "DNS" in payload["dns_warning"]


def test_schedule_travel_uses_detached_user_systemd(monkeypatch, tmp_path: Path):
    helper = tmp_path / "homehub-hostctl.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(host, "HOSTCTL", helper)
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(host.subprocess, "run", fake_run)
    unit = host._schedule_travel(2.0)
    command = seen["command"]
    assert command[:2] == ["systemd-run", "--user"]
    assert "--collect" in command
    assert "--no-block" in command
    assert str(helper) in command
    assert command[-4:] == [str(helper), "travel", "--delay", "2.0"]
    assert unit.startswith("home-hub-travel-enter-")


def test_hostctl_contract_keeps_ambient_parked_and_dns_out_of_scope():
    script = (host.PROJECT_ROOT / "scripts" / "homehub-hostctl.sh").read_text(encoding="utf-8")
    assert "disable --now" in script
    assert "home-hub-latitude-streaming.service" in script
    assert "home-hub-tunnel.service" in script
    assert "home-hub-kiosk-recycle.timer" in script
    assert "home-hub-ambient.service" in script
    assert "SUPPRESSED_UNITS" in script
    assert "enable --now home-hub-ambient.service" not in script
    assert "docker compose stop" not in script
    assert "Google/Nest Wifi DNS failover is not changed" in script


def test_systemd_home_units_respect_travel_marker():
    condition = "ConditionPathExists=!%h/.local/state/home-hub/travel-mode"
    units = [
        "home-hub.service", "home-hub-tunnel.service",
        "home-hub-latitude-streaming.service", "home-hub-ambient.service",
        "home-hub-kiosk-recycle.service", "home-hub-kiosk-recycle.timer",
    ]
    for unit in units:
        body = (host.PROJECT_ROOT / "deployment" / unit).read_text(encoding="utf-8")
        assert condition in body


def test_deploy_respects_travel_marker():
    script = (host.PROJECT_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    expected = 'TRAVEL_MARKER="$HOME/.local/state/home-hub/travel-mode"'
    assert expected in script
    assert "Travel Mode is active" in script


def test_travel_helper_is_armed_before_graceful_departure(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    events = []
    monkeypatch.setattr(host, "_schedule_travel", lambda delay_seconds=5.0: events.append("armed") or "travel-test.service")

    class FakeAway:
        async def handle_event(self, event, source):
            events.append("away")
            return "ok"

    with TestClient(app) as client:
        app.state.away_manager = FakeAway()
        app.state.presence = SimpleNamespace(invalidate_source=lambda source: events.append("invalidate"))
        response = client.post("/api/host/travel")
    assert response.status_code == 200
    assert events[0] == "armed"
    assert events.index("armed") < events.index("away")
