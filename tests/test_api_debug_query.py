"""
Tests for the hardened /api/debug/query endpoint.

Covers two independent gates:

1. Statement validator — rejects non-SELECT/WITH queries with 400.
2. Engine-level read-only — even if validator is bypassed, the
   underlying SQLite connection refuses every mutation.

Plus the row cap and a regression check that /api/debug/event-summary
still works with the new RO connection.
"""
from __future__ import annotations

import sqlite3

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from backend.api.routes.debug import (
    MAX_QUERY_ROWS,
    _RO_URI,
    _is_read_only_query,
)
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestIsReadOnlyQueryValidator:
    """Unit tests for the validator predicate."""

    def test_select_passes(self):
        assert _is_read_only_query("SELECT 1")

    def test_lowercase_select_passes(self):
        assert _is_read_only_query("select 1")

    def test_with_cte_passes(self):
        assert _is_read_only_query(
            "WITH x AS (SELECT 1 AS a) SELECT * FROM x"
        )

    def test_leading_whitespace_tolerated(self):
        assert _is_read_only_query("   \n\t SELECT 1")

    def test_leading_line_comment_tolerated(self):
        assert _is_read_only_query("-- pulled from the docs\nSELECT 1")

    def test_leading_block_comment_tolerated(self):
        assert _is_read_only_query("/* note */\nSELECT 1")

    def test_insert_rejected(self):
        assert not _is_read_only_query("INSERT INTO x VALUES (1)")

    def test_update_rejected(self):
        assert not _is_read_only_query("UPDATE x SET a = 1")

    def test_delete_rejected(self):
        assert not _is_read_only_query("DELETE FROM x")

    def test_drop_rejected(self):
        assert not _is_read_only_query("DROP TABLE x")

    def test_attach_rejected(self):
        assert not _is_read_only_query("ATTACH DATABASE 'foo.db' AS bar")

    def test_pragma_rejected(self):
        assert not _is_read_only_query("PRAGMA writable_schema = ON")

    def test_empty_string_rejected(self):
        assert not _is_read_only_query("")

    def test_whitespace_only_rejected(self):
        assert not _is_read_only_query("   \n  \t  ")

    def test_comment_only_rejected(self):
        # All-comment input has no real first token → reject.
        assert not _is_read_only_query("-- nothing here")
        assert not _is_read_only_query("/* nothing */")

    def test_select_after_comment_disguising_write(self):
        # Trying to hide UPDATE behind a comment still fails because the
        # validator strips the comment first; first real token is UPDATE.
        assert not _is_read_only_query("/* SELECT */ UPDATE x SET a = 1")


class TestQueryRouteValidator:
    """End-to-end: validator rejection comes back as 400."""

    def test_select_returns_200(self, client):
        # `SELECT 1` doesn't need a real table, runs against any RO conn.
        resp = client.get("/api/debug/query", params={"sql": "SELECT 1 AS one"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"] == [{"one": 1}]
        assert body["truncated"] is False

    def test_with_cte_returns_200(self, client):
        resp = client.get(
            "/api/debug/query",
            params={"sql": "WITH x AS (SELECT 1 AS a) SELECT * FROM x"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == [{"a": 1}]

    def test_insert_rejected_with_400(self, client):
        resp = client.get(
            "/api/debug/query",
            params={"sql": "INSERT INTO mode_playlists VALUES ('x')"},
        )
        assert resp.status_code == 400
        assert "SELECT" in resp.json()["detail"]

    def test_drop_rejected_with_400(self, client):
        resp = client.get(
            "/api/debug/query",
            params={"sql": "DROP TABLE mode_playlists"},
        )
        assert resp.status_code == 400

    def test_pragma_rejected_with_400(self, client):
        resp = client.get(
            "/api/debug/query",
            params={"sql": "PRAGMA writable_schema = ON"},
        )
        assert resp.status_code == 400


class TestEngineLevelReadOnly:
    """If the validator were bypassed, the engine would still refuse writes.

    These tests open the same RO URI the route uses and try to mutate
    directly — they MUST raise ``OperationalError(readonly)``. This is
    the load-bearing security guarantee; the validator is a clarity /
    early-error layer in front of it.
    """

    @pytest.mark.asyncio
    async def test_engine_refuses_create_table(self):
        async with aiosqlite.connect(_RO_URI, uri=True) as db:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                await db.execute(
                    "CREATE TABLE _hacker (id INTEGER PRIMARY KEY)"
                )
            assert "readonly" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_engine_refuses_delete(self):
        # DELETE without column references is the cleanest write-attempt
        # against a real table — INSERT/UPDATE would parse columns first
        # and fail with a schema error in environments whose dev DB lags
        # the canonical schema, masking the readonly-engine assertion.
        async with aiosqlite.connect(_RO_URI, uri=True) as db:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                await db.execute("DELETE FROM mode_playlists WHERE 1=0")
            assert "readonly" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_engine_refuses_drop(self):
        async with aiosqlite.connect(_RO_URI, uri=True) as db:
            with pytest.raises(sqlite3.OperationalError) as exc_info:
                await db.execute("DROP TABLE mode_playlists")
            assert "readonly" in str(exc_info.value).lower()


class TestRowCap:
    """Result sets > MAX_QUERY_ROWS are truncated and flagged."""

    def test_under_cap_not_truncated(self, client):
        # `WITH RECURSIVE` is a legitimate read query — and a tidy way to
        # produce N rows without touching the real schema.
        n = 5
        sql = (
            "WITH RECURSIVE cnt(x) AS ("
            "  SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < {}"
            ") SELECT x FROM cnt"
        ).format(n)
        resp = client.get("/api/debug/query", params={"sql": sql})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["result"]) == n
        assert body["truncated"] is False

    def test_over_cap_truncated(self, client):
        # Generate one more than the cap — server should clamp + flag.
        n = MAX_QUERY_ROWS + 50
        sql = (
            "WITH RECURSIVE cnt(x) AS ("
            "  SELECT 1 UNION ALL SELECT x+1 FROM cnt WHERE x < {}"
            ") SELECT x FROM cnt"
        ).format(n)
        resp = client.get("/api/debug/query", params={"sql": sql})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["result"]) == MAX_QUERY_ROWS
        assert body["truncated"] is True


class TestEventSummaryStillWorks:
    """Regression: /api/debug/event-summary uses the new RO connection."""

    def test_event_summary_returns_200(self, client):
        resp = client.get("/api/debug/event-summary", params={"days": 7})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["days"] == 7
        # Shape only — actual counts depend on whatever is in the dev DB.
        assert "mode_transitions" in body
        assert "light_adjustments" in body
        assert "sonos_events" in body
