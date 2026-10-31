"""Offline-only comparison of two operator-supplied lighting snapshots.

No live GET, device write, background capture, database or automatic persistence.

  python scripts/lighting_output_pair.py --frames samples.json
  python scripts/lighting_output_pair.py --feedback-snapshot sample.json --rating too_dark

Frame JSON: {"samples": [{"collected_at": "<ISO8601 with UTC offset>",
                           "snapshot": {"automation_status": ...}}, ...]}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.lighting_output_pair import (  # noqa: E402
    compare_frames,
    frozen_feedback,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--frames", type=Path)
    group.add_argument("--feedback-snapshot", type=Path)
    parser.add_argument("--rating", choices=("too_dark", "comfortable", "too_bright"))
    args = parser.parse_args(argv)
    if args.frames is not None:
        if args.rating is not None:
            parser.error("--rating is only valid with --feedback-snapshot")
        with args.frames.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        report = compare_frames(raw.get("samples") if isinstance(raw, dict) else None)
    else:
        if args.rating is None:
            parser.error("--feedback-snapshot requires --rating")
        with args.feedback_snapshot.open(encoding="utf-8") as handle:
            report = frozen_feedback(json.load(handle), args.rating)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
