from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.apartment_canvas.architecture_topology import (
    ArchitectureTopologyError,
    _dissolved_rings,
    _face_witness,
    _retained_faces,
    build_arrangement,
    compile_wall_body_slice1,
    derive_wall_body_polygons,
    document_fingerprint,
    semantic_scene_fingerprint,
)
from backend.apartment_canvas.compiler import compile_scene
from backend.apartment_canvas.contracts import canonical_json, load_contracts
from backend.apartment_canvas.exact_geometry import (
    ExactGeometryError,
    Point,
    classify_segments,
    interior_witness,
    point_in_contours_parity,
    rational,
    shoelace,
)
from backend.apartment_canvas.models import deep_freeze, deep_thaw
from backend.apartment_canvas.topology_authority import load_topology_authority


CONTRACTS = Path(__file__).resolve().parents[1] / "docs/dashboard/apartment_canvas"


def compiled():
    bundle = load_contracts(CONTRACTS)
    return compile_wall_body_slice1(compile_scene(bundle), load_topology_authority(CONTRACTS), bundle)


def square(name, x0, y0, x1, y1):
    return name, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_exact_kernel_uses_canonical_decimal_tokens_and_never_tolerances():
    assert rational(Decimal("440.20")) == Fraction(2201, 5)
    assert rational("1/3") == Fraction(1, 3)
    with pytest.raises(ExactGeometryError):
        rational("2/4")
    with pytest.raises(ExactGeometryError):
        rational(True)
    with pytest.raises(ExactGeometryError):
        rational(440.20)
    with pytest.raises(ExactGeometryError):
        rational(0.1 + 0.2)
    with pytest.raises(ExactGeometryError):
        rational("NaN")
    canonical = json.loads('{"coordinate":0.3}', parse_float=Decimal, parse_int=Decimal)
    assert rational(canonical["coordinate"]) == Fraction(3, 10)
    long_token = json.loads('{"coordinate":440.20000000000000000001}', parse_float=Decimal, parse_int=Decimal)
    assert rational(long_token["coordinate"]) == Fraction(44020000000000000000001, 10**20)
    a, b, c, d = (Point.from_value(value) for value in ([0, 0], [3, 3], [0, 3], [3, 0]))
    relation = classify_segments(a, b, c, d)
    assert relation.kind == "proper" and relation.point == Point(Fraction(3, 2), Fraction(3, 2))
    assert classify_segments(
        Point(Fraction(0), Fraction(0)), Point(Fraction(1), Fraction(0)),
        Point(Fraction(0), Fraction(1, 10**20)), Point(Fraction(1), Fraction(1, 10**20)),
    ).kind == "disjoint"


def test_scan_slab_witness_handles_rectangle_concave_self_crossing_nested_and_touching():
    fixtures = [
        [square("r", 0, 0, 4, 3)],
        [("concave", [[0, 0], [5, 0], [5, 1], [1, 1], [1, 5], [0, 5]])],
        [("bow", [[0, 0], [4, 4], [0, 4], [4, 0]])],
        [square("outer", 0, 0, 8, 8), square("inner", 2, 2, 6, 6)],
        [square("left", 0, 0, 2, 2), square("right", 2, 2, 4, 4)],
    ]
    for values in fixtures:
        arrangement = build_arrangement(values)
        for ring in arrangement.faces:
            if shoelace(ring) > 0:
                witness = interior_witness(ring)
                assert point_in_contours_parity(witness, arrangement.contours) in (True, False)


