"""Tests for the staged-arrival VibeRouter (GH#107 NL layer)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.services.personality.vibe_router import (
    PENDING_ARRIVAL_VIBE_KEY,
    VibePlan,
    VibeRouter,
    VibeRouterError,
)

pytestmark = pytest.mark.asyncio


class FakeSettings:
    def __init__(self):
        self.store = {}

    async def save(self, key, value):
        self.store[key] = value

    async def load(self, key):
        return self.store.get(key)


class FakeAutomation:
    def __init__(self):
        self.current_mode = "idle"
        self.set_manual_override = AsyncMock()
        self.mark_light_manual = MagicMock()


async def _session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


def _router(app_state, settings, db_engine, *, anthropic_api_key=None):
    return VibeRouter(
        app_state=app_state,
        save_setting=settings.save,
        load_setting=settings.load,
        session_factory=async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False,
        ),
        anthropic_api_key=anthropic_api_key,
    )


async def test_rules_parse_coming_home_with_friends(db_engine):
    settings = FakeSettings()
    router = _router(SimpleNamespace(), settings, db_engine)

    plan, cache_hit, cost = await router.parse(
        "I'm coming back to the apartment with friends, set the mood"
    )

    assert plan.mode == "social"
    assert plan.scene_id == "house_party"
    assert plan.parser == "rules"
    assert cache_hit is False
    assert cost == 0.0


async def test_ambiguous_parse_without_anthropic_key_fails_cleanly(db_engine):
    settings = FakeSettings()
    router = _router(SimpleNamespace(), settings, db_engine, anthropic_api_key="")

    with pytest.raises(VibeRouterError, match="ANTHROPIC_API_KEY"):
        await router.parse("make it feel like a private gallery opening")


async def test_handle_request_stages_when_away(db_engine):
    settings = FakeSettings()
    notifier = MagicMock()
    notifier.emit_alert = AsyncMock()
    app_state = SimpleNamespace(
        away_manager=SimpleNamespace(away=True),
        notifier=notifier,
    )
    router = _router(app_state, settings, db_engine)

    result = await router.handle_request(
        transcript="coming home with friends, party mood",
        source="ios_shortcut:vibe",
    )

    assert result["staged"] is True
    assert result["applied"] is False
    pending = settings.store[PENDING_ARRIVAL_VIBE_KEY]
    assert pending["plan"]["scene_id"] == "house_party"
    notifier.emit_alert.assert_awaited_once()


async def test_apply_pending_arrival_applies_mode_then_scene_and_clears(db_engine, mock_hue, mock_hue_v2, mock_ws):
    settings = FakeSettings()
    settings.store[PENDING_ARRIVAL_VIBE_KEY] = {
        "transcript": "party mood",
        "source": "ios_shortcut:vibe",
        "plan": VibePlan(
            mode="social",
            scene_id="house_party",
            acknowledgement="Party lighting ready.",
            confidence=0.9,
            parser="rules",
        ).to_dict(),
    }
    automation = FakeAutomation()
    event_logger = MagicMock()
    event_logger.log_scene_activation = AsyncMock()
    app_state = SimpleNamespace(
        automation=automation,
        hue=mock_hue,
        hue_v2=mock_hue_v2,
        ws_manager=mock_ws,
        event_logger=event_logger,
    )
    router = _router(app_state, settings, db_engine)

    result = await router.apply_pending_arrival(source="arrival:ios_shortcut")

    assert result["plan"]["scene_id"] == "house_party"
    automation.set_manual_override.assert_awaited_once_with(
        "social", source="api:arrival:ios_shortcut"
    )
    assert automation.mark_light_manual.call_count >= 1
    event_logger.log_scene_activation.assert_awaited_once()
    assert settings.store[PENDING_ARRIVAL_VIBE_KEY] == {}
