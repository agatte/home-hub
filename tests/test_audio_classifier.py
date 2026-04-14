"""
Tests for the YAMNet audio scene classifier.

Tests class mapping, temporal smoothing, SceneState sustained-detection
logic, and confidence thresholds. Does NOT require the actual YAMNet model
file — all tests use mocked inference results.
"""

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.services.ml.audio_classifier import (
    SMOOTHING_WINDOW,
    YAMNET_SAMPLES,
    AudioSceneClassifier,
    ClassificationResult,
    SceneState,
)


# ---------------------------------------------------------------------------
# SceneState — sustained detection gating
# ---------------------------------------------------------------------------


class TestSceneState:
    """Verify sustained-duration + confidence gates for mode signals."""

    def test_speech_multiple_below_sustain_returns_none(self):
        state = SceneState()
        now = time.time()
        # First call sets the class
        assert state.update("speech_multiple", 0.85, now) is None
        # 29 seconds later — not yet sustained
        assert state.update("speech_multiple", 0.85, now + 29) is None

    def test_speech_multiple_above_sustain_returns_social(self):
        state = SceneState()
        now = time.time()
        state.update("speech_multiple", 0.85, now)
        result = state.update("speech_multiple", 0.85, now + 31)
        assert result == "social"

    def test_speech_multiple_below_confidence_never_triggers(self):
        state = SceneState()
        now = time.time()
        state.update("speech_multiple", 0.79, now)
        # Even after a long time, 79% < 80% threshold
        assert state.update("speech_multiple", 0.79, now + 300) is None

    def test_silence_returns_quiet_after_60s(self):
        state = SceneState()
        now = time.time()
        state.update("silence", 0.75, now)
        assert state.update("silence", 0.75, now + 59) is None
        assert state.update("silence", 0.75, now + 61) == "quiet"

    def test_silence_below_confidence_never_triggers(self):
        state = SceneState()
        now = time.time()
        state.update("silence", 0.69, now)
        assert state.update("silence", 0.69, now + 120) is None

    def test_game_audio_triggers_immediately(self):
        """game_audio has sustain_s=0, so it triggers on first sustained check."""
        state = SceneState()
        now = time.time()
        state.update("game_audio", 0.80, now)
        # Second call with same class — duration >= 0
        result = state.update("game_audio", 0.80, now + 1)
        assert result == "watching"

    def test_class_change_resets_timer(self):
        state = SceneState()
        now = time.time()
        state.update("speech_multiple", 0.85, now)
        state.update("speech_multiple", 0.85, now + 20)
        # Class changes — timer resets
        state.update("music", 0.90, now + 25)
        # Back to speech_multiple — timer starts over
        state.update("speech_multiple", 0.85, now + 26)
        # Only 10s since reset, not 30s
        assert state.update("speech_multiple", 0.85, now + 36) is None
        # Now 30s since reset
        assert state.update("speech_multiple", 0.85, now + 57) == "social"

    def test_unmapped_class_returns_none(self):
        state = SceneState()
        now = time.time()
        state.update("music", 0.95, now)
        assert state.update("music", 0.95, now + 300) is None


# ---------------------------------------------------------------------------
# Temporal smoothing
# ---------------------------------------------------------------------------


class TestTemporalSmoothing:
    """Verify that temporal smoothing averages over the window."""

    def setup_method(self):
        self.classifier = AudioSceneClassifier.__new__(AudioSceneClassifier)
        from collections import deque
        self.classifier._score_history = deque(maxlen=SMOOTHING_WINDOW)

    def test_single_result_returns_unchanged(self):
        scores = {"silence": 0.8, "speech_single": 0.1, "music": 0.1}
        result = self.classifier._apply_temporal_smoothing(scores)
        assert result == scores

    def test_smoothing_averages_over_history(self):
        # Feed 5 frames of silence, then 5 frames of music
        for _ in range(5):
            self.classifier._apply_temporal_smoothing(
                {"silence": 0.9, "music": 0.1}
            )
        result = self.classifier._apply_temporal_smoothing(
            {"silence": 0.1, "music": 0.9}
        )
        # After 6 frames (5 silence + 1 music), silence should still dominate
        assert result["silence"] > result["music"]

    def test_spike_doesnt_dominate(self):
        # 9 frames of silence
        for _ in range(9):
            self.classifier._apply_temporal_smoothing(
                {"silence": 0.9, "speech_multiple": 0.05, "music": 0.05}
            )
        # 1 spike of speech
        result = self.classifier._apply_temporal_smoothing(
            {"silence": 0.1, "speech_multiple": 0.8, "music": 0.1}
        )
        # Silence should still be top class after smoothing
        assert result["silence"] > result["speech_multiple"]


# ---------------------------------------------------------------------------
# ClassificationResult dataclass
# ---------------------------------------------------------------------------


class TestClassificationResult:
    """Verify the result dataclass structure."""

    def test_fields(self):
        result = ClassificationResult(
            top_class="speech_multiple",
            confidence=0.87,
            all_scores={"speech_multiple": 0.87, "silence": 0.13},
            raw_yamnet_top5=[("Conversation", 0.72), ("Speech", 0.65)],
            inference_ms=15.3,
        )
        assert result.top_class == "speech_multiple"
        assert result.confidence == 0.87
        assert len(result.raw_yamnet_top5) == 2
        assert result.inference_ms == 15.3


