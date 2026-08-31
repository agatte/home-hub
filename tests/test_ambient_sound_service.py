"""
Tests for AmbientSoundService two-directory scan + URL resolution.

Covers the long-form / short-fallback override pattern introduced when
``data/ambient/`` joined ``backend/static/ambient/`` as a scan target.
The service walks SCAN_DIRS in priority order (data/ first), shadowing
same-name files in lower-priority dirs and resolving URLs to the right
prefix per-file.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.services import ambient_sound_service as svc


def _make_service(monkeypatch, tmp_path):
    """Build a service with SCAN_DIRS pointing at tmp dirs.

    After this returns the test can reach the dirs via
    ``svc.LONG_AMBIENT_DIR`` / ``svc.SHORT_AMBIENT_DIR``.
    """
    long_dir = tmp_path / "data" / "ambient"
    short_dir = tmp_path / "backend" / "static" / "ambient"
    long_dir.mkdir(parents=True)
    short_dir.mkdir(parents=True)
    monkeypatch.setattr(
        svc,
        "SCAN_DIRS",
        ((long_dir, "/static/ambient-long"), (short_dir, "/static/ambient")),
    )
    monkeypatch.setattr(svc, "SHORT_AMBIENT_DIR", short_dir)
    monkeypatch.setattr(svc, "LONG_AMBIENT_DIR", long_dir)

    ws = MagicMock()
    ws.broadcast = AsyncMock()
    weather = MagicMock()
    sonos = MagicMock()
    sonos.connected = False  # avoid sonos paths in these tests
    return svc.AmbientSoundService(ws_manager=ws, weather_service=weather, sonos=sonos)


def _touch_mp3(directory: Path, name: str) -> Path:
    """Create an empty .mp3 file in the directory."""
    p = directory / name
    p.write_bytes(b"")
    return p


def _activate_stream(service, *, stream_id="rain-stream", url="https://example.test/rain", source="weather"):
    """Set up an already-owned Sonos ambient stream for transport tests."""
    service._sound_index[stream_id] = {
        "kind": "stream", "url": url, "label": "Rain stream",
    }
    service._current_sound = stream_id
    service._playing = True
    service._source = source
    service._sonos_ambient_active = True
    service._sonos_ambient_is_stream = True
    service._sonos_ambient_uri = url


def test_empty_long_dir_falls_back_to_short(monkeypatch, tmp_path):
    """data/ambient/ empty → service serves only the short fallbacks."""
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "fireplace.mp3")

    sounds = service.scan_sounds()

    assert {s["filename"] for s in sounds} == {"rain.mp3", "fireplace.mp3"}
    assert service._url_for("rain.mp3") == "/static/ambient/rain.mp3"
    assert service._url_for("fireplace.mp3") == "/static/ambient/fireplace.mp3"


def test_long_dir_file_uses_long_url_prefix(monkeypatch, tmp_path):
    """data/ambient/forest.mp3 → URL points to /static/ambient-long/."""
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.LONG_AMBIENT_DIR, "forest-8h.mp3")

    sounds = service.scan_sounds()

    assert [s["filename"] for s in sounds] == ["forest-8h.mp3"]
    assert service._url_for("forest-8h.mp3") == "/static/ambient-long/forest-8h.mp3"


def test_collision_long_wins_and_logs_debug(monkeypatch, tmp_path, caplog):
    """Same filename in both dirs → data/ wins, short version logged as shadowed."""
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.LONG_AMBIENT_DIR, "rain.mp3")
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")

    with caplog.at_level("DEBUG", logger="home_hub.ambient"):
        service.scan_sounds()

    # rain.mp3 appears once, resolved to the long-form URL
    assert service._url_for("rain.mp3") == "/static/ambient-long/rain.mp3"
    # The short version was shadowed and logged
    shadow_msgs = [r.message for r in caplog.records if "shadowed by" in r.message]
    assert shadow_msgs, "expected a 'shadowed by' debug log for the short rain.mp3"


def test_url_for_absolute_uses_local_ip(monkeypatch, tmp_path):
    """absolute=True returns http://LOCAL_IP:8000{prefix}/{name} for Sonos."""
    from backend.config import settings as cfg_settings

    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.LONG_AMBIENT_DIR, "rain.mp3")
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "fireplace.mp3")
    service.scan_sounds()

    abs_long = service._url_for("rain.mp3", absolute=True)
    abs_short = service._url_for("fireplace.mp3", absolute=True)

    expected_long = f"http://{cfg_settings.LOCAL_IP}:8000/static/ambient-long/rain.mp3"
    expected_short = f"http://{cfg_settings.LOCAL_IP}:8000/static/ambient/fireplace.mp3"
    assert abs_long == expected_long
    assert abs_short == expected_short


