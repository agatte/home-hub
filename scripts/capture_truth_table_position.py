"""Capture both cameras + presence state for one truth-table position.

Used during the dual-camera arbitration diagnostic walk. Each invocation:
    1. Snapshots the Latitude camera (annotated).
    2. Requests + polls a snapshot from the desktop pc_agent.
    3. Captures the current PresenceFusion sources + camera status.
    4. Saves everything under data/diagnostics/truthtable/<label>/.

Usage:
    python scripts/capture_truth_table_position.py <label>

Example:
    python scripts/capture_truth_table_position.py 02_bed_chair_out
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


BASE = os.environ.get("HOME_HUB_URL", "http://192.168.86.210:8000")
API_KEY = os.environ.get("HOME_HUB_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
DESKTOP_POLL_TIMEOUT_S = 20


def _post(path: str, **kwargs) -> httpx.Response:
    return httpx.post(f"{BASE}{path}", headers=HEADERS, timeout=8, **kwargs)


def _get(path: str, **kwargs) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", headers=HEADERS, timeout=8, **kwargs)


def main(label: str) -> int:
    out_dir = Path("data/diagnostics/truthtable") / label
    out_dir.mkdir(parents=True, exist_ok=True)
    capture_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"[{label}] capturing at {capture_ts}")

    # 1. Latitude snapshot (annotated for context)
    r = _get("/api/camera/snapshot?annotate=true")
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
        (out_dir / f"latitude_{capture_ts}.jpg").write_bytes(r.content)
        print(f"  Latitude snapshot: {len(r.content)} bytes")
    else:
        print(f"  Latitude snapshot FAILED: {r.status_code} {r.text[:150]}")

    # 2. Capture presence + camera status BEFORE requesting desktop snapshot
    #    so we have the state at the moment we triggered the test.
    r = _get("/api/camera/status")
    if r.status_code == 200:
        (out_dir / f"camera_status_{capture_ts}.json").write_text(
            json.dumps(r.json(), indent=2)
        )
        sources = r.json().get("presence", {}).get("sources", {})
        for src, info in sources.items():
            print(
                f"  {src}: face_present={info.get('face_present')} "
                f"face_conf={info.get('face_confidence')} "
                f"zone={info.get('zone')} posture={info.get('posture')} "
                f"detection_source={info.get('detection_source')} "
                f"age_s={info.get('age_s')}"
            )

    # 3. Desktop snapshot — request + poll. Note the previous latest ts so
    #    we know when a NEW upload arrives (versus a stale one from before).
    prior_head = _get("/api/camera/desktop/snapshot/latest")
    prior_ts = prior_head.headers.get("X-Snapshot-Ts") if prior_head.status_code == 200 else None

    req = _post("/api/camera/desktop/snapshot/request")
    if req.status_code >= 400:
        print(f"  Desktop snapshot REQUEST failed: {req.status_code} {req.text[:150]}")
        return 1
    print(f"  Desktop snapshot requested, waiting up to {DESKTOP_POLL_TIMEOUT_S}s...")

    desktop_jpg = None
    desktop_ts = None
    for _ in range(DESKTOP_POLL_TIMEOUT_S):
        time.sleep(1)
        r = _get("/api/camera/desktop/snapshot/latest")
        if r.status_code != 200:
            continue
        ts = r.headers.get("X-Snapshot-Ts")
        if ts and ts != prior_ts:
            desktop_jpg = r.content
            desktop_ts = ts
            break

    if desktop_jpg:
        (out_dir / f"desktop_{capture_ts}.jpg").write_bytes(desktop_jpg)
        print(f"  Desktop snapshot: {len(desktop_jpg)} bytes (camera ts={desktop_ts})")
    else:
        print(f"  Desktop snapshot TIMED OUT after {DESKTOP_POLL_TIMEOUT_S}s")
        # Not fatal — record the timeout state. For bed/kitchen positions
        # this might mean the desktop can't see the user from there.
        (out_dir / f"desktop_TIMEOUT_{capture_ts}.txt").write_text(
            "Desktop snapshot did not arrive within timeout. The pc_agent "
            "may not have detected a face, the webcam may be shuttered, or "
            "the supervisor isn't running. Check logs/supervisor.log."
        )

    # 4. Capture presence state AFTER snapshot (might shift mid-position).
    r = _get("/api/camera/status")
    if r.status_code == 200:
        (out_dir / f"camera_status_after_{capture_ts}.json").write_text(
            json.dumps(r.json(), indent=2)
        )

    print(f"[{label}] done -> {out_dir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/capture_truth_table_position.py <label>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
