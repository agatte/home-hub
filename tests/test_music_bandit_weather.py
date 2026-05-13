"""
Tests for Phase B (2026-05-12) of the music bandit — weather context.

Pins:
  - Legacy 3-pipe key migration on load (one-shot, idempotent)
  - 4-tuple ``mode|period|weather|title`` arm creation via ``select``
  - Warm-start: weather-specific arms inherit from ``WEATHER_ANY`` priors
  - ``record_reward`` updates the right weather slot
  - ``retrain`` reads ``weather_class`` from events
  - ``get_status`` returns the nested {mode: {weather: [...]}} shape
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import SonosPlaybackEvent
from backend.services.ml.music_bandit import (
    PRIOR_DEFAULT,
    PRIOR_PREFERRED,
    REWARD_KEEP_PLAYING,
    WEATHER_ANY,
    MusicBandit,
)


@pytest.fixture
def bandit(tmp_path):
    return MusicBandit(model_manager=None, data_dir=tmp_path)


@pytest.fixture(autouse=True)
def _seed_random():
    random.seed(42)


# ---------------------------------------------------------------------------
# Legacy 3-pipe key migration
# ---------------------------------------------------------------------------

class TestLegacyMigration:

    def test_three_pipe_keys_migrate_to_four_pipe_with_any(self, tmp_path):
        """A pre-Phase-B JSON file has 3-pipe keys (mode|period|title).
        On load, each becomes 4-pipe (mode|period|any|title) preserving priors."""
        legacy = {
            "arms": {
                "working|day|Lo-Fi": [5.0, 2.0],
                "relax|night|Ambient": [3.0, 1.0],
            },
            "total_selections": 17,
        }
        (tmp_path / "music_bandit.json").write_text(json.dumps(legacy))

        b = MusicBandit(model_manager=None, data_dir=tmp_path)

        assert "working|day|any|Lo-Fi" in b._arms
        assert "relax|night|any|Ambient" in b._arms
        # Original 3-pipe keys are gone — migration is in-place.
        assert "working|day|Lo-Fi" not in b._arms
        # Priors preserved.
        assert b._arms["working|day|any|Lo-Fi"] == [5.0, 2.0]
        assert b._arms["relax|night|any|Ambient"] == [3.0, 1.0]
        assert b._total_selections == 17

    def test_migration_persists_to_disk(self, tmp_path):
        """After migration the file is saved in new shape — second load is fast/no-op."""
        legacy = {"arms": {"working|day|Lo-Fi": [3.0, 1.0]}, "total_selections": 5}
        (tmp_path / "music_bandit.json").write_text(json.dumps(legacy))

        MusicBandit(model_manager=None, data_dir=tmp_path)
        on_disk = json.loads((tmp_path / "music_bandit.json").read_text())
        assert "working|day|any|Lo-Fi" in on_disk["arms"]
        assert "working|day|Lo-Fi" not in on_disk["arms"]

    def test_already_migrated_file_is_idempotent(self, tmp_path):
        """4-pipe keys already on disk pass through untouched."""
        prepped = {
            "arms": {"working|day|rain|Lo-Fi": [4.0, 1.0]},
            "total_selections": 3,
        }
        (tmp_path / "music_bandit.json").write_text(json.dumps(prepped))

        b = MusicBandit(model_manager=None, data_dir=tmp_path)
        assert b._arms == {"working|day|rain|Lo-Fi": [4.0, 1.0]}

    def test_mixed_legacy_and_new_keys(self, tmp_path):
        """Real-world transition state — some arms 3-pipe, some 4-pipe."""
        mixed = {
            "arms": {
                "working|day|Lo-Fi": [2.0, 1.0],          # legacy
                "working|day|rain|Lo-Fi": [3.0, 1.0],      # already migrated
            },
            "total_selections": 0,
        }
        (tmp_path / "music_bandit.json").write_text(json.dumps(mixed))

        b = MusicBandit(model_manager=None, data_dir=tmp_path)
        assert "working|day|any|Lo-Fi" in b._arms
        assert "working|day|rain|Lo-Fi" in b._arms
        assert "working|day|Lo-Fi" not in b._arms


# ---------------------------------------------------------------------------
# 4-tuple select + warm-start
# ---------------------------------------------------------------------------

class TestSelectWithWeather:

    def test_select_creates_weather_specific_arm(self, bandit):
        candidates = [{"favorite_title": "Lo-Fi", "vibe": "chill"}]
        bandit.select("working", "day", candidates, weather="rain")
        assert "working|day|rain|Lo-Fi" in bandit._arms

    def test_select_default_weather_is_any(self, bandit):
        candidates = [{"favorite_title": "Lo-Fi", "vibe": "chill"}]
        bandit.select("working", "day", candidates)
        assert "working|day|any|Lo-Fi" in bandit._arms

    def test_weather_specific_arm_warm_starts_from_any(self, bandit):
        """When a weather-specific arm is first created and the matching
        ``mode|period|any|title`` arm has accumulated priors, the new arm
        inherits those priors instead of starting at Beta(1,1)."""
        # Seed the "any" arm with strong priors.
        bandit._arms["working|day|any|Lo-Fi"] = [10.0, 2.0]

        candidates = [{"favorite_title": "Lo-Fi"}]
        bandit.select("working", "day", candidates, weather="rain")

        # New rain-specific arm inherited the any-arm priors.
        assert bandit._arms["working|day|rain|Lo-Fi"] == [10.0, 2.0]
        # Parent any-arm is unchanged (copy, not reference).
        assert bandit._arms["working|day|any|Lo-Fi"] == [10.0, 2.0]

    def test_warm_start_copies_not_references(self, bandit):
        """Subsequent rewards on the weather arm don't bleed back to any."""
        bandit._arms["working|day|any|Lo-Fi"] = [10.0, 2.0]
        bandit.select("working", "day", [{"favorite_title": "Lo-Fi"}], weather="rain")
        bandit.record_reward("working", "day", "Lo-Fi", 5.0, weather="rain")

        assert bandit._arms["working|day|rain|Lo-Fi"] == [15.0, 2.0]
        # Parent any-arm untouched.
        assert bandit._arms["working|day|any|Lo-Fi"] == [10.0, 2.0]

    def test_warm_start_only_when_any_arm_exists(self, bandit):
        """No any-arm to inherit from → new weather arm gets PRIOR_DEFAULT."""
        bandit.select("relax", "evening", [{"favorite_title": "New"}], weather="snow")
        assert bandit._arms["relax|evening|snow|New"] == [
            PRIOR_DEFAULT[0], PRIOR_DEFAULT[1],
        ]

    def test_preferred_vibe_prior_still_applies(self, bandit):
        """Cold-start preferred-vibe priors work in the 4-tuple shape."""
        candidates = [{"favorite_title": "Lo-Fi", "vibe": "chill"}]
        bandit.select("working", "day", candidates,
                      preferred_vibes=["chill"], weather="rain")
        assert bandit._arms["working|day|rain|Lo-Fi"] == [
            PRIOR_PREFERRED[0], PRIOR_PREFERRED[1],
        ]


