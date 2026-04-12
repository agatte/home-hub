"""
Shared test fixtures for Home Hub backend tests.

Provides mock Hue/Sonos/WebSocket services and an in-memory SQLite engine
so tests never touch real hardware or the production database.
"""
from typing import Any, Optional

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models import Base


# ---------------------------------------------------------------------------
# In-memory database
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Provide a transactional async session that rolls back after each test."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Mock services
# ---------------------------------------------------------------------------

class MockHueService:
    """Minimal mock for HueService — no bridge calls."""

    def __init__(self) -> None:
        self.connected = True
        self._lights: dict[str, dict] = {
            "1": {"id": "1", "name": "Living Room", "on": True, "bri": 200, "hue": 8000, "sat": 140, "reachable": True},
            "2": {"id": "2", "name": "Bedroom", "on": True, "bri": 150, "hue": 8000, "sat": 140, "reachable": True},
            "3": {"id": "3", "name": "Kitchen Front", "on": True, "bri": 200, "hue": 8000, "sat": 140, "reachable": True},
            "4": {"id": "4", "name": "Kitchen Back", "on": False, "bri": 0, "hue": 0, "sat": 0, "reachable": True},
        }

    async def get_all_lights(self) -> list[dict]:
        return list(self._lights.values())

    async def get_light(self, light_id: str) -> Optional[dict]:
        return self._lights.get(str(light_id))

    async def set_light(self, light_id: str, state: dict) -> bool:
        lid = str(light_id)
        if lid in self._lights:
            self._lights[lid].update(state)
            return True
        return False

    async def set_all_lights(self, state: dict) -> bool:
        for lid in self._lights:
            self._lights[lid].update(state)
        return True


class MockHueV2Service:
    """Minimal mock for HueV2Service."""

    def __init__(self) -> None:
        self.connected = True

    async def activate_scene(self, scene_id: str) -> bool:
        return True

    async def activate_effect(self, effect_name: str, light_ids: Optional[list] = None) -> bool:
        return True

    async def stop_effect(self, v1_light_id: str) -> bool:
        return True

    async def stop_effect_all(self) -> bool:
        return True

    async def set_effect_all(self, effect_name: str) -> bool:
        return True

    async def set_effect(self, effect_name: str, v1_light_id: str) -> bool:
        return True


class MockSonosService:
    """Minimal mock for SonosService."""

    def __init__(self) -> None:
        self.connected = True
        self._state = {
            "state": "PAUSED_PLAYBACK",
            "track": "",
            "artist": "",
            "album": "",
            "art_url": "",
            "volume": 20,
            "mute": False,
        }

    async def get_status(self) -> dict:
        return self._state.copy()

    async def play(self) -> bool:
        self._state["state"] = "PLAYING"
        return True

    async def pause(self) -> bool:
        self._state["state"] = "PAUSED_PLAYBACK"
        return True

    async def set_volume(self, volume: int) -> bool:
        self._state["volume"] = max(0, min(100, volume))
        return True

    async def get_favorites(self) -> list[dict]:
        return [{"title": "Lo-Fi Beats", "uri": "x-rincon:fake"}]

    async def play_favorite(self, title: str) -> bool:
        self._state["state"] = "PLAYING"
        self._state["track"] = title
        return True


class MockWebSocketManager:
    """Captures broadcast calls for assertion."""

    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, Any]] = []

    async def broadcast(self, msg_type: str, data: Any) -> None:
        self.broadcasts.append((msg_type, data))

    @property
    def client_count(self) -> int:
        return 0


@pytest.fixture
def mock_hue():
    return MockHueService()


@pytest.fixture
def mock_hue_v2():
    return MockHueV2Service()


@pytest.fixture
def mock_sonos():
    return MockSonosService()


@pytest.fixture
def mock_ws():
    return MockWebSocketManager()
