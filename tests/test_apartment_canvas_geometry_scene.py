from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.apartment_canvas import geometry_scene
from backend.apartment_canvas.architecture_topology import compile_wall_body_slice1
from backend.apartment_canvas.compiler import compile_scene
from backend.apartment_canvas.contracts import (
    ContractError,
    CONTRACT_FILENAMES,
    canonical_json,
    fingerprint,
    load_contracts,
)
from backend.apartment_canvas.exact_geometry import Point
from backend.apartment_canvas.geometry_scene import (
    ALGORITHM,
    SCHEMA,
    STATUS,
    canonical_geometry_scene_json,
    compile_geometry_scene,
    geometry_scene_fingerprint,
)
from backend.apartment_canvas.models import deep_thaw
from backend.apartment_canvas.topology_authority import load_topology_authority


CONTRACTS = Path(__file__).resolve().parents[1] / "docs/dashboard/apartment_canvas"


def documents() -> dict:
    return {
        name: json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        for name in CONTRACT_FILENAMES
    }


def compiled() -> dict:
    bundle = load_contracts(CONTRACTS)
    return compile_geometry_scene(bundle, load_topology_authority(CONTRACTS))


def slice1() -> dict:
    bundle = load_contracts(CONTRACTS)
    return compile_wall_body_slice1(
        compile_scene(bundle), load_topology_authority(CONTRACTS), bundle,
    )


def _exact_tokens(points) -> list[list[str]]:
    canonical_points = json.loads(
        canonical_json(points), parse_float=Decimal, parse_int=Decimal,
    )
    return [Point.from_value(point).to_tokens() for point in canonical_points]


def test_schema_status_and_pinned_separated_upstream_provenance():
    scene = compiled()
    assert scene["schema"] == SCHEMA
    assert scene["status"] == STATUS
    assert scene["algorithm"] == ALGORITHM
    provenance = scene["provenance"]
    source_ids = {
        source["id"]
        for category in ("physical_xy", "aperture_semantic")
        for source in provenance[category]["sources"]
    }
    assert {
        "geometry_v1.json",
        "geometry_v1_6_patch.json",
        "topology_authority_v1.json",
        "architecture_wall_topology_slice_1.wall_body",
        "aperture_registry_v1.json",
    }.issubset(source_ids)
    assert "projection_contract_v1.json" not in source_ids
    assert provenance["camera"]["source"]["id"] == "camera_v2.json"
    assert provenance["visibility"]["source"]["id"] == "visibility_contract_v2.json"
    assert provenance["excluded_dependencies"] == [
        "PhysicalWallBandAuthorityV1",
        "PhysicalFamilyPreflight",
        "PhysicalFamilyAuthorityV1",
    ]
    assert scene["fingerprint"] == geometry_scene_fingerprint(scene)


def test_every_accepted_visible_wall_body_polygon_is_extruded_exactly_once():
    source = slice1()["wall_body"]["polygons"]
    scene = compiled()
    extrusions = scene["wall_extrusions"]
    assert {item["source_polygon_id"] for item in extrusions} == {item["id"] for item in source}
    assert len(extrusions) == len(source)
    expected = {item["id"]: item for item in source}
    for extrusion in extrusions:
        polygon = expected[extrusion["source_polygon_id"]]
        assert extrusion["footprint_gu"] == {
            "outer": polygon["outer"], "holes": polygon["holes"],
        }
        assert extrusion["polygon_provenance"] == polygon["provenance"]
        assert extrusion["z_status"] == "provisional_whitebox_default"


def test_accepted_floor_and_balcony_footprints_are_preserved_as_separate_slabs():
    authority = load_topology_authority(CONTRACTS).to_dict()
    bundle = load_contracts(CONTRACTS)
    balcony = deep_thaw(bundle.patch)["contract_amendments"]["balcony_semantics"]
    slabs = {slab["id"]: slab for slab in compiled()["floor_slabs"]}
    apartment = slabs[authority["apartment_slab"]["id"]]
    balcony_slab = slabs[balcony["id"]]
    assert apartment["source_ring_gu"] == authority["apartment_slab"]["ring_gu"]
    assert apartment["footprint_ring_gu"] == _exact_tokens(authority["apartment_slab"]["ring_gu"])
    assert apartment["source"]["balcony_excluded"] is True
    assert balcony_slab["source_ring_gu"] == balcony["ring_gu"]
    assert balcony_slab["footprint_ring_gu"] == _exact_tokens(balcony["ring_gu"])
    assert balcony_slab["source"]["shared_architecture_edge_id"] == balcony["shared_architecture_edge_id"]
    assert all(slab["z_status"] == "provisional_whitebox_default" for slab in slabs.values())


