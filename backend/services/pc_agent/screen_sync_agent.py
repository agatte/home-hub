"""
Screen Sync Agent — standalone desktop process.

Runs on the user's desktop. Captures the dominant color of the primary
screen every 2.5 seconds and POSTs it to the Home Hub backend on the laptop.
The backend gates application by current automation mode (only gaming /
watching / movie modes apply the color); this agent stays dumb and always
sends.

Usage:
    python -m backend.services.pc_agent.screen_sync_agent
    python -m backend.services.pc_agent.screen_sync_agent --server http://192.168.1.30:8000

Autostart on Windows:
    Create a Task Scheduler task that runs at user logon. Action:
        python.exe -m backend.services.pc_agent.screen_sync_agent --server http://192.168.1.30:8000
    Set "Run whether user is logged on or not" off (it needs the user session
    to capture the screen). Set "Hidden" on so it stays out of the way.
"""
import argparse
import logging
import time
from typing import Optional

import httpx
import mss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("home_hub.screen_sync_agent")

CAPTURE_INTERVAL = 2.5  # seconds between captures


def capture_dominant_color() -> Optional[tuple[int, int, int]]:
    """
    Capture the primary screen and extract the dominant color.

    Grabs the full screen, downsamples to ~100x60, crops to the center 60%
    (avoiding taskbar / window chrome), and averages the pixel colors.
    """
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            screenshot = sct.grab(monitor)

            width = screenshot.width
            height = screenshot.height
            raw = screenshot.rgb

            step_x = max(1, width // 100)
            step_y = max(1, height // 60)

            x_start = int(width * 0.2)
            x_end = int(width * 0.8)
            y_start = int(height * 0.2)
            y_end = int(height * 0.8)

            r_total, g_total, b_total = 0, 0, 0
            count = 0

            for y in range(y_start, y_end, step_y):
                for x in range(x_start, x_end, step_x):
                    idx = (y * width + x) * 3
                    if idx + 2 < len(raw):
                        r_total += raw[idx]
                        g_total += raw[idx + 1]
                        b_total += raw[idx + 2]
                        count += 1

            if count == 0:
                return None

            return (r_total // count, g_total // count, b_total // count)
    except Exception as e:
        logger.error(f"Screen capture error: {e}")
        return None


def run_agent(server_url: str) -> None:
    """
    Main loop — capture, POST, sleep, repeat. Backs off on HTTP errors.
    """
    endpoint = f"{server_url.rstrip('/')}/api/automation/screen-color"
    backoff = 1

    logger.info(f"Screen Sync Agent started — reporting to {endpoint}")

    while True:
        try:
            rgb = capture_dominant_color()
            if rgb is not None:
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.post(
                            endpoint,
                            json={
                                "r": rgb[0],
                                "g": rgb[1],
                                "b": rgb[2],
                                "source": "desktop",
                            },
                        )
                        resp.raise_for_status()
                        backoff = 1
                except httpx.HTTPError as e:
                    logger.warning(f"Failed to report color: {e}")
                    backoff = min(backoff * 2, 60)

            time.sleep(CAPTURE_INTERVAL if backoff == 1 else backoff)

        except KeyboardInterrupt:
            logger.info("Screen sync agent stopped")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Home Hub Screen Sync Agent")
    parser.add_argument(
        "--server",
        default="http://localhost:8000",
        help="Home Hub server URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()
    run_agent(args.server)