# ---------------------------------------------------------------------------
# record_reward with weather
# ---------------------------------------------------------------------------

class TestRecordRewardWithWeather:

    def test_reward_targets_specific_weather_arm(self, bandit):
        bandit.record_reward("working", "day", "Lo-Fi", REWARD_KEEP_PLAYING, weather="rain")
        # Only the rain arm is touched, not the any arm.
        assert "working|day|rain|Lo-Fi" in bandit._arms
        assert "working|day|any|Lo-Fi" not in bandit._arms
        assert bandit._arms["working|day|rain|Lo-Fi"][0] == (
            PRIOR_DEFAULT[0] + REWARD_KEEP_PLAYING
        )

    def test_default_weather_is_any(self, bandit):
        bandit.record_reward("working", "day", "Lo-Fi", 1.0)
        assert "working|day|any|Lo-Fi" in bandit._arms
        # Confirm no concrete-weather slot got created.
        assert all(WEATHER_ANY in k for k in bandit._arms.keys())


# ---------------------------------------------------------------------------
# retrain reads weather_class from events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRetrainWithWeather:

    async def test_events_with_weather_class_produce_weather_arms(self, bandit, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=2),
                event_type="auto_play",
                favorite_title="Lo-Fi",
                mode_at_time="working",
                triggered_by="auto",
                weather_class="rain",
            ))
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=1),
                event_type="play",
                favorite_title="Synthwave",
                mode_at_time="working",
                triggered_by="manual",
                weather_class="clear",
            ))
            await session.commit()

        await bandit.retrain()

        assert any("rain" in k and "Lo-Fi" in k for k in bandit._arms)
        assert any("clear" in k and "Synthwave" in k for k in bandit._arms)

    async def test_events_with_null_weather_class_fall_back_to_any(self, bandit, ml_db):
        """Pre-migration legacy rows have NULL weather_class — retrain
        buckets them into WEATHER_ANY rather than skipping them."""
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=1),
                event_type="play",
                favorite_title="Legacy",
                mode_at_time="relax",
                triggered_by="manual",
                weather_class=None,
            ))
            await session.commit()

        await bandit.retrain()

        # Arm key includes the "any" weather slot.
        assert any("|any|Legacy" in k for k in bandit._arms)


# ---------------------------------------------------------------------------
# get_status nested shape
# ---------------------------------------------------------------------------

class TestGetStatusShape:

    def test_nested_by_weather_class(self, bandit):
        bandit._arms = {
            "working|day|rain|Lo-Fi": [3.0, 1.0],
            "working|day|clear|Lo-Fi": [2.0, 1.0],
            "working|day|any|Jazz": [5.0, 1.0],
            "relax|night|any|Ambient": [4.0, 1.0],
        }
        status = bandit.get_status()
        assert status["arm_count"] == 4
        # Top arms nested {mode: {weather_class: [...]}}
        assert "rain" in status["top_arms"]["working"]
        assert "clear" in status["top_arms"]["working"]
        assert "any" in status["top_arms"]["working"]
        assert status["top_arms"]["working"]["rain"][0]["title"] == "Lo-Fi"
        # Counts roll up to per-mode totals.
        assert status["arms_per_mode"]["working"] == 3
        assert status["arms_per_mode"]["relax"] == 1
