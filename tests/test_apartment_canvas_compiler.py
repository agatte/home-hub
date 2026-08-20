from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from backend.apartment_canvas.compiler import canonical_scene_json, compile_scene
from backend.apartment_canvas.contracts import (
    CONTRACT_FILENAMES,
    ContractError,
    fingerprint,
    load_contracts,
)
from backend.apartment_canvas.models import deep_freeze, deep_thaw
from backend.apartment_canvas.validation import validate_scene

CONTRACTS = Path(__file__).resolve().parents[1] / "docs/dashboard/apartment_canvas"


def documents():
    return {
        name: json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        for name in CONTRACT_FILENAMES
    }


def compiled():
    return compile_scene(load_contracts(documents=documents()))


def broken(mutator):
    values = documents()
    mutator(values)
    with pytest.raises(ContractError):
        compile_scene(load_contracts(documents=values))


def diagnostics_for(values):
    with pytest.raises(ContractError) as raised:
        load_contracts(documents=values)
    return {diagnostic.code for diagnostic in raised.value.diagnostics}


def semantic_broken(mutator):
    bundle = load_contracts(documents=documents())
    registry = deep_thaw(bundle.aperture_registry)
    mutator(registry)
    with pytest.raises(ContractError) as raised:
        compile_scene(replace(bundle, aperture_registry=deep_freeze(registry)))
    return {diagnostic.code for diagnostic in raised.value.diagnostics}


def test_happy_path_inventories_and_semantic_coordinate_system():
    scene = compiled().to_dict()
    assert scene["coordinate_system"]["axes"] == {"x": "right", "y": "down", "z": "up"}
    assert len(scene["architecture"]["wall_contours_gu"]) == 6
    assert len(scene["objects"]) == 42 and len(scene["unplaced_objects"]) == 1
    assert len(scene["wall_volumes"]) == 11
    assert sum(len(volume["faces"]) for volume in scene["wall_volumes"]) == 22
    assert len(scene["apertures"]) == 11
    assert sum(item["type"] == "window" for item in scene["apertures"]) == 4
    assert sum(item["type"] == "door" for item in scene["apertures"]) == 7


def test_compilation_and_source_fingerprints_are_canonical_and_repeatable():
    first, second = compiled(), compiled()
    assert canonical_scene_json(first) == canonical_scene_json(second)
    value = {"b": 1, "a": ["x", 2]}
    assert fingerprint(value) == fingerprint(json.loads('{\n "a": ["x", 2], "b": 1\n}'))
    assert [item["id"] for item in first.source_manifest] == list(CONTRACT_FILENAMES)


def test_manifest_fingerprints_raw_authority_not_reconciled_geometry_and_raw_is_unchanged():
    source = documents()
    bundle = load_contracts(documents=source)
    manifest = {item["id"]: item["sha256"] for item in bundle.source_manifest}
    raw_geometry = source["geometry_v1.json"]
    raw_rug = next(item for item in raw_geometry["objects"] if item["id"] == "living.rug")
    effective_rug = next(item for item in deep_thaw(bundle.geometry)["objects"] if item["id"] == "living.rug")
    assert manifest["geometry_v1.json"] == fingerprint(raw_geometry)
    assert manifest["geometry_v1.json"] != fingerprint(deep_thaw(bundle.geometry))
    retained_rug = next(
        item
        for item in deep_thaw(bundle.raw_documents)["geometry_v1.json"]["objects"]
        if item["id"] == "living.rug"
    )
    assert retained_rug == raw_rug
    assert raw_rug["rect"] != effective_rug["rect"]


def test_authority_fingerprints_are_independent_of_json_whitespace_and_line_endings():
    raw = (CONTRACTS / "geometry_v1.json").read_text(encoding="utf-8")
    assert fingerprint(json.loads(raw.replace("\n", "\r\n"))) == fingerprint(json.loads(raw))


