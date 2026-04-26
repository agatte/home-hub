"""
Tests for the SSRF allowlist that gates ``sonos.play_uri``.

The allowlist is built once at module import from ``settings.LOCAL_IP``,
so the unit tests use that value directly rather than monkeypatching
(monkeypatching the setting wouldn't recompile the regex tuple).

Two layers are exercised:

1. ``is_allowed_play_uri`` — pure predicate; covers the patterns and
   common bypass attempts (suffix injection, exotic schemes, empty input).
2. ``POST /api/music/preview`` — route smoke; confirms a non-allowlisted
   URL is rejected with 400 before it ever reaches the speaker.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.services.sonos_service import is_allowed_play_uri


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestIsAllowedPlayUri:
    """Unit tests for the predicate itself."""

    def test_itunes_apple_subdomain_allowed(self):
        assert is_allowed_play_uri(
            "https://audio-ssl.itunes.apple.com/itunes-assets/preview.m4a"
        )

    def test_mzstatic_subdomain_allowed(self):
        assert is_allowed_play_uri("https://a1.mzstatic.com/some/preview.mp3")

    def test_local_ip_with_port_allowed(self):
        # TTS path: http://{LOCAL_IP}:8000/static/tts/foo.mp3
        uri = f"http://{settings.LOCAL_IP}:8000/static/tts/foo.mp3"
        assert is_allowed_play_uri(uri)

    def test_local_ip_without_port_allowed(self):
        uri = f"http://{settings.LOCAL_IP}/static/anything.mp3"
        assert is_allowed_play_uri(uri)

    def test_local_ip_case_insensitive_scheme(self):
        uri = f"HTTP://{settings.LOCAL_IP}:8000/static/tts/foo.mp3"
        assert is_allowed_play_uri(uri)

    def test_other_lan_ip_rejected(self):
        # Operator with a different LOCAL_IP must not be implicitly trusted.
        # Pick an address that is unlikely to ever match LOCAL_IP.
        other = "10.255.255.254"
        assert other != settings.LOCAL_IP
        assert not is_allowed_play_uri(f"http://{other}:8000/static/x.mp3")

    def test_arbitrary_https_rejected(self):
        assert not is_allowed_play_uri("https://evil.com/preview.mp3")

    def test_suffix_injection_rejected(self):
        # The leading subdomain pattern is anchored with `^https://...\.itunes.apple.com/`,
        # so a host like itunes.apple.com.evil.com must not match.
        assert not is_allowed_play_uri("https://itunes.apple.com.evil.com/x.mp3")
        assert not is_allowed_play_uri("https://mzstatic.com.evil.com/x.mp3")

    def test_apex_itunes_apple_rejected(self):
        # The pattern requires a subdomain of itunes.apple.com (matches the
        # real preview hosts like audio-ssl.itunes.apple.com). Apex-only
        # URLs aren't a real source and shouldn't be implicitly trusted.
        assert not is_allowed_play_uri("https://itunes.apple.com/preview.mp3")

    def test_http_itunes_rejected(self):
        # Plain http:// to apple is not on the list; preview URLs are https.
        assert not is_allowed_play_uri(
            "http://audio-ssl.itunes.apple.com/preview.m4a"
        )

    def test_file_scheme_rejected(self):
        assert not is_allowed_play_uri("file:///etc/passwd")

    def test_gopher_scheme_rejected(self):
        assert not is_allowed_play_uri("gopher://internal.host/_admin")

    def test_empty_string_rejected(self):
        assert not is_allowed_play_uri("")

    def test_none_safe(self):
        # Defensive: callers shouldn't pass None, but the predicate should
        # not raise. The route layer rejects empty/None on its own first,
        # but the service is the last line of defense.
        assert not is_allowed_play_uri(None)  # type: ignore[arg-type]


class TestPlayUriRouteAllowlist:
    """End-to-end: the /api/music/preview route enforces the allowlist."""

    def test_evil_url_rejected_with_400(self, client):
        resp = client.post(
            "/api/music/preview",
            json={"preview_url": "https://evil.com/x.mp3"},
        )
        assert resp.status_code == 400, resp.text
        assert "allowlist" in resp.json()["detail"].lower()

    def test_file_scheme_rejected_with_400(self, client):
        resp = client.post(
            "/api/music/preview",
            json={"preview_url": "file:///etc/passwd"},
        )
        assert resp.status_code == 400
        assert "allowlist" in resp.json()["detail"].lower()

    def test_missing_preview_url_still_400(self, client):
        # Pre-existing behavior — we want to confirm the allowlist guard
        # didn't displace the "preview_url is required" check.
        resp = client.post("/api/music/preview", json={})
        assert resp.status_code == 400
        assert "required" in resp.json()["detail"].lower()

    def test_valid_itunes_url_not_rejected_by_allowlist(self, client):
        # We can't assert 200 here — the test env's Sonos may not be
        # connected, in which case the route returns 503. We just need to
        # confirm the allowlist didn't bounce the request with 400.
        resp = client.post(
            "/api/music/preview",
            json={
                "preview_url": (
                    "https://audio-ssl.itunes.apple.com/itunes-assets/preview.m4a"
                )
            },
        )
        assert resp.status_code != 400, resp.text
