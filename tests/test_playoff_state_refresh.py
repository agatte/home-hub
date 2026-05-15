"""
Tests for the Tuesday playoff-state refresh — GAMEDAY_SPEC §10.5.

Covers the pure-function `compute_playoff_state` parser (no I/O), plus a
smoke test on `refresh_playoff_state` with a mocked save_setting callable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.playoff_state_refresh import (
    PLAYOFF_STATE_KEY,
    REFRESH_HOUR_ET,
    REFRESH_MINUTE_ET,
    REFRESH_WEEKDAY,
    compute_playoff_state,
    refresh_playoff_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _final_game(*, colts_score: int, opp_score: int, season_type: int = 2) -> dict:
    """Build an ESPN-shaped event for a FINAL game with given scores."""
    return {
        "season": {"type": season_type},
        "competitions": [{
            "status": {"type": {"name": "STATUS_FINAL"}},
            "competitors": [
                {"team": {"id": "11"}, "score": str(colts_score)},
                {"team": {"id": "15"}, "score": str(opp_score)},
            ],
        }],
    }


def _scheduled_game(season_type: int = 2) -> dict:
    return {
        "season": {"type": season_type},
        "competitions": [{
            "status": {"type": {"name": "STATUS_SCHEDULED"}},
            "competitors": [
                {"team": {"id": "11"}, "score": "0"},
                {"team": {"id": "15"}, "score": "0"},
            ],
        }],
    }


# ---------------------------------------------------------------------------
# Schedule constants
# ---------------------------------------------------------------------------

class TestScheduleConstants:

    def test_tuesday_6am_et(self):
        """Spec §10.5 — Tuesday 06:00 ET refresh cadence."""
        assert REFRESH_HOUR_ET == 6
        assert REFRESH_MINUTE_ET == 0
        assert REFRESH_WEEKDAY == 1  # Mon=0, Tue=1


# ---------------------------------------------------------------------------
# compute_playoff_state — pure parser
# ---------------------------------------------------------------------------

class TestComputePlayoffState:

    def test_empty_schedule_zero_record(self):
        state = compute_playoff_state(
            [], today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [0, 0, 0]
        assert state["is_preseason"] is False
        assert state["season_week"] == 1

    def test_three_wins_two_losses(self):
        events = [
            _final_game(colts_score=24, opp_score=17),
            _final_game(colts_score=10, opp_score=27),
            _final_game(colts_score=31, opp_score=28),
            _final_game(colts_score=7, opp_score=21),
            _final_game(colts_score=20, opp_score=14),
        ]
        state = compute_playoff_state(
            events, today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [3, 2, 0]
        assert state["season_week"] == 6  # 5 played + 1

    def test_one_tie(self):
        events = [_final_game(colts_score=21, opp_score=21)]
        state = compute_playoff_state(
            events, today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [0, 0, 1]

    def test_preseason_games_excluded_from_record(self):
        """Preseason wins/losses shouldn't count toward the regular-season record."""
        events = [
            _final_game(colts_score=24, opp_score=10, season_type=1),  # preseason
            _final_game(colts_score=24, opp_score=10, season_type=1),  # preseason
            _final_game(colts_score=24, opp_score=10, season_type=2),  # regular
        ]
        state = compute_playoff_state(
            events, today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [1, 0, 0]

    def test_scheduled_games_excluded_from_record(self):
        events = [
            _final_game(colts_score=24, opp_score=10),
            _scheduled_game(),
            _scheduled_game(),
        ]
        state = compute_playoff_state(
            events, today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [1, 0, 0]
        # 1 played + 1 = season_week 2
        assert state["season_week"] == 2

    def test_august_is_preseason(self):
        state = compute_playoff_state(
            [], today=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        assert state["is_preseason"] is True
        assert state["season_week"] == 0

    def test_september_is_regular_season(self):
        state = compute_playoff_state(
            [], today=datetime(2026, 9, 15, tzinfo=timezone.utc),
        )
        assert state["is_preseason"] is False

    def test_state_shape_matches_spec(self):
        """All §10.5 keys present + reasonable types."""
        state = compute_playoff_state(
            [], today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert "playoff_probability" in state
        assert "division_gap_games" in state
        assert "is_eliminated" in state
        assert "record" in state
        assert "refreshed_at" in state
        assert "season_week" in state
        assert "is_preseason" in state
        # v1 ships with None for fields not yet wired
        assert state["playoff_probability"] is None
        assert state["division_gap_games"] is None
        assert state["is_eliminated"] is False
        assert isinstance(state["record"], list)
        assert len(state["record"]) == 3
        assert isinstance(state["refreshed_at"], str)

    def test_malformed_score_treated_as_zero(self):
        """Score that won't parse → 0; game shouldn't crash the parser."""
        bad_event = {
            "season": {"type": 2},
            "competitions": [{
                "status": {"type": {"name": "STATUS_FINAL"}},
                "competitors": [
                    {"team": {"id": "11"}, "score": "garbage"},
                    {"team": {"id": "15"}, "score": "17"},
                ],
            }],
        }
        state = compute_playoff_state(
            [bad_event], today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        # 0 vs 17 → loss
        assert state["record"] == [0, 1, 0]

    def test_missing_team_id_skipped(self):
        """Event with no Colts competitor (parser bug guard) — skip cleanly."""
        bad_event = {
            "season": {"type": 2},
            "competitions": [{
                "status": {"type": {"name": "STATUS_FINAL"}},
                "competitors": [
                    {"team": {"id": "20"}, "score": "24"},
                    {"team": {"id": "15"}, "score": "17"},
                ],
            }],
        }
        state = compute_playoff_state(
            [bad_event], today=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [0, 0, 0]


# ---------------------------------------------------------------------------
# refresh_playoff_state — I/O wrapper
# ---------------------------------------------------------------------------

class TestRefreshPlayoffState:

    @pytest.mark.asyncio
    async def test_persists_to_save_setting(self, monkeypatch):
        """End-to-end: mock HTTP + capture the save_setting call."""
        # Stub httpx.AsyncClient to return a fixed schedule.
        import httpx

        class _FakeResponse:
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        class _FakeClient:
            def __init__(self, *a, **kw): self._payload = {
                "events": [_final_game(colts_score=24, opp_score=10)],
            }
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url): return _FakeResponse(self._payload)

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

        captured: dict = {}
        async def fake_save(key: str, value: dict) -> None:
            captured["key"] = key
            captured["value"] = value

        result = await refresh_playoff_state(fake_save)

        assert captured["key"] == PLAYOFF_STATE_KEY
        assert captured["value"]["record"] == [1, 0, 0]
        assert result["record"] == [1, 0, 0]

    @pytest.mark.asyncio
    async def test_http_failure_returns_empty_no_write(self, monkeypatch):
        """If ESPN fetch fails, refresh logs + returns {} without persisting."""
        import httpx

        class _BoomClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url): raise httpx.HTTPError("boom")

        monkeypatch.setattr(httpx, "AsyncClient", _BoomClient)

        save_called = False
        async def fake_save(key, value):
            nonlocal save_called
            save_called = True

        result = await refresh_playoff_state(fake_save)
        assert result == {}
        assert save_called is False
