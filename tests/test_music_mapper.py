"""
Tests for the music mapper — playlist selection, time-of-day heuristic, auto-play.

Uses mock Sonos/WebSocket services from conftest. Cache is set directly
to avoid database round-trips.
"""
from unittest.mock import patch

import pytest

from backend.services.music_mapper import MusicMapper, _time_period


# ---------------------------------------------------------------------------
# Time period helper
# ---------------------------------------------------------------------------

class TestTimePeriod:
    """Verify _time_period() maps hours to correct periods."""

    def test_early_morning_is_night(self):
        assert _time_period(3) == "night"

    def test_5am_is_morning(self):
        assert _time_period(5) == "morning"

    def test_9am_is_morning(self):
        assert _time_period(9) == "morning"

    def test_10am_is_day(self):
        assert _time_period(10) == "day"

    def test_17h_is_day(self):
        assert _time_period(17) == "day"

    def test_18h_is_evening(self):
        assert _time_period(18) == "evening"

    def test_21h_is_evening(self):
        assert _time_period(21) == "evening"

    def test_22h_is_night(self):
        assert _time_period(22) == "night"

    def test_midnight_is_night(self):
        assert _time_period(0) == "night"


# ---------------------------------------------------------------------------
# Playlist selection
# ---------------------------------------------------------------------------

def _entry(title="Lo-Fi Beats", vibe="mellow", auto_play=True, priority=0):
    """Helper to create a cache entry."""
    return {
        "id": 1,
        "favorite_title": title,
        "vibe": vibe,
        "auto_play": auto_play,
        "priority": priority,
    }


