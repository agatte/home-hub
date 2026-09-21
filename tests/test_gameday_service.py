"""
Tests for GameDayService — schedule polling, play diffing, mode flips, parser.

Mocks httpx; mocks AutomationEngine + WebSocketManager. Real ESPN response
shapes are validated via tests/fixtures/espn_colts_2025_summary.json (Colts
vs Dolphins, 2025-09-07, sampled once for parser-quality validation per
spec §7).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from backend.services.gameday_service import (
    COLTS_TEAM_ID,
    GAMEDAY_AUTO_SOURCE,
    POST_GAME_CLEAR_MINUTES,
    PRE_GAME_AMBIENT_FLIP_MINUTES,
    PRE_KICKOFF_FLIP_MINUTES,
    PREGAMEDAY_AUTO_SOURCE,
    SCHEDULE_CACHE_TTL,
    SCHEDULE_RETRY_BACKOFFS,
    SUMMARY_RETRY_BACKOFFS,
    CurrentDrive,
    GameDayService,
    GameDayState,
    GameDayStateTransition,
    PlayEvent,
    _parse_espn_datetime,
    _play_event_payload,
)
from backend.services.websocket_manager import WebSocketManager
from backend.api.routes.gameday import (
    get_state as route_get_state,
    test_event as route_test_event,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "espn_colts_2025_summary.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


def _mock_client(responses: list[dict] | Exception) -> AsyncMock:
    """httpx.AsyncClient mock — sequential responses or single exception."""
    client = AsyncMock()
    if isinstance(responses, Exception):
        client.get = AsyncMock(side_effect=responses)
    else:
        client.get = AsyncMock(side_effect=[_mock_response(r) for r in responses])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _make_automation_mock(
    current_mode: str = "idle",
    override_source: str | None = None,
) -> AsyncMock:
    """AutomationEngine stand-in. set_manual_override / clear_override are
    AsyncMocks; current_mode + override_source are simple attributes the
    test can read after."""
    mock = MagicMock()
    mock.current_mode = current_mode
    mock.house_state = "home"
    mock.override_source = override_source
    mock.set_manual_override = AsyncMock()
    mock.clear_override = AsyncMock()
    return mock


def _make_ws_mock() -> MagicMock:
    ws = MagicMock()
    ws.broadcast = AsyncMock()
    return ws


def _make_service(automation=None, ws=None) -> GameDayService:
    return GameDayService(
        automation_engine=automation or _make_automation_mock(),
        ws_manager=ws or _make_ws_mock(),
    )


def _schedule_event(
    game_id: str,
    kickoff_iso: str,
    opponent_id: str = "15",
    opponent_name: str = "Miami Dolphins",
    status: str = "STATUS_SCHEDULED",
    colts_home: bool = True,
) -> dict:
    """Build an ESPN-shaped schedule event dict."""
    colts_home_away = "home" if colts_home else "away"
    opp_home_away = "away" if colts_home else "home"
    return {
        "id": game_id,
        "date": kickoff_iso,
        "name": f"{opponent_name} at Indianapolis Colts",
        "shortName": "MIA @ IND",
        "competitions": [
            {
                "status": {"type": {"name": status}},
                "competitors": [
                    {"team": {"id": COLTS_TEAM_ID, "displayName": "Indianapolis Colts"},
                     "homeAway": colts_home_away},
                    {"team": {"id": opponent_id, "displayName": opponent_name},
                     "homeAway": opp_home_away},
                ],
            }
        ],
    }


def _summary_payload(
    status_name: str = "STATUS_IN_PROGRESS",
    period: int = 2,
    clock: str = "5:32",
    score_colts: int = 14,
    score_opp: int = 7,
    plays: list[dict] | None = None,
) -> dict:
    """Build an ESPN-shaped /summary response."""
    if plays is None:
        plays = []
    return {
        "header": {
            "competitions": [
                {
                    "status": {
                        "type": {"name": status_name},
                        "period": period,
                        "clock": {"displayValue": clock},
                    },
                    "competitors": [
                        {"team": {"id": COLTS_TEAM_ID, "abbreviation": "IND"},
                         "score": str(score_colts)},
                        {"team": {"id": "15", "abbreviation": "MIA"},
                         "score": str(score_opp)},
                    ],
                }
            ]
        },
        "drives": {"previous": [{"plays": plays}]},
        "scoringPlays": [p for p in plays if p.get("scoringPlay")],
    }


def _td_play(play_id: str, text: str = "J.Taylor 5 yard run, TOUCHDOWN.") -> dict:
    return {
        "id": play_id,
        "text": text,
        "scoringPlay": True,
        "scoringType": {"abbreviation": "RUSH TD"},
        "type": {"text": "Rushing Touchdown"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 2},
        "clock": {"displayValue": "5:32"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _fg_play(play_id: str, text: str = "S.Shrader 24 yard field goal is GOOD.") -> dict:
    return {
        "id": play_id,
        "text": text,
        "scoringPlay": True,
        "scoringType": {"abbreviation": "FG"},
        "type": {"text": "Field Goal Good"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 1},
        "clock": {"displayValue": "10:37"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _safety_play(play_id: str = "s1") -> dict:
    """ESPN-shaped safety event. scoringType varies — sometimes SF, sometimes
    nothing; relying on either abbreviation or text fallback."""
    return {
        "id": play_id,
        "text": "Safety, tackled in end zone.",
        "scoringPlay": True,
        "scoringType": {"abbreviation": "SF"},
        "type": {"text": "Safety"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 2},
        "clock": {"displayValue": "0:42"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _pat_play(play_id: str = "p1") -> dict:
    return {
        "id": play_id,
        "text": "S.Shrader extra point is GOOD.",
        "scoringPlay": True,
        "scoringType": {"abbreviation": "PAT"},
        "type": {"text": "Extra Point Good"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 2},
        "clock": {"displayValue": "8:12"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _2pt_play(play_id: str = "tp1") -> dict:
    return {
        "id": play_id,
        "text": "Two-point conversion is GOOD.",
        "scoringPlay": True,
        "scoringType": {"abbreviation": "2PT"},
        "type": {"text": "Two Point Conversion"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 4},
        "clock": {"displayValue": "1:58"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _pick_six_play(play_id: str = "ps1") -> dict:
    """Pick-six: TD scoringType but text indicates an interception return."""
    return {
        "id": play_id,
        "text": "J.Sanders 32 Yd interception return for TOUCHDOWN.",
        "scoringPlay": True,
        "scoringType": {"abbreviation": "TD"},
        "type": {"text": "Defensive Touchdown"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 3},
        "clock": {"displayValue": "12:04"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


def _fumble_td_play(play_id: str = "ft1") -> dict:
    return {
        "id": play_id,
        "text": "Fumble recovered by D.Buckner, 18 Yd return for TOUCHDOWN.",
        "scoringPlay": True,
        "scoringType": {"abbreviation": "TD"},
        "type": {"text": "Defensive Touchdown"},
        "team": {"id": COLTS_TEAM_ID},
        "period": {"number": 2},
        "clock": {"displayValue": "6:21"},
        "wallclock": "2026-09-21T01:00:00Z",
    }


# ---------------------------------------------------------------------------
# Schedule + state
# ---------------------------------------------------------------------------

class TestSchedule:

    async def test_espn_requests_use_httpx_default_user_agent(self):
        svc = _make_service()
        svc._now_override = datetime(2026, 8, 31, tzinfo=timezone.utc)
        schedule_client = _mock_client([{"events": []}])
        summary_client = _mock_client([_summary_payload()])

        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            side_effect=[schedule_client, summary_client],
        ) as client_factory:
            await svc._refresh_schedule()
            await svc._fetch_summary("401001")

        assert client_factory.call_count == 2
        assert all(
            "headers" not in client_call.kwargs
            for client_call in client_factory.call_args_list
        )
        assert "headers" not in schedule_client.get.await_args.kwargs
        assert schedule_client.get.await_args.kwargs["params"] == {
            "season": 2026,
            "seasontype": 2,
        }
        assert "headers" not in summary_client.get.await_args.kwargs

    def test_schedule_query_uses_previous_nfl_season_in_january_and_february(self):
        svc = _make_service()
        for month in (1, 2):
            svc._now_override = datetime(2027, month, 15, tzinfo=timezone.utc)
            assert svc._schedule_query_params() == {"season": 2026, "seasontype": 2}

    async def test_no_game_returns_none(self):
        svc = _make_service()
        client = _mock_client([{"events": []}])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        assert svc.current_state() is None

    async def test_schedule_parsing(self):
        svc = _make_service()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([{
            "events": [
                _schedule_event("401001", future, opponent_name="Miami Dolphins"),
                _schedule_event("401002", future.replace("T", "T", 1),
                                opponent_name="Houston Texans"),
            ]
        }])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            upcoming = await svc.get_upcoming_schedule(limit=5)
        assert len(upcoming) == 2
        assert upcoming[0]["opponent"] == "Miami Dolphins"
        assert upcoming[0]["id"] == "401001"

    async def test_schedule_peek_never_refreshes_provider(self):
        svc = _make_service()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([{"events": [_schedule_event("401001", future)]}])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
        with patch("backend.services.gameday_service.httpx.AsyncClient") as provider:
            upcoming = svc.peek_upcoming_schedule(limit=1)
            assert not provider.called
        assert [game["id"] for game in upcoming] == ["401001"]

    async def test_cache_ttl(self):
        svc = _make_service()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%MZ")
        sched = {"events": [_schedule_event("401001", future)]}

        # First refresh hits httpx.
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client([sched]),
        ) as cm1:
            await svc.connect()
            assert cm1.called

        # Second refresh within TTL — should NOT hit httpx (no client created).
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
        ) as cm2:
            await svc._refresh_schedule_if_stale()
            assert not cm2.called

        # Expire the cache; next refresh hits httpx again.
        svc._schedule_cache_time = time.time() - SCHEDULE_CACHE_TTL - 1
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client([sched]),
        ) as cm3:
            await svc._refresh_schedule_if_stale()
            assert cm3.called


class TestProviderHealth:

    async def test_initial_schedule_failure_is_visible_without_blocking_connect(self):
        svc = _make_service()
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client(httpx.ConnectError("ESPN unavailable")),
        ):
            await svc.connect()

        health = svc.provider_health()
        assert svc.connected is True
        assert health["status"] == "healthy"
        assert health["degraded"] is False
        assert health["schedule"]["status"] == "unhealthy"
        assert health["schedule"]["consecutive_failures"] == 1
        assert health["schedule"]["last_error"] == "ESPN unavailable"
        assert svc._schedule_cache == []

    async def test_schedule_failures_back_off_and_cap_without_replacing_cache(self):
        svc = _make_service()
        cached = {"id": "cached"}
        svc._schedule_cache = [cached]
        svc._schedule_cache_time = 123.0
        failing_client = _mock_client(httpx.ConnectError("down"))
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=failing_client,
        ), patch("backend.services.gameday_service.time.time", return_value=1000.0):
            for _ in range(4):
                with pytest.raises(httpx.ConnectError):
                    await svc._refresh_schedule()

        assert svc._schedule_cache == [cached]
        assert svc._schedule_cache_time == 123.0
        assert svc._schedule_provider.consecutive_failures == 4
        assert svc._schedule_provider.next_eligible_retry == 1000.0 + SCHEDULE_RETRY_BACKOFFS[-1]

    async def test_schedule_retry_waits_until_its_backoff_expires(self):
        svc = _make_service()
        svc._schedule_cache_time = 0.0
        svc._schedule_provider.next_eligible_retry = time.time() + 60
        with patch("backend.services.gameday_service.httpx.AsyncClient") as client_factory:
            await svc._refresh_schedule_if_stale()
        client_factory.assert_not_called()

    async def test_schedule_recovery_resets_provider_failure_state(self):
        svc = _make_service()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%MZ")
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            side_effect=[
                _mock_client(httpx.ConnectError("down")),
                _mock_client([{"events": [_schedule_event("401001", future)]}]),
            ],
        ):
            with pytest.raises(httpx.ConnectError):
                await svc._refresh_schedule()
            await svc._refresh_schedule()

        lane = svc.provider_health()["schedule"]
        assert lane["status"] == "healthy"
        assert lane["consecutive_failures"] == 0
        assert lane["last_error"] is None
        assert lane["next_eligible_retry"] is None

        assert svc.provider_health()["status"] == "healthy"

    async def test_stale_scheduled_game_remains_live_selectable_after_kickoff(self):
        svc = _make_service()
        kickoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        svc._schedule_cache = [{
            "id": "401001", "kickoff_utc": kickoff, "opponent": "Miami Dolphins",
            "colts_are_home": True, "status": "STATUS_SCHEDULED",
        }]
        svc._schedule_cache_time = time.time()
        summary_client = _mock_client([_summary_payload()])
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient", return_value=summary_client,
        ):
            await svc._tick()

        assert svc.current_state() is not None
        assert svc.current_state().status == "in-progress"
        assert summary_client.get.await_count == 1

    async def test_first_live_summary_failure_keeps_fast_recovery_cadence(self):
        svc = _make_service()
        svc._schedule_cache = [{
            "id": "401001", "kickoff_utc": datetime.now(timezone.utc) - timedelta(minutes=1),
            "opponent": "Miami Dolphins", "colts_are_home": True,
            "status": "STATUS_SCHEDULED",
        }]
        svc._schedule_cache_time = time.time()
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client(httpx.ConnectError("summary down")),
        ):
            await svc._tick()

        assert svc._in_live_window() is True
        assert svc._summary_provider.consecutive_failures == 1
        assert svc._summary_provider.next_eligible_retry - time.time() <= SUMMARY_RETRY_BACKOFFS[0]

    async def test_stale_scheduled_cache_stops_live_cadence_after_same_game_final(self):
        """A final summary wins over stale schedule metadata for its own game."""
        svc = _make_service()
        kickoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        svc._schedule_cache = [{
            "id": "401001", "kickoff_utc": kickoff, "opponent": "Miami Dolphins",
            "colts_are_home": True, "status": "STATUS_SCHEDULED",
        }]
        svc._schedule_cache_time = time.time() - SCHEDULE_CACHE_TTL - 1

        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            side_effect=[
                _mock_client(httpx.ConnectError("schedule down")),
                _mock_client([_summary_payload(status_name="STATUS_FINAL")]),
            ],
        ):
            await svc._tick()

        assert svc.current_state() is not None
        assert svc.current_state().status == "final"
        assert svc._post_game_clear_task is not None
        assert svc._in_live_window() is False
        health = svc.provider_health()
        assert health["live_summary_required"] is False
        assert health["schedule"]["status"] == "unhealthy"

        svc._summary_provider.next_eligible_retry = 0.0
        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client(httpx.ConnectError("summary down")),
        ):
            await svc._tick()

        assert svc.current_state().status == "final"
        assert svc._summary_provider.status == "unhealthy"
        assert svc.provider_health()["live_summary_required"] is False
        await svc.close()

    def test_final_for_an_old_game_does_not_suppress_a_new_live_window(self):
        svc = _make_service()
        old_kickoff = datetime.now(timezone.utc) - timedelta(days=7)
        new_kickoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        svc._current_state = GameDayState(
            status="final", opponent="Houston Texans", kickoff_utc=old_kickoff,
            score_colts=24, score_opp=17, quarter=4, clock="", possession=None,
            last_play=None,
        )
        svc._schedule_cache = [{
            "id": "401002", "kickoff_utc": new_kickoff, "opponent": "Miami Dolphins",
            "colts_are_home": True, "status": "STATUS_SCHEDULED",
        }]

        assert svc._in_live_window() is True

    async def test_live_summary_failures_back_off_cap_and_recover(self):
        svc = _make_service()
        with patch("backend.services.gameday_service.time.time", return_value=1000.0):
            for _ in range(4):
                with patch(
                    "backend.services.gameday_service.httpx.AsyncClient",
                    return_value=_mock_client(httpx.ConnectError("down")),
                ):
                    assert await svc._fetch_summary("401001") is None
        assert svc._summary_provider.consecutive_failures == 4
        assert svc._summary_provider.next_eligible_retry == 1000.0 + SUMMARY_RETRY_BACKOFFS[-1]

        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=_mock_client([_summary_payload()]),
        ):
            assert await svc._fetch_summary("401001") is not None
        lane = svc.provider_health()["live_summary"]
        assert lane["status"] == "healthy"
        assert lane["consecutive_failures"] == 0
        assert lane["next_eligible_retry"] is None

    def test_cached_schedule_failure_degrades_provider_health(self):
        svc = _make_service()
        svc._schedule_cache = [{
            "id": "cached", "status": "STATUS_SCHEDULED",
            "kickoff_utc": datetime.now(timezone.utc) + timedelta(days=2),
        }]
        svc._record_provider_failure(
            svc._schedule_provider, RuntimeError("down"),
            SCHEDULE_RETRY_BACKOFFS, "schedule",
        )
        assert svc.provider_health()["status"] == "unhealthy"

    def test_provider_failure_logging_is_transition_and_escalation_only(self, caplog):
        svc = _make_service()
        caplog.set_level("WARNING", logger="home_hub.gameday")
        with patch("backend.services.gameday_service.time.time", return_value=1000.0):
            for _ in range(4):
                svc._record_provider_failure(
                    svc._schedule_provider, RuntimeError("down"),
                    SCHEDULE_RETRY_BACKOFFS, "schedule",
                )

        messages = [record.getMessage() for record in caplog.records]
        assert len(messages) == 3
        assert "failed" in messages[0]
        assert "escalated" in messages[1]
        assert "escalated" in messages[2]


# ---------------------------------------------------------------------------
# Play parsing
# ---------------------------------------------------------------------------

class TestPlayParser:

    def test_td_player_extracted(self):
        svc = _make_service()
        play = svc._parse_play(_td_play("1", text="J.Taylor 5 yard run, TOUCHDOWN."))
        assert play.play_type == "touchdown"
        assert play.player == "J.Taylor"
        assert play.scoring_team == "colts"

    def test_fg_kicker_and_yards_extracted(self):
        svc = _make_service()
        play = svc._parse_play(_fg_play("2", text="S.Shrader 38 yard field goal is GOOD."))
        assert play.play_type == "field_goal"
        assert play.kicker == "S.Shrader"
        assert play.yards == 38

    def test_unparseable_text_falls_back_to_none(self):
        svc = _make_service()
        play = svc._parse_play({
            "id": "x",
            "text": "Weird unparseable description",
            "scoringPlay": True,
            "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
        })
        assert play.play_type == "touchdown"
        assert play.player is None  # regex didn't match — graceful fallback

    # ------------------------------------------------- Slice C+ score subtypes

    def test_safety_parsed_by_abbreviation(self):
        svc = _make_service()
        play = svc._parse_play(_safety_play())
        assert play.play_type == "safety"
        assert play.scoring_team == "colts"

    def test_safety_parsed_by_text_when_abbrev_missing(self):
        svc = _make_service()
        raw = _safety_play()
        raw["scoringType"] = {}  # ESPN sometimes omits abbreviation
        play = svc._parse_play(raw)
        assert play.play_type == "safety"

    def test_extra_point_good_parsed(self):
        svc = _make_service()
        play = svc._parse_play(_pat_play())
        assert play.play_type == "extra_point_good"

    def test_two_point_conversion_parsed(self):
        svc = _make_service()
        play = svc._parse_play(_2pt_play())
        assert play.play_type == "two_point_conv"

    def test_pick_six_parsed_as_defensive_td(self):
        svc = _make_service()
        play = svc._parse_play(_pick_six_play())
        assert play.play_type == "defensive_td"
        assert play.scoring_team == "colts"

    def test_fumble_return_td_parsed_as_defensive_td(self):
        svc = _make_service()
        play = svc._parse_play(_fumble_td_play())
        assert play.play_type == "defensive_td"

    def test_offensive_td_still_parses_as_touchdown(self):
        """Defensive-TD branch must not steal offensive TDs.

        Order-of-check matters in _parse_play — a vanilla rushing TD has
        scoringType=TD but no 'interception' or 'fumble' in the text, so
        it should land in the offensive 'touchdown' branch.
        """
        svc = _make_service()
        play = svc._parse_play(_td_play("td_off", text="J.Taylor 12 Yd Rush"))
        assert play.play_type == "touchdown"

    def test_real_fixture_finds_scoring_plays(self):
        """Validates parser against a real 2025 Colts summary response.

        Spec §7 open question: "confirm during slice A that play.description
        reliably contains <player_name> for TD runs and <kicker_name> +
        <yards> for FG." This test answers that question against the
        2025-09-07 Colts vs Dolphins game.
        """
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)

        svc = _make_service()
        scoring_plays = summary.get("scoringPlays") or []
        assert len(scoring_plays) > 0, "fixture should have scoring plays"

        parsed_tds = []
        parsed_fgs = []
        for raw in scoring_plays:
            play = svc._parse_play(raw)
            if play.play_type == "touchdown":
                parsed_tds.append(play)
            elif play.play_type == "field_goal":
                parsed_fgs.append(play)

        # At least one TD with an extractable player name.
        td_with_player = [p for p in parsed_tds if p.player]
        assert td_with_player, (
            f"expected at least one TD with parseable player; "
            f"got TDs: {[(p.description, p.player) for p in parsed_tds]}"
        )

        # At least one FG with extractable kicker + yards.
        fg_with_kicker = [p for p in parsed_fgs if p.kicker and p.yards]
        assert fg_with_kicker, (
            f"expected at least one FG with parseable kicker+yards; "
            f"got FGs: {[(p.description, p.kicker, p.yards) for p in parsed_fgs]}"
        )


# ---------------------------------------------------------------------------
# Play diffing
# ---------------------------------------------------------------------------

class TestPlayDiffing:

    async def test_only_new_plays_emitted(self):
        svc = _make_service()
        # First tick — both plays are new.
        first = _summary_payload(plays=[
            _fg_play("p1"),
            _td_play("p2"),
        ])
        new_plays = svc._extract_new_plays(first)
        assert len(new_plays) == 2
        assert {p.play_type for p in new_plays} == {"touchdown", "field_goal"}

        # Second tick — same plays + one new TD. Only the new one fires.
        second = _summary_payload(plays=[
            _fg_play("p1"),
            _td_play("p2"),
            _td_play("p3", text="M.Pittman 12 yard pass, TOUCHDOWN."),
        ])
        new_plays = svc._extract_new_plays(second)
        assert len(new_plays) == 1
        assert new_plays[0].play_type == "touchdown"

    async def test_play_callback_receives_event(self):
        svc = _make_service()
        received: list[PlayEvent] = []

        async def cb(play):
            received.append(play)

        svc.register_on_play_event(cb)
        await svc._fire_play_event(
            PlayEvent(
                timestamp=datetime.now(timezone.utc),
                play_type="touchdown",
                description="test",
                player="J.Taylor", kicker=None, yards=None,
                scoring_team="colts",
            )
        )
        assert len(received) == 1
        assert received[0].play_type == "touchdown"

    async def test_synthetic_play_fires_callbacks(self):
        svc = _make_service()
        received: list[PlayEvent] = []

        async def cb(play):
            received.append(play)

        svc.register_on_play_event(cb)
        await svc.trigger_synthetic_play("touchdown")
        assert len(received) == 1
        assert received[0].description.startswith("[TEST]")


    @pytest.mark.parametrize(
        ("won", "expected_colts", "expected_opp"),
        [(True, 27, 20), (False, 20, 27)],
    )
    async def test_synthetic_final_uses_transition_path_and_restores_state(
        self, won, expected_colts, expected_opp,
    ):
        svc = _make_service()
        original = GameDayState(
            status="in-progress", opponent="Baltimore Ravens", kickoff_utc=None,
            score_colts=10, score_opp=7, quarter=2, clock="8:00",
            possession="colts", last_play=None,
        )
        svc._current_state = original
        observed: list[tuple[GameDayStateTransition, GameDayState | None]] = []

        async def cb(transition):
            observed.append((transition, svc.current_state()))

        svc.register_on_state_transition(cb)
        result = await svc.trigger_synthetic_final(won=won)

        assert len(observed) == 1
        transition, during = observed[0]
        assert transition.from_status == "in-progress"
        assert transition.to_status == "final"
        assert during is not None and during.status == "final"
        assert during.opponent == "Baltimore Ravens"
        assert (during.score_colts, during.score_opp) == (expected_colts, expected_opp)
        assert result["outcome"] == ("win" if won else "loss")
        assert svc.current_state() is original

    async def test_synthetic_final_is_task_local_and_cannot_clobber_live_state(self):
        svc = _make_service()
        original = GameDayState(
            status="in-progress", opponent="Baltimore Ravens", kickoff_utc=None,
            score_colts=10, score_opp=7, quarter=2, clock="8:00",
            possession="colts", last_play=None,
        )
        live_update = GameDayState(
            status="in-progress", opponent="Baltimore Ravens", kickoff_utc=None,
            score_colts=17, score_opp=14, quarter=3, clock="4:12",
            possession="opp", last_play=None,
        )
        svc._current_state = original
        entered = asyncio.Event()
        release = asyncio.Event()

        async def cb(_transition):
            during = svc.current_state()
            assert during is not None and during.status == "final"
            entered.set()
            await release.wait()

        svc.register_on_state_transition(cb)
        task = asyncio.create_task(svc.trigger_synthetic_final(won=True))
        await entered.wait()

        # The caller/poller task never sees synthetic state.
        assert svc.current_state() is original
        svc._current_state = live_update
        assert svc.current_state() is live_update

        release.set()
        await task

        assert svc.current_state() is live_update

    @pytest.mark.parametrize(
        ("event", "won"),
        [("end_of_game_win", True), ("end_of_game_loss", False)],
    )
    async def test_end_game_route_calls_synthetic_final_not_other_play(self, event, won):
        svc = MagicMock()
        svc.trigger_synthetic_final = AsyncMock(
            return_value={"outcome": "win" if won else "loss"}
        )
        svc.trigger_synthetic_play = AsyncMock()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(gameday=svc))
        )

        result = await route_test_event(event, request)

        assert result["event"] == event
        svc.trigger_synthetic_final.assert_awaited_once_with(won=won)
        svc.trigger_synthetic_play.assert_not_awaited()



# ---------------------------------------------------------------------------
# Event authority / restart hardening (#253)
# ---------------------------------------------------------------------------

class TestEventAuthorityHardening:

    async def test_restart_midgame_hydrates_history_before_any_callback(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        received: list[PlayEvent] = []

        async def cb(play):
            received.append(play)

        svc.register_on_play_event(cb)
        kickoff = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).strftime("%Y-%m-%dT%H:%MZ")
        schedule = {
            "events": [
                _schedule_event(
                    "restart-live",
                    kickoff,
                    status="STATUS_IN_PROGRESS",
                )
            ]
        }
        historical = _summary_payload(plays=[_fg_play("p1"), _td_play("p2")])
        next_poll = _summary_payload(
            plays=[
                _fg_play("p1"),
                _td_play("p2"),
                _td_play("p3", text="M.Pittman 12 yard pass, TOUCHDOWN."),
            ]
        )
        client = _mock_client([schedule, historical, next_poll])

        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=client,
        ):
            await svc.connect()
            assert svc._history_hydration_pending_game_id == "restart-live"

            await svc._tick()
            assert received == []
            assert {"p1", "p2"} <= svc._known_play_ids
            assert svc._history_hydration_pending_game_id is None

            await svc._tick()

        assert [play.event_id for play in received] == ["p3"]
        assert [play.game_id for play in received] == ["restart-live"]

    async def test_restart_after_final_never_replays_historical_score(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        svc._schedule_post_game_clear = MagicMock()
        received: list[PlayEvent] = []

        async def cb(play):
            received.append(play)

        svc.register_on_play_event(cb)
        kickoff = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        ).strftime("%Y-%m-%dT%H:%MZ")
        schedule = {
            "events": [
                _schedule_event(
                    "restart-final",
                    kickoff,
                    status="STATUS_FINAL",
                )
            ]
        }
        final_summary = _summary_payload(
            status_name="STATUS_FINAL",
            period=4,
            clock="0:00",
            score_colts=24,
            score_opp=31,
            plays=[_td_play("historical-td")],
        )
        final_summary["header"]["competitions"][0]["status"]["type"].update(
            {"state": "post", "completed": True}
        )
        client = _mock_client([schedule, final_summary])

        with patch(
            "backend.services.gameday_service.httpx.AsyncClient",
            return_value=client,
        ):
            await svc.connect()
            await svc._tick()

        assert received == []
        assert "historical-td" in svc._known_play_ids
        assert svc.current_state() is not None
        assert svc.current_state().status == "final"
        assert "restart-final" in svc._finalized_game_ids

    @pytest.mark.parametrize(
        ("status_name", "provider_state"),
        [
            ("STATUS_HALFTIME", None),
            ("STATUS_END_PERIOD", None),
            ("STATUS_END_QUARTER", "in"),
            ("STATUS_IN_PROGRESS", "in"),
        ],
    )
    def test_live_break_statuses_never_collapse_to_no_game(
        self,
        status_name,
        provider_state,
    ):
        svc = _make_service()
        kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
        meta = {
            "id": "live-break",
            "kickoff_utc": kickoff,
            "opponent": "Baltimore Ravens",
            "colts_are_home": True,
            "status": "STATUS_IN_PROGRESS",
        }
        svc._current_game_id = "live-break"
        svc._current_state = GameDayState(
            status="in-progress",
            opponent="Baltimore Ravens",
            kickoff_utc=kickoff,
            score_colts=7,
            score_opp=7,
            quarter=2,
            clock="0:00",
            possession=None,
            last_play=None,
        )
        summary = _summary_payload(
            status_name=status_name,
            period=2,
            clock="0:00",
        )
        if provider_state is not None:
            summary["header"]["competitions"][0]["status"]["type"]["state"] = (
                provider_state
            )

        state = svc._build_state(summary, meta)

        assert state.status == "in-progress"

    async def test_halftime_tick_emits_no_false_lifecycle_transition(self):
        svc = _make_service()
        kickoff = datetime.now(timezone.utc) - timedelta(hours=1)
        raw = _schedule_event(
            "halftime-live",
            kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            status="STATUS_IN_PROGRESS",
        )
        game = svc._normalize_schedule_event(raw)
        assert game is not None
        svc._schedule_cache = [game]
        svc._schedule_cache_time = time.time()
        svc._current_game_id = "halftime-live"
        svc._current_state = GameDayState(
            status="in-progress",
            opponent=game["opponent"],
            kickoff_utc=game["kickoff_utc"],
            score_colts=10,
            score_opp=10,
            quarter=2,
            clock="0:00",
            possession=None,
            last_play=None,
        )
        summary = _summary_payload(
            status_name="STATUS_HALFTIME",
            period=2,
            clock="0:00",
        )
        transitions: list[GameDayStateTransition] = []

        async def on_transition(transition):
            transitions.append(transition)

        svc.register_on_state_transition(on_transition)
        svc._fetch_summary = AsyncMock(return_value=summary)

        await svc._tick()

        assert svc.current_state() is not None
        assert svc.current_state().status == "in-progress"
        assert transitions == []

    async def test_unseen_score_in_final_summary_is_history_not_fresh_event(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        svc._schedule_post_game_clear = MagicMock()
        kickoff = datetime.now(timezone.utc) - timedelta(hours=3)
        raw = _schedule_event(
            "live-to-final",
            kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            status="STATUS_IN_PROGRESS",
        )
        game = svc._normalize_schedule_event(raw)
        assert game is not None
        svc._schedule_cache = [game]
        svc._schedule_cache_time = time.time()
        svc._current_game_id = "live-to-final"
        svc._current_state = GameDayState(
            status="in-progress",
            opponent=game["opponent"],
            kickoff_utc=game["kickoff_utc"],
            score_colts=17,
            score_opp=24,
            quarter=4,
            clock="0:20",
            possession="colts",
            last_play=None,
        )
        final_summary = _summary_payload(
            status_name="STATUS_FINAL",
            period=4,
            clock="0:00",
            score_colts=24,
            score_opp=31,
            plays=[_td_play("unseen-at-final")],
        )
        final_summary["header"]["competitions"][0]["status"]["type"].update(
            {"state": "post", "completed": True}
        )
        svc._fetch_summary = AsyncMock(return_value=final_summary)
        plays: list[PlayEvent] = []
        transitions: list[tuple[GameDayStateTransition, str | None]] = []

        async def on_play(play):
            plays.append(play)

        async def on_transition(transition):
            state = svc.current_state()
            transitions.append((transition, state.status if state else None))

        svc.register_on_play_event(on_play)
        svc.register_on_state_transition(on_transition)

        await svc._tick()

        assert plays == []
        assert "unseen-at-final" in svc._known_play_ids
        assert len(transitions) == 1
        assert transitions[0][0].to_status == "final"
        assert transitions[0][0].game_id == "live-to-final"
        assert transitions[0][1] == "final"

    def test_final_latch_is_monotonic_across_stale_provider_rows(self):
        svc = _make_service()
        svc._finalized_game_ids.add("latched-final")
        game = {
            "id": "latched-final",
            "kickoff_utc": datetime.now(timezone.utc) - timedelta(hours=3),
            "opponent": "Baltimore Ravens",
            "colts_are_home": True,
            "status": "STATUS_IN_PROGRESS",
            "status_state": "in",
            "status_completed": False,
        }

        assert svc._schedule_game_phase(game) == "final"

        summary = _summary_payload(status_name="STATUS_IN_PROGRESS", period=4)
        summary["header"]["competitions"][0]["status"]["type"]["state"] = "in"
        assert svc._build_state(summary, game).status == "final"

    def test_celebration_eligibility_requires_current_game_mode_and_phase(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        svc._current_game_id = "authority-game"
        svc._current_state = GameDayState(
            status="in-progress",
            opponent="Baltimore Ravens",
            kickoff_utc=datetime.now(timezone.utc),
            score_colts=14,
            score_opp=10,
            quarter=2,
            clock="12:07",
            possession="colts",
            last_play=None,
        )

        assert svc.celebration_eligibility(
            game_id="authority-game",
        ) == (True, "current Game Day authority")
        allowed, reason = svc.celebration_eligibility(game_id="old-game")
        assert allowed is False
        assert "stale game id" in reason

        automation.current_mode = "watching"
        allowed, reason = svc.celebration_eligibility(game_id="authority-game")
        assert allowed is False
        assert reason == "automation mode=watching"

        automation.current_mode = "gameday"
        svc._current_state.status = "final"
        svc._finalized_game_ids.add("authority-game")
        assert svc.celebration_eligibility(
            game_id="authority-game",
        )[0] is False
        assert svc.celebration_eligibility(
            game_id="authority-game",
            allow_final=True,
        )[0] is True

    async def test_pregame_owned_game_does_not_suppress_first_live_score(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        now = datetime.now(timezone.utc)
        svc._now_override = now
        kickoff = now + timedelta(minutes=20)
        raw = _schedule_event(
            "pregame-owned",
            kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            status="STATUS_SCHEDULED",
        )
        game = svc._normalize_schedule_event(raw)
        assert game is not None
        svc._schedule_cache = [game]
        svc._schedule_cache_time = time.time()
        assert svc._ensure_event_game(game) == "pregame-owned"
        assert svc._history_hydration_pending_game_id is None

        svc._now_override = kickoff + timedelta(minutes=1)
        live_summary = _summary_payload(plays=[_td_play("first-live-score")])
        svc._fetch_summary = AsyncMock(return_value=live_summary)
        received: list[PlayEvent] = []

        async def on_play(play):
            received.append(play)

        svc.register_on_play_event(on_play)
        await svc._tick()

        assert [play.event_id for play in received] == ["first-live-score"]


# ---------------------------------------------------------------------------
# Mode flips
# ---------------------------------------------------------------------------

class TestModeFlips:

    async def test_t30_flip_when_kickoff_imminent(self):
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)

        # Kickoff in 25 minutes — within the T-30 window.
        kickoff_in_25 = (
            datetime.now(timezone.utc) + timedelta(minutes=25)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_25)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()

        automation.set_manual_override.assert_awaited_once_with(
            "gameday", source=GAMEDAY_AUTO_SOURCE,
        )

    async def test_t30_no_flip_when_kickoff_far_away(self):
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)

        kickoff_in_3h = (
            datetime.now(timezone.utc) + timedelta(hours=3)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_3h)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()

        automation.set_manual_override.assert_not_called()

    async def test_t30_flip_idempotent_when_already_gameday(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        kickoff_in_25 = (
            datetime.now(timezone.utc) + timedelta(minutes=25)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_25)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        # Already gameday — skip the flip.
        automation.set_manual_override.assert_not_called()

    async def test_post_game_clear_fires_when_source_still_gameday_auto(self):
        automation = _make_automation_mock(
            current_mode="gameday", override_source=GAMEDAY_AUTO_SOURCE,
        )
        svc = _make_service(automation=automation)
        await svc._maybe_clear_postgame()
        automation.clear_override.assert_awaited_once_with(source=GAMEDAY_AUTO_SOURCE)

    async def test_post_game_clear_skipped_when_user_overrode(self):
        automation = _make_automation_mock(
            current_mode="working", override_source="api:192.168.1.30",
        )
        svc = _make_service(automation=automation)
        await svc._maybe_clear_postgame()
        # User touched it — don't clobber.
        automation.clear_override.assert_not_called()

    async def test_post_game_clear_scheduled_on_final_transition(self):
        """When the game flips to final, a delayed clear task is scheduled."""
        svc = _make_service()
        assert svc._post_game_clear_task is None
        svc._schedule_post_game_clear()
        assert svc._post_game_clear_task is not None
        # Cleanup — cancel the task so it doesn't run after the test.
        svc._post_game_clear_task.cancel()

    # ------------------------------------------------------------- pregameday
    # T-60 pregameday flip — GAMEDAY_SPEC §10.1
    # ----------------------------------------------------------------------

    async def test_t60_ambient_flip_when_in_pregame_window(self):
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)
        # Kickoff in 45 min — within T-60 window, outside T-30.
        kickoff_in_45 = (
            datetime.now(timezone.utc) + timedelta(minutes=45)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_45)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        automation.set_manual_override.assert_awaited_once_with(
            "pregameday", source=PREGAMEDAY_AUTO_SOURCE,
        )

    async def test_t60_no_flip_when_kickoff_far_away(self):
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)
        # 90 min out — outside even the T-60 window.
        kickoff_in_90 = (
            datetime.now(timezone.utc) + timedelta(minutes=90)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_90)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        automation.set_manual_override.assert_not_called()

    async def test_t60_idempotent_when_already_pregameday(self):
        automation = _make_automation_mock(current_mode="pregameday")
        svc = _make_service(automation=automation)
        kickoff_in_45 = (
            datetime.now(timezone.utc) + timedelta(minutes=45)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_45)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        automation.set_manual_override.assert_not_called()

    async def test_t60_does_not_downgrade_gameday(self):
        """If we're somehow already in gameday during a T-60 window (e.g. user
        manually fired it), pregameday must not displace gameday."""
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        kickoff_in_45 = (
            datetime.now(timezone.utc) + timedelta(minutes=45)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_45)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        automation.set_manual_override.assert_not_called()

    async def test_t30_window_takes_gameday_path_not_pregameday(self):
        """Within T-30, the gameday flip wins — pregameday is for T-60..T-30."""
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)
        kickoff_in_20 = (
            datetime.now(timezone.utc) + timedelta(minutes=20)
        ).strftime("%Y-%m-%dT%H:%MZ")
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_in_20)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            await svc._tick()
        automation.set_manual_override.assert_awaited_once_with(
            "gameday", source=GAMEDAY_AUTO_SOURCE,
        )

    async def test_now_override_drives_t60_then_t30_lifecycle(self):
        """Synthetic time injection (GAMEDAY_SPEC §10.6) — exercise the
        T-60 → T-30 lifecycle without sleeping."""
        automation = _make_automation_mock(current_mode="working")
        svc = _make_service(automation=automation)
        # Kickoff at a real future time the schedule cache can parse.
        kickoff = datetime.now(timezone.utc) + timedelta(minutes=200)
        kickoff_iso = kickoff.strftime("%Y-%m-%dT%H:%MZ")
        # We need TWO ticks — one inside T-60 window, one inside T-30 window.
        # Schedule fetch is one request per refresh; cache TTL is 900s so the
        # second tick hits cache. Provide two schedule fetches to be safe.
        client = _mock_client([
            {"events": [_schedule_event("401001", kickoff_iso)]},
            {"events": [_schedule_event("401001", kickoff_iso)]},
        ])
        with patch("backend.services.gameday_service.httpx.AsyncClient", return_value=client):
            await svc.connect()
            # T-50 — should land pregameday.
            svc._now_override = kickoff - timedelta(minutes=50)
            await svc._tick()
            automation.set_manual_override.assert_awaited_with(
                "pregameday", source=PREGAMEDAY_AUTO_SOURCE,
            )
            # Now switch automation's current_mode to reflect the flip,
            # then advance to T-20 — gameday should fire.
            automation.current_mode = "pregameday"
            svc._now_override = kickoff - timedelta(minutes=20)
            await svc._tick()
            automation.set_manual_override.assert_awaited_with(
                "gameday", source=GAMEDAY_AUTO_SOURCE,
            )

    async def test_synthetic_pregame_fires_override_and_clears(self):
        """trigger_synthetic_pregame sets the override + schedules a clear."""
        automation = _make_automation_mock(current_mode="working")
        # After flip, override_source is what _delayed_clear checks.
        automation.override_source = PREGAMEDAY_AUTO_SOURCE
        svc = _make_service(automation=automation)
        result = await svc.trigger_synthetic_pregame(
            opponent="Houston Texans",
            stakes_tier="big_stakes",
            hold_seconds=0,  # Don't wait in tests — clear immediately
        )
        # Override was set
        automation.set_manual_override.assert_awaited_once_with(
            "pregameday", source=PREGAMEDAY_AUTO_SOURCE,
        )
        assert result["mode"] == "pregameday"
        assert result["opponent"] == "Houston Texans"
        assert result["stakes_tier"] == "big_stakes"
        # Yield to the event loop so the _delayed_clear task can run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # And the clear fires
        automation.clear_override.assert_awaited_once_with(
            source=PREGAMEDAY_AUTO_SOURCE,
        )

    async def test_synthetic_pregame_skips_clear_if_user_overrode(self):
        """If override_source changed before hold expires, leave it alone."""
        automation = _make_automation_mock(current_mode="pregameday")
        automation.override_source = "api:192.168.1.30"  # user touched it
        svc = _make_service(automation=automation)
        await svc.trigger_synthetic_pregame(
            opponent="Houston Texans",
            stakes_tier="standard",
            hold_seconds=0,
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # The set_manual_override fired for the initial flip, but clear must NOT
        automation.clear_override.assert_not_called()


# ---------------------------------------------------------------------------
# Current drive aggregates
# ---------------------------------------------------------------------------

class TestCurrentDrive:

    def test_real_fixture_drive_uses_provider_aggregates_not_raw_play_count(self):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)

        # The final fixture has no drives.current, so promote a completed drive
        # only to exercise the exact ESPN drive-object shape. That drive has 10
        # raw events but ESPN says 7 offensive plays — the latter is authoritative.
        drive = summary["drives"]["previous"][-2]
        summary["drives"]["current"] = drive
        current = _make_service()._extract_current_drive(summary)

        assert current == CurrentDrive(
            team="colts", plays=7, yards=21, elapsed="3:58"
        )
        assert current.plays != len(drive["plays"])

    def test_previous_drive_is_never_reused_as_current(self):
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)

        assert summary["drives"].get("current") is None
        assert summary["drives"].get("previous")
        assert _make_service()._extract_current_drive(summary) is None

    @pytest.mark.parametrize(
        ("current", "expected"),
        [
            (
                {
                    "team": {"id": "15"},
                    "offensivePlays": "6",
                    "yards": "-3",
                    "timeElapsed": {"displayValue": " 1:42 "},
                },
                CurrentDrive(team="opp", plays=6, yards=-3, elapsed="1:42"),
            ),
            (
                {
                    "team": {"id": COLTS_TEAM_ID},
                    "offensivePlays": 0,
                    "yards": 0,
                    "timeElapsed": {"displayValue": "0:00"},
                },
                CurrentDrive(team="colts", plays=0, yards=0, elapsed="0:00"),
            ),
        ],
    )
    def test_current_drive_normalizes_truthful_provider_values(self, current, expected):
        summary = {"drives": {"current": current}}
        assert _make_service()._extract_current_drive(summary) == expected

    @pytest.mark.parametrize(
        "summary",
        [
            {},
            {"drives": None},
            {"drives": {"current": None}},
            {"drives": {"current": []}},
            {"drives": {"current": {"team": {"id": COLTS_TEAM_ID}}}},
            {"drives": {"current": {"offensivePlays": "bad", "yards": None}}},
        ],
    )
    def test_current_drive_missing_or_unusable_fails_neutral(self, summary):
        assert _make_service()._extract_current_drive(summary) is None

    def test_build_state_replaces_drive_with_none_when_provider_current_disappears(self):
        svc = _make_service()
        meta = {"opponent": "Miami Dolphins", "kickoff_utc": None}
        first = _summary_payload()
        first["drives"]["current"] = {
            "team": {"id": COLTS_TEAM_ID},
            "offensivePlays": 6,
            "yards": 48,
            "timeElapsed": {"displayValue": "2:11"},
            "plays": [],
        }
        with_drive = svc._build_state(first, meta)
        assert with_drive.current_drive == CurrentDrive(
            team="colts", plays=6, yards=48, elapsed="2:11"
        )

        second = _summary_payload()
        without_drive = svc._build_state(second, meta)
        assert without_drive.current_drive is None

    def test_final_state_never_exposes_provider_current_drive(self):
        svc = _make_service()
        summary = _summary_payload(status_name="STATUS_FINAL")
        summary["drives"]["current"] = {
            "team": {"id": COLTS_TEAM_ID},
            "offensivePlays": 9,
            "yards": 75,
            "timeElapsed": {"displayValue": "4:20"},
        }

        state = svc._build_state(
            summary, {"opponent": "Miami Dolphins", "kickoff_utc": None}
        )

        assert state.status == "final"
        assert state.current_drive is None

    async def test_state_route_exposes_nested_current_drive_contract(self):
        svc = _make_service()
        route_play = PlayEvent(
            timestamp=datetime.now(timezone.utc), play_type="touchdown",
            description="test", player="J.Taylor", kicker=None, yards=5,
            scoring_team="colts", event_id="evt", game_id="game",
        )
        svc._current_state = GameDayState(
            status="in-progress", opponent="Dolphins", kickoff_utc=None,
            score_colts=14, score_opp=7, quarter=2, clock="5:32",
            possession="colts", last_play=route_play,
            current_drive=CurrentDrive(
                team="colts", plays=6, yards=48, elapsed="2:11"
            ),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(gameday=svc)))

        payload = await route_get_state(request)

        assert payload["current_drive"] == {
            "team": "colts", "plays": 6, "yards": 48, "elapsed": "2:11"
        }
        assert {"event_id", "game_id", "synthetic"}.isdisjoint(
            payload["last_play"] or {}
        )


# ---------------------------------------------------------------------------
# State transitions + WS broadcasts
# ---------------------------------------------------------------------------

class TestStateTransitions:

    async def test_transition_callback_receives_event(self):
        svc = _make_service()
        received: list[GameDayStateTransition] = []

        async def cb(t):
            received.append(t)

        svc.register_on_state_transition(cb)
        await svc._fire_state_transition(
            GameDayStateTransition(
                from_status="pregame",
                to_status="in-progress",
                timestamp=datetime.now(timezone.utc),
            )
        )
        assert len(received) == 1
        assert received[0].from_status == "pregame"

    async def test_ws_broadcast_on_state_update(self):
        ws = _make_ws_mock()
        svc = _make_service(ws=ws)
        state = GameDayState(
            status="in-progress", opponent="Dolphins",
            kickoff_utc=None, score_colts=14, score_opp=7,
            quarter=2, clock="5:32", possession="colts", last_play=None,
        )
        await svc._update_state(state)
        ws.broadcast.assert_awaited_once()
        args, _ = ws.broadcast.call_args
        assert args[0] == "gameday_state"
        assert args[1]["score_colts"] == 14

    async def test_game_day_payloads_cross_real_json_boundary(self):
        class _Socket:
            def __init__(self):
                self.sent: list[str] = []

            async def send_text(self, payload: str) -> None:
                self.sent.append(payload)

        manager = WebSocketManager()
        socket = _Socket()
        manager._connections.add(socket)
        svc = _make_service(ws=manager)
        play = PlayEvent(
            timestamp=datetime(2026, 9, 13, 17, 5, tzinfo=timezone.utc),
            play_type="touchdown",
            description="Jonathan Taylor 5 Yd Rush",
            player="Jonathan Taylor", kicker=None, yards=5,
            scoring_team="colts", wpa=0.12,
        )
        state = GameDayState(
            status="in-progress", opponent="Houston Texans",
            kickoff_utc=datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc),
            score_colts=7, score_opp=0, quarter=1, clock="12:34",
            possession="colts", last_play=play,
            current_drive=CurrentDrive(
                team="colts", plays=4, yards=31, elapsed="1:54"
            ),
        )

        await svc._update_state(state)
        await manager.broadcast("gameday_play", _play_event_payload(play))

        state_payload = json.loads(socket.sent[0])
        play_payload = json.loads(socket.sent[1])
        assert state_payload["data"]["kickoff_utc"] == "2026-09-13T17:00:00+00:00"
        assert state_payload["data"]["last_play"]["timestamp"] == "2026-09-13T17:05:00+00:00"
        assert state_payload["data"]["current_drive"] == {
            "team": "colts", "plays": 4, "yards": 31, "elapsed": "1:54"
        }
        assert play_payload["data"]["timestamp"] == "2026-09-13T17:05:00+00:00"
        internal_keys = {"event_id", "game_id", "synthetic"}
        assert internal_keys.isdisjoint(play_payload["data"])
        assert internal_keys.isdisjoint(state_payload["data"]["last_play"])


# ---------------------------------------------------------------------------
# WPA — Win Probability Added on scoring plays
# ---------------------------------------------------------------------------

class TestWpa:
    """WPA is sampled from summary.winprobability and attached to each
    emitted PlayEvent. Sign convention: positive = Colts WP went up."""

    def test_wpa_extracted_from_real_fixture_colts_home(self):
        """2025-09-07 Colts vs Dolphins, Colts at home, won 33-8. Pittman's
        TD entry is at idx 33 (homeWP 0.7605) with prior at idx 32
        (homeWP 0.6479) → WPA_home ≈ +0.1126 → WPA_colts ≈ +0.1126."""
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)

        # Colts are home in this fixture.
        wpa = GameDayService._compute_wpa(
            "401772719800",  # Pittman TD
            summary,
            colts_are_home=True,
        )
        assert wpa is not None
        assert wpa > 0.10  # solid bump
        assert wpa < 0.15
        # First FG is a smaller swing.
        wpa_fg = GameDayService._compute_wpa(
            "401772719263",
            summary,
            colts_are_home=True,
        )
        assert wpa_fg is not None
        assert 0.0 < wpa_fg < 0.05

    def test_wpa_sign_flips_for_away_colts(self):
        """Same fixture, but if Colts had been the AWAY team, the same
        homeWP delta should sign-flip into a WPA_colts negative-going
        value (the home team's gain is the road team's loss)."""
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)

        wpa_home = GameDayService._compute_wpa(
            "401772719800", summary, colts_are_home=True,
        )
        wpa_away = GameDayService._compute_wpa(
            "401772719800", summary, colts_are_home=False,
        )
        assert wpa_home is not None and wpa_away is not None
        assert wpa_away == pytest.approx(-wpa_home, rel=1e-9)

    def test_wpa_returns_none_when_play_id_missing(self):
        """ESPN's WP model can lag the play feed by 30-60s. Until the
        play appears in the array, _compute_wpa returns None and the
        celebration falls back to margin/clock heuristics."""
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            summary = json.load(f)
        wpa = GameDayService._compute_wpa(
            "9999999999",  # not in the array
            summary,
            colts_are_home=True,
        )
        assert wpa is None

    def test_wpa_returns_none_when_array_empty(self):
        wpa = GameDayService._compute_wpa(
            "401772719800",
            {"winprobability": []},
            colts_are_home=True,
        )
        assert wpa is None

    def test_wpa_returns_none_when_array_missing(self):
        wpa = GameDayService._compute_wpa(
            "401772719800",
            {},  # no winprobability key at all
            colts_are_home=True,
        )
        assert wpa is None

    def test_wpa_first_play_falls_back_to_half(self):
        """Edge case: scoring play is the first WP entry. Prior WP is
        unknown; we anchor at 0.5."""
        summary = {
            "winprobability": [
                {"playId": "abc", "homeWinPercentage": 0.70},
            ]
        }
        wpa = GameDayService._compute_wpa(
            "abc", summary, colts_are_home=True,
        )
        assert wpa == pytest.approx(0.20, rel=1e-9)

    async def test_wpa_attached_in_extract_new_plays_when_active_game_home(self):
        """End-to-end: schedule a home game, set up a summary with both
        scoringPlays and winprobability, and verify _extract_new_plays
        returns plays with wpa populated."""
        svc = _make_service()

        # Seed schedule cache with a single live home game.
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%MZ"
        )
        sched = {"events": [
            _schedule_event("401001", future, status="STATUS_IN_PROGRESS",
                            colts_home=True),
        ]}
        client = _mock_client([sched])
        with patch("backend.services.gameday_service.httpx.AsyncClient",
                   return_value=client):
            await svc._refresh_schedule()

        td = _td_play("p1")
        td["id"] = "401001-td-1"
        summary = _summary_payload(plays=[td])
        summary["winprobability"] = [
            {"playId": "401001-pre", "homeWinPercentage": 0.50},
            {"playId": "401001-td-1", "homeWinPercentage": 0.70},
        ]

        new_plays = svc._extract_new_plays(summary)
        assert len(new_plays) == 1
        assert new_plays[0].wpa == pytest.approx(0.20, rel=1e-9)

    async def test_wpa_attached_in_extract_new_plays_away_game_flips_sign(self):
        svc = _make_service()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%MZ"
        )
        sched = {"events": [
            _schedule_event("401002", future, status="STATUS_IN_PROGRESS",
                            colts_home=False),
        ]}
        client = _mock_client([sched])
        with patch("backend.services.gameday_service.httpx.AsyncClient",
                   return_value=client):
            await svc._refresh_schedule()

        td = _td_play("p1")
        td["id"] = "401002-td-1"
        summary = _summary_payload(plays=[td])
        summary["winprobability"] = [
            {"playId": "401002-pre", "homeWinPercentage": 0.50},
            {"playId": "401002-td-1", "homeWinPercentage": 0.70},
        ]
        new_plays = svc._extract_new_plays(summary)
        assert len(new_plays) == 1
        # Colts are away → home went up by 0.20 → Colts down by 0.20.
        assert new_plays[0].wpa == pytest.approx(-0.20, rel=1e-9)

    def test_wpa_default_none_when_no_active_game(self):
        """No schedule cache → _find_active_game returns None → wpa stays
        None. Verifies graceful degradation."""
        svc = _make_service()
        td = _td_play("p1")
        td["id"] = "orphan-td"
        summary = _summary_payload(plays=[td])
        summary["winprobability"] = [
            {"playId": "orphan-td", "homeWinPercentage": 0.70},
        ]
        new_plays = svc._extract_new_plays(summary)
        assert len(new_plays) == 1
        # No active game → colts_are_home defaults to False, but the WP
        # entry exists for this play. Result is computed but with the
        # away-side sign convention. Important: it does NOT raise.
        assert new_plays[0].wpa is not None


# ---------------------------------------------------------------------------
# WPA momentum extraction (Phase 2)
# ---------------------------------------------------------------------------

def _momentum_summary(*plays_with_wp: tuple[str, float]) -> dict:
    """Build a minimal ESPN-shaped summary with synthetic plays + WP.

    Each tuple is (play_id, home_wp_after). WPA is implicit: delta from
    the previous entry's home_wp. First entry has prior=0.5 (coin flip).
    """
    plays = []
    wp_entries = []
    for pid, wp in plays_with_wp:
        plays.append({
            "id": pid,
            "text": f"Synthetic play {pid}",
            "type": {"text": ""},
            "scoringType": {},
            "wallclock": "2026-09-21T01:00:00Z",
        })
        wp_entries.append({
            "playId": pid,
            "homeWinPercentage": wp,
        })
    return {
        "drives": {"previous": [{"plays": plays}]},
        "winprobability": wp_entries,
    }


class TestMomentumExtraction:
    """WPA momentum lane: only Colts-positive non-scoring plays with
    WPA >= MOMENTUM_WPA_THRESHOLD surface as PlayEvent(play_type="momentum")."""

    def test_threshold_below_skips(self):
        svc = _make_service()
        # Colts are away in this synthetic service: home WP 0.5 → 0.38 means
        # Colts WPA +0.12, below the +0.15 threshold.
        summary = _momentum_summary(("p1", 0.38))
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_threshold_at_fires(self):
        svc = _make_service()
        # Colts are away: home WP 0.5 → 0.35 means Colts WPA +0.15.
        summary = _momentum_summary(("p1", 0.35))
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1
        assert out[0].play_type == "momentum"
        assert out[0].wpa == pytest.approx(0.15, abs=1e-9)

    def test_threshold_above_fires(self):
        svc = _make_service()
        # Colts are away: home WP 0.5 → 0.30 means Colts WPA +0.20.
        summary = _momentum_summary(("p1", 0.30))
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1
        assert out[0].wpa >= 0.15

    def test_negative_colts_wpa_is_silent(self):
        """A large swing against Indianapolis must never celebrate."""
        svc = _make_service()
        # Colts are away: home WP 0.5 → 0.75 means Colts WPA -0.25.
        summary = _momentum_summary(("p1", 0.75))
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_end_of_regulation_row_is_not_momentum(self):
        """Provider bookkeeping must not become a room celebration."""
        svc = _make_service()
        summary = {
            "drives": {"previous": [{"plays": [{
                "id": "p1",
                "text": "END QUARTER 4",
                "type": {"id": "79", "text": "End of Regulation", "abbreviation": "ER"},
                "scoringPlay": False,
                "scoringType": {},
            }]}]},
            "winprobability": [
                {"playId": "p1", "homeWinPercentage": 0.10},
            ],
        }
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_skips_play_already_in_known_ids(self):
        """Scoring plays added themselves to _known_play_ids first.
        Momentum walk must skip them to avoid double-firing."""
        svc = _make_service()
        svc._known_play_ids.add("p1")
        summary = _momentum_summary(("p1", 0.20))
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_wpa_none_skipped(self):
        svc = _make_service()
        # WP array missing this play_id → _compute_wpa returns None.
        summary = {
            "drives": {"previous": [{"plays": [
                {"id": "p1", "text": "play", "type": {}, "scoringType": {}},
            ]}]},
            "winprobability": [],  # empty
        }
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_walks_current_drive_when_present(self):
        """drives.current is the in-progress drive; its plays land in WP
        before the drive ends. Momentum should fire from current too."""
        svc = _make_service()
        summary = {
            "drives": {
                "previous": [],
                "current": {"plays": [
                    {"id": "p1", "text": "in-drive big play",
                     "type": {}, "scoringType": {},
                     "wallclock": "2026-09-21T01:00:00Z"},
                ]},
            },
            "winprobability": [
                {"playId": "p1", "homeWinPercentage": 0.25},  # Colts WPA +0.25
            ],
        }
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1

    def test_emits_minimal_play_event_fields(self):
        """Momentum plays don't parse player/yards — lights-only celebration.
        But fields should be coherent: type=momentum, scoring_team=None."""
        svc = _make_service()
        summary = _momentum_summary(("p1", 0.30))
        out = svc._extract_new_momentum_plays(summary)
        assert out[0].play_type == "momentum"
        assert out[0].scoring_team is None
        assert out[0].player is None
        assert out[0].kicker is None
        assert out[0].description == "Synthetic play p1"

    def test_adds_to_known_play_ids_so_no_refire(self):
        svc = _make_service()
        summary = _momentum_summary(("p1", 0.30))
        svc._extract_new_momentum_plays(summary)
        # Second call same tick — should return empty (play_id in known set).
        out = svc._extract_new_momentum_plays(summary)
        assert out == []


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_parse_espn_datetime_handles_z_suffix():
    dt = _parse_espn_datetime("2025-09-07T17:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2025 and dt.month == 9 and dt.day == 7


def test_parse_espn_datetime_handles_offset():
    dt = _parse_espn_datetime("2025-09-07T17:00:00+00:00")
    assert dt is not None
    assert dt.hour == 17


def test_parse_espn_datetime_returns_none_for_garbage():
    assert _parse_espn_datetime("not a date") is None
    assert _parse_espn_datetime("") is None


# ---------------------------------------------------------------------------
# #253 — game-sensitive semantic football events
# ---------------------------------------------------------------------------

def _semantic_play(
    *,
    play_id: str = "semantic-1",
    start_team: str = "33",
    end_team: str = COLTS_TEAM_ID,
    down: int = 4,
    play_type: str = "Pass Incompletion",
    text: str = "Pass incomplete on fourth down.",
    scoring: bool = False,
) -> dict:
    return {
        "id": play_id,
        "text": text,
        "type": {"text": play_type},
        "scoringPlay": scoring,
        "wallclock": "2026-09-21T01:00:00Z",
        "start": {"down": down, "team": {"id": start_team}},
        "end": {"down": 1, "team": {"id": end_team}},
    }


def _semantic_summary(
    raw: dict, *, home_wp: float | None, prior_wp: float = 0.181
) -> dict:
    wp = [
        {"playId": "prior", "homeWinPercentage": prior_wp, "tiePercentage": 0.0}
    ]
    if home_wp is not None:
        wp.append({
            "playId": str(raw["id"]),
            "homeWinPercentage": home_wp,
            "tiePercentage": 0.0,
        })
    return {
        "drives": {"previous": [{"plays": [raw]}]},
        "winprobability": wp,
    }


def _home_semantic_service() -> GameDayService:
    svc = _make_service()
    svc._find_active_game = MagicMock(return_value={"colts_are_home": True})
    return svc


class TestSemanticEventExtraction:
    def test_ravens_fourth_down_stop_fires_below_generic_wpa_threshold(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="4018726591191",
            text="(Shotgun) L.Jackson pass incomplete short right to J.Lane.",
        )
        summary = _semantic_summary(raw, home_wp=0.2087, prior_wp=0.1810)

        out = svc._extract_new_semantic_plays(summary)

        assert len(out) == 1
        assert out[0].play_type == "fourth_down_stop"
        assert out[0].event_id == "4018726591191"
        assert out[0].wpa == pytest.approx(0.0277, abs=1e-9)
        assert abs(out[0].wpa) < 0.15

    def test_semantic_floor_suppresses_below_five_percent_and_claims_play(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="garbage-time-stop")
        summary = _semantic_summary(raw, home_wp=0.049, prior_wp=0.040)

        assert svc._extract_new_semantic_plays(summary) == []
        assert "garbage-time-stop" in svc._known_play_ids
        assert svc._extract_new_semantic_plays(summary) == []

    def test_semantic_ceiling_suppresses_once_game_is_effectively_won(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="garbage-time-winning-stop")
        summary = _semantic_summary(raw, home_wp=0.951, prior_wp=0.94)

        assert svc._extract_new_semantic_plays(summary) == []
        assert "garbage-time-winning-stop" in svc._known_play_ids

    def test_semantic_ceiling_exactly_ninety_five_percent_is_still_live(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="ninety-five-percent-stop")
        summary = _semantic_summary(raw, home_wp=0.95, prior_wp=0.94)

        out = svc._extract_new_semantic_plays(summary)

        assert len(out) == 1
        assert out[0].play_type == "fourth_down_stop"

    def test_semantic_floor_exactly_five_percent_is_still_live(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="five-percent-stop")
        summary = _semantic_summary(raw, home_wp=0.05, prior_wp=0.04)

        out = svc._extract_new_semantic_plays(summary)

        assert len(out) == 1
        assert out[0].play_type == "fourth_down_stop"

    def test_missing_play_specific_wp_waits_without_claiming(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="wp-lagged-stop")
        summary = _semantic_summary(raw, home_wp=None)

        assert svc._extract_new_semantic_plays(summary) == []
        assert "wp-lagged-stop" not in svc._known_play_ids

    def test_real_shape_blocked_punt_fires_lower_amp_lane(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="4017728511134",
            play_type="Blocked Punt",
            text=(
                "A.Cole punt is BLOCKED by S.Olubi, Center-J.Bobenmoyer, "
                "recovered by LV-I.Thomas at LV 8."
            ),
        )
        summary = _semantic_summary(raw, home_wp=0.7979, prior_wp=0.70)

        out = svc._extract_new_semantic_plays(summary)

        assert len(out) == 1
        assert out[0].play_type == "blocked_punt"

    def test_ordinary_opponent_punt_is_not_a_semantic_stop(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="ordinary-punt",
            play_type="Punt",
            text="R.Eckley punts 53 yards to IND 18.",
        )
        summary = _semantic_summary(raw, home_wp=0.20)
        assert svc._extract_new_semantic_plays(summary) == []

    def test_colts_fourth_down_failure_is_not_a_positive_semantic_event(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="colts-failed-fourth",
            start_team=COLTS_TEAM_ID,
            end_team="33",
            play_type="Sack",
            text="D.Jones sacked on fourth down.",
        )
        summary = _semantic_summary(raw, home_wp=0.15)
        assert svc._extract_new_semantic_plays(summary) == []

    @pytest.mark.parametrize(
        "play_type,text",
        [
            ("Timeout", "Timeout by Baltimore."),
            ("Penalty", "PENALTY on BLT - No Play."),
            ("Field Goal Missed", "45 yard field goal is No Good."),
        ],
    )
    def test_admin_or_kicking_fourth_down_rows_do_not_fire(self, play_type, text):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id=f"excluded-{play_type}",
            play_type=play_type,
            text=text,
        )
        summary = _semantic_summary(raw, home_wp=0.25)
        assert svc._extract_new_semantic_plays(summary) == []

    def test_blocked_punt_touchdown_stays_in_scoring_lane(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="blocked-punt-touchdown",
            play_type="Blocked Punt Touchdown",
            text="Punt is BLOCKED and returned for a TOUCHDOWN.",
            scoring=True,
        )
        summary = _semantic_summary(raw, home_wp=0.70)
        assert svc._extract_new_semantic_plays(summary) == []

    def test_opponent_block_of_colts_punt_does_not_fire(self):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id="opponent-block",
            start_team=COLTS_TEAM_ID,
            end_team="33",
            play_type="Blocked Punt",
            text="Colts punt is BLOCKED by Baltimore.",
        )
        summary = _semantic_summary(raw, home_wp=0.30)
        assert svc._extract_new_semantic_plays(summary) == []

    def test_semantic_event_claims_play_before_high_wpa_lane(self):
        svc = _home_semantic_service()
        raw = _semantic_play(play_id="huge-fourth-down-stop")
        summary = _semantic_summary(raw, home_wp=0.70, prior_wp=0.40)

        semantic = svc._extract_new_semantic_plays(summary)
        momentum = svc._extract_new_momentum_plays(summary)

        assert len(semantic) == 1
        assert semantic[0].play_type == "fourth_down_stop"
        assert semantic[0].wpa == pytest.approx(0.30)
        assert momentum == []

    def test_away_win_probability_accounts_for_tie_probability(self):
        summary = {
            "winprobability": [{
                "playId": "p1",
                "homeWinPercentage": 0.70,
                "tiePercentage": 0.02,
            }],
        }
        assert GameDayService._colts_win_probability_after(
            "p1", summary, colts_are_home=False
        ) == pytest.approx(0.28)

    @pytest.mark.parametrize(
        "play_type,text,expected",
        [
            (
                "Interception",
                "Pass intended for Rice INTERCEPTED by L.Latu.",
                "interception",
            ),
            (
                "Fumble Recovery",
                "K.Hunt FUMBLES, RECOVERED by IND-C.Ward.",
                "fumble_recovery",
            ),
            (
                "Blocked Field Goal",
                "J.Slye 62 yard field goal is BLOCKED by G.Stewart.",
                "blocked_field_goal",
            ),
        ],
    )
    def test_other_unambiguous_colts_takeaways_use_semantic_lane(
        self, play_type, text, expected
    ):
        svc = _home_semantic_service()
        raw = _semantic_play(
            play_id=f"semantic-{expected}",
            down=2 if expected != "blocked_field_goal" else 4,
            play_type=play_type,
            text=text,
        )
        summary = _semantic_summary(raw, home_wp=0.22, prior_wp=0.20)

        out = svc._extract_new_semantic_plays(summary)

        assert len(out) == 1
        assert out[0].play_type == expected


@pytest.mark.asyncio
async def test_celebration_authority_rejects_away_even_if_mode_still_gameday():
    automation = _make_automation_mock(current_mode="gameday")
    automation.house_state = "away"
    svc = _make_service(automation=automation)
    svc._current_game_id = "away-live-game"
    svc._current_state = GameDayState(
        status="in-progress",
        opponent="Baltimore Ravens",
        kickoff_utc=datetime.now(timezone.utc),
        score_colts=14,
        score_opp=10,
        quarter=2,
        clock="12:07",
        possession="colts",
        last_play=None,
    )

    allowed, reason = svc.celebration_eligibility(game_id="away-live-game")

    assert allowed is False
    assert reason == "house state=away"


# ---------------------------------------------------------------------------
# #253 real ESPN scoring-shape hardening
# ---------------------------------------------------------------------------

class TestRealScoringShapes253:
    @pytest.mark.parametrize(("text", "player", "yards"), [
        ("Jonathan Taylor 1 Yd Rush (Spencer Shrader Kick)", "Jonathan Taylor", 1),
        ("Michael Pittman Jr. 27 Yd pass from Daniel Jones (Spencer Shrader Kick)", "Michael Pittman Jr.", 27),
    ])
    def test_offensive_touchdown_preserves_provider_yardage(self, text, player, yards):
        svc = _make_service()
        play = svc._parse_play({
            "id": f"td-{yards}", "text": text, "scoringPlay": True,
            "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Rushing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
        })
        assert play.player == player
        assert play.yards == yards

    def test_scoring_event_uses_matching_drive_wallclock(self):
        svc = _make_service()
        svc._current_game_id = "wallclock-game"
        scoring = {
            "id": "401872659257",
            "text": "Jonathan Taylor 1 Yd Rush (Spencer Shrader PAT Failed)",
            "scoringPlay": True,
            "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Rushing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
        }
        drive_play = dict(scoring, wallclock="2026-09-13T17:11:36Z")
        summary = {
            "scoringPlays": [scoring],
            "drives": {"previous": [{"plays": [drive_play]}]},
        }

        plays = svc._extract_new_plays(summary)

        assert len(plays) == 1
        assert plays[0].event_id == "401872659257"
        assert plays[0].timestamp == datetime(2026, 9, 13, 17, 11, 36, tzinfo=timezone.utc)

    def test_special_teams_return_touchdowns_are_not_defensive_tds(self):
        svc = _make_service()
        examples = [
            ("Punt Return Touchdown", "Malik Washington 74 Yd Punt Return (Riley Patterson Kick)"),
            ("Kickoff Return Touchdown", "Antonio Gibson 90 Yd Kickoff Return (Andy Borregales Kick)"),
            ("Blocked Field Goal", "Blocked Kick Recovered by Jordan Davis (PHI) Jordan Davis 61 Yd Touchown Return"),
        ]
        for index, (type_text, text) in enumerate(examples):
            play = svc._parse_play({
                "id": f"return-{index}", "text": text, "scoringPlay": True,
                "scoringType": {"abbreviation": "TD"},
                "type": {"text": type_text}, "team": {"id": COLTS_TEAM_ID},
            })
            assert play.play_type == "return_td"

    def test_standalone_defensive_pat_conversion_shape_is_two_points(self):
        svc = _make_service()
        play = svc._parse_play({
            "id": "4017729215125",
            "text": "Markquese Bell Defensive PAT Conversion",
            "scoringPlay": True,
            "scoringType": {"abbreviation": "2PTC"},
            "type": {}, "team": {"id": COLTS_TEAM_ID},
        })
        assert play.play_type == "two_point_conv"

    def test_embedded_pat_can_arrive_after_touchdown_row_was_seen(self):
        svc = _make_service()
        svc._current_game_id = "mutation-game"
        raw = {
            "id": "4018726591927", "text": "Jonathan Taylor 3 Yd Rush",
            "scoringPlay": True, "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Rushing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
            "wallclock": "2026-09-21T01:00:00Z",
        }
        first = svc._extract_new_plays({"scoringPlays": [raw]})
        assert [p.play_type for p in first] == ["touchdown"]

        raw = dict(raw, text="Jonathan Taylor 3 Yd Rush (Spencer Shrader Kick)")
        second = svc._extract_new_plays({"scoringPlays": [raw]})
        assert [p.play_type for p in second] == ["extra_point_good"]
        assert second[0].event_id == "4018726591927:extra_point_good"
        assert svc._extract_new_plays({"scoringPlays": [raw]}) == []

    def test_embedded_two_point_conversion_is_derived_once(self):
        svc = _make_service()
        svc._current_game_id = "two-point-game"
        raw = {
            "id": "4017728103486",
            "text": "Aaron Jones Sr. 27 Yd pass from J.J. McCarthy (J.J. McCarthy Pass to Adam Thielen for Two-Point Conversion)",
            "scoringPlay": True, "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Passing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
            "wallclock": "2026-09-21T01:00:00Z",
        }
        plays = svc._extract_new_plays({"scoringPlays": [raw]})
        assert [p.play_type for p in plays] == ["touchdown", "two_point_conv"]
        assert plays[1].event_id == "4017728103486:two_point_conv"

    @pytest.mark.parametrize("text", [
        "Jonathan Taylor 1 Yd Rush (Spencer Shrader PAT Failed)",
        "Justin Jefferson 13 Yd pass from J.J. McCarthy (Two-Point Pass Conversion Failed)",
        "Romeo Doubs 1 Yd pass from Jordan Love (Brandon McManus PAT blocked)",
    ])
    def test_failed_or_blocked_try_does_not_create_conversion_event(self, text):
        svc = _make_service()
        svc._current_game_id = "failed-try-game"
        raw = {
            "id": "failed-try", "text": text, "scoringPlay": True,
            "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Passing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
            "wallclock": "2026-09-21T01:00:00Z",
        }
        assert [p.play_type for p in svc._extract_new_plays({"scoringPlays": [raw]})] == ["touchdown"]

    def test_restart_hydration_claims_embedded_conversion_identity(self):
        svc = _make_service()
        raw = {
            "id": "hydrated-td",
            "text": "Tyler Warren 9 Yd pass from Daniel Jones (Spencer Shrader Kick)",
            "scoringPlay": True, "scoringType": {"abbreviation": "TD"},
            "type": {"text": "Passing Touchdown"},
            "team": {"id": COLTS_TEAM_ID},
        }
        ids = svc._provider_play_ids({"scoringPlays": [raw]})
        assert "hydrated-td" in ids
        assert "hydrated-td:extra_point_good" in ids

    @pytest.mark.asyncio
    async def test_live_summary_emits_pregame_to_in_progress_transition_once(self):
        automation = _make_automation_mock(current_mode="gameday")
        svc = _make_service(automation=automation)
        now = datetime(2026, 9, 21, 0, 21, tzinfo=timezone.utc)
        svc._now_override = now
        raw = _schedule_event(
            "kickoff-transition", "2026-09-21T00:20Z",
            opponent_name="Kansas City Chiefs", status="STATUS_SCHEDULED",
        )
        game = svc._normalize_schedule_event(raw)
        assert game is not None
        svc._schedule_cache = [game]
        svc._schedule_cache_time = time.time()
        svc._current_game_id = "kickoff-transition"
        svc._current_state = svc._pregame_state(game)
        svc._fetch_summary = AsyncMock(return_value=_summary_payload())
        transitions = []

        async def on_transition(transition):
            transitions.append(transition)

        svc.register_on_state_transition(on_transition)
        await svc._tick()
        assert [(t.from_status, t.to_status) for t in transitions] == [
            ("pregame", "in-progress")
        ]
        assert transitions[0].game_id == "kickoff-transition"

    @pytest.mark.asyncio
    async def test_return_td_is_available_through_synthetic_test_route(self):
        svc = MagicMock()
        svc.trigger_synthetic_play = AsyncMock(return_value=PlayEvent(
            timestamp=datetime.now(timezone.utc), play_type="return_td",
            description="[TEST] Synthetic return_td", player=None,
            kicker=None, yards=None, scoring_team="colts", synthetic=True,
        ))
        svc.trigger_synthetic_final = AsyncMock()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(gameday=svc))
        )

        result = await route_test_event("return_td", request)

        assert result["event"] == "return_td"
        svc.trigger_synthetic_play.assert_awaited_once_with("return_td")
        svc.trigger_synthetic_final.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_state_broadcast_precedes_viewer_state_queue():
    order: list[str] = []
    ws = _make_ws_mock()
    ws.broadcast = AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("canonical"))
    viewer_sync = MagicMock()
    viewer_sync.queue_state = MagicMock(side_effect=lambda *_args, **_kwargs: order.append("viewer"))
    svc = _make_service(ws=ws)
    svc.set_viewer_sync(viewer_sync)
    play = PlayEvent(
        timestamp=datetime(2026, 9, 15, 23, 30, tzinfo=timezone.utc),
        play_type="other", description="First down", player=None, kicker=None,
        yards=8, scoring_team="colts", synthetic=False,
    )
    state = GameDayState(
        status="in-progress", opponent="Houston Texans", kickoff_utc=None,
        score_colts=7, score_opp=3, quarter=2, clock="8:14",
        possession="colts", last_play=play,
    )

    await svc._update_state(state)

    assert order == ["canonical", "viewer"]
    viewer_sync.queue_state.assert_called_once()
    assert viewer_sync.queue_state.call_args.args[1] == play.timestamp

@pytest.mark.asyncio
async def test_tick_publishes_canonical_before_transition_callback_and_uses_provider_kickoff_anchor():
    automation = _make_automation_mock(current_mode="gameday")
    ws = _make_ws_mock()
    order: list[str] = []

    async def broadcast(kind, _payload):
        order.append(kind)

    ws.broadcast = AsyncMock(side_effect=broadcast)
    svc = _make_service(automation=automation, ws=ws)
    poll_time = datetime(2026, 9, 21, 0, 21, tzinfo=timezone.utc)
    provider_time = datetime(2026, 9, 21, 0, 20, 18, tzinfo=timezone.utc)
    svc._now_override = poll_time
    raw = _schedule_event(
        "kickoff-order", "2026-09-21T00:20Z",
        opponent_name="Kansas City Chiefs", status="STATUS_SCHEDULED",
    )
    game = svc._normalize_schedule_event(raw)
    assert game is not None
    svc._schedule_cache = [game]
    svc._schedule_cache_time = time.time()
    svc._current_game_id = "kickoff-order"
    svc._current_state = svc._pregame_state(game)
    opening_play = {
        "id": "opening-play",
        "text": "Opening kickoff returned to the 27 yard line.",
        "wallclock": provider_time.isoformat().replace("+00:00", "Z"),
        "type": {"text": "Kickoff"},
        "team": {"id": "15"},
        "period": {"number": 1},
        "clock": {"displayValue": "14:55"},
    }
    svc._fetch_summary = AsyncMock(return_value=_summary_payload(
        period=1, clock="14:55", score_colts=0, score_opp=0,
        plays=[opening_play],
    ))
    viewer_sync = MagicMock()
    svc.set_viewer_sync(viewer_sync)
    order.clear()
    viewer_sync.queue_state.reset_mock()
    transitions: list[GameDayStateTransition] = []

    async def on_transition(transition):
        order.append("transition_callback")
        transitions.append(transition)

    svc.register_on_state_transition(on_transition)
    await svc._tick()

    assert order[0] == "gameday_state"
    assert order.index("gameday_state") < order.index("transition_callback")
    assert len(transitions) == 1
    assert transitions[0].timestamp == provider_time
    assert viewer_sync.queue_state.call_args.args[1] == provider_time



def test_viewer_delayed_play_can_finish_after_canonical_final_without_weakening_mode_gate():
    automation = _make_automation_mock(current_mode="gameday")
    svc = _make_service(automation=automation)
    game_id = "viewer-delayed-final"
    svc._current_game_id = game_id
    svc._finalized_game_ids.add(game_id)
    svc._current_state = GameDayState(
        status="final", opponent="Houston Texans", kickoff_utc=None,
        score_colts=27, score_opp=24, quarter=4, clock="0:00",
        possession=None, last_play=None,
    )
    viewer = MagicMock()
    viewer.queue_state = MagicMock()
    viewer.snapshot.return_value = {"presentation_active": True}
    svc.set_viewer_sync(viewer)

    allowed, _ = svc.celebration_eligibility(
        game_id=game_id, allow_viewer_delayed_play=True,
    )
    assert allowed is True
    assert svc.celebration_eligibility(game_id=game_id)[0] is False

    automation.current_mode = "watching"
    assert svc.celebration_eligibility(
        game_id=game_id, allow_viewer_delayed_play=True,
    )[0] is False


def test_final_transition_uses_provider_final_observation_not_duplicate_last_play_anchor():
    svc = _make_service()
    provider_time = datetime(2026, 9, 15, 23, 58, 42, tzinfo=timezone.utc)
    poll_time = provider_time + timedelta(seconds=9)
    last_play = PlayEvent(
        timestamp=provider_time, play_type="other", description="Game ends",
        player=None, kicker=None, yards=None, scoring_team=None,
    )
    state = GameDayState(
        status="final", opponent="Houston Texans", kickoff_utc=None,
        score_colts=27, score_opp=24, quarter=4, clock="0:00",
        possession=None, last_play=last_play,
    )

    assert svc._viewer_transition_anchor("in-progress", state, poll_time) == poll_time



@pytest.mark.asyncio
async def test_provider_batch_assigns_shared_visual_anchor_to_each_new_play():
    automation = _make_automation_mock(current_mode="gameday")
    ws = _make_ws_mock()
    svc = _make_service(automation=automation, ws=ws)
    kickoff = datetime(2026, 9, 15, 23, 0, tzinfo=timezone.utc)
    raw = _schedule_event(
        "batch-game", kickoff.isoformat().replace("+00:00", "Z"),
        opponent_name="Houston Texans", status="STATUS_IN_PROGRESS",
    )
    game = svc._normalize_schedule_event(raw)
    assert game is not None
    svc._schedule_cache = [game]
    svc._schedule_cache_time = time.time()
    svc._current_game_id = "batch-game"
    svc._current_state = GameDayState(
        status="in-progress", opponent="Houston Texans", kickoff_utc=kickoff,
        score_colts=0, score_opp=0, quarter=1, clock="12:00",
        possession="colts", last_play=None,
    )

    first_time = kickoff + timedelta(minutes=10)
    second_time = first_time + timedelta(seconds=8)
    first = _td_play("batch-1")
    first["wallclock"] = first_time.isoformat().replace("+00:00", "Z")
    second = _td_play("batch-2", "A.Richardson 2 yard run, TOUCHDOWN.")
    second["wallclock"] = second_time.isoformat().replace("+00:00", "Z")
    svc._fetch_summary = AsyncMock(return_value=_summary_payload(
        period=2, clock="5:24", score_colts=12, score_opp=0,
        plays=[first, second],
    ))
    seen: list[PlayEvent] = []

    async def on_play(play):
        seen.append(play)

    svc.register_on_play_event(on_play)
    viewer = MagicMock()
    viewer.queue_state = MagicMock()
    svc.set_viewer_sync(viewer)
    viewer.queue_state.reset_mock()

    await svc._tick()

    assert [play.event_id for play in seen[:2]] == ["batch-1", "batch-2"]
    assert seen[0].timestamp == first_time
    assert seen[1].timestamp == second_time
    assert seen[0].viewer_anchor == second_time
    assert seen[1].viewer_anchor == second_time
    assert viewer.queue_state.call_args.args[1] == second_time


def test_score_changing_viewer_anchor_requires_complete_trusted_score_timing() -> None:
    svc = _make_service()
    provider_time = datetime(2026, 9, 21, 0, 31, 6, tzinfo=timezone.utc)
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=0,
        score_opp=0,
        quarter=1,
        clock="10:00",
        possession="colts",
        last_play=None,
    )
    touchdown = PlayEvent(
        timestamp=provider_time,
        play_type="touchdown",
        description="TD",
        player="Tyler Warren",
        kicker=None,
        yards=1,
        scoring_team="colts",
        event_id="td",
        game_id="game",
        timestamp_trusted=True,
    )
    scored = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=6,
        score_opp=0,
        quarter=1,
        clock="9:51",
        possession="colts",
        last_play=touchdown,
    )

    assert svc._viewer_state_anchor(
        scored,
        previous_state=previous,
        scoring_events=(touchdown,),
    ) == provider_time

    embedded_pat = PlayEvent(
        timestamp=provider_time,
        play_type="extra_point_good",
        description="TD row mutated with kick",
        player=None,
        kicker=None,
        yards=None,
        scoring_team="colts",
        event_id="td:extra_point_good",
        game_id="game",
        timestamp_trusted=False,
    )
    after_pat = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=0,
        quarter=1,
        clock="9:51",
        possession="colts",
        last_play=touchdown,
    )

    assert svc._viewer_state_anchor(
        after_pat,
        previous_state=scored,
        scoring_events=(embedded_pat,),
    ) is None


@pytest.mark.asyncio
async def test_unanchored_score_frame_still_publishes_canonical_truth() -> None:
    ws = _make_ws_mock()
    viewer = MagicMock()
    viewer.queue_state = MagicMock()
    svc = _make_service(ws=ws)
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=6,
        score_opp=0,
        quarter=1,
        clock="9:51",
        possession="colts",
        last_play=None,
    )
    svc._current_state = previous
    new_state = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=0,
        quarter=1,
        clock="9:51",
        possession="colts",
        last_play=None,
    )
    svc.set_viewer_sync(viewer)
    viewer.queue_state.reset_mock()
    ws.broadcast.reset_mock()

    await svc._update_state(
        new_state,
        viewer_anchor=None,
        queue_viewer_state=False,
    )

    ws.broadcast.assert_awaited_once()
    assert ws.broadcast.await_args.args[0] == "gameday_state"
    assert ws.broadcast.await_args.args[1]["score_colts"] == 7
    viewer.queue_state.assert_not_called()


def test_score_without_provider_wallclock_stays_pending_until_timestamp_arrives() -> None:
    svc = _make_service()
    svc._current_game_id = "timestamp-game"
    raw = _td_play("timestamp-td")
    raw.pop("wallclock")

    assert svc._extract_new_plays({"scoringPlays": [raw]}) == []
    assert "timestamp-td" not in svc._known_play_ids

    raw["wallclock"] = "2026-09-21T00:31:06Z"
    plays = svc._extract_new_plays({"scoringPlays": [raw]})

    assert [play.play_type for play in plays] == ["touchdown"]
    assert plays[0].timestamp == datetime(
        2026, 9, 21, 0, 31, 6, tzinfo=timezone.utc
    )
    assert plays[0].timestamp_trusted is True


def test_mutated_td_pat_waits_for_real_timestamp_and_preserves_parent_order() -> None:
    svc = _make_service()
    svc._current_game_id = "timestamp-pat-game"
    raw = _td_play("timestamp-pat")
    raw.pop("wallclock")

    assert svc._extract_new_plays({"scoringPlays": [raw]}) == []

    raw["text"] = (
        "J.Taylor 5 yard run, TOUCHDOWN. "
        "S.Shrader extra point is GOOD, Center-X."
    )
    raw["wallclock"] = "2026-09-21T00:31:06Z"
    plays = svc._extract_new_plays({"scoringPlays": [raw]})

    assert [play.play_type for play in plays] == [
        "touchdown",
        "extra_point_good",
    ]
    assert plays[0].timestamp == plays[1].timestamp
    assert plays[0].event_id == "timestamp-pat"
    assert plays[1].event_id == "timestamp-pat:extra_point_good"


def test_qualifying_momentum_without_provider_wallclock_remains_reconsiderable() -> None:
    svc = _make_service()
    summary = _momentum_summary(("pending-momentum", 0.30))
    raw = summary["drives"]["previous"][0]["plays"][0]
    raw.pop("wallclock")

    assert svc._extract_new_momentum_plays(summary) == []
    assert "pending-momentum" not in svc._known_play_ids

    raw["wallclock"] = "2026-09-21T03:35:03Z"
    plays = svc._extract_new_momentum_plays(summary)
    assert [play.event_id for play in plays] == ["pending-momentum"]


def test_quarter_change_without_new_play_uses_observation_time() -> None:
    svc = _make_service()
    play_time = datetime(2026, 9, 21, 0, 50, 0, tzinfo=timezone.utc)
    observed_at = play_time + timedelta(seconds=75)
    play = PlayEvent(
        timestamp=play_time,
        play_type="other",
        description="End of first quarter",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=None,
        timestamp_trusted=True,
    )
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=1,
        clock="0:00",
        possession=None,
        last_play=play,
    )
    current = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=2,
        clock="15:00",
        possession=None,
        last_play=play,
    )

    candidate = svc._viewer_state_anchor(
        current,
        previous_state=previous,
        scoring_events=(),
    )
    assert candidate == play_time

    anchor, apply_offset = svc._viewer_frame_timing(
        previous,
        current,
        candidate,
        observed_at,
    )
    assert anchor == observed_at
    assert apply_offset is False


def test_quarter_change_with_new_trusted_play_keeps_provider_time() -> None:
    svc = _make_service()
    old_time = datetime(2026, 9, 21, 0, 50, 0, tzinfo=timezone.utc)
    new_time = old_time + timedelta(seconds=80)
    observed_at = new_time + timedelta(seconds=35)
    old_play = PlayEvent(
        timestamp=old_time,
        play_type="other",
        description="End of first quarter",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=None,
        timestamp_trusted=True,
    )
    new_play = PlayEvent(
        timestamp=new_time,
        play_type="other",
        description="First play of second quarter",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=None,
        timestamp_trusted=True,
    )
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=1,
        clock="0:00",
        possession=None,
        last_play=old_play,
    )
    current = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=2,
        clock="14:54",
        possession="colts",
        last_play=new_play,
    )

    anchor, apply_offset = svc._viewer_frame_timing(
        previous,
        current,
        new_time,
        observed_at,
    )
    assert anchor == new_time
    assert apply_offset is True


def test_quarter_change_does_not_override_untrusted_score_gate() -> None:
    svc = _make_service()
    observed_at = datetime(2026, 9, 21, 0, 55, 0, tzinfo=timezone.utc)
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=1,
        clock="0:00",
        possession=None,
        last_play=None,
    )
    current = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=10,
        score_opp=3,
        quarter=2,
        clock="15:00",
        possession=None,
        last_play=None,
    )

    anchor, apply_offset = svc._viewer_frame_timing(
        previous,
        current,
        None,
        observed_at,
    )
    assert anchor is None
    assert apply_offset is True


@pytest.mark.asyncio
async def test_update_state_can_queue_observation_time_without_program_offset() -> None:
    ws = _make_ws_mock()
    viewer = MagicMock()
    viewer.queue_state = MagicMock()
    svc = _make_service(ws=ws)
    svc.set_viewer_sync(viewer)
    viewer.queue_state.reset_mock()
    anchor = datetime(2026, 9, 21, 0, 55, 0, tzinfo=timezone.utc)
    state = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=None,
        score_colts=7,
        score_opp=3,
        quarter=2,
        clock="15:00",
        possession=None,
        last_play=None,
    )

    await svc._update_state(
        state,
        viewer_anchor=anchor,
        viewer_apply_program_time_offset=False,
    )

    viewer.queue_state.assert_called_once()
    assert viewer.queue_state.call_args.args[1] == anchor
    assert (
        viewer.queue_state.call_args.kwargs["apply_program_time_offset"]
        is False
    )


@pytest.mark.asyncio
async def test_tick_queues_quarter_transition_at_provider_observation_time() -> None:
    automation = _make_automation_mock(current_mode="gameday")
    ws = _make_ws_mock()
    svc = _make_service(automation=automation, ws=ws)
    play_time = datetime(2026, 9, 21, 0, 50, 0, tzinfo=timezone.utc)
    observed_at = play_time + timedelta(seconds=75)
    play = PlayEvent(
        timestamp=play_time,
        play_type="other",
        description="End of first quarter",
        player=None,
        kicker=None,
        yards=None,
        scoring_team=None,
        timestamp_trusted=True,
    )
    previous = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=play_time - timedelta(hours=1),
        score_colts=7,
        score_opp=3,
        quarter=1,
        clock="0:00",
        possession=None,
        last_play=play,
    )
    current = GameDayState(
        status="in-progress",
        opponent="Kansas City Chiefs",
        kickoff_utc=previous.kickoff_utc,
        score_colts=7,
        score_opp=3,
        quarter=2,
        clock="15:00",
        possession=None,
        last_play=play,
    )
    active = {
        "id": "quarter-game",
        "status": "STATUS_IN_PROGRESS",
        "kickoff_utc": previous.kickoff_utc,
    }
    svc._current_game_id = "quarter-game"
    svc._current_state = previous
    svc._refresh_schedule_if_stale = AsyncMock()
    svc._find_active_game = MagicMock(return_value=active)
    svc._ensure_event_game = MagicMock(return_value="quarter-game")
    svc._now_utc = MagicMock(return_value=observed_at)
    svc._fetch_summary = AsyncMock(return_value={})
    svc._build_state = MagicMock(return_value=current)
    svc._hydrate_event_history_if_pending = MagicMock(return_value=False)
    svc._extract_new_plays = MagicMock(return_value=[])
    svc._extract_new_semantic_plays = MagicMock(return_value=[])
    svc._extract_new_momentum_plays = MagicMock(return_value=[])

    viewer = MagicMock()
    viewer.queue_state = MagicMock()
    svc.set_viewer_sync(viewer)
    viewer.queue_state.reset_mock()

    await svc._tick()

    viewer.queue_state.assert_called_once()
    assert viewer.queue_state.call_args.args[1] == observed_at
    assert viewer.queue_state.call_args.args[0]["quarter"] == 2
    assert (
        viewer.queue_state.call_args.kwargs["apply_program_time_offset"]
        is False
    )
