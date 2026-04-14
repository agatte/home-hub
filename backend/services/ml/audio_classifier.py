"""YAMNet audio scene classifier — maps ambient audio to 9 scene classes.

Uses Google's pretrained YAMNet TFLite model (521 AudioSet classes) with
a collapsing layer that maps to 9 Home Hub scene classes:
  silence, speech_single, speech_multiple, music, tv_dialog,
  game_audio, doorbell, cooking, mechanical_noise

The model accepts 0.975s of 16kHz mono audio as raw waveform input.
Only classification labels and confidence scores persist — raw audio is
overwritten each inference cycle. No audio is ever saved to disk.

Usage:
    classifier = AudioSceneClassifier()
    if classifier.load_model():
        result = classifier.classify(audio_float32)  # np.ndarray, shape (15600,)
"""

import csv
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("home_hub.ml.audio")

# YAMNet expects exactly 0.975s at 16kHz
YAMNET_SAMPLE_RATE = 16000
YAMNET_SAMPLES = 15600  # 0.975s * 16000

# Default model paths (relative to project root, persisted on Latitude)
DEFAULT_MODEL_DIR = Path("data/models")
MODEL_FILENAME = "yamnet.tflite"
CLASS_MAP_FILENAME = "yamnet_class_map.csv"

# Download URLs for the YAMNet TFLite model
MODEL_URL = "https://storage.googleapis.com/audioset/yamnet.tflite"
CLASS_MAP_URL = (
    "https://raw.githubusercontent.com/tensorflow/models/master/"
    "research/audioset/yamnet/yamnet_class_map.csv"
)

# Temporal smoothing window (number of inference results to average)
SMOOTHING_WINDOW = 10

# ── Target scene classes ────────────────────────────────────────────
# Each key is a Home Hub target class. Values are lists of substrings
# matched case-insensitively against YAMNet's display_name column.
# Order matters for ambiguous matches — first match wins.
TARGET_CLASS_KEYWORDS: dict[str, list[str]] = {
    "silence": ["silence"],
    "speech_single": ["narration", "monologue"],
    "speech_multiple": [
        "conversation",
        "crowd",
        "laughter",
        "babble",
        "chatter",
        "hubbub",
    ],
    "music": [
        "music",
        "musical instrument",
        "singing",
        "guitar",
        "piano",
        "drum",
        "bass",
        "organ",
        "synthesizer",
        "orchestra",
        "choir",
        "hip hop",
        "jazz",
        "rock",
        "pop",
        "reggae",
        "soul",
        "funk",
        "techno",
        "disco",
        "punk",
        "grunge",
    ],
    "game_audio": [
        "video game",
        "beep",
        "bleep",
        "buzzer",
    ],
    "doorbell": ["doorbell", "ding-dong", "ding dong", "knock"],
    "cooking": [
        "frying",
        "sizzle",
        "microwave",
        "chopping",
        "blender",
    ],
    "mechanical_noise": [
        "mechanical fan",
        "air conditioning",
        "vacuum cleaner",
        "washing machine",
        "hair dryer",
    ],
}

# "Speech" is broad — assign to speech_single as a fallback.
# speech_multiple keywords (conversation, crowd, etc.) are checked first
# in _build_class_mapping because they appear earlier in the dict.
SPEECH_FALLBACK_KEYWORDS = ["speech"]

# tv_dialog is a co-occurrence rule, not a simple keyword match.
# It requires both Speech AND Television scores > 0.3.
TV_DIALOG_KEYWORDS = ["television"]

# Confidence thresholds for mode mapping (from ML_SPEC)
MODE_THRESHOLDS: dict[str, dict] = {
    "speech_multiple": {"confidence": 0.80, "sustain_s": 30, "mode": "social"},
    "silence": {"confidence": 0.70, "sustain_s": 60, "mode": "quiet"},
    "game_audio": {"confidence": 0.75, "sustain_s": 0, "mode": "watching"},
}


@dataclass
class ClassificationResult:
    """Result of a single audio scene classification."""

    top_class: str
    confidence: float
    all_scores: dict[str, float]
    raw_yamnet_top5: list[tuple[str, float]]
    inference_ms: float


@dataclass
class SceneState:
    """Tracks sustained detection for mode-change gating."""

    current_class: str = ""
    class_start: float = 0.0

    def update(
        self, new_class: str, confidence: float, now: float
    ) -> Optional[str]:
        """Check if a scene class has been sustained long enough to signal a mode.

        Returns:
            Mode string ("social", "quiet", "watching") or None.
        """
        if new_class != self.current_class:
            self.current_class = new_class
            self.class_start = now
            return None

        threshold = MODE_THRESHOLDS.get(new_class)
        if threshold is None:
            return None

        if confidence < threshold["confidence"]:
            return None

        duration = now - self.class_start
        if duration >= threshold["sustain_s"]:
            return threshold["mode"]

        return None