def test_camera_patch_and_balcony_are_preserved_explicitly():
    scene = compiled().to_dict()
    assert scene["camera"] == documents()["camera_v1.json"]["camera"]
    rug = next(item for item in scene["objects"] if item["id"] == "living.rug")
    assert rug["rect"] == {"x": 666.3, "y": 268.61, "w": 181.44, "h": 375.87}
    ring = scene["balcony_footprint"]["ring_gu"]
    assert ring[0] == ring[-1]


def test_apertures_are_on_declared_host_faces_and_treatment_c_excludes_architecture():
    scene = compiled().to_dict()
    faces = {
        face["id"]: volume["id"] for volume in scene["wall_volumes"] for face in volume["faces"]
    }
    assert all(
        faces[aperture["host_face_id"]] == aperture["parent_wall_id"]
        for aperture in scene["apertures"]
    )
    c = next(
        t for t in scene["visibility_treatments"] if t["id"] == "visibility.bedroom_front_wall"
    )
    assert "wall_volume.bedroom_living.projector_divider" in c["excluded_wall_ids"]
    assert "bedroom_door.lintel" in c["opaque_architecture"]


def test_assembly_relationships_and_pendant_cardinality():
    assemblies = {item["id"]: item for item in compiled().to_dict()["assemblies"]}
    assert "exactly_two_pillows" in assemblies["assembly.bed"]["requirements"]
    assert "pc_under_opposite_left_desk_side" in assemblies["assembly.workstation"]["relationships"]
    assert assemblies["assembly.kitchen_pendants"]["members"] == [
        "kitchen.pendant_1",
        "kitchen.pendant_2",
    ]


@pytest.mark.parametrize("filename", CONTRACT_FILENAMES)
def test_every_contract_rejects_wrong_schema_and_status(filename):
    values = documents()
    values[filename]["schema"] = "wrong.schema"
    assert "contract.schema" in diagnostics_for(values)
    values = documents()
    values[filename]["status"] = "draft"
    assert "contract.status" in diagnostics_for(values)


@pytest.mark.parametrize(
    ("filename", "field"),
    [
        ("geometry_v1_6_patch.json", "base"),
        ("aperture_registry_v1.json", "source"),
        ("projection_contract_v1.json", "source_geometry"),
        ("camera_v1.json", "source_geometry"),
        ("visibility_contract_v1.json", "source_geometry"),
        ("visibility_contract_v1.json", "camera"),
    ],
)
def test_contract_bindings_are_explicitly_authoritative(filename, field):
    values = documents()
    values[filename][field] = "wrong binding"
    assert "contract.binding" in diagnostics_for(values)


def test_authority_rejects_patch_semantic_coordinate_drift_and_overridden_base_drift():
    values = documents()
    values["geometry_v1_6_patch.json"]["contract_amendments"]["semantic_wall_volumes"][0][
        "faces"
    ][0]["bearing_line_gu"][0][0] += 1
    assert "contract.authority" in diagnostics_for(values)
    values = documents()
    next(item for item in values["geometry_v1.json"]["objects"] if item["id"] == "living.rug")[
        "rect"
    ]["x"] += 1
    assert "contract.authority" in diagnostics_for(values)


@pytest.mark.parametrize(
    ("segment", "orientation", "code"),
    [
        ([[1, 1], [1, 1]], "horizontal", "aperture.segment"),
        ([[1, 1], 2], "horizontal", "aperture.segment"),
        ([[1, "bad"], [2, 1]], "horizontal", "aperture.segment"),
        ([[118.79576891781937, 52.88852725793328], [222.94548413344185, 52.88852725793328]], "vertical", "aperture.orientation"),
        ([[0, 0], [1, 0]], "horizontal", "aperture.trace"),
    ],
)
def test_aperture_segment_validation_is_defensive(segment, orientation, code):
    def mutate(registry):
        registry["apertures"][0]["segment_gu"] = segment
        registry["apertures"][0]["orientation"] = orientation

    assert code in semantic_broken(mutate)


def test_scene_is_deeply_immutable_and_serialization_is_detached():
    scene = compiled()
    before = canonical_scene_json(scene)
    with pytest.raises(TypeError):
        scene.camera["eye_gu"][0] = 1
    with pytest.raises(TypeError):
        scene.assemblies[0]["relationships"] = ()
    emitted = scene.to_dict()
    emitted["camera"]["eye_gu"][0] = 1
    emitted["assemblies"][0]["members"].append("mutated")
    assert canonical_scene_json(scene) == before


