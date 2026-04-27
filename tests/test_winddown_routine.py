"""
Tests for the WinddownRoutineService — execute() flow + camera veto.
"""
import pytest

from backend.services.winddown_routine import WinddownRoutineService


class _FakeAutomation:
    """Minimal automation engine stub for winddown."""

    def __init__(self, current_mode="working", at_desk=False):
        self.current_mode = current_mode
        self._at_desk = at_desk
        self.override_calls: list[str] = []

    def is_at_desk_fresh(self) -> bool:
        return self._at_desk

    async def set_manual_override(self, mode: str, source: str = "internal") -> None:
        self.override_calls.append(mode)
        self.override_sources: list[str] = getattr(self, "override_sources", [])
        self.override_sources.append(source)


class _FakeSonos:
    def __init__(self, connected=True):
        self.connected = connected
        self.volume_calls: list[int] = []

    async def set_volume(self, vol: int) -> None:
        self.volume_calls.append(vol)


class _FakeTTS:
    def __init__(self):
        self.spoken: list[tuple[str, int]] = []

    async def speak(self, text: str, volume: int = 10) -> None:
        self.spoken.append((text, volume))


@pytest.fixture
def deps():
    return _FakeAutomation(), _FakeSonos(), _FakeTTS()


class TestWinddownExecuteHappyPath:
    """No camera veto — full routine fires (lights + volume + TTS)."""

    async def test_force_executes_full_routine(self, deps):
        auto, sonos, tts = deps
        wd = WinddownRoutineService(auto, sonos, tts, volume=15)
        ok = await wd.execute(force=True)
        assert ok is True
        assert auto.override_calls == ["relax"]
        assert sonos.volume_calls == [15]
        assert len(tts.spoken) == 1

    async def test_skip_if_active_blocks_when_gaming(self, deps):
        auto, sonos, tts = deps
        auto.current_mode = "gaming"
        wd = WinddownRoutineService(auto, sonos, tts, skip_if_active=True)
        # Patch the retry sleep so test runs instantly.
        import backend.services.winddown_routine as mod
        original_sleep = None
        try:
            import asyncio as _asyncio
            original_sleep = _asyncio.sleep

            async def _fast_sleep(_):
                pass
            mod.asyncio.sleep = _fast_sleep
            ok = await wd.execute(force=False)
        finally:
            mod.asyncio.sleep = original_sleep
        assert ok is False
        assert auto.override_calls == []  # never overrode


class TestWinddownCameraVeto:
    """When camera sees Anthony at the desk, lights stay put — TTS + volume still nudge."""

    async def test_at_desk_skips_lights(self, deps):
        auto, sonos, tts = deps
        auto._at_desk = True
        wd = WinddownRoutineService(auto, sonos, tts, volume=12)
        ok = await wd.execute(force=True)
        assert ok is True
        # Lights override skipped.
        assert auto.override_calls == []
        # But volume nudge + TTS still fire — the audible cue.
        assert sonos.volume_calls == [12]
        assert len(tts.spoken) == 1

    async def test_at_desk_returns_true_not_false(self, deps):
        """The veto is a soft skip, not a failure — return True so the
        scheduler logs success and doesn't retry."""
        auto, sonos, tts = deps
        auto._at_desk = True
        wd = WinddownRoutineService(auto, sonos, tts)
        assert await wd.execute(force=True) is True

    async def test_camera_off_runs_normally(self, deps):
        """is_at_desk_fresh=False (camera off, bed, etc.) → original behavior."""
        auto, sonos, tts = deps
        auto._at_desk = False
        wd = WinddownRoutineService(auto, sonos, tts)
        await wd.execute(force=True)
        assert auto.override_calls == ["relax"]

    async def test_missing_helper_falls_back(self, deps):
        """An automation engine without ``is_at_desk_fresh`` (older fake)
        treats it as 'no veto' and executes the lights override."""
        auto, sonos, tts = deps
        # Strip the helper to simulate an older automation engine.
        del type(auto).is_at_desk_fresh
        try:
            wd = WinddownRoutineService(auto, sonos, tts)
            await wd.execute(force=True)
            assert auto.override_calls == ["relax"]
        finally:
            # Restore for other tests sharing the class.
            _FakeAutomation.is_at_desk_fresh = (
                lambda self: getattr(self, "_at_desk", False)
            )


class TestWinddownCameraServiceWiring:
    """The set_camera_service hook lets bootstrap attach the camera lazily."""

    def test_constructor_accepts_camera_service(self, deps):
        auto, sonos, tts = deps
        sentinel = object()
        wd = WinddownRoutineService(auto, sonos, tts, camera_service=sentinel)
        assert wd._camera is sentinel

    def test_set_camera_service_overwrites(self, deps):
        auto, sonos, tts = deps
        wd = WinddownRoutineService(auto, sonos, tts)
        assert wd._camera is None
        sentinel = object()
        wd.set_camera_service(sentinel)
        assert wd._camera is sentinel
