"""
Tests for the Tuesday playoff-state refresh — GAMEDAY_SPEC §10.5.

Covers the pure-function `compute_playoff_state` parser (no I/O), plus a
smoke test on `refresh_playoff_state` with a mocked save_setting callable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.playoff_state_refresh import (
    _AFC_SOUTH_GROUP_ID,
    _SCHEDULE_URL,
    _STANDINGS_URL,
    PLAYOFF_STATE_KEY,
    REFRESH_HOUR_ET,
    REFRESH_MINUTE_ET,
    REFRESH_WEEKDAY,
    compute_playoff_state,
    nfl_season_year,
    parse_colts_division_standings,
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


def _standings_payload(*, wins=3, losses=2, ties=1, games_behind=0.5) -> dict:
    return {
        "id": str(_AFC_SOUTH_GROUP_ID),
        "name": "AFC South",
        "standings": {"entries": [
            {
                "team": {"id": "10", "displayName": "Tennessee Titans"},
                "stats": [
                    {"name": "wins", "value": 4},
                    {"name": "losses", "value": 2},
                    {"name": "ties", "value": 0},
                    {"name": "gamesBehind", "value": 0},
                ],
            },
            {
                "team": {"id": "11", "displayName": "Indianapolis Colts"},
                "stats": [
                    {"name": "wins", "value": wins},
                    {"name": "losses", "value": losses},
                    {"name": "ties", "value": ties},
                    {"name": "gamesBehind", "value": games_behind},
                ],
            },
            {
                "team": {"id": "30", "displayName": "Jacksonville Jaguars"},
                "stats": [
                    {"name": "wins", "value": 2},
                    {"name": "losses", "value": 3},
                    {"name": "ties", "value": 0},
                    {"name": "gamesBehind", "value": 1.5},
                ],
            },
            {
                "team": {"id": "34", "displayName": "Houston Texans"},
                "stats": [
                    {"name": "wins", "value": 1},
                    {"name": "losses", "value": 4},
                    {"name": "ties", "value": 0},
                    {"name": "gamesBehind", "value": 2.5},
                ],
            },
        ]},
    }


def _standings_payload_colts_lead_1_0() -> dict:
    payload = _standings_payload(wins=1, losses=0, ties=0, games_behind=0)
    rows = payload["standings"]["entries"]
    replacements = {
        "10": (0, 0, 0, 0.5),
        "30": (0, 0, 0, 0.5),
        "34": (0, 0, 0, 0.5),
    }
    for row in rows:
        team_id = row["team"]["id"]
        if team_id not in replacements:
            continue
        wins, losses, ties, gap = replacements[team_id]
        values = {stat["name"]: stat for stat in row["stats"]}
        values["wins"]["value"] = wins
        values["losses"]["value"] = losses
        values["ties"]["value"] = ties
        values["gamesBehind"]["value"] = gap
    return payload


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


class TestDivisionStandingsParser:

    def test_uses_verified_site_api_standings_endpoint(self):
        assert _STANDINGS_URL == (
            "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
        )

    def test_extracts_colts_record_and_division_gap(self):
        assert parse_colts_division_standings(_standings_payload()) == ([3, 2, 1], 0.5)

    def test_missing_colts_degrades_to_none(self):
        payload = _standings_payload()
        payload["standings"]["entries"][1]["team"]["id"] = "30"
        assert parse_colts_division_standings(payload) is None

    def test_malformed_numeric_fields_degrade_to_none(self):
        assert parse_colts_division_standings(_standings_payload(wins="not-a-number")) is None

    def test_wrong_group_provenance_degrades_to_none(self):
        payload = _standings_payload()
        payload["id"] = "8"
        payload["name"] = "AFC"
        assert parse_colts_division_standings(payload) is None

    def test_incomplete_division_degrades_to_none(self):
        payload = _standings_payload()
        payload["standings"]["entries"].pop()
        assert parse_colts_division_standings(payload) is None

    def test_duplicate_division_row_degrades_to_none(self):
        payload = _standings_payload()
        payload["standings"]["entries"].append(
            payload["standings"]["entries"][1].copy()
        )
        assert parse_colts_division_standings(payload) is None

    def test_negative_games_behind_degrades_to_none(self):
        assert parse_colts_division_standings(
            _standings_payload(games_behind=-0.5)
        ) is None

    def test_non_half_game_games_behind_degrades_to_none(self):
        assert parse_colts_division_standings(
            _standings_payload(games_behind=0.1)
        ) is None

    def test_cross_entry_inconsistent_gap_degrades_to_none(self):
        payload = _standings_payload(wins=3, losses=2, ties=0, games_behind=0)
        assert parse_colts_division_standings(payload) is None

    def test_january_and_february_use_previous_nfl_season(self):
        assert nfl_season_year(datetime(2027, 1, 15, tzinfo=timezone.utc)) == 2026
        assert nfl_season_year(datetime(2027, 2, 15, tzinfo=timezone.utc)) == 2026
        assert nfl_season_year(datetime(2026, 9, 1, tzinfo=timezone.utc)) == 2026


class TestComputePlayoffStateContinued:

    def test_postseason_final_does_not_change_regular_season_record(self):
        events = [
            _final_game(colts_score=24, opp_score=17, season_type=2),
            _final_game(colts_score=14, opp_score=21, season_type=3),
        ]
        state = compute_playoff_state(
            events, today=datetime(2027, 1, 15, tzinfo=timezone.utc),
        )
        assert state["record"] == [1, 0, 0]
        assert state["season_week"] == 2

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
        """End-to-end: ESPN uses default headers and persists its result."""
        # Stub httpx.AsyncClient to return a fixed schedule.
        import httpx

        class _FakeResponse:
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        class _FakeClient:
            init_kwargs: dict = {}
            get_kwargs: dict = {}
            get_calls: list[tuple[str, dict]] = []

            def __init__(self, *args, **kwargs):
                self.__class__.init_kwargs = kwargs
                self._schedule_payload = {"events": [_final_game(colts_score=24, opp_score=10)]}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                self.__class__.get_kwargs = kwargs
                self.__class__.get_calls.append((url, kwargs))
                if url == _STANDINGS_URL:
                    return _FakeResponse(_standings_payload_colts_lead_1_0())
                return _FakeResponse(self._schedule_payload)

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

        captured: dict = {}
        async def fake_save(key: str, value: dict) -> None:
            captured["key"] = key
            captured["value"] = value

        result = await refresh_playoff_state(
            fake_save, today=datetime(2027, 1, 15, tzinfo=timezone.utc),
        )

        assert captured["key"] == PLAYOFF_STATE_KEY
        assert captured["value"]["record"] == [1, 0, 0]
        assert captured["value"]["division_gap_games"] == 0
        assert result["record"] == [1, 0, 0]
        assert "headers" not in _FakeClient.init_kwargs
        assert _FakeClient.get_calls == [
            (_SCHEDULE_URL, {"params": {"season": 2026, "seasontype": 2}}),
            (
                _STANDINGS_URL,
                {
                    "params": {
                        "season": 2026,
                        "seasontype": 2,
                        "group": _AFC_SOUTH_GROUP_ID,
                    }
                },
            ),
        ]

    @pytest.mark.asyncio
    async def test_mismatched_standings_record_is_ignored(self, monkeypatch):
        import httpx

        class _FakeResponse:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                if url == _STANDINGS_URL:
                    return _FakeResponse(
                        _standings_payload(wins=0, losses=2, ties=1, games_behind=2.5)
                    )
                return _FakeResponse(
                    {"events": [_final_game(colts_score=24, opp_score=10)]}
                )

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
        captured = {}
        async def fake_save(key, value): captured["value"] = value

        result = await refresh_playoff_state(fake_save)
        assert result["record"] == [1, 0, 0]
        assert result["division_gap_games"] is None
        assert captured["value"] == result

    @pytest.mark.asyncio
    async def test_standings_failure_persists_schedule_fallback(self, monkeypatch):
        import httpx

        class _FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"events": [_final_game(colts_score=24, opp_score=10)]}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                if url == _STANDINGS_URL:
                    raise httpx.HTTPError("standings boom")
                return _FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
        captured = {}
        async def fake_save(key, value): captured["value"] = value

        result = await refresh_playoff_state(fake_save)
        assert result["record"] == [1, 0, 0]
        assert result["division_gap_games"] is None
        assert captured["value"] == result

    @pytest.mark.asyncio
    async def test_malformed_standings_persists_schedule_fallback(self, monkeypatch):
        import httpx

        class _FakeResponse:
            def __init__(self, payload): self.payload = payload
            def raise_for_status(self): pass
            def json(self): return self.payload

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, url, **kwargs):
                if url == _STANDINGS_URL:
                    return _FakeResponse(_standings_payload(losses="bad"))
                return _FakeResponse({"events": [_final_game(colts_score=24, opp_score=10)]})

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
        captured = {}
        async def fake_save(key, value): captured["value"] = value

        result = await refresh_playoff_state(fake_save)
        assert result["record"] == [1, 0, 0]
        assert result["division_gap_games"] is None
        assert captured["value"] == result

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
