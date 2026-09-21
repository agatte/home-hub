"""Full-game regression replay for Colts at Chiefs, 2026-09-20.

The fixture is a post-final ESPN summary snapshot. These tests never touch
Hue, Sonos, or live services. They replay the provider evidence through the
same GameDayService extraction and CelebrationOrchestrator routing used in
production so the failures exposed by this game remain permanently covered.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.celebration_orchestrator import CelebrationOrchestrator
from backend.services.gameday_service import (
    MOMENTUM_WPA_THRESHOLD,
    GameDayService,
    GameDayState,
    PlayEvent,
)
from backend.services.gameday_viewer_sync import (
    DEFAULT_HULU_PROGRAM_TIME_OFFSET_SECONDS,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "espn_colts_chiefs_2026_09_20_summary.json"
)
GAME_ID = "401872945"

# These were the false-positive room reactions observed during the live game.
OPPONENT_OR_ADMIN_BIG_SWING_IDS = {
    "4018729453945",  # Colts incompletion, Colts WPA -16.1%
    "4018729454107",  # Mahomes -> Rice 31 yd, Colts WPA -39.4%
    "4018729454146",  # ESPN END QUARTER 4 administrative row
    "4018729454241",  # Mahomes -> Thornton 30 yd, Colts WPA -21.7%
    "4018729454843",  # Mahomes -> Walker 22 yd, Colts WPA -19.8%
}

EXPECTED_COLTS_SCORE_EVENT_IDS = {
    "401872945340",
    "401872945340:extra_point_good",
    "4018729451004",
    "4018729451397",
    "4018729452035",
    "4018729452035:extra_point_good",
    "4018729453579",
    "4018729453579:extra_point_good",
    "4018729454698",
}
EXPECTED_COLTS_ROOM_EFFECT_EVENT_IDS = {
    event_id
    for event_id in EXPECTED_COLTS_SCORE_EVENT_IDS
    if ":" not in event_id
}
EXPECTED_OPPONENT_SCORE_EVENT_IDS = {
    "401872945531",
    "401872945663",
    "401872945663:extra_point_good",
    "4018729451782",
    "4018729451782:extra_point_good",
    "4018729452584",
    "4018729452584:extra_point_good",
    "4018729453179",
    "4018729454455",
    "4018729454908",
}
EXPECTED_MOMENTUM_EVENT_ID = "4018729454505"


def _load_summary() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _make_service() -> GameDayService:
    svc = GameDayService(
        automation_engine=MagicMock(),
        ws_manager=MagicMock(),
    )
    svc._current_game_id = GAME_ID
    svc._find_active_game = lambda: {"colts_are_home": False}
    return svc


def _drive_plays(summary: dict) -> list[dict]:
    drives = summary.get("drives") or {}
    all_drives = list(drives.get("previous") or [])
    current = drives.get("current")
    if isinstance(current, dict):
        all_drives.append(current)
    plays = [
        raw
        for drive in all_drives
        for raw in (drive.get("plays") or [])
    ]
    return sorted(
        plays,
        key=lambda raw: int(raw.get("sequenceNumber") or 0),
    )


def _extract_full_game_events(summary: dict) -> list[PlayEvent]:
    """Run the same score -> semantic -> momentum extraction order as production."""
    svc = _make_service()
    events: list[PlayEvent] = []
    events.extend(svc._extract_new_plays(summary))
    events.extend(svc._extract_new_semantic_plays(summary))
    events.extend(svc._extract_new_momentum_plays(summary))
    return events


def _make_routing_orchestrator() -> CelebrationOrchestrator:
    hue = MagicMock()
    hue.set_light = AsyncMock(return_value=True)

    tts = MagicMock()
    tts.speak = AsyncMock(return_value=True)

    ws = MagicMock()
    ws.broadcast = AsyncMock()

    gameday = MagicMock()
    gameday.current_state = MagicMock(
        return_value=GameDayState(
            status="in-progress",
            opponent="Kansas City Chiefs",
            kickoff_utc=datetime(2026, 9, 21, 0, 20, tzinfo=timezone.utc),
            score_colts=30,
            score_opp=33,
            quarter=5,
            clock="",
            possession=None,
            last_play=None,
        )
    )
    gameday.celebration_eligibility = MagicMock(
        return_value=(True, "fixture replay")
    )

    automation = MagicMock()
    automation.current_mode = "gameday"
    automation.house_state = "home"
    automation.is_dnd_active = MagicMock(return_value=False)
    automation.transient_light_write_block_reason = MagicMock(return_value=None)
    automation.supersede_screen_sync_lights = MagicMock()
    automation.reapply_current_mode = AsyncMock()

    camera = MagicMock()
    camera.is_present_within_seconds = MagicMock(return_value=True)

    orch = CelebrationOrchestrator(
        hue_service=hue,
        tts_service=tts,
        ws_manager=ws,
        gameday_service=gameday,
        automation_engine=automation,
        camera_service=camera,
    )
    # Routing is the contract under test here. Do not execute real choreography
    # sleeps or even mocked Hue writes for 213-play replay coverage.
    orch._run_sequence = AsyncMock()
    return orch


def test_fixture_is_complete_final_overtime_game() -> None:
    summary = _load_summary()
    meta = summary["_fixture_meta"]
    plays = _drive_plays(summary)

    assert meta["game_id"] == GAME_ID
    assert meta["final_score"] == {"colts": 30, "chiefs": 33}
    assert len(plays) == 213
    assert len({str(play.get("id")) for play in plays}) == 213
    assert {int((play.get("period") or {}).get("number") or 0) for play in plays} == {
        1, 2, 3, 4, 5
    }
    assert len(summary.get("scoringPlays") or []) == 13
    assert len(summary.get("winprobability") or []) == 211

    svc = _make_service()
    state = svc._build_state(
        summary,
        {
            "id": GAME_ID,
            "opponent": "Kansas City Chiefs",
            "kickoff_utc": datetime(2026, 9, 21, 0, 20, tzinfo=timezone.utc),
        },
    )
    assert state.status == "final"
    assert state.score_colts == 30
    assert state.score_opp == 33
    # ESPN's post-final header collapses period to 0; the complete play corpus
    # above proves the game reached period 5/overtime before finalization.
    assert state.quarter == 0
    assert state.current_drive is None


def test_all_213_plays_leave_only_one_generic_big_play() -> None:
    summary = _load_summary()
    svc = _make_service()
    scoring_ids = {
        str(raw.get("id") or "")
        for raw in (summary.get("scoringPlays") or [])
    }

    eligible: list[tuple[str, float, str]] = []
    observed_ids: set[str] = set()
    for raw in _drive_plays(summary):
        play_id = str(raw.get("id") or "")
        observed_ids.add(play_id)
        if not play_id or play_id in scoring_ids:
            continue
        if svc._is_administrative_momentum_play(raw):
            continue
        wpa = svc._compute_wpa(play_id, summary, colts_are_home=False)
        if wpa is not None and wpa >= MOMENTUM_WPA_THRESHOLD:
            eligible.append((play_id, wpa, str(raw.get("text") or "")))

    assert OPPONENT_OR_ADMIN_BIG_SWING_IDS <= observed_ids
    assert [(event_id, pytest.approx(wpa, abs=1e-4)) for event_id, wpa, _ in eligible] == [
        (EXPECTED_MOMENTUM_EVENT_ID, pytest.approx(0.3489, abs=1e-4))
    ]
    assert "Laquon Treadwell" in eligible[0][2]


def test_full_game_event_ledger_has_no_duplicates_or_opponent_momentum() -> None:
    summary = _load_summary()
    events = _extract_full_game_events(summary)
    event_ids = [event.event_id for event in events]

    assert len(event_ids) == len(set(event_ids))
    assert None not in event_ids
    assert len(events) == 20

    colts_scores = {
        event.event_id
        for event in events
        if event.scoring_team == "colts"
        and event.play_type != "momentum"
    }
    opponent_scores = {
        event.event_id
        for event in events
        if event.scoring_team == "opp"
    }
    momentum = [event for event in events if event.play_type == "momentum"]

    assert colts_scores == EXPECTED_COLTS_SCORE_EVENT_IDS
    assert opponent_scores == EXPECTED_OPPONENT_SCORE_EVENT_IDS
    assert len(momentum) == 1
    assert momentum[0].event_id == EXPECTED_MOMENTUM_EVENT_ID
    assert momentum[0].wpa == pytest.approx(0.3489, abs=1e-4)
    assert momentum[0].wpa > 0

    emitted_ids = set(event_ids)
    assert not (OPPONENT_OR_ADMIN_BIG_SWING_IDS & emitted_ids)


@pytest.mark.asyncio
async def test_entire_game_routes_only_colts_positive_events_to_room_effects() -> None:
    events = _extract_full_game_events(_load_summary())
    orch = _make_routing_orchestrator()

    for event in sorted(
        events,
        key=lambda event: (
            event.timestamp,
            event.event_id or "",
        ),
    ):
        await orch.on_play_event(event)

    calls = orch._run_sequence.await_args_list
    routed = [
        (call.args[0], call.kwargs["play"])
        for call in calls
    ]
    routed_ids = {play.event_id for _, play in routed}

    assert routed_ids == (
        EXPECTED_COLTS_ROOM_EFFECT_EVENT_IDS
        | {EXPECTED_MOMENTUM_EVENT_ID}
    )
    assert len(routed) == 7

    for sequence_key, play in routed:
        if play.play_type == "momentum":
            assert sequence_key == "big_play"
            assert play.wpa is not None and play.wpa > 0
            assert play.event_id == EXPECTED_MOMENTUM_EVENT_ID
        else:
            assert play.scoring_team == "colts"

    assert not (EXPECTED_OPPONENT_SCORE_EVENT_IDS & routed_ids)
    assert not (OPPONENT_OR_ADMIN_BIG_SWING_IDS & routed_ids)
def test_real_room_hulu_program_targets_match_chiefs_couch_calibration() -> None:
    events = {
        event.event_id: event
        for event in _extract_full_game_events(_load_summary())
    }
    offset = DEFAULT_HULU_PROGRAM_TIME_OFFSET_SECONDS

    # These five Colts scoring plays are the ones Anthony evaluated relative
    # to what was actually visible on Hulu. The +29s program-time translation
    # explains the formerly early/late mix without baking in stream latency.
    expected_targets = {
        "401872945340": datetime(2026, 9, 21, 0, 31, 35, tzinfo=timezone.utc),
        "4018729451004": datetime(2026, 9, 21, 1, 1, 13, tzinfo=timezone.utc),
        "4018729451397": datetime(2026, 9, 21, 1, 15, 40, tzinfo=timezone.utc),
        "4018729452035": datetime(2026, 9, 21, 1, 41, 5, tzinfo=timezone.utc),
        "4018729453579": datetime(2026, 9, 21, 2, 55, 47, tzinfo=timezone.utc),
    }

    for event_id, expected in expected_targets.items():
        translated_epoch = events[event_id].timestamp.timestamp() + offset
        actual = datetime.fromtimestamp(translated_epoch, tz=timezone.utc)
        assert actual == expected
