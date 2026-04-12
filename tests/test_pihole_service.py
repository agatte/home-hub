"""
Tests for the Pi-hole service — auth, caching, response parsing.

Mocks httpx to avoid real Pi-hole API calls.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.pihole_service import PiholeService, SUMMARY_CACHE_TTL


def _make_service():
    return PiholeService(api_url="http://localhost:8080", api_key="test-pass")


def _mock_client(responses):
    """Create a mock httpx.AsyncClient that returns responses in order."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=responses)
    mock_client.post = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _ok_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    resp.content = b"ok"
    return resp


def _auth_response(valid=True):
    return _ok_response({
        "session": {"valid": valid, "sid": "test-sid-123", "csrf": "test-csrf"}
    })


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    """Test _authenticate() session management."""

    async def test_stores_sid_on_success(self):
        svc = _make_service()
        client = _mock_client([_auth_response(valid=True)])
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=client):
            result = await svc._authenticate()
        assert result is True
        assert svc._sid == "test-sid-123"
        assert svc._csrf == "test-csrf"

    async def test_returns_false_on_invalid(self):
        svc = _make_service()
        client = _mock_client([_auth_response(valid=False)])
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=client):
            result = await svc._authenticate()
        assert result is False

    async def test_returns_false_on_network_error(self):
        svc = _make_service()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc._authenticate()
        assert result is False


# ---------------------------------------------------------------------------
# Request with 401 retry
# ---------------------------------------------------------------------------

class TestRequest:
    """Test _request() auto-auth and 401 retry."""

    async def test_authenticates_on_first_call(self):
        svc = _make_service()
        assert svc._sid is None

        auth_resp = _auth_response(valid=True)
        data_resp = _ok_response({"queries": {"total": 100}})

        # First call: _authenticate (uses post), then _request (uses request)
        auth_client = _mock_client([auth_resp])
        data_client = _mock_client([data_resp])

        call_count = 0
        def client_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return auth_client
            return data_client

        with patch("backend.services.pihole_service.httpx.AsyncClient", side_effect=client_factory):
            result = await svc._request("GET", "/api/stats/summary")
        assert result is not None

    async def test_retries_on_401(self):
        svc = _make_service()
        svc._sid = "old-sid"

        unauthorized = MagicMock()
        unauthorized.status_code = 401

        auth_resp = _auth_response(valid=True)
        data_resp = _ok_response({"queries": {"total": 100}})

        call_count = 0
        def client_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First request client returns 401, then success after re-auth
                c = AsyncMock()
                c.request = AsyncMock(side_effect=[unauthorized, data_resp])
                c.__aenter__ = AsyncMock(return_value=c)
                c.__aexit__ = AsyncMock(return_value=False)
                return c
            # Auth client
            return _mock_client([auth_resp])

        with patch("backend.services.pihole_service.httpx.AsyncClient", side_effect=client_factory):
            result = await svc._request("GET", "/api/stats/summary")
        # Should have re-authenticated
        assert svc._sid == "test-sid-123"


# ---------------------------------------------------------------------------
# Summary caching
# ---------------------------------------------------------------------------

class TestSummary:
    """Test get_summary() caching and parsing."""

    async def test_returns_cache_when_fresh(self):
        svc = _make_service()
        svc._summary_cache = {"total_queries": 500, "cached": True}
        svc._summary_cache_time = time.time()
        result = await svc.get_summary()
        assert result["cached"] is True

    async def test_cache_expired_fetches(self):
        svc = _make_service()
        svc._summary_cache = {"old": True}
        svc._summary_cache_time = time.time() - SUMMARY_CACHE_TTL - 1
        svc._sid = "test-sid"

        api_data = {
            "queries": {"total": 1000, "blocked": 150, "percent_blocked": 15.0,
                        "unique_domains": 200, "forwarded": 500, "cached": 350},
            "gravity": {"domains_being_blocked": 2000000},
            "clients": {"active": 5, "total": 8},
        }
        data_client = _mock_client([_ok_response(api_data)])
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=data_client):
            result = await svc.get_summary()
        assert result["total_queries"] == 1000
        assert result["blocked"] == 150
        assert result["percent_blocked"] == 15.0
        assert result["domains_on_blocklist"] == 2000000

    async def test_stale_cache_on_failure(self):
        svc = _make_service()
        svc._summary_cache = {"total_queries": 500, "stale": True}
        svc._summary_cache_time = time.time() - SUMMARY_CACHE_TTL - 1
        svc._sid = "test-sid"

        fail_client = AsyncMock()
        fail_client.request = AsyncMock(side_effect=Exception("timeout"))
        fail_client.__aenter__ = AsyncMock(return_value=fail_client)
        fail_client.__aexit__ = AsyncMock(return_value=False)
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=fail_client):
            result = await svc.get_summary()
        assert result["stale"] is True


# ---------------------------------------------------------------------------
# DNS host parsing
# ---------------------------------------------------------------------------

class TestDnsHosts:
    """Test get_dns_hosts() response parsing."""

    async def test_parses_string_format(self):
        svc = _make_service()
        svc._sid = "test-sid"

        data = {"config": {"dns": {"hosts": ["192.168.1.210 homehub.local", "192.168.1.50 hue.local"]}}}
        client = _mock_client([_ok_response(data)])
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_dns_hosts()
        assert len(result) == 2
        assert result[0]["ip"] == "192.168.1.210"
        assert result[0]["hostname"] == "homehub.local"

    async def test_parses_dict_format(self):
        svc = _make_service()
        svc._sid = "test-sid"

        data = {"config": {"dns": {"hosts": [{"ip": "192.168.1.210", "hostname": "homehub.local"}]}}}
        client = _mock_client([_ok_response(data)])
        with patch("backend.services.pihole_service.httpx.AsyncClient", return_value=client):
            result = await svc.get_dns_hosts()
        assert len(result) == 1
        assert result[0]["ip"] == "192.168.1.210"


# ---------------------------------------------------------------------------
# Connected property
# ---------------------------------------------------------------------------

class TestConnected:
    """Test connected property."""

    def test_not_connected_initially(self):
        svc = _make_service()
        assert svc.connected is False

    def test_connected_after_cache(self):
        svc = _make_service()
        svc._summary_cache = {"total_queries": 100}
        assert svc.connected is True