# ---------------------------------------------------------------------------
# Class mapping
# ---------------------------------------------------------------------------


class TestClassMapping:
    """Verify YAMNet → target class mapping logic."""

    def _make_classifier_with_csv(self, tmp_path, rows):
        """Create a classifier with a fake class map CSV."""
        csv_path = tmp_path / "yamnet_class_map.csv"
        with csv_path.open("w", encoding="utf-8") as f:
            f.write("index,mid,display_name\n")
            for idx, mid, name in rows:
                f.write(f"{idx},{mid},{name}\n")

        clf = AudioSceneClassifier.__new__(AudioSceneClassifier)
        clf._class_map_path = csv_path
        clf._index_to_target = {}
        clf._index_to_name = {}
        clf._tv_indices = []
        clf._speech_indices = []
        clf._build_class_mapping()
        return clf

    def test_silence_mapped(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(0, "/m/0", "Silence")]
        )
        assert clf._index_to_target[0] == "silence"

    def test_conversation_maps_to_speech_multiple(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(2, "/m/2", "Conversation")]
        )
        assert clf._index_to_target[2] == "speech_multiple"

    def test_speech_fallback_to_speech_single(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(1, "/m/1", "Speech")]
        )
        assert clf._index_to_target[1] == "speech_single"

    def test_music_mapped(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(137, "/m/137", "Music")]
        )
        assert clf._index_to_target[137] == "music"

    def test_television_tracked_for_tv_dialog(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(520, "/m/520", "Television")]
        )
        assert 520 in clf._tv_indices

    def test_doorbell_mapped(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(335, "/m/335", "Doorbell")]
        )
        assert clf._index_to_target[335] == "doorbell"

    def test_vacuum_maps_to_mechanical_noise(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(398, "/m/398", "Vacuum cleaner")]
        )
        assert clf._index_to_target[398] == "mechanical_noise"

    def test_unmapped_class_not_in_target(self, tmp_path):
        clf = self._make_classifier_with_csv(
            tmp_path, [(999, "/m/999", "Exotic Bird Call")]
        )
        assert 999 not in clf._index_to_target


# ---------------------------------------------------------------------------
# Score mapping (521 → 9)
# ---------------------------------------------------------------------------


class TestScoreMapping:
    """Verify the max-pooling score collapse and tv_dialog co-occurrence."""

    def _make_classifier(self, tmp_path):
        rows = [
            (0, "/m/0", "Silence"),
            (1, "/m/1", "Speech"),
            (2, "/m/2", "Conversation"),
            (137, "/m/137", "Music"),
            (519, "/m/519", "Video game music"),
            (520, "/m/520", "Television"),
        ]
        csv_path = tmp_path / "yamnet_class_map.csv"
        with csv_path.open("w", encoding="utf-8") as f:
            f.write("index,mid,display_name\n")
            for idx, mid, name in rows:
                f.write(f"{idx},{mid},{name}\n")

        clf = AudioSceneClassifier.__new__(AudioSceneClassifier)
        clf._class_map_path = csv_path
        clf._index_to_target = {}
        clf._index_to_name = {}
        clf._tv_indices = []
        clf._speech_indices = []
        clf._build_class_mapping()
        return clf

    def test_max_pooling(self, tmp_path):
        clf = self._make_classifier(tmp_path)
        scores = np.zeros(521, dtype=np.float32)
        scores[0] = 0.9  # Silence
        result = clf._map_yamnet_to_scene(scores)
        assert result["silence"] > 0
        assert result["silence"] == max(result.values())

    def test_tv_dialog_cooccurrence(self, tmp_path):
        clf = self._make_classifier(tmp_path)
        scores = np.zeros(521, dtype=np.float32)
        scores[1] = 0.5   # Speech
        scores[520] = 0.4  # Television
        result = clf._map_yamnet_to_scene(scores)
        assert result["tv_dialog"] > 0

    def test_no_tv_dialog_without_cooccurrence(self, tmp_path):
        clf = self._make_classifier(tmp_path)
        scores = np.zeros(521, dtype=np.float32)
        scores[1] = 0.5   # Speech only, no TV
        result = clf._map_yamnet_to_scene(scores)
        assert result["tv_dialog"] == 0.0

    def test_scores_sum_to_one(self, tmp_path):
        clf = self._make_classifier(tmp_path)
        scores = np.zeros(521, dtype=np.float32)
        scores[0] = 0.3
        scores[137] = 0.5
        scores[2] = 0.2
        result = clf._map_yamnet_to_scene(scores)
        assert abs(sum(result.values()) - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify classifier handles missing model gracefully."""

    def test_classify_when_not_loaded_returns_none(self):
        clf = AudioSceneClassifier(model_dir=None)
        clf._loaded = False
        result = clf.classify(np.zeros(YAMNET_SAMPLES, dtype=np.float32))
        assert result is None

    def test_status_when_not_loaded(self):
        clf = AudioSceneClassifier.__new__(AudioSceneClassifier)
        clf._loaded = False
        clf._model_path = "fake/path"
        clf._index_to_target = {}
        clf._score_history = MagicMock()
        clf._score_history.__len__ = lambda _: 0
        status = clf.get_status()
        assert status["loaded"] is False
