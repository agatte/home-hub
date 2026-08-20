#!/usr/bin/env python
"""Read-only Apartment Canvas semantic compiler inspection CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.apartment_canvas.compiler import canonical_scene_json, compile_scene_from_directory
from backend.apartment_canvas.contracts import ContractError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contracts-dir", type=Path, default=ROOT / "docs/dashboard/apartment_canvas"
    )
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--emit-scene", metavar="OUTPUT", nargs="?", const="-")
    args = parser.parse_args()
    try:
        scene = compile_scene_from_directory(args.contracts_dir)
    except ContractError as exc:
        for diagnostic in exc.diagnostics:
            print(f"{diagnostic.code}\t{diagnostic.path}\t{diagnostic.message}", file=sys.stderr)
        return 1
    if args.validate:
        print("Apartment Canvas contracts: valid")
    if args.summary:
        data = scene.to_dict()
        print(
            f"wall_contours={len(data['architecture']['wall_contours_gu'])} objects={len(data['objects'])} unplaced_objects={len(data['unplaced_objects'])} wall_volumes={len(data['wall_volumes'])} wall_faces={sum(len(v['faces']) for v in data['wall_volumes'])} apertures={len(data['apertures'])}"
        )
    if args.emit_scene is not None:
        output = canonical_scene_json(scene)
        if args.emit_scene == "-":
            sys.stdout.buffer.write(output.encode("utf-8"))
        else:
            Path(args.emit_scene).write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