def test_all_registered_apertures_are_exact_opening_descriptors_without_guessed_geometry():
    registry = deep_thaw(load_contracts(CONTRACTS).aperture_registry)
    source = {aperture["id"]: aperture for aperture in registry["apertures"]}
    openings = compiled()["openings"]
    assert {opening["source_aperture_id"] for opening in openings} == set(source)
    assert len(openings) == len(source)
    for opening in openings:
        aperture = source[opening["source_aperture_id"]]
        assert opening["source_segment_gu"] == aperture["segment_gu"]
        assert opening["segment_gu"] == _exact_tokens(aperture["segment_gu"])
        assert opening["parent_wall_id"] == aperture["parent_wall_id"]
        assert opening["host_face_id"] == aperture["host_face_id"]
        assert opening["vertical"]["status"] == aperture["vertical"]["status"] == "provisional"
        assert opening["realization"]["boolean_wall_cut_applied"] is False
    assert any(opening["source_aperture_id"] == "balcony_door" for opening in openings)


def test_semantic_host_wall_faces_are_forwarded_exactly_for_renderer_binding():
    bundle = load_contracts(CONTRACTS)
    source = deep_thaw(bundle.patch)["contract_amendments"]["semantic_wall_volumes"]
    volumes = {item["id"]: item for item in compiled()["semantic_wall_volumes"]}

    assert set(volumes) == {item["id"] for item in source}
    for source_volume in source:
        volume = volumes[source_volume["id"]]
        assert volume["semantic_edge_id"] == source_volume["semantic_edge_id"]
        assert {face["id"] for face in volume["faces"]} == {
            face["id"] for face in source_volume["faces"]
        }
        for face in volume["faces"]:
            expected = next(item for item in source_volume["faces"] if item["id"] == face["id"])
            assert face["bearing_line_gu"] == _exact_tokens(expected["bearing_line_gu"])
            assert face["plan_normal"] == expected["plan_normal"]
            assert face["role"] == expected["role"]

    faces = {face["id"] for volume in volumes.values() for face in volume["faces"]}
    for opening in compiled()["openings"]:
        assert opening["parent_wall_id"] in volumes
        assert opening["host_face_id"] in faces


def test_inspection_annotations_only_forward_accepted_room_and_object_xy():
    source = deep_thaw(load_contracts(CONTRACTS).geometry)
    annotations = compiled()["inspection_annotations"]
    assert annotations["status"] == "accepted_annotation_forwarding_for_local_debug_only"
    rooms = {room["id"]: room for room in annotations["rooms"]}
    for source_room in source["rooms"]:
        room = rooms[source_room["id"]]
        assert room["label"] == source_room["label"]
        assert room["label_gu"] == _exact_tokens([source_room["label_gu"]])[0]
        assert room["source"] == "geometry_v1.json#/rooms"
    objects = {item["id"]: item for item in annotations["objects"]}
    for source_object in source["objects"]:
        if "rect" not in source_object:
            continue
        item = objects[source_object["id"]]
        assert item["rect_gu"] == {
            key: geometry_scene._exact_number(source_object["rect"][key])
            for key in ("x", "y", "w", "h")
        }
        assert item["source"] == source_object["source"]


def test_camera_and_named_visibility_treatments_bind_the_accepted_contracts():
    bundle = load_contracts(CONTRACTS)
    scene = compiled()
    assert scene["camera"] == deep_thaw(bundle.camera)
    treatments = {item["id"]: item for item in scene["visibility_treatments"]}
    cutaway = treatments["visibility.global_cutaway"]
    bedroom = treatments["visibility.bedroom_front_wall"]
    assert cutaway["selector"]["wall_ids"] == ["wall_volume.exterior.bedroom_north", "wall_volume.living.balcony_north"]
    assert cutaway["parameters"]["lip_height_gu"] == "provisional"
    assert cutaway["parameters"]["inspection_lip_height_gu"] == 72
    assert cutaway["parameters"]["inspection_lip_status"] == "provisional"
    assert bedroom["selector"]["solid_face_id"] == "bedroom_front_wall.solid_lower"
    assert bedroom["selector"]["translucent_face_id"] == "bedroom_front_wall.translucent_upper"
    assert bedroom["excluded_aperture_ids"] == ["bedroom_door"]
    assert bedroom["parameters"] == {
        "solid_base_height_gu": "provisional", "upper_opacity": "provisional",
    }
    volumes = {item["id"]: item for item in scene["semantic_wall_volumes"]}
    faces = {face["id"] for volume in volumes.values() for face in volume["faces"]}
    assert cutaway["selector"]["wall_ids"] == ["wall_volume.exterior.bedroom_north", "wall_volume.living.balcony_north"]
    assert cutaway["selector"]["face_ids"] == ["wall_face.exterior.bedroom_north.exterior_north", "wall_face.living.balcony_north.balcony_north"]
    assert bedroom["selector"]["wall_id"] == "wall_volume.bedroom.south_desk_facing"
    assert bedroom["selector"]["face_id"] == "wall_face.bedroom.south_desk_facing.bedroom_north"
    assert set(cutaway["selector"]["wall_ids"]) <= set(volumes)
    assert set(cutaway["selector"]["face_ids"]) <= faces
    assert bedroom["selector"]["wall_id"] in volumes
    assert bedroom["selector"]["face_id"] in faces