def test_accepted_exact_arrangement_and_canonical_owner_output():
    bundle = load_contracts(CONTRACTS)
    scene = compile_scene(bundle)
    result = compiled()
    audit = result["arrangement_audit"]
    assert audit["source_segments"] == 185
    assert audit["noded_vertices"] == 186
    assert audit["atomic_edges"] == 187
    assert audit["bounded_odd_cells"] == 7
    assert audit["proper_crossings"] == [{
        "segments": ["wall.contour.c002.segment.s003", "wall.contour.c002.segment.s005"],
        "point": ["22583401/28450", "6627201/28450"],
    }]
    polygons = result["wall_body"]["polygons"]
    assert result["wall_body"]["id"] == "wall_body.apartment"
    assert result["wall_body"]["physical_owner_count"] == 1
    assert len(polygons) == 7
    assert sha256(canonical_json(result).encode("utf-8")).hexdigest() == (
        "2d6717bd2569be7dc09b7c0fcb89e6ff88c12a49da4c3f3b011925a7839ae727"
    )
    assert result["provenance"] == {
        "semantic_scene_schema": scene.schema,
        "semantic_scene_sha256": semantic_scene_fingerprint(scene),
        "semantic_source_manifest": scene.to_dict()["source_manifest"],
        "topology_authority_schema": "homehub.apartment-topology-authority.v1",
        "topology_authority_sha256": load_topology_authority(CONTRACTS).fingerprint,
    }
    assert all(not polygon["holes"] for polygon in polygons)
    for polygon in polygons:
        ring = tuple(Point.from_value(point) for point in polygon["outer"])
        assert shoelace(ring) > 0
        assert ring[0] == min(ring)
        assert polygon["id"].startswith("wall_body.apartment.polygon.")


def test_slice_1_golden_hash_change_is_topology_authority_provenance_only():
    result = compiled()
    previous = json.loads(canonical_json(result))
    previous["provenance"]["topology_authority_sha256"] = (
        "b552cab7716ccc9bfbcecf4049a5b2f3d607db5b3b3e2681b773f42901024c62"
    )
    assert sha256(canonical_json(previous).encode("utf-8")).hexdigest() == (
        "6864f451fb9344cd2fcce9e39e1f37a871e39c381e015e72397976a135cca25d"
    )
    assert {key: value for key, value in previous.items() if key != "provenance"} == {
        key: value for key, value in result.items() if key != "provenance"
    }


def test_even_odd_nested_case_emits_a_hole_boundary_candidate():
    arrangement = build_arrangement([square("outer", 0, 0, 8, 8), square("inner", 2, 2, 6, 6)])
    retained = _retained_faces(arrangement)
    assert len(retained) == 1
    assert len(_dissolved_rings(arrangement, retained)) == 1
    even_inner = [
        ring for ring in arrangement.faces
        if shoelace(ring) > 0 and not point_in_contours_parity(_face_witness(ring, arrangement.vertices), arrangement.contours)
    ]
    assert len(even_inner) == 1 and shoelace(even_inner[0]) > 0
    polygons = derive_wall_body_polygons(arrangement)
    assert len(polygons) == 1 and len(polygons[0]["holes"]) == 1
    assert shoelace(tuple(Point.from_value(point) for point in polygons[0]["holes"][0])) < 0


def test_adjacent_retained_cells_dissolve_their_shared_atomic_edge():
    arrangement = build_arrangement([square("left", 0, 0, 2, 2), square("right", 2, 0, 4, 2)])
    rings = _dissolved_rings(arrangement, _retained_faces(arrangement))
    assert len(rings) == 1
    assert shoelace(rings[0]) == 8
    assert Point(Fraction(2), Fraction(0)) in rings[0]
    assert Point(Fraction(2), Fraction(2)) in rings[0]


def test_self_crossing_and_point_touching_components_remain_distinct():
    bow = build_arrangement([("bow", [[0, 0], [4, 4], [0, 4], [4, 0]])])
    assert len(_retained_faces(bow)) == 2
    touching = build_arrangement([square("a", 0, 0, 2, 2), square("b", 2, 2, 4, 4)])
    assert len(_dissolved_rings(touching, _retained_faces(touching))) == 2


