"""
Ambient noise monitor — uses the Blue Yeti microphone for social detection.

Measures real-time RMS audio levels from the mic to detect when multiple people
are in the room (party/social mode). Optionally runs a YAMNet-based audio
scene classifier in shadow mode alongside the RMS detector.

Never records or saves audio — only measures volume levels and (when the
classifier is enabled) computes ephemeral classification labels in memory.

Detection logic (RMS):
  - Sustained ambient noise above threshold for >2 minutes = "social" mode
  - Gaming mode (from activity_detector) takes priority — headset isolates
    game audio, so mic stays quiet during solo gaming sessions

Detection logic (YAMNet classifier, shadow/active):
  - speech_multiple ≥80% for 30s → social
  - silence ≥70% for 60s → quiet (exit social)
  - game_audio ≥75% → watching (when no game process detected)

Usage:
    python -m backend.services.pc_agent.ambient_monitor
    python -m backend.services.pc_agent.ambient_monitor --server http://192.168.1.210:8000
    python -m backend.services.pc_agent.ambient_monitor --classifier --shadow
    python -m backend.services.pc_agent.ambient_monitor --classifier --active
"""

import argparse
import logging
import sys
import time
from collections import deque
from datetime import datetime
from typing import Optional

import httpx
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("home_hub.ambient")

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024  # Samples per read
FORMAT_WIDTH = 2  # 16-bit audio = 2 bytes

# Detection settings
WINDOW_SECONDS = 5  # RMS averaging window
SUSTAINED_SECONDS = 120  # 2 minutes of sustained noise = social
QUIET_SECONDS = 60  # 1 minute of quiet resets social detection
POLL_INTERVAL = 1  # Read mic every second
DEFAULT_THRESHOLD = 800  # RMS threshold (calibrated per environment)

# YAMNet buffer size (0.975s at 16kHz)
YAMNET_SAMPLES = 15600

# Shadow logging throttle — log on class change or every N seconds
SHADOW_LOG_INTERVAL = 30


