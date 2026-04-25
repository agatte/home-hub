"""
Tests for PlantAppService scheme validation.

The Plant App login posts email + password as JSON. Sending that
over plain HTTP exposes credentials to anything sniffing the LAN.
The service refuses to construct against http:// unless an explicit
escape hatch is set. These tests pin that contract.
"""
import logging

import pytest

from backend.services.plant_app_service import PlantAppService


class TestSchemeValidation:
    """Construction-time URL scheme rejection."""

    def test_https_url_constructs(self):
        svc = PlantAppService(
            api_url="https://plants.example.com",
            email="me@example.com",
            password="hunter2",
        )
        # Trailing slash is stripped by __init__.
        assert svc._api_url == "https://plants.example.com"
        assert svc._insecure is False

    def test_http_without_escape_hatch_raises(self):
        with pytest.raises(ValueError) as exc_info:
            PlantAppService(
                api_url="http://plants.example.com",
                email="me@example.com",
                password="hunter2",
            )
        msg = str(exc_info.value)
        # The error must name both the risk and the env var so the
        # operator can act on it without grepping the source.
        assert "cleartext" in msg
        assert "PLANT_APP_ALLOW_INSECURE" in msg

    def test_http_with_escape_hatch_constructs(self):
        svc = PlantAppService(
            api_url="http://plants.example.com",
            email="me@example.com",
            password="hunter2",
            allow_insecure=True,
        )
        assert svc._insecure is True

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError) as exc_info:
            PlantAppService(
                api_url="ftp://plants.example.com",
                email="me@example.com",
                password="hunter2",
            )
        assert "scheme" in str(exc_info.value).lower()

    def test_no_scheme_raises(self):
        # urlparse on "plants.example.com" yields scheme="" — must reject.
        with pytest.raises(ValueError):
            PlantAppService(
                api_url="plants.example.com",
                email="me@example.com",
                password="hunter2",
            )


class TestInsecureWarning:
    """When the escape hatch is on, _login must surface a warning."""

    @pytest.mark.asyncio
    async def test_insecure_login_emits_warning(self, caplog, monkeypatch):
        # Force the login path to bail before any network I/O — we only
        # care that the warning fires *before* the post is attempted.
        async def boom(*_a, **_kw):
            raise RuntimeError("network disabled in test")

        import httpx
        monkeypatch.setattr(
            httpx.AsyncClient, "post",
            lambda self, *a, **k: boom(),
        )

        svc = PlantAppService(
            api_url="http://plants.example.com",
            email="me@example.com",
            password="hunter2",
            allow_insecure=True,
        )

        with caplog.at_level(logging.WARNING, logger="home_hub.plant_app"):
            ok = await svc._login()
        assert ok is False
        # The warning fires every login attempt — that's the contract.
        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "cleartext" in r.message
        ]
        assert warning_records, "expected cleartext warning on insecure login"

    @pytest.mark.asyncio
    async def test_https_login_does_not_warn(self, caplog, monkeypatch):
        async def boom(*_a, **_kw):
            raise RuntimeError("network disabled in test")

        import httpx
        monkeypatch.setattr(
            httpx.AsyncClient, "post",
            lambda self, *a, **k: boom(),
        )

        svc = PlantAppService(
            api_url="https://plants.example.com",
            email="me@example.com",
            password="hunter2",
        )

        with caplog.at_level(logging.WARNING, logger="home_hub.plant_app"):
            await svc._login()
        # No cleartext-credentials warning on the secure path.
        for record in caplog.records:
            assert "cleartext" not in record.message