def test_url_for_unknown_filename_returns_none(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()

    assert service._url_for("not-there.mp3") is None
    assert service._url_for("not-there.mp3", absolute=True) is None


def test_missing_long_dir_is_silently_skipped(monkeypatch, tmp_path):
    """Fresh checkout with no data/ambient/ dir → service boots clean."""
    service = _make_service(monkeypatch, tmp_path)
    # Remove the long dir entirely; only short remains.
    svc.LONG_AMBIENT_DIR.rmdir()
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "wind.mp3")

    sounds = service.scan_sounds()

    assert [s["filename"] for s in sounds] == ["wind.mp3"]
    assert service._url_for("wind.mp3") == "/static/ambient/wind.mp3"


def test_non_audio_files_ignored(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    (svc.SHORT_AMBIENT_DIR / "README.txt").write_text("hands-off")
    (svc.SHORT_AMBIENT_DIR / "cover.jpg").write_bytes(b"")

    sounds = service.scan_sounds()

    assert [s["filename"] for s in sounds] == ["rain.mp3"]


def test_check_weather_prefers_long_form_rain(monkeypatch, tmp_path):
    """Weather=rain + both rain.mp3 in long and short → long-form picked."""
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.LONG_AMBIENT_DIR, "rain.mp3")
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()

    service._weather_service.get_cached = MagicMock(
        return_value={"description": "light rain"}
    )

    match = service._check_weather()

    assert match == "rain.mp3"
    # And the URL resolves to the long-form prefix
    assert service._url_for(match) == "/static/ambient-long/rain.mp3"


def test_check_weather_no_match_returns_none(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "fireplace.mp3")  # no rain.mp3 anywhere
    service.scan_sounds()

    service._weather_service.get_cached = MagicMock(
        return_value={"description": "rain shower"}
    )

    assert service._check_weather() is None


def test_state_payload_includes_sound_url(monkeypatch, tmp_path):
    """get_state() exposes sound_url so the frontend picks the right prefix."""
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.LONG_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()
    service._current_sound = "rain.mp3"
    service._playing = True

    state = service.get_state()

    assert state["sound"] == "rain.mp3"
    assert state["sound_url"] == "/static/ambient-long/rain.mp3"