class AmbientMonitor:
    """
    Monitors ambient audio levels from the Blue Yeti microphone.

    Only measures RMS (root mean square) volume — no audio is recorded,
    stored, or transmitted. Data stays in memory for <5 seconds.

    When classifier_enabled=True, also runs YAMNet audio scene classification
    on the same audio stream.
    """

    def __init__(
        self,
        threshold: int = DEFAULT_THRESHOLD,
        classifier_enabled: bool = False,
        shadow_mode: bool = True,
    ) -> None:
        self._threshold = threshold
        self._rms_history: deque[float] = deque(maxlen=WINDOW_SECONDS)
        self._loud_start: Optional[float] = None
        self._quiet_start: Optional[float] = None
        self._is_social = False
        self._stream = None
        self._audio = None

        # YAMNet classifier
        self._classifier_enabled = classifier_enabled
        self._shadow_mode = shadow_mode
        self._classifier = None
        self._scene_state = None
        self._audio_buffer: deque = deque(maxlen=YAMNET_SAMPLES)

        if classifier_enabled:
            self._init_classifier()

    @property
    def threshold(self) -> int:
        """Current noise threshold for social detection."""
        return self._threshold

    @threshold.setter
    def threshold(self, value: int) -> None:
        """Update the noise threshold."""
        self._threshold = max(100, value)
        logger.info(f"Ambient threshold updated to {self._threshold}")

    def _init_classifier(self) -> None:
        """Initialize the YAMNet audio scene classifier."""
        try:
            from backend.services.ml.audio_classifier import (
                AudioSceneClassifier,
                SceneState,
            )

            self._classifier = AudioSceneClassifier()
            if self._classifier.load_model():
                self._scene_state = SceneState()
                logger.info(
                    "YAMNet classifier loaded — mode: %s",
                    "shadow" if self._shadow_mode else "active",
                )
            else:
                logger.warning(
                    "YAMNet classifier failed to load — "
                    "falling back to RMS-only detection"
                )
                self._classifier = None
        except ImportError as exc:
            logger.warning(
                "Cannot import audio classifier: %s — "
                "falling back to RMS-only detection",
                exc,
            )
            self._classifier = None

    def _init_audio(self) -> bool:
        """
        Initialize PyAudio and open the microphone stream.

        Returns:
            True if the mic was found and opened successfully.
        """
        try:
            import pyaudio

            self._audio = pyaudio.PyAudio()

            # Find the Blue Yeti (or fall back to default input)
            device_index = None
            for i in range(self._audio.get_device_count()):
                info = self._audio.get_device_info_by_index(i)
                name = info.get("name", "").lower()
                if "yeti" in name or "blue" in name:
                    device_index = i
                    logger.info(f"Found Blue Yeti at device index {i}: {info['name']}")
                    break

            if device_index is None:
                # Fall back to default input device
                default = self._audio.get_default_input_device_info()
                device_index = int(default["index"])
                logger.info(
                    f"Blue Yeti not found — using default input: {default['name']}"
                )

            self._stream = self._audio.open(
                format=self._audio.get_format_from_width(FORMAT_WIDTH),
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=CHUNK_SIZE,
            )
            return True

        except ImportError:
            logger.error("pyaudio not installed — run: pip install pyaudio")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize microphone: {e}")
            return False

    def _read_rms(self) -> Optional[tuple[float, bytes]]:
        """
        Read a chunk of audio and compute the RMS level.

        Returns:
            Tuple of (RMS value, raw audio bytes), or None if the read failed.
        """
        if not self._stream:
            return None

        try:
            data = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float64)
            rms = float(np.sqrt(np.mean(samples ** 2)))
            return rms, data
        except Exception as e:
            logger.error(f"Error reading mic: {e}")
            return None

    def check(self) -> Optional[str]:
        """
        Read audio level and determine if we're in social mode.

        Returns:
            "social" if sustained noise detected, "quiet" if noise stopped,
            None if no change.
        """
        read_result = self._read_rms()
        if read_result is None:
            return None

        rms, raw_bytes = read_result

        # Feed raw audio into YAMNet buffer
        if self._classifier is not None:
            samples = np.frombuffer(raw_bytes, dtype=np.int16)
            self._audio_buffer.extend(samples.tolist())

        self._rms_history.append(rms)

        # Average over the window
        avg_rms = sum(self._rms_history) / len(self._rms_history)
        now = time.time()

        if avg_rms > self._threshold:
            # Noise above threshold
            self._quiet_start = None

            if self._loud_start is None:
                self._loud_start = now

            elif now - self._loud_start >= SUSTAINED_SECONDS and not self._is_social:
                self._is_social = True
                logger.info(
                    f"Social mode detected — sustained noise for "
                    f"{SUSTAINED_SECONDS}s (avg RMS: {avg_rms:.0f})"
                )
                return "social"

        else:
            # Below threshold
            self._loud_start = None

            if self._is_social:
                if self._quiet_start is None:
                    self._quiet_start = now
                elif now - self._quiet_start >= QUIET_SECONDS:
                    self._is_social = False
                    self._quiet_start = None
                    logger.info("Social mode ended — room is quiet")
                    return "quiet"

        return None

    def classify_scene(self) -> Optional[dict]:
        """Run YAMNet classification on the buffered audio.

        Returns:
            Dict with classification result and mode signal, or None
            if the buffer isn't full or classification failed.
        """
        if self._classifier is None or self._scene_state is None:
            return None

        if len(self._audio_buffer) < YAMNET_SAMPLES:
            return None

        # Convert buffer to float32 waveform in [-1.0, 1.0]
        audio = np.array(list(self._audio_buffer), dtype=np.float32)
        audio = audio / 32768.0

        result = self._classifier.classify(audio)
        if result is None:
            return None

        now = time.time()
        mode_signal = self._scene_state.update(
            result.top_class, result.confidence, now
        )

        return {
            "top_class": result.top_class,
            "confidence": result.confidence,
            "all_scores": result.all_scores,
            "raw_yamnet_top5": result.raw_yamnet_top5,
            "inference_ms": result.inference_ms,
            "mode_signal": mode_signal,
        }

    def calibrate(self, duration: int = 10) -> int:
        """
        Calibrate the noise threshold by measuring the ambient noise floor.

        Measures RMS for `duration` seconds and sets the threshold to
        2x the average (to account for normal background noise).

        Args:
            duration: Seconds to measure.

        Returns:
            The new threshold value.
        """
        logger.info(f"Calibrating ambient noise floor for {duration}s...")
        readings: list[float] = []

        for _ in range(duration):
            read_result = self._read_rms()
            if read_result is not None:
                readings.append(read_result[0])
            time.sleep(1)

        if readings:
            avg = sum(readings) / len(readings)
            self._threshold = max(100, int(avg * 2))
            logger.info(
                f"Calibration complete — avg floor: {avg:.0f}, "
                f"new threshold: {self._threshold}"
            )
        else:
            logger.warning("Calibration failed — no readings. Using default threshold.")

        return self._threshold

    def close(self) -> None:
        """Clean up audio resources."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._audio:
            self._audio.terminate()


def run_monitor(
    server_url: str,
    classifier_enabled: bool = False,
    shadow_mode: bool = True,
) -> None:
    """
    Main loop — monitor ambient noise, report social/quiet changes to server.

    Args:
        server_url: Base URL of the Home Hub backend.
        classifier_enabled: Whether to run YAMNet classifier.
        shadow_mode: If True, log ML results but don't act on them.
    """
    monitor = AmbientMonitor(
        classifier_enabled=classifier_enabled,
        shadow_mode=shadow_mode,
    )
    base_url = server_url.rstrip("/")
    activity_endpoint = f"{base_url}/api/automation/activity"
    ml_endpoint = f"{base_url}/api/learning/audio-decision"

    if not monitor._init_audio():
        logger.error("Cannot start ambient monitor — mic not available")
        sys.exit(1)

    # Auto-calibrate on startup
    monitor.calibrate(duration=5)

    mode_label = "shadow" if shadow_mode else "active"
    classifier_label = (
        f"YAMNet ({mode_label})" if classifier_enabled else "disabled"
    )
    logger.info(
        "Ambient monitor started — threshold: %d, classifier: %s, "
        "reporting to %s",
        monitor.threshold,
        classifier_label,
        activity_endpoint,
    )

    # Shadow logging throttle state
    last_logged_class: Optional[str] = None
    last_log_time: float = 0.0

    try:
        while True:
            # ── RMS-based detection (always runs) ──────────────
            rms_result = monitor.check()

            if rms_result in ("social", "quiet"):
                mode = "social" if rms_result == "social" else "idle"
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.post(
                            activity_endpoint,
                            json={
                                "mode": mode,
                                "source": "ambient",
                                "detected_at": datetime.now().isoformat(),
                            },
                        )
                        resp.raise_for_status()
                        logger.info(f"Reported '{mode}' to server (RMS)")
                except httpx.HTTPError as e:
                    logger.warning(f"Failed to report RMS result to server: {e}")

            # ── YAMNet classification ──────────────────────────
            if classifier_enabled:
                ml_result = monitor.classify_scene()
                if ml_result is not None:
                    mode_signal = ml_result["mode_signal"]

                    # Determine what mode the ML would set
                    ml_mode = None
                    if mode_signal == "social":
                        ml_mode = "social"
                    elif mode_signal == "quiet":
                        ml_mode = "idle"
                    elif mode_signal == "watching":
                        ml_mode = "watching"

                    # Determine what RMS would say right now
                    rms_would_say = None
                    if rms_result == "social":
                        rms_would_say = "social"
                    elif rms_result == "quiet":
                        rms_would_say = "idle"

                    # In active mode, use ML result for mode changes
                    if not shadow_mode and ml_mode is not None:
                        try:
                            with httpx.Client(timeout=5.0) as client:
                                resp = client.post(
                                    activity_endpoint,
                                    json={
                                        "mode": ml_mode,
                                        "source": "audio_ml",
                                        "detected_at": datetime.now().isoformat(),
                                    },
                                )
                                resp.raise_for_status()
                                logger.info(
                                    "Reported '%s' to server (YAMNet active)",
                                    ml_mode,
                                )
                        except httpx.HTTPError as e:
                            logger.warning(
                                "Failed to report ML result to server: %s", e
                            )

                    # Log ML decision — throttled in shadow mode
                    # (log on class change, mode signal, or every 30s)
                    now_log = time.time()
                    class_changed = ml_result["top_class"] != last_logged_class
                    interval_elapsed = (now_log - last_log_time) >= SHADOW_LOG_INTERVAL
                    should_log = (
                        not shadow_mode
                        or class_changed
                        or mode_signal is not None
                        or interval_elapsed
                    )

                    if should_log:
                        last_logged_class = ml_result["top_class"]
                        last_log_time = now_log
                        try:
                            with httpx.Client(timeout=5.0) as client:
                                resp = client.post(
                                    ml_endpoint,
                                    json={
                                        "predicted_mode": ml_mode or ml_result["top_class"],
                                        "confidence": ml_result["confidence"],
                                        "applied": not shadow_mode and ml_mode is not None,
                                        "factors": {
                                            "top_class": ml_result["top_class"],
                                            "all_scores": ml_result["all_scores"],
                                            "raw_yamnet_top5": ml_result["raw_yamnet_top5"],
                                            "inference_ms": ml_result["inference_ms"],
                                            "rms_would_say": rms_would_say,
                                            "mode_signal": mode_signal,
                                            "shadow_mode": shadow_mode,
                                        },
                                    },
                                )
                                resp.raise_for_status()
                        except httpx.HTTPError as e:
                            logger.debug("Failed to log ML decision: %s", e)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Ambient monitor stopped")
    finally:
        monitor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Home Hub Ambient Noise Monitor")
    parser.add_argument(
        "--server",
        default="http://localhost:8000",
        help="Home Hub server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--classifier",
        action="store_true",
        help="Enable YAMNet audio scene classifier",
    )
    parser.add_argument(
        "--shadow",
        action="store_true",
        default=True,
        help="Run classifier in shadow mode (log only, don't act). Default.",
    )
    parser.add_argument(
        "--active",
        action="store_true",
        help="Run classifier in active mode (ML drives mode changes)",
    )
    args = parser.parse_args()

    shadow = not args.active
    run_monitor(
        server_url=args.server,
        classifier_enabled=args.classifier,
        shadow_mode=shadow,
    )
