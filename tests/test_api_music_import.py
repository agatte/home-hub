"""
Tests for the POST /api/music/import upload guards.

The route gets its input as multipart/form-data. These tests monkeypatch
``MAX_IMPORT_BYTES`` down to small values so oversize cases can be tested
without allocating large buffers, and monkeypatch ``app.state.library_import``
to a stub so the happy-path doesn't need a real taste-profile write.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.routes import music as music_route
from backend.main import app


_VALID_PLIST_BODY = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
    b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    b'<plist version="1.0"><dict>'
    b"<key>Tracks</key><dict></dict>"
    b"<key>Playlists</key><array></array>"
    b"</dict></plist>\n"
)


class _StubImportService:
    """Records the path it was handed and returns canned stats."""

    def __init__(self) -> None:
        self.last_path: Path | None = None

    async def import_xml(self, path: Path) -> dict:
        self.last_path = path
        return {"track_count": 0, "artist_count": 0, "genre_count": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def stub_import_service(monkeypatch):
    stub = _StubImportService()
    monkeypatch.setattr(app.state, "library_import", stub, raising=False)
    return stub


def _post(client, body: bytes, content_type: str = "application/xml",
          filename: str = "library.xml"):
    return client.post(
        "/api/music/import",
        files={"file": (filename, body, content_type)},
    )


class TestImportGuards:
    def test_rejects_oversize_via_content_length(self, client, monkeypatch):
        """Body larger than the cap is rejected with 413."""
        monkeypatch.setattr(music_route, "MAX_IMPORT_BYTES", 1024)
        body = _VALID_PLIST_BODY + (b"A" * 2048)
        resp = _post(client, body)
        assert resp.status_code == 413
        assert "too large" in resp.json()["detail"].lower()

    def test_rejects_entity_declaration(self, client, stub_import_service):
        """Any <!ENTITY declaration in the payload is a 400 — blocks billion-laughs."""
        body = (
            b'<?xml version="1.0"?>\n'
            b'<!DOCTYPE plist [<!ENTITY lol "LOL">]>\n'
            b'<plist version="1.0"><dict></dict></plist>'
        )
        resp = _post(client, body)
        assert resp.status_code == 400
        assert "entity" in resp.json()["detail"].lower()
        # Never reached the parser.
        assert stub_import_service.last_path is None

    def test_rejects_wrong_content_type(self, client, stub_import_service):
        """A non-XML content type (e.g. application/zip) is a 400."""
        resp = _post(client, _VALID_PLIST_BODY, content_type="application/zip")
        assert resp.status_code == 400
        assert "content type" in resp.json()["detail"].lower()
        assert stub_import_service.last_path is None

    def test_rejects_non_xml_filename(self, client, stub_import_service):
        """Filename extension check (pre-existing) still fires."""
        resp = _post(client, _VALID_PLIST_BODY, filename="library.zip")
        assert resp.status_code == 400
        assert ".xml" in resp.json()["detail"].lower()
        assert stub_import_service.last_path is None

    def test_happy_path_small_plist_accepted(self, client, stub_import_service):
        """A valid small plist with matching content type reaches the service."""
        resp = _post(client, _VALID_PLIST_BODY)
        assert resp.status_code == 200
        assert resp.json() == {"track_count": 0, "artist_count": 0, "genre_count": 0}
        # The route wrote the temp file and handed it to our stub.
        assert stub_import_service.last_path is not None
        assert stub_import_service.last_path.name == "library_import.xml"