def test_state_payload_sound_url_none_when_no_sound(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    service.scan_sounds()

    state = service.get_state()

    assert state["sound"] is None
    assert state["sound_url"] is None


async def test_play_requires_connected_sonos(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()
    service._save_config = AsyncMock()

    result = await service.play("rain.mp3", source="manual")

    assert result["status"] == "error"
    assert result["detail"] == "Ambient sound requires Sonos"
    assert service._current_sound == "rain.mp3"
    assert service._playing is False
    assert service._weather_override_active is False
    assert service._sonos_ambient_pending is False
    service._ws_manager.broadcast.assert_awaited()


async def test_busy_sonos_start_pauses_state_instead_of_falling_back(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()
    service._save_config = AsyncMock()
    service._sonos.connected = True
    service._sonos.get_status = AsyncMock(return_value={"state": "PLAYING"})
    service._current_sound = "rain.mp3"
    service._playing = True
    service._sonos_ambient_pending = True

    await service._start_sonos_ambient()

    assert service._playing is False
    assert service._sonos_ambient_active is False
    assert service._weather_override_active is False
    assert service._sonos_ambient_pending is False
    service._sonos.play_uri.assert_not_called()
    service._ws_manager.broadcast.assert_awaited()


async def test_manual_pause_learns_mode_auto_play_suppression(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    service._save_config = AsyncMock()
    service._automation = MagicMock(current_mode="relax")
    service._mode_auto_play = {"relax": True}
    service._source = "mode"
    service._current_sound = "fireplace.mp3"
    service._playing = True

    await service.pause(learn=True)

    assert service._mode_auto_play["relax"] is False
    assert service._playing is False
    service._save_config.assert_awaited()


async def test_manual_stop_learns_weather_suppression(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    service._save_config = AsyncMock()
    service._source = "weather"
    service._weather_reactive = True
    service._weather_override_active = True
    service._current_sound = "rain.mp3"
    service._playing = True

    await service.stop(learn=True)

    assert service._weather_reactive is False
    assert service._weather_override_active is False
    assert service._current_sound is None
    service._save_config.assert_awaited()


async def test_load_from_db_migrates_legacy_browser_only_sonos_disabled(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    saved = []

    async def fake_load_setting(key):
        if key == svc.AMBIENT_CONFIG_KEY:
            return {
                "sonos_enabled": False,
                "mode_sounds": {"relax": "fireplace.mp3"},
                "mode_auto_play": {"relax": True},
            }
        return {}

    async def fake_save_setting(key, value):
        saved.append((key, value))

    monkeypatch.setattr("backend.api.routes.routines.load_setting", fake_load_setting)
    monkeypatch.setattr("backend.api.routes.routines.save_setting", fake_save_setting)
    service._load_stream_library = AsyncMock()

    await service.load_from_db()

    assert service._sonos_enabled is True
    assert service._sonos_only_migrated is True
    assert saved[-1][0] == svc.AMBIENT_CONFIG_KEY
    assert saved[-1][1]["sonos_enabled"] is True
    assert saved[-1][1]["sonos_only_migrated"] is True


async def test_load_from_db_respects_post_migration_sonos_disabled(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    saved = []

    async def fake_load_setting(key):
        if key == svc.AMBIENT_CONFIG_KEY:
            return {
                "sonos_enabled": False,
                "sonos_only_migrated": True,
                "mode_sounds": {"relax": "fireplace.mp3"},
                "mode_auto_play": {"relax": True},
            }
        return {}

    async def fake_save_setting(key, value):
        saved.append((key, value))

    monkeypatch.setattr("backend.api.routes.routines.load_setting", fake_load_setting)
    monkeypatch.setattr("backend.api.routes.routines.save_setting", fake_save_setting)
    service._load_stream_library = AsyncMock()

    await service.load_from_db()

    assert service._sonos_enabled is False
    assert service._sonos_only_migrated is True
    assert saved == []


async def test_stream_health_tolerates_one_bad_transport_sample(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service)

    handled = await service._observe_stream_playback_health("STOPPED")

    assert handled is False
    assert service._stream_health == {}
    assert service._stream_failure_streak == 1


async def test_two_bad_stream_samples_mark_current_url_unhealthy(monkeypatch, tmp_path, caplog):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service, source="manual")

    with caplog.at_level("WARNING", logger="home_hub.ambient"):
        await service._observe_stream_playback_health("TRANSITIONING")
        await service._observe_stream_playback_health("ZPSTR_BUFFERING")
        await service._observe_stream_playback_health("STOPPED")

    assert service._stream_health["https://example.test/rain"][0] is False
    unhealthy_logs = [r for r in caplog.records if "stream unhealthy" in r.message]
    assert len(unhealthy_logs) == 1


async def test_playing_resets_stream_failure_streak(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service)

    await service._observe_stream_playback_health("STOPPED")
    await service._observe_stream_playback_health("PLAYING")
    await service._observe_stream_playback_health("STOPPED")

    assert service._stream_health == {}
    assert service._stream_failure_streak == 1


async def test_weather_stream_failure_reaches_local_file_fallback(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service._stream_library = {
        "rain": [{"id": "rain-stream", "url": "https://example.test/rain"}]
    }
    service.scan_sounds()
    service._weather_service.get_cached = MagicMock(
        return_value={"description": "steady rain"}
    )
    _activate_stream(service)
    service.play = AsyncMock()

    await service._observe_stream_playback_health("STOPPED")
    handled = await service._observe_stream_playback_health("ZPSTR_BUFFERING")

    assert handled is True
    assert service._check_weather() == "rain.mp3"
    service.play.assert_awaited_once_with("rain.mp3", source="weather")


async def test_finite_file_stopped_replay_is_preserved(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _touch_mp3(svc.SHORT_AMBIENT_DIR, "rain.mp3")
    service.scan_sounds()
    service._sonos.connected = True
    service._sonos.get_status = AsyncMock(return_value={"state": "STOPPED", "volume": 20})
    service._sonos.play_uri = AsyncMock(return_value=True)
    service._sonos.pause = AsyncMock()
    service._current_sound = "rain.mp3"
    service._playing = True
    service._sonos_ambient_active = True
    service._sonos_ambient_uri = service._url_for("rain.mp3", absolute=True)

    ticks = 0

    async def one_iteration_then_stop(_):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            service._sonos_ambient_active = False

    monkeypatch.setattr(svc.asyncio, "sleep", one_iteration_then_stop)
    await service._sonos_ambient_loop()

    service._sonos.play_uri.assert_awaited_once_with(
        service._url_for("rain.mp3", absolute=True), volume=20, force_radio=False
    )


async def test_paused_playback_does_not_poison_stream_health(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service)

    await service._observe_stream_playback_health("STOPPED")
    await service._observe_stream_playback_health("PAUSED_PLAYBACK")

    assert service._stream_health == {}
    assert service._stream_failure_streak == 0


async def test_unhealthy_manual_stream_is_not_replaced_by_weather(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service, source="manual")
    service._evaluate = AsyncMock()

    await service._observe_stream_playback_health("STOPPED")
    handled = await service._observe_stream_playback_health("STOPPED")

    assert handled is False
    assert service._stream_health["https://example.test/rain"][0] is False
    service._evaluate.assert_not_awaited()


async def test_stream_and_ownership_changes_reset_failure_streak(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    _activate_stream(service)

    await service._observe_stream_playback_health("STOPPED")
    _activate_stream(service, stream_id="wind-stream", url="https://example.test/wind")
    await service._observe_stream_playback_health("STOPPED")

    assert service._stream_failure_streak == 1
    service._sonos_ambient_active = False
    await service._observe_stream_playback_health("STOPPED")
    assert service._stream_failure_streak == 0