class TestPickPlaylist:
    """Test pick_playlist() selection logic."""

    @pytest.fixture
    def mapper(self, mock_sonos, mock_ws):
        return MusicMapper(mock_sonos, mock_ws)

    def test_empty_cache_returns_none(self, mapper):
        assert mapper.pick_playlist("gaming") is None

    def test_single_entry_returns_it(self, mapper):
        mapper._cache["gaming"] = [_entry("Hype Mix", "energetic")]
        result = mapper.pick_playlist("gaming")
        assert result["favorite_title"] == "Hype Mix"

    def test_explicit_vibe_filters(self, mapper):
        mapper._cache["gaming"] = [
            _entry("Chill", "mellow"),
            _entry("Hype", "energetic"),
        ]
        result = mapper.pick_playlist("gaming", vibe="energetic")
        assert result["favorite_title"] == "Hype"

    def test_explicit_vibe_not_found_falls_back(self, mapper):
        mapper._cache["gaming"] = [_entry("Chill", "mellow")]
        result = mapper.pick_playlist("gaming", vibe="hype")
        assert result["favorite_title"] == "Chill"

    @patch("backend.services.music_mapper.datetime")
    def test_morning_prefers_focus(self, mock_dt, mapper):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        mock_dt.now.return_value = datetime(2026, 4, 12, 7, 0, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
        mapper._cache["working"] = [
            _entry("Energetic Mix", "energetic"),
            _entry("Focus Flow", "focus"),
        ]
        result = mapper.pick_playlist("working")
        assert result["favorite_title"] == "Focus Flow"

    @patch("backend.services.music_mapper.datetime")
    def test_day_prefers_energetic(self, mock_dt, mapper):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        mock_dt.now.return_value = datetime(2026, 4, 12, 14, 0, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
        mapper._cache["working"] = [
            _entry("Focus Flow", "focus"),
            _entry("Energetic Mix", "energetic"),
        ]
        result = mapper.pick_playlist("working")
        assert result["favorite_title"] == "Energetic Mix"

    @patch("backend.services.music_mapper.datetime")
    def test_evening_prefers_mellow(self, mock_dt, mapper):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        mock_dt.now.return_value = datetime(2026, 4, 12, 20, 0, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
        mapper._cache["relax"] = [
            _entry("Energetic Mix", "energetic"),
            _entry("Mellow Vibes", "mellow"),
        ]
        result = mapper.pick_playlist("relax")
        assert result["favorite_title"] == "Mellow Vibes"


# ---------------------------------------------------------------------------
# Auto-play on mode change
# ---------------------------------------------------------------------------

class TestOnModeChange:
    """Test on_mode_change() Sonos interaction logic."""

    @pytest.fixture
    def mapper(self, mock_sonos, mock_ws):
        return MusicMapper(mock_sonos, mock_ws)

    async def test_no_mapping_returns_none(self, mapper):
        result = await mapper.on_mode_change("gaming")
        assert result is None

    async def test_auto_play_disabled_returns_none(self, mapper):
        mapper._cache["gaming"] = [_entry("Hype", "energetic", auto_play=False)]
        result = await mapper.on_mode_change("gaming")
        assert result is None

    async def test_sonos_disconnected_returns_none(self, mapper):
        mapper._cache["gaming"] = [_entry("Hype", "energetic", auto_play=True)]
        mapper._sonos.connected = False
        result = await mapper.on_mode_change("gaming")
        assert result is None

    async def test_sonos_paused_auto_plays(self, mapper, mock_ws):
        mapper._cache["gaming"] = [_entry("Hype", "energetic", auto_play=True)]
        mapper._sonos._state["state"] = "PAUSED_PLAYBACK"
        result = await mapper.on_mode_change("gaming")
        assert result is not None
        assert result["action"] == "auto_played"
        assert result["title"] == "Hype"
        # Should broadcast music_auto_played
        auto_plays = [b for b in mock_ws.broadcasts if b[0] == "music_auto_played"]
        assert len(auto_plays) == 1

    async def test_sonos_playing_sends_suggestion(self, mapper, mock_ws):
        mapper._cache["gaming"] = [_entry("Hype", "energetic", auto_play=True)]
        mapper._sonos._state["state"] = "PLAYING"
        result = await mapper.on_mode_change("gaming")
        assert result is not None
        assert result["action"] == "suggested"
        suggestions = [b for b in mock_ws.broadcasts if b[0] == "music_suggestion"]
        assert len(suggestions) == 1

    async def test_sonos_stopped_auto_plays(self, mapper):
        mapper._cache["gaming"] = [_entry("Hype", "energetic", auto_play=True)]
        mapper._sonos._state["state"] = "STOPPED"
        result = await mapper.on_mode_change("gaming")
        assert result is not None
        assert result["action"] == "auto_played"

    async def test_pregameday_silent_build_no_autoplay(self, mapper):
        """GAMEDAY_SPEC §10 — pregameday entry is silent at T-60.

        Even with a pregameday playlist row set to auto_play=true, the
        on_mode_change handler must early-return so the build window stays
        quiet. Audio fires at the T-30 transition via dispatch_pregame_audio.
        """
        mapper._cache["pregameday"] = [_entry("Hype", "hype", auto_play=True)]
        mapper._sonos._state["state"] = "STOPPED"
        result = await mapper.on_mode_change("pregameday")
        assert result is None
        # Confirm we did NOT broadcast or play.
        assert mapper._sonos._state["state"] == "STOPPED"


# ---------------------------------------------------------------------------
# Pregame audio dispatch (GAMEDAY_SPEC §10.3)
# ---------------------------------------------------------------------------

class _MockTTS:
    def __init__(self):
        self.spoken: list[str] = []

    async def speak(self, line: str, **_kwargs) -> None:
        self.spoken.append(line)


def _decision(
    tier="standard",
    tts_line="Game day. Colts and Houston Texans in 30.",
    sonos_hype_play=False,
    sonos_vibe=None,
):
    from backend.services.pregame_audio_policy import PregameAudioDecision
    return PregameAudioDecision(
        tier=tier,
        tts_line=tts_line,
        sonos_hype_play=sonos_hype_play,
        sonos_vibe=sonos_vibe,
    )


class TestDispatchPregameAudio:

    @pytest.fixture
    def mapper(self, mock_sonos, mock_ws):
        tts = _MockTTS()
        m = MusicMapper(mock_sonos, mock_ws, tts_service=tts)
        m._tts_mock = tts  # accessible to assertions
        return m

    async def test_tts_only_when_no_hype(self, mapper):
        # Patch sleep to avoid waiting in the test.
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(_decision())
        assert result["tts_fired"] is True
        assert result["sonos_fired"] is False
        assert mapper._tts_mock.spoken == [
            "Game day. Colts and Houston Texans in 30."
        ]

    async def test_silent_decision_fires_nothing(self, mapper):
        d = _decision(tts_line=None, sonos_hype_play=False)
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(d)
        assert result["tts_fired"] is False
        assert result["sonos_fired"] is False
        assert mapper._tts_mock.spoken == []

    async def test_hype_fires_sonos_when_playlist_mapped(self, mapper):
        mapper._cache["pregameday"] = [
            _entry("Colts Hype Mix", "energetic", auto_play=True),
        ]
        d = _decision(
            tier="big_stakes",
            tts_line="Colts and {opp} in 30.",
            sonos_hype_play=True,
        )
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(d)
        assert result["tts_fired"] is True
        assert result["sonos_fired"] is True
        assert result["picked_title"] == "Colts Hype Mix"
        assert mapper._sonos._state["state"] == "PLAYING"

    async def test_hype_skipped_when_no_playlist_mapped(self, mapper):
        # Empty cache for pregameday
        d = _decision(sonos_hype_play=True)
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(d)
        assert result["tts_fired"] is True  # TTS still fires
        assert result["sonos_fired"] is False  # No Sonos — no row to pick

    async def test_mellow_vibe_prefers_mellow_entry(self, mapper):
        """Victory-lap tier sets sonos_vibe='mellow' — picker should prefer
        mellow/background-tagged entries over energetic ones."""
        mapper._cache["pregameday"] = [
            _entry("Hype Mix", "energetic", auto_play=True, priority=10),
            _entry("Chill Pregame", "mellow", auto_play=True, priority=0),
        ]
        d = _decision(
            tier="victory_lap",
            sonos_hype_play=True,
            sonos_vibe="mellow",
        )
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(d)
        assert result["picked_title"] == "Chill Pregame"

    async def test_default_vibe_uses_first_priority(self, mapper):
        """Default (no sonos_vibe) takes the highest-priority entry."""
        mapper._cache["pregameday"] = [
            _entry("Hype Mix", "energetic", auto_play=True, priority=10),
            _entry("Chill Pregame", "mellow", auto_play=True, priority=0),
        ]
        d = _decision(sonos_hype_play=True, sonos_vibe=None)
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await mapper.dispatch_pregame_audio(d)
        # First entry in cache list — _reload_mode sorts by priority DESC,
        # so Hype Mix (priority 10) comes first.
        assert result["picked_title"] == "Hype Mix"

    async def test_no_tts_service_skips_tts(self, mock_sonos, mock_ws):
        """Defensive — mapper without tts_service still dispatches Sonos."""
        m = MusicMapper(mock_sonos, mock_ws)  # no tts_service
        m._cache["pregameday"] = [_entry("Hype", "energetic", auto_play=True)]
        d = _decision(sonos_hype_play=True)
        async def _async_noop(*_a, **_k):
            return None
        with patch("backend.services.music_mapper.asyncio.sleep", new=_async_noop):
            result = await m.dispatch_pregame_audio(d)
        assert result["tts_fired"] is False
        assert result["sonos_fired"] is True