def test_all_new_vertical_values_are_explicitly_provisional():
    scene = compiled()
    assert scene["z_policy"]["status"] == "provisional"
    assert scene["z_policy"]["wall_body"]["height_gu"] == "240/1"
    assert scene["z_policy"]["floor_slab"]["thickness_gu"] == "4/1"
    assert all(item["z_status"] == "provisional_whitebox_default" for item in scene["wall_extrusions"])
    assert all(item["vertical"]["status"] == "provisional" for item in scene["openings"])


def _reverse_mapping_order(value):
    if isinstance(value, dict):
        return {key: _reverse_mapping_order(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [_reverse_mapping_order(item) for item in value]
    return value


def test_repeated_compilation_and_input_mapping_order_are_deterministic():
    first = compiled()
    assert canonical_geometry_scene_json(compiled()) == canonical_geometry_scene_json(first)
    reordered_bundle = load_contracts(documents=_reverse_mapping_order(documents()))
    reordered = compile_geometry_scene(reordered_bundle, load_topology_authority(CONTRACTS))
    assert canonical_geometry_scene_json(reordered) == canonical_geometry_scene_json(first)


def test_authoritative_xy_is_fingerprint_sensitive_and_source_drift_fails_closed():
    scene = compiled()
    changed = deepcopy(scene)
    changed["wall_extrusions"][0]["footprint_gu"]["outer"][0][0] = "1/1"
    assert geometry_scene_fingerprint(changed) != scene["fingerprint"]

    source = documents()
    source["geometry_v1.json"]["architecture"]["wall_polygons_gu"][0][0][0] += 1
    assert fingerprint(source["geometry_v1.json"]) != next(
        item["sha256"] for item in load_contracts(CONTRACTS).source_manifest
        if item["id"] == "geometry_v1.json"
    )
    with pytest.raises(ContractError):
        load_contracts(documents=source)


def test_projection_only_slice1_audit_change_does_not_churn_geometry_scene(monkeypatch):
    bundle = load_contracts(CONTRACTS)
    authority = load_topology_authority(CONTRACTS)
    expected = compile_geometry_scene(bundle, authority)
    projection_only_audit_change = deepcopy(
        compile_wall_body_slice1(compile_scene(bundle), authority, bundle)
    )
    # Slice 1's semantic-scene audit includes projection policy.  GeometryScene
    # deliberately consumes only the physical wall_body, which is unchanged.
    projection_only_audit_change["provenance"]["semantic_scene_sha256"] = "projection-only-change"
    monkeypatch.setattr(
        geometry_scene,
        "compile_wall_body_slice1",
        lambda *_args: projection_only_audit_change,
    )

    changed = geometry_scene.compile_geometry_scene(bundle, authority)

    assert canonical_geometry_scene_json(changed) == canonical_geometry_scene_json(expected)
    assert changed["fingerprint"] == expected["fingerprint"]


def test_compilation_is_hash_seed_deterministic():
    expected = compiled()["fingerprint"]
    command = (
        "from backend.apartment_canvas.geometry_scene import compile_geometry_scene_from_directory;"
        "print(compile_geometry_scene_from_directory()['fingerprint'])"
    )
    for seed in ("1", "987654"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", command],
            check=True, capture_output=True, text=True, env=environment,
        )
        assert completed.stdout.strip() == expected


def test_static_imports_have_no_physical_family_or_wall_band_dependency():
    source = Path("backend/apartment_canvas/geometry_scene.py").read_text(encoding="utf-8")
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert not any("physical_family" in name or "wall_band" in name for name in imports)
