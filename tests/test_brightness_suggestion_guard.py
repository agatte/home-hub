"""Offline contract tests for learned-brightness acceptance. No real DB or Hue."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from backend.api.routes import rules
from backend.services.ws_manual_light_guard import ManualLightDispatch


def setup(targets=None):
    payload = {"mode": "working", "period": "day", "weather_class": "rain",
               "light_targets": targets if targets is not None else {"1": 100, "2": 120}}
    service = SimpleNamespace(
        accept_brightness_suggestion=AsyncMock(return_value={"status": "accepted", "payload": payload}),
        brightness_context_matches=Mock(return_value=True),
    )
    learner = SimpleNamespace(write_learned_pref=AsyncMock())
    state = SimpleNamespace(rule_engine=service, lighting_learner=learner,
                            automation=SimpleNamespace(current_mode="working"), hue=object())
    request = SimpleNamespace(app=SimpleNamespace(state=state), client=SimpleNamespace(host="test"))
    return request, service, learner, payload


@pytest.mark.asyncio
async def test_partial_application_is_distinct_from_saved_preferences(monkeypatch):
    request, service, learner, payload = setup()
    dispatch = AsyncMock(side_effect=[
        ManualLightDispatch("acknowledged", {"bri": 60}), ManualLightDispatch("denied"),
    ])
    monkeypatch.setattr(rules, "dispatch_manual_light", dispatch)
    result = await rules.accept_brightness_suggestion(7, request)
    assert result["status"] == "partial_failure"
    assert result["preference_saved"] == ["1", "2"]
    assert result["applied_now"] == [{"light_id": "1", "bri": 100}]
    assert result["blocked"] == ["2"]
    assert learner.write_learned_pref.await_count == 2
    assert dispatch.await_count == 2
    assert dispatch.await_args_list[0].args[2:] == ("1", {"bri": 100})
    check = dispatch.await_args_list[0].kwargs["context_valid"]
    assert check() is True
    service.brightness_context_matches.return_value = False
    assert check() is False


@pytest.mark.asyncio
async def test_invalid_inventory_rejects_entire_suggestion(monkeypatch):
    request, _, learner, _ = setup({"1": 100, "999": 120})
    dispatch = AsyncMock()
    monkeypatch.setattr(rules, "dispatch_manual_light", dispatch)
    with pytest.raises(HTTPException) as error:
        await rules.accept_brightness_suggestion(7, request)
    assert error.value.status_code == 409
    learner.write_learned_pref.assert_not_awaited()
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_preference_write_stops_immediate_application(monkeypatch):
    request, _, learner, _ = setup({"1": 100, "2": 120, "3": 130})
    learner.write_learned_pref.side_effect = [None, OSError("test failure")]
    dispatch = AsyncMock()
    monkeypatch.setattr(rules, "dispatch_manual_light", dispatch)
    result = await rules.accept_brightness_suggestion(7, request)
    assert result["status"] == "partial_failure"
    assert result["preference_saved"] == ["1"]
    assert result["preference_uncertain"] == ["2"]
    assert result["preference_not_attempted"] == ["3"]
    assert result["not_attempted"] == ["1", "2", "3"]
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_or_already_resolved_never_learns_or_writes(monkeypatch):
    request, service, learner, _ = setup()
    dispatch = AsyncMock()
    monkeypatch.setattr(rules, "dispatch_manual_light", dispatch)
    for response in (None, {"status": "expired"}):
        service.accept_brightness_suggestion.return_value = response
        with pytest.raises(HTTPException) as error:
            await rules.accept_brightness_suggestion(7, request)
        assert error.value.status_code == 410
    learner.write_learned_pref.assert_not_awaited()
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_dispatch_outcome_is_not_retried(monkeypatch):
    request, _, _, _ = setup({"1": 100})
    dispatch = AsyncMock(side_effect=RuntimeError("test unknown outcome"))
    monkeypatch.setattr(rules, "dispatch_manual_light", dispatch)
    result = await rules.accept_brightness_suggestion(7, request)
    assert result["status"] == "partial_failure"
    assert result["uncertain"] == ["1"]
    assert result["applied_now"] == []
    dispatch.assert_awaited_once()
