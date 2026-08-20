from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.apartment_canvas.compiler import canonical_scene_json, compile_scene
from backend.apartment_canvas.contracts import ContractError, load_contracts
from backend.apartment_canvas.models import deep_freeze, deep_thaw
from backend.apartment_canvas.topology_authority import (
    load_topology_authority,
    validate_topology_authority,
)


CONTRACTS = Path(__file__).resolve().parents[1] / "docs/dashboard/apartment_canvas"


def topology_document():
    return json.loads((CONTRACTS / "topology_authority_v1.json").read_text(encoding="utf-8"))


def bundle():
    return load_contracts(CONTRACTS)


def diagnostic_codes(mutator, *, source_bundle=None):
    value = topology_document()
    mutator(value)
    with pytest.raises(ContractError) as raised:
        validate_topology_authority(value, source_bundle or bundle())
    return {item.code for item in raised.value.diagnostics}


def geometry_mutation(mutator):
    original = bundle()
    geometry = deep_thaw(original.geometry)
    mutator(geometry)
    return replace(original, geometry=deep_freeze(geometry))


def patch_mutation(mutator):
    original = bundle()
    patch = deep_thaw(original.patch)
    mutator(patch)
    return replace(original, patch=deep_freeze(patch))


def test_happy_path_is_separate_and_deterministic():
    authority = load_topology_authority(CONTRACTS)
    assert authority.schema == "homehub.apartment-topology-authority.v1"
    assert authority.to_dict()["semantic_face_resolution"]["overrides"] == []
    assert authority.to_dict()["aperture_resolution"]["overrides"] == []


def test_semantic_scene_serialization_and_six_source_manifest_are_unchanged():
    before = compile_scene(bundle())
    load_topology_authority(CONTRACTS)
    after = compile_scene(bundle())
    assert canonical_scene_json(before) == canonical_scene_json(after)
    assert [item["id"] for item in after.source_manifest] == [
        "geometry_v1.json",
        "geometry_v1_6_patch.json",
        "aperture_registry_v1.json",
        "projection_contract_v1.json",
        "camera_v1.json",
        "visibility_contract_v1.json",
    ]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["apartment_slab"].__setitem__("ring_gu", d["apartment_slab"]["ring_gu"][:-1]),
        lambda d: d["apartment_slab"]["ring_gu"][3].__setitem__(0, 441.20),
        lambda d: d["apartment_slab"].__setitem__("balcony_ring_gu", [[1, 1], [2, 1], [1, 1]]),
        lambda d: d["derived_junctions"][0].__setitem__("vertical_source", "wrong"),
        lambda d: d["wall_body"].__setitem__("fill_rule", "non_zero"),
        lambda d: d["wall_body"].__setitem__("retain_odd_cells", False),
        lambda d: d["wall_body"].__setitem__("dissolve_internal_boundaries", False),
        lambda d: d["wall_body"].__setitem__("physical_owner_count", 2),
        lambda d: d["wall_body"].__setitem__("nominal_wall_thickness", 1),
        lambda d: d["wall_body"]["contours"].__setitem__(0, d["wall_body"]["contours"][1]),
        lambda d: d["wall_body"]["contours"][0].__setitem__("source", "bad-pointer"),
        lambda d: d["wall_body"].__setitem__("accepted_proper_self_crossings", []),
        lambda d: d["semantic_face_resolution"].__setitem__("overrides", [{"face_id": "unknown"}]),
        lambda d: d["aperture_resolution"].__setitem__("overrides", [{"aperture_id": "unknown"}]),
        lambda d: d.__setitem__("semantic_source_manifest", []),
    ],
)
def test_structural_authority_mutations_fail_closed(mutator):
    assert diagnostic_codes(mutator)


def test_changed_source_contour_and_derived_support_line_fail_closed():
    original = bundle()
    geometry = deep_thaw(original.geometry)
    geometry["architecture"]["wall_polygons_gu"][0][0][0] += 1
    assert diagnostic_codes(
        lambda d: None, source_bundle=replace(original, geometry=deep_freeze(geometry))
    )
    patch = deep_thaw(original.patch)
    edge = next(
        item
        for item in patch["contract_amendments"]["semantic_wall_edges_gu"]
        if item["id"] == "wall.living.balcony_north"
    )
    edge["points"][0][1] += 1
    assert diagnostic_codes(
        lambda d: None, source_bundle=replace(original, patch=deep_freeze(patch))
    )


def test_cross_contour_proper_crossing_fails_closed():
    source_bundle = geometry_mutation(
        lambda geometry: geometry["architecture"]["wall_polygons_gu"].__setitem__(
            4, [[400.00, 40.00], [400.00, 80.00], [410.00, 80.00], [410.00, 40.00]]
        )
    )
    assert "topology.cross_contour_intersection" in diagnostic_codes(
        lambda d: None, source_bundle=source_bundle
    )


def test_cross_contour_endpoint_on_segment_contact_fails_closed():
    source_bundle = geometry_mutation(
        lambda geometry: geometry["architecture"]["wall_polygons_gu"].__setitem__(
            4, [[429.00, 528.07], [450.00, 550.00], [460.00, 550.00], [460.00, 500.00]]
        )
    )
    assert "topology.cross_contour_contact" in diagnostic_codes(
        lambda d: None, source_bundle=source_bundle
    )


@pytest.mark.parametrize("reversed", [False, True])
def test_cross_contour_collinear_overlap_and_duplicate_edge_fail_closed(reversed):
    edge = [[427.18, 528.07], [431.24, 528.07]]
    if reversed:
        edge.reverse()
    source_bundle = geometry_mutation(
        lambda geometry: geometry["architecture"]["wall_polygons_gu"].__setitem__(
            4, [*edge, [450.00, 550.00], [420.00, 550.00]]
        )
    )
    codes = diagnostic_codes(lambda d: None, source_bundle=source_bundle)
    assert "topology.collinear_overlap" in codes
    assert "topology.duplicate_edge" in codes


def test_derived_junction_rejects_nonvertical_support():
    source_bundle = geometry_mutation(
        lambda geometry: geometry["architecture"]["wall_polygons_gu"][3][17].__setitem__(
            0, 440.21
        )
    )
    assert "topology.derived" in diagnostic_codes(lambda d: None, source_bundle=source_bundle)


def test_derived_junction_rejects_changed_frozen_point():
    assert "topology.derived" in diagnostic_codes(
        lambda document: document["derived_junctions"][0].__setitem__(
            "point_gu", [440.20, 222.14]
        )
    )


def test_derived_junction_rejects_nonhorizontal_support():
    source_bundle = patch_mutation(
        lambda patch: next(
            item
            for item in patch["contract_amendments"]["semantic_wall_edges_gu"]
            if item["id"] == "wall.living.balcony_north"
        )["points"][1].__setitem__(1, 222.14)
    )
    assert "topology.derived" in diagnostic_codes(lambda d: None, source_bundle=source_bundle)


def test_derived_junction_rejects_zero_length_vertical_support():
    source_bundle = geometry_mutation(
        lambda geometry: geometry["architecture"]["wall_polygons_gu"][3][17].__setitem__(
            1, 214.81
        )
    )
    assert "topology.derived" in diagnostic_codes(lambda d: None, source_bundle=source_bundle)


def test_loader_fingerprint_rejects_checked_in_authority_mutation():
    value = topology_document()
    value["wall_body"]["fill_rule"] = "non_zero"
    with pytest.raises(ContractError) as raised:
        load_topology_authority(CONTRACTS, document=value)
    assert {item.code for item in raised.value.diagnostics} == {"topology.authority"}
