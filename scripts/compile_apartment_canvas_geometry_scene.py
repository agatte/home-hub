"""Write or summarize the deterministic offline Apartment Canvas GeometrySceneV1."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.apartment_canvas.geometry_scene import (
    canonical_geometry_scene_json,
    compile_geometry_scene_from_directory,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", type=Path, default=ROOT / "docs/dashboard/apartment_canvas")
    parser.add_argument("--output", type=Path, help="Write canonical GeometrySceneV1 JSON to this path.")
    parser.add_argument("--summary", action="store_true", help="Print a concise deterministic inventory.")
    args = parser.parse_args()

    scene = compile_geometry_scene_from_directory(args.contracts)
    if args.output:
        args.output.write_text(canonical_geometry_scene_json(scene), encoding="utf-8")
    if args.summary or not args.output:
        summary = scene["whitebox_summary"]
        print(
            f"{scene['schema']} {scene['status']} "
            f"fingerprint={scene['fingerprint']} "
            f"slabs={summary['floor_slab_count']} walls={summary['wall_extrusion_count']} "
            f"openings={summary['opening_descriptor_count']}"
        )


if __name__ == "__main__":
    main()
