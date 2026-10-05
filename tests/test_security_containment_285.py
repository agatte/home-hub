"""Focused regression coverage for GH #285 immediate containment."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.config import settings
from backend.main import _resolve_frontend_candidate, app, serve_frontend


@pytest.fixture
def frontend_root(tmp_path, monkeypatch):
    root = tmp_path / "build"
    root.mkdir()
    (root / "index.html").write_text("<html>HomeHub</html>", encoding="utf-8")
    (root / "app.js").write_text("packaged asset", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside secret", encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIST", root)
    return root


@pytest.fixture
def client(frontend_root, monkeypatch):
    # Preserve the real route order, but never start the hardware/bootstrap
    # lifecycle. Install the fallback even when no frontend build is present.
    test_app = FastAPI(routes=[
        route for route in app.routes
        if getattr(route, "endpoint", None) is not serve_frontend
    ])
    test_app.add_api_route("/{path:path}", serve_frontend, methods=["GET"])
    monkeypatch.setattr(settings, "HOME_HUB_API_KEY", "synthetic-test-key")
    with TestClient(test_app, client=("192.168.86.30", 12345)) as c:
        yield c


def test_frontend_candidate_accepts_packaged_asset_and_safe_missing_route(tmp_path):
    root = tmp_path / "build"
    root.mkdir()
    asset = root / "app.js"
    asset.write_text("ok", encoding="utf-8")

    assert _resolve_frontend_candidate("app.js", root) == asset.resolve()
    assert _resolve_frontend_candidate("settings/profile", root) == (
        root / "settings" / "profile"
    ).resolve()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "%2e%2e/outside.txt",
        "%252e%252e/outside.txt",
        "..\\outside.txt",
        "%255c%255coutside.txt",
        "/etc/passwd",
        "//server/share/file",
        "C:/Windows/win.ini",
        "C%3A/Windows/win.ini",
        "app.js:stream",
        "%00",
    ],
)
def test_frontend_candidate_rejects_traversal_and_absolute_forms(tmp_path, path):
    root = tmp_path / "build"
    root.mkdir()
    with pytest.raises(ValueError):
        _resolve_frontend_candidate(path, root)


def test_frontend_candidate_rejects_prefix_sibling_escape(tmp_path):
    root = tmp_path / "build"
    sibling = tmp_path / "build-secret"
    root.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError):
        _resolve_frontend_candidate("../build-secret/secret.txt", root)


def test_frontend_candidate_rejects_symlink_escape(tmp_path):
    root = tmp_path / "build"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError):
        _resolve_frontend_candidate("escape/secret.txt", root)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", [
    "/api", "/api/", "/api/auth", "/api/not-a-homehub-route",
    "/api/pihole/not-a-route", "/admin", "/admin/", "/admin/api.php",
])
def test_unknown_api_and_former_pihole_proxy_paths_are_terminal_404(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 404
    if method != "HEAD":
        assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/", "/settings/network", "/analytics", "/missing.js"])
def test_safe_spa_routes_still_serve_index(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>HomeHub</html>"


def test_packaged_asset_is_served(client):
    response = client.get("/app.js")
    assert response.status_code == 200
    assert response.text == "packaged asset"


@pytest.mark.parametrize("path", [
    "/%2e%2e/secret.txt", "/%252e%252e/secret.txt",
    "/%2e%2e%5csecret.txt", "/%252e%252e%255csecret.txt",
    "/%2Fetc/passwd", "/C%3A/Windows/win.ini", "/app.js%3Astream", "/%00",
])
def test_unsafe_file_requests_return_404_not_spa(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "outside secret" not in response.text


@pytest.mark.parametrize("link_name,path", [
    ("escape.txt", "/escape.txt"), ("index.html", "/settings/network"),
])
def test_file_and_fallback_symlink_escapes_are_rejected(client, frontend_root, link_name, path):
    link = frontend_root / link_name
    # Only disposable files in this test's build root are replaced.
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(frontend_root.parent / "secret.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    assert client.get(path).status_code == 404


def test_typed_pihole_routes_remain_registered():
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/pihole/stats" in route_paths
    assert "/api/pihole/dns" in route_paths
    assert "/admin/{path:path}" in route_paths
    assert not any(
        getattr(route, "endpoint", None)
        and getattr(route.endpoint, "__module__", "") == "backend.api.routes.pihole_proxy"
        for route in app.routes
    )


def test_typed_pihole_reads_and_writes_still_work(client):
    service = MagicMock()
    service.get_summary = AsyncMock(return_value={"total_queries": 42})
    service.get_dns_hosts = AsyncMock(return_value=[])
    service.add_dns_host = AsyncMock()
    client.app.state.pihole_service = service
    assert client.get("/api/pihole/stats").json()["pihole"] == {"total_queries": 42}
    assert client.get("/api/pihole/dns").json()["dns_hosts"] == []
    response = client.post("/api/pihole/dns", json={"ip": "192.168.86.99", "hostname": "test.lan"})
    assert response.status_code == 200
    service.add_dns_host.assert_awaited_once_with("192.168.86.99", "test.lan")


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "synthetic-test-key"}])
def test_desktop_snapshot_diagnostic_job_flow_is_disabled(client, headers):
    diagnostic_paths = {
        "/api/camera/desktop/snapshot/request",
        "/api/camera/desktop/snapshot/pending",
        "/api/camera/desktop/snapshot/upload",
        "/api/camera/desktop/snapshot/latest",
    }
    registered_paths = {getattr(route, "path", None) for route in app.routes}
    assert diagnostic_paths.isdisjoint(registered_paths)

    assert client.post("/api/camera/desktop/snapshot/request", headers=headers).status_code == 404
    assert client.get("/api/camera/desktop/snapshot/pending", headers=headers).status_code == 404
    assert client.post(
        "/api/camera/desktop/snapshot/upload", headers=headers,
        files={"image": ("frame.jpg", b"synthetic image", "image/jpeg")},
    ).status_code == 404
    assert client.get("/api/camera/desktop/snapshot/latest", headers=headers).status_code == 404


def test_non_diagnostic_desktop_camera_routes_remain_registered():
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/camera/observation" in route_paths
    assert "/api/camera/desktop/lux" in route_paths
    assert "/api/camera/desktop/lux/calibration" in route_paths


def test_private_lan_presence_and_lux_ingestion_still_work_without_key(client):
    presence = MagicMock()
    presence.latest_zone.return_value = None
    presence.latest_posture.return_value = None
    channel = MagicMock()
    client.app.state.presence = presence
    client.app.state.bedroom_lux = channel
    captured_at = datetime.now(timezone.utc).isoformat()

    response = client.post("/api/camera/observation", json={
        "source": "desktop", "captured_at": captured_at, "face_present": True,
        "face_confidence": 0.9, "detection_source": "face", "zone": "desk",
    })
    assert response.status_code == 200
    reading = presence.on_observation.call_args.args[0]
    assert reading.source == "desktop"
    assert reading.zone == "desk"
    assert reading.face_present is True

    response = client.post("/api/camera/desktop/lux", json={
        "ambient_lux": 75.0, "captured_at": captured_at,
    })
    assert response.status_code == 200
    channel.update.assert_called_once_with(
        75.0, captured_at=datetime.fromisoformat(captured_at),
    )