def test_malformed_emitted_assembly_is_rejected_by_scene_level_validation():
    scene = compiled()
    malformed = scene.to_dict()
    workstation = next(item for item in malformed["assemblies"] if item["id"] == "assembly.workstation")
    workstation["relationships"].remove("pc_under_opposite_left_desk_side")
    bad_scene = replace(scene, assemblies=deep_freeze(malformed["assemblies"]))
    with pytest.raises(ContractError) as raised:
        validate_scene(bad_scene)
    assert "assembly.required" in {diagnostic.code for diagnostic in raised.value.diagnostics}


@pytest.mark.parametrize(
    ("assembly_id", "mutate"),
    [
        ("assembly.bed", lambda members: members.append("bedroom.bed")),
        ("assembly.workstation", lambda members: members.append("bedroom.pc")),
        ("assembly.workstation", lambda members: members.pop()),
        ("assembly.bed", lambda members: members.append("bedroom.pc")),
    ],
)
def test_scene_level_validation_rejects_duplicate_missing_and_extra_assembly_members(
    assembly_id, mutate
):
    scene = compiled()
    malformed = scene.to_dict()
    assembly = next(item for item in malformed["assemblies"] if item["id"] == assembly_id)
    mutate(assembly["members"])
    bad_scene = replace(scene, assemblies=deep_freeze(malformed["assemblies"]))
    with pytest.raises(ContractError) as raised:
        validate_scene(bad_scene)
    assert "assembly.required" in {diagnostic.code for diagnostic in raised.value.diagnostics}


def test_scene_level_validation_keeps_pendant_exactly_two_cardinality():
    scene = compiled()
    malformed = scene.to_dict()
    pendants = next(
        item for item in malformed["assemblies"] if item["id"] == "assembly.kitchen_pendants"
    )
    pendants["members"].append("kitchen.pendant_1")
    bad_scene = replace(scene, assemblies=deep_freeze(malformed["assemblies"]))
    with pytest.raises(ContractError) as raised:
        validate_scene(bad_scene)
    assert {"assembly.required", "assembly.pendants"}.issubset(
        {diagnostic.code for diagnostic in raised.value.diagnostics}
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["aperture_registry_v1.json"]["apertures"].__setitem__(
            0, {**d["aperture_registry_v1.json"]["apertures"][0], "host_face_id": "unknown.face"}
        ),
        lambda d: d["geometry_v1.json"]["objects"].append(
            copy.deepcopy(d["geometry_v1.json"]["objects"][0])
        ),
        lambda d: d["camera_v1.json"]["camera"].__setitem__("yaw_degrees_right", 21.0),
        lambda d: d["geometry_v1.json"]["objects"][0]["rect"].__setitem__("x", 15.0),
        lambda d: d["geometry_v1_6_patch.json"]["changes"][0].__setitem__("orientation_deg", 90),
        lambda d: d["geometry_v1_6_patch.json"]["contract_amendments"]["semantic_wall_volumes"][0][
            "faces"
        ][0].__setitem__("plan_normal", "diagonal"),
        lambda d: d["aperture_registry_v1.json"]["apertures"][0].__setitem__(
            "segment_gu", [[0, 0], [1, 1]]
        ),
        lambda d: d["geometry_v1_6_patch.json"]["contract_amendments"][
            "balcony_semantics"
        ].__setitem__("ring_gu", [[1, 1], [2, 1], [2, 2]]),
        lambda d: d["visibility_contract_v1.json"]["accepted_direction"][
            "bedroom_front_wall"
        ].__setitem__("excluded_wall_ids", []),
        lambda d: d["visibility_contract_v1.json"]["accepted_direction"][
            "bedroom_front_wall"
        ].__setitem__("coordinate_zone", [0, 0, 1, 1]),
    ],
)
def test_representative_contract_mutations_are_rejected(mutator):
    broken(mutator)