class AudioSceneClassifier:
    """YAMNet-based audio scene classifier for Home Hub.

    Loads the YAMNet TFLite model, maps 521 AudioSet classes to 9 target
    scene classes, and applies temporal smoothing over a sliding window.
    """

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        self._model_dir = model_dir or DEFAULT_MODEL_DIR
        self._model_path = self._model_dir / MODEL_FILENAME
        self._class_map_path = self._model_dir / CLASS_MAP_FILENAME

        self._interpreter = None
        self._input_details = None
        self._output_details = None
        self._loaded = False

        # 521-index → target class name (or None for unmapped)
        self._index_to_target: dict[int, str] = {}
        # 521-index → YAMNet display name (for debug output)
        self._index_to_name: dict[int, str] = {}
        # Indices for tv_dialog co-occurrence detection
        self._tv_indices: list[int] = []
        self._speech_indices: list[int] = []

        # Temporal smoothing
        self._score_history: deque[dict[str, float]] = deque(
            maxlen=SMOOTHING_WINDOW
        )

    @property
    def is_loaded(self) -> bool:
        """Whether the model is loaded and ready for inference."""
        return self._loaded

    def load_model(self) -> bool:
        """Load the YAMNet TFLite model and class mapping.

        Returns:
            True if model loaded successfully.
        """
        if not self._ensure_model_files():
            return False

        try:
            from ai_edge_litert.interpreter import Interpreter

            self._interpreter = Interpreter(
                model_path=str(self._model_path)
            )
            self._interpreter.allocate_tensors()

            self._input_details = self._interpreter.get_input_details()
            self._output_details = self._interpreter.get_output_details()

            input_shape = self._input_details[0]["shape"]
            logger.info(
                "YAMNet loaded — input shape: %s, outputs: %d",
                input_shape.tolist(),
                len(self._output_details),
            )

            self._build_class_mapping()
            self._loaded = True
            logger.info(
                "Audio classifier ready — %d YAMNet classes mapped to %d targets",
                len(self._index_to_target),
                len(set(self._index_to_target.values())),
            )
            return True

        except ImportError:
            logger.error(
                "ai-edge-litert not installed — "
                "run: pip install ai-edge-litert"
            )
            return False
        except Exception as exc:
            logger.error(
                "Failed to load YAMNet model: %s", exc, exc_info=True
            )
            return False

    def classify(self, audio: np.ndarray) -> Optional[ClassificationResult]:
        """Classify an audio segment.

        Args:
            audio: Raw PCM audio as float32 in [-1.0, 1.0], shape (15600,).

        Returns:
            ClassificationResult or None on failure.
        """
        if not self._loaded or self._interpreter is None:
            return None

        try:
            start = time.perf_counter()

            # Ensure correct shape and dtype
            audio = audio.astype(np.float32)
            if audio.shape[0] > YAMNET_SAMPLES:
                audio = audio[:YAMNET_SAMPLES]
            elif audio.shape[0] < YAMNET_SAMPLES:
                audio = np.pad(audio, (0, YAMNET_SAMPLES - audio.shape[0]))

            # Reshape for model input
            input_shape = self._input_details[0]["shape"]
            if len(input_shape) == 2:
                audio = audio.reshape(1, -1)
            # else: some YAMNet builds expect (15600,) flat

            self._interpreter.set_tensor(
                self._input_details[0]["index"], audio
            )
            self._interpreter.invoke()

            # YAMNet outputs: [0] = scores (num_frames, 521)
            scores = self._interpreter.get_tensor(
                self._output_details[0]["index"]
            )

            # Average across frames if multiple
            if scores.ndim == 2:
                avg_scores = scores.mean(axis=0)
            else:
                avg_scores = scores.flatten()

            elapsed_ms = (time.perf_counter() - start) * 1000

            # Map to target classes
            scene_scores = self._map_yamnet_to_scene(avg_scores)

            # Apply temporal smoothing
            smoothed = self._apply_temporal_smoothing(scene_scores)

            # Top class
            top_class = max(smoothed, key=smoothed.get)
            top_confidence = smoothed[top_class]

            # Raw YAMNet top-5 for debugging
            top5_indices = np.argsort(avg_scores)[-5:][::-1]
            raw_top5 = [
                (
                    self._index_to_name.get(int(i), f"class_{i}"),
                    float(avg_scores[i]),
                )
                for i in top5_indices
            ]

            return ClassificationResult(
                top_class=top_class,
                confidence=top_confidence,
                all_scores=smoothed,
                raw_yamnet_top5=raw_top5,
                inference_ms=round(elapsed_ms, 1),
            )

        except Exception as exc:
            logger.error("Classification failed: %s", exc, exc_info=True)
            return None

    def get_status(self) -> dict:
        """Return classifier status for health checks."""
        return {
            "loaded": self._loaded,
            "model_path": str(self._model_path),
            "mapped_classes": len(self._index_to_target),
            "smoothing_window": SMOOTHING_WINDOW,
            "history_size": len(self._score_history),
        }

    def reset_history(self) -> None:
        """Clear the temporal smoothing buffer."""
        self._score_history.clear()

    # ── Private methods ─────────────────────────────────────────────

    def _ensure_model_files(self) -> bool:
        """Check model files exist; download if missing.

        Returns:
            True if files are available.
        """
        self._model_dir.mkdir(parents=True, exist_ok=True)

        if self._model_path.exists() and self._class_map_path.exists():
            return True

        logger.info("YAMNet model files not found — attempting download...")
        return self._download_model_files()

    def _download_model_files(self) -> bool:
        """Download YAMNet TFLite model and class map from TFHub.

        Returns:
            True if both files downloaded successfully.
        """
        try:
            import httpx

            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                if not self._model_path.exists():
                    logger.info("Downloading YAMNet TFLite model...")
                    resp = client.get(MODEL_URL)
                    resp.raise_for_status()
                    self._model_path.write_bytes(resp.content)
                    logger.info(
                        "YAMNet model saved (%d bytes)",
                        len(resp.content),
                    )

                if not self._class_map_path.exists():
                    logger.info("Downloading YAMNet class map...")
                    resp = client.get(CLASS_MAP_URL)
                    resp.raise_for_status()
                    self._class_map_path.write_bytes(resp.content)
                    logger.info("YAMNet class map saved")

            return True

        except Exception as exc:
            logger.error(
                "Failed to download YAMNet files: %s. "
                "Place yamnet.tflite and yamnet_class_map.csv "
                "in %s manually.",
                exc,
                self._model_dir,
            )
            return False

    def _build_class_mapping(self) -> None:
        """Parse yamnet_class_map.csv and build index → target class mapping."""
        if not self._class_map_path.exists():
            logger.warning("Class map CSV not found at %s", self._class_map_path)
            return

        with self._class_map_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx = int(row["index"])
                display_name = row["display_name"].strip()
                self._index_to_name[idx] = display_name

                name_lower = display_name.lower()

                # Check tv_dialog keywords (co-occurrence, not direct map)
                for kw in TV_DIALOG_KEYWORDS:
                    if kw in name_lower:
                        self._tv_indices.append(idx)

                # Check speech keywords (for co-occurrence tracking)
                for kw in SPEECH_FALLBACK_KEYWORDS:
                    if kw in name_lower:
                        self._speech_indices.append(idx)

                # Match against target classes (first match wins)
                matched = False
                for target, keywords in TARGET_CLASS_KEYWORDS.items():
                    for kw in keywords:
                        if kw in name_lower:
                            self._index_to_target[idx] = target
                            matched = True
                            break
                    if matched:
                        break

                # Speech fallback — if not already matched, assign to
                # speech_single
                if not matched:
                    for kw in SPEECH_FALLBACK_KEYWORDS:
                        if kw in name_lower:
                            self._index_to_target[idx] = "speech_single"
                            break

    def _map_yamnet_to_scene(
        self, yamnet_scores: np.ndarray
    ) -> dict[str, float]:
        """Collapse 521 YAMNet scores into 9 target scene scores.

        Uses max-pooling: for each target class, take the highest score
        among all YAMNet indices mapped to it.

        Special case: tv_dialog is detected via co-occurrence of Speech
        and Television scores both exceeding 0.3.
        """
        all_targets = list(TARGET_CLASS_KEYWORDS.keys()) + ["tv_dialog"]
        raw: dict[str, float] = {t: 0.0 for t in all_targets}

        for idx, target in self._index_to_target.items():
            if idx < len(yamnet_scores):
                raw[target] = max(raw[target], float(yamnet_scores[idx]))

        # tv_dialog co-occurrence: Speech AND Television both > 0.3
        tv_max = max(
            (float(yamnet_scores[i]) for i in self._tv_indices
             if i < len(yamnet_scores)),
            default=0.0,
        )
        speech_max = max(
            (float(yamnet_scores[i]) for i in self._speech_indices
             if i < len(yamnet_scores)),
            default=0.0,
        )
        if tv_max > 0.3 and speech_max > 0.3:
            raw["tv_dialog"] = min(tv_max, speech_max)
            # Reduce speech_single to avoid double-counting
            raw["speech_single"] = max(
                0.0, raw["speech_single"] - raw["tv_dialog"]
            )

        # Normalize to sum=1.0 (softmax-style but simpler)
        total = sum(raw.values())
        if total > 0:
            return {k: v / total for k, v in raw.items()}
        return raw

    def _apply_temporal_smoothing(
        self, raw_scores: dict[str, float]
    ) -> dict[str, float]:
        """Average scores over the sliding window for stability."""
        self._score_history.append(raw_scores)

        if len(self._score_history) == 1:
            return raw_scores

        all_keys = raw_scores.keys()
        smoothed: dict[str, float] = {}
        for key in all_keys:
            values = [h.get(key, 0.0) for h in self._score_history]
            smoothed[key] = sum(values) / len(values)

        return smoothed
