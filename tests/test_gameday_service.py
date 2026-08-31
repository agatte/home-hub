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
    GameDayService,
    GameDayState,
    GameDayStateTransition,
    PlayEvent,
    _parse_espn_datetime,
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
    }


# ---------------------------------------------------------------------------
# Schedule + state
# ---------------------------------------------------------------------------

class TestSchedule:

    async def test_espn_requests_use_httpx_default_user_agent(self):
        svc = _make_service()
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
        assert "headers" not in summary_client.get.await_args.kwargs

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
    """Phase 2 WPA-driven momentum lane: non-scoring plays with
    |WPA| >= MOMENTUM_WPA_THRESHOLD surface as PlayEvent(play_type="momentum")."""

    def test_threshold_below_skips(self):
        svc = _make_service()
        # WP goes 0.5 → 0.62 → delta = 0.12. Below 0.15 threshold.
        summary = _momentum_summary(("p1", 0.62))
        out = svc._extract_new_momentum_plays(summary)
        assert out == []

    def test_threshold_at_fires(self):
        svc = _make_service()
        # WP delta exactly 0.15 (0.5 → 0.65). Magnitude meets threshold.
        # Sign depends on whether Colts are home/away — _make_service has
        # no active game so colts_are_home defaults to False, but the
        # threshold check is on |WPA| so either sign qualifies.
        summary = _momentum_summary(("p1", 0.65))
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1
        assert out[0].play_type == "momentum"
        assert abs(out[0].wpa) == pytest.approx(0.15, abs=1e-9)

    def test_threshold_above_fires(self):
        svc = _make_service()
        # WP delta magnitude 0.20 (0.5 → 0.70).
        summary = _momentum_summary(("p1", 0.70))
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1
        assert abs(out[0].wpa) >= 0.15

    def test_negative_magnitude_fires(self):
        """Negative-direction WPA (Colts lose ground) is still a momentum
        moment — magnitude alone clears the threshold. The room reacts to
        BIG plays, not Colts-favorable plays."""
        svc = _make_service()
        # 0.5 → 0.25 home-WP delta = -0.25 home-side. Magnitude 0.25
        # always >= threshold regardless of home/away sign convention.
        summary = _momentum_summary(("p1", 0.25))
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1
        assert abs(out[0].wpa) >= 0.15

    def test_skips_play_already_in_known_ids(self):
        """Scoring plays added themselves to _known_play_ids first.
        Momentum walk must skip them to avoid double-firing."""
        svc = _make_service()
        svc._known_play_ids.add("p1")
        summary = _momentum_summary(("p1", 0.80))
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
                     "type": {}, "scoringType": {}},
                ]},
            },
            "winprobability": [
                {"playId": "p1", "homeWinPercentage": 0.75},  # delta +0.25
            ],
        }
        out = svc._extract_new_momentum_plays(summary)
        assert len(out) == 1

    def test_emits_minimal_play_event_fields(self):
        """Momentum plays don't parse player/yards — lights-only celebration.
        But fields should be coherent: type=momentum, scoring_team=None."""
        svc = _make_service()
        summary = _momentum_summary(("p1", 0.70))
        out = svc._extract_new_momentum_plays(summary)
        assert out[0].play_type == "momentum"
        assert out[0].scoring_team is None
        assert out[0].player is None
        assert out[0].kicker is None
        assert out[0].description == "Synthetic play p1"

    def test_adds_to_known_play_ids_so_no_refire(self):
        svc = _make_service()
        summary = _momentum_summary(("p1", 0.70))
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
