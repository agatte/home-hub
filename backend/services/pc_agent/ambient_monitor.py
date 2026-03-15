"""
Ambient noise monitor — uses the Blue Yeti microphone for social detection.

Measures real-time RMS audio levels from the mic to detect when multiple people
are in the room (party/social mode). Never records or saves audio — only
measures volume levels in memory.

Detection logic:
  - Sustained ambient noise above threshold for >2 minutes = "social" mode
  - Gaming mode (from activity_detector) takes priority — headset isolates
    game audio, so mic stays quiet during solo gaming sessions

Usage:
    python -m backend.services.pc_agent.ambient_monitor
    python -m backend.services.pc_agent.ambient_monitor --server http://192.168.1.30:8000
"""
import argparse
import audioop
import logging
import struct
import sys
import time
from collections import deque
from datetime import datetime
from typing import Optional

import httpx

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


class AmbientMonitor:
    """
    Monitors ambient audio levels from the Blue Yeti microphone.

    Only measures RMS (root mean square) volume — no audio is recorded,
    stored, or transmitted. Data stays in memory for <5 seconds.
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self._threshold = threshold
        self._rms_history: deque[float] = deque(maxlen=WINDOW_SECONDS)
        self._loud_start: Optional[float] = None
        self._quiet_start: Optional[float] = None
        self._is_social = False
        self._stream = None
        self._audio = None

    @property
    def threshold(self) -> int:
        """Current noise threshold for social detection."""
        return self._threshold

    @threshold.setter
    def threshold(self, value: int) -> None:
        """Update the noise threshold."""
        self._threshold = max(100, value)
        logger.info(f"Ambient threshold updated to {self._threshold}")

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

    def _read_rms(self) -> Optional[float]:
        """
        Read a chunk of audio and compute the RMS level.

        Returns:
            RMS value as a float, or None if the read failed.
        """
        if not self._stream:
            return None

        try:
            data = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
            rms = audioop.rms(data, FORMAT_WIDTH)
            return float(rms)
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
        rms = self._read_rms()
        if rms is None:
            return None

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
            rms = self._read_rms()
            if rms is not None:
                readings.append(rms)
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


def run_monitor(server_url: str) -> None:
    """
    Main loop — monitor ambient noise, report social/quiet changes to server.

    Args:
        server_url: Base URL of the Home Hub backend.
    """
    monitor = AmbientMonitor()
    endpoint = f"{server_url.rstrip('/')}/api/automation/activity"

    if not monitor._init_audio():
        logger.error("Cannot start ambient monitor — mic not available")
        sys.exit(1)

    # Auto-calibrate on startup
    monitor.calibrate(duration=5)

    logger.info(
        f"Ambient monitor started — threshold: {monitor.threshold}, "
        f"reporting to {endpoint}"
    )

    try:
        while True:
            result = monitor.check()

            if result in ("social", "quiet"):
                mode = "social" if result == "social" else "idle"
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.post(
                            endpoint,
                            json={
                                "mode": mode,
                                "source": "ambient",
                                "detected_at": datetime.now().isoformat(),
                            },
                        )
                        resp.raise_for_status()
                        logger.info(f"Reported '{mode}' to server")
                except httpx.HTTPError as e:
                    logger.warning(f"Failed to report to server: {e}")

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
    args = parser.parse_args()
    run_monitor(args.server)