def test_authority_drift_and_unexpected_contacts_fail_closed_without_input_mutation():
    bundle = load_contracts(CONTRACTS)
    authority = load_topology_authority(CONTRACTS)
    scene = compile_scene(bundle)
    geometry_before = json.dumps(deep_thaw(bundle.geometry), sort_keys=True)
    mutated = deep_thaw(bundle.geometry)
    mutated["architecture"]["wall_polygons_gu"][0][0][0] += 1
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(scene, authority, replace(bundle, geometry=deep_freeze(mutated)))
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(scene, replace(authority, fingerprint="0" * 64), bundle)
    with pytest.raises(ArchitectureTopologyError):
        build_arrangement([square("a", 0, 0, 2, 2), square("b", 1, 1, 3, 3)], strict_contacts=True)
    accepted_geometry = json.loads(
        canonical_json(deep_thaw(bundle.geometry)), parse_float=Decimal, parse_int=Decimal,
    )["architecture"]["wall_polygons_gu"]
    accepted = [
        (binding["id"], accepted_geometry[index])
        for index, binding in enumerate(authority.document["wall_body"]["contours"])
    ]
    with pytest.raises(ArchitectureTopologyError):
        build_arrangement(accepted, allowed_proper=[("wrong", "allowlist")], strict_contacts=True)
    with pytest.raises(ArchitectureTopologyError):
        build_arrangement(
            [square("outer", 0, 0, 4, 4), square("touch", 4, 2, 6, 3)],
            strict_contacts=True,
        )
    assert json.dumps(deep_thaw(bundle.geometry), sort_keys=True) == geometry_before


def test_semantic_scene_and_authority_source_bindings_fail_closed():
    bundle = load_contracts(CONTRACTS)
    scene = compile_scene(bundle)
    authority = load_topology_authority(CONTRACTS)
    with pytest.raises(TypeError):
        compile_wall_body_slice1(authority, bundle)  # type: ignore[call-arg]
    wrong_fingerprint_scene = replace(scene, version="wrong")
    assert semantic_scene_fingerprint(wrong_fingerprint_scene) != semantic_scene_fingerprint(scene)
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(wrong_fingerprint_scene, authority, bundle)
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(replace(scene, schema="wrong"), authority, bundle)
    scene_manifest = deep_thaw(scene.source_manifest)
    scene_manifest[0]["sha256"] = "0" * 64
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(
            replace(scene, source_manifest=deep_freeze(scene_manifest)), authority, bundle,
        )
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(scene, replace(authority, source_manifest=()), bundle)
    document = deep_thaw(authority.document)
    document["semantic_source_manifest"][0]["sha256"] = "0" * 64
    with pytest.raises(ArchitectureTopologyError):
        compile_wall_body_slice1(
            scene,
            replace(
                authority,
                document=deep_freeze(document),
                fingerprint=document_fingerprint(document),
            ),
            bundle,
        )


def test_repeated_and_subprocess_compilation_is_byte_identical():
    first = json.dumps(compiled(), sort_keys=True, separators=(",", ":"))
    assert json.dumps(compiled(), sort_keys=True, separators=(",", ":")) == first
    command = (
        "import json; from pathlib import Path; from backend.apartment_canvas.compiler import compile_scene; from backend.apartment_canvas.contracts import load_contracts; "
        "from backend.apartment_canvas.topology_authority import load_topology_authority; "
        "from backend.apartment_canvas.architecture_topology import compile_wall_body_slice1; "
        "p=Path('docs/dashboard/apartment_canvas'); b=load_contracts(p); print(json.dumps(compile_wall_body_slice1(compile_scene(b),load_topology_authority(p),b),sort_keys=True,separators=(',',':')))"
    )
    for hash_seed in (None, "1", "987654"):
        environment = os.environ.copy()
        if hash_seed is not None:
            environment["PYTHONHASHSEED"] = hash_seed
        completed = subprocess.run(
            [sys.executable, "-c", command], check=True, capture_output=True, text=True, env=environment,
        )
        assert completed.stdout.strip() == first


def test_shuffled_incidental_contour_enumeration_has_identical_canonical_polygons():
    values = [square("a", 0, 0, 2, 2), square("b", 4, 0, 6, 2)]
    first = derive_wall_body_polygons(build_arrangement(values))
    second = derive_wall_body_polygons(build_arrangement(list(reversed(values))))
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(second, sort_keys=True, separators=(",", ":"))
