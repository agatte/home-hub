"""
Tests for MusicBandit — Thompson sampling playlist selection.
"""
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.models import SonosPlaybackEvent
from backend.services.ml.music_bandit import (
    MusicBandit,
    PRIOR_DEFAULT,
    PRIOR_PREFERRED,
    REWARD_KEEP_PLAYING,
    REWARD_MANUAL_PLAY,
)


@pytest.fixture
def bandit(tmp_path):
    """Bandit rooted at a temp directory — never touches data/models/."""
    return MusicBandit(model_manager=None, data_dir=tmp_path)


@pytest.fixture(autouse=True)
def _seed_random():
    """Make Thompson sampling deterministic across runs."""
    random.seed(42)


class TestInit:
    def test_no_file_yields_empty_arms(self, bandit):
        assert bandit._arms == {}
        assert bandit._total_selections == 0

    def test_loads_persisted_file(self, tmp_path):
        (tmp_path / "music_bandit.json").write_text(json.dumps({
            "arms": {"working|day|Lo-Fi": [3.0, 1.0]},
            "total_selections": 10,
        }))
        b = MusicBandit(model_manager=None, data_dir=tmp_path)
        assert b._arms == {"working|day|Lo-Fi": [3.0, 1.0]}
        assert b._total_selections == 10


class TestSelect:
    def test_empty_candidates_returns_none(self, bandit):
        assert bandit.select("working", "day", []) is None

    def test_returns_one_of_candidates(self, bandit):
        candidates = [
            {"favorite_title": "Lo-Fi", "vibe": "chill"},
            {"favorite_title": "Synthwave", "vibe": "energetic"},
        ]
        # Disable forced exploration so we exercise the Thompson path.
        random.seed(0)
        chosen = bandit.select("working", "day", candidates)
        assert chosen in candidates
        assert bandit._total_selections == 1

    def test_creates_arm_for_new_candidate(self, bandit):
        candidates = [{"favorite_title": "Lo-Fi", "vibe": "chill"}]
        bandit.select("working", "day", candidates, preferred_vibes=["chill"])
        # Arm now exists with PRIOR_PREFERRED.
        key = "working|day|Lo-Fi"
        assert key in bandit._arms
        assert bandit._arms[key] == [PRIOR_PREFERRED[0], PRIOR_PREFERRED[1]]


class TestRecordReward:
    def test_positive_reward_increments_alpha(self, bandit, tmp_path):
        bandit.record_reward("working", "day", "Lo-Fi", REWARD_KEEP_PLAYING)
        key = "working|day|Lo-Fi"
        # New arm starts at PRIOR_DEFAULT then gets the reward.
        assert bandit._arms[key][0] == PRIOR_DEFAULT[0] + REWARD_KEEP_PLAYING
        assert bandit._arms[key][1] == PRIOR_DEFAULT[1]

    def test_negative_reward_increments_beta(self, bandit):
        bandit.record_reward("working", "day", "Lo-Fi", -1.0)
        key = "working|day|Lo-Fi"
        assert bandit._arms[key][0] == PRIOR_DEFAULT[0]
        assert bandit._arms[key][1] == PRIOR_DEFAULT[1] + 1.0

    def test_persists_to_disk(self, bandit, tmp_path):
        bandit.record_reward("working", "day", "Lo-Fi", 1.0)
        # File should exist with the new arm.
        on_disk = json.loads((tmp_path / "music_bandit.json").read_text())
        assert "working|day|Lo-Fi" in on_disk["arms"]


class TestGetStatus:
    def test_shape(self, bandit):
        bandit._arms = {
            "working|day|Lo-Fi": [3.0, 1.0],
            "working|day|Jazz": [1.0, 1.0],
            "relax|night|Ambient": [5.0, 1.0],
        }
        status = bandit.get_status()
        assert status["arm_count"] == 3
        assert "working" in status["arms_per_mode"]
        assert status["arms_per_mode"]["working"] == 2
        # Top arms within each mode sorted by mean descending.
        assert status["top_arms"]["working"][0]["title"] == "Lo-Fi"


@pytest.mark.asyncio
class TestRetrain:
    async def test_no_events_no_crash(self, bandit, ml_db):
        await bandit.retrain()
        assert bandit._arms == {}

    async def test_rebuilds_from_events(self, bandit, ml_db):
        now = datetime.now(timezone.utc)
        async with ml_db() as session:
            # auto_play kept playing → reward.
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=2),
                event_type="auto_play",
                favorite_title="Lo-Fi",
                mode_at_time="working",
                triggered_by="auto",
            ))
            # Manual play in same mode → another reward (different arm here).
            session.add(SonosPlaybackEvent(
                timestamp=now - timedelta(hours=1),
                event_type="play",
                favorite_title="Synthwave",
                mode_at_time="working",
                triggered_by="manual",
            ))
            await session.commit()

        await bandit.retrain()
        # Both events produced arms keyed by mode|period|title.
        keys = list(bandit._arms.keys())
        assert any("Lo-Fi" in k for k in keys)
        assert any("Synthwave" in k for k in keys)
        # Manual-play arm got REWARD_MANUAL_PLAY on top of PRIOR_DEFAULT.
        synth_key = next(k for k in keys if "Synthwave" in k)
        assert bandit._arms[synth_key][0] == PRIOR_DEFAULT[0] + REWARD_MANUAL_PLAY
