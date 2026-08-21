from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.apartment_canvas.compiler import canonical_scene_json, compile_scene
from backend.apartment_canvas.contracts import ContractError, fingerprint, load_contracts
from backend.apartment_canvas.models import deep_freeze, deep_thaw
from backend.apartment_canvas.topology_authority import (
    TOPOLOGY_AUTHORITY_DESCRIPTOR,
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
    document = authority.to_dict()
    assert document["semantic_face_resolution"]["policy"] == "normal_directed_unique_wall_band"
    assert document["semantic_face_resolution"]["overrides"] == []
    assert document["aperture_resolution"]["policy"] == "unique_two_jamb_wall_band_traversal"
    assert document["aperture_resolution"]["overrides"] == []


def test_registered_aperture_boundary_transition_is_global_exact_derived_only():
    document = load_topology_authority(CONTRACTS).to_dict()
    face_resolution = document["semantic_face_resolution"]
    transition = face_resolution["registered_aperture_boundary_transition"]

    assert set(face_resolution) == {
        "policy",
        "registered_gap_continuity",
        "registered_aperture_boundary_transition",
        "overrides",
    }
    assert transition["status"] == "derived_exact_face_continuity_only"
    assert transition["scope"] == "accepted_resolved_semantic_face_bearing_interval"
    assert transition["aperture_scope"] == (
        "registered_host_face_and_unique_directed_opposite_face_of_same_parent_wall"
    )
    assert transition["endpoint_source"] == (
        "immutable_segment_gu_endpoint_or_its_exact_normal_projection_to_the_unique_directed_opposite_face"
    )
    assert transition["evidence_source"] == "accepted_physical_slice_1_wall_body_topology_only"
    assert transition["candidate_interval"] == {
        "kind": "nonempty_open_complement_interval",
        "containment": "strictly_inside_accepted_resolved_semantic_face_bearing_interval",
        "registered_aperture_endpoint_boundaries": "exactly_one",
    }
    assert transition["monotonic_search"] == {
        "direction": "away_from_registered_aperture_endpoint",
        "decisive_candidate": "first_positive_area_accepted_physical_slice_1_wall_remnant",
        "nearer_incompatible_remnant": "fail_closed_immediately",
        "farther_compatible_after_nearer_obstruction": "forbidden",
    }
    assert transition["remnant_compatibility"] == [
        "parent_wall_id",
        "registered_host_face_id",
        "resolved_face_id",
        "required_directed_host_opposite_relationship",
        "exact_source_contour_jamb_cap_provenance",
    ]
    assert transition["open_interval_interior_forbidden"] == [
        "physical_slice_1_wall_remnant",
        "registered_aperture_endpoint_or_interior",
        "accepted_or_derived_junction",
        "semantic_face_boundary",
        "competing_directed_continuation",
    ]
    assert transition["derived_record"] == [
        "aperture_id",
        "parent_wall_id",
        "registered_host_face_id",
        "resolved_face_id",
        "segment_endpoint_index",
        "immutable_segment_endpoint_gu",
        "physical_remnant_event_gu",
        "exact_open_interval_gu",
        "exact_source_contour_segment_refs",
    ]
    assert transition["ordering"] == [
        "first_find_decisive_physical_evidence_from_accepted_slice_1_only",
        "then_emit_boundary_transition_metadata_for_qualifying_exact_in_face_complement_interval",
        "independently_perform_registered_gap_reconstruction_inside_segment_gu_from_accepted_slice_1_physical_evidence_only",
        "neither_derived_output_may_supply_evidence_for_the_other",
    ]
    assert transition["authority"] == [
        "face_continuity_jamb_event_metadata_only",
        "derived_only",
        "never_positive_area_physical_wall",
        "never_wall_owner",
        "never_modify_slice_1",
        "never_change_segment_gu",
        "never_reconstruction_evidence",
        "never_evidence_for_another_boundary_transition_or_aperture",
        "never_recursively_justify_geometry",
    ]
    assert transition["exclusions"] == [
        "physical_aperture_overlap_is_not_boundary_transition",
        "front_door_remains_literal_two_jamb_traversal_and_requires_no_boundary_transition",
        "fully_apertured_face_without_strict_in_face_interval_is_excluded",
    ]
    assert transition["fail_closed"] == [
        "missing_or_multiple_or_competing_evidence",
        "candidate_interval_not_strictly_inside_resolved_face",
        "registered_aperture_endpoint_boundary_count_not_exactly_one",
        "nearest_positive_area_physical_remnant_incompatible",
        "open_interval_interior_not_empty_of_forbidden_events",
        "missing_exact_source_contour_jamb_cap_provenance",
        "requires_tolerance_epsilon_width_gu_threshold_source_pixel_threshold_snapping_buffering_repair_or_approximate_adjacency",
    ]
    assert document["aperture_resolution"]["registered_gap_reconstruction"] == {
        "prerequisite": "required_when_exact_registered_jamb_trace_lacks_local_wall_band",
        "evidence_source": "accepted_physical_slice_1_wall_body_topology_only",
        "forbidden_evidence": [
            "registered_gap_reconstruction",
            "virtual_pre_aperture_band",
            "derived_semantic_face_runs",
            "future_construction_topology",
            "inferred_or_guessed_geometry",
        ],
        "tangent_search": {
            "order": "monotonic_outward_from_registered_interval_on_each_open_tangent_side",
            "decisive_candidate": "first_positive_area_physical_slice_1_wall_remnant",
            "nearest_incompatible_remnant": "fail_closed_immediately",
            "farther_compatible_after_nearer_obstruction": "forbidden",
        },
        "candidate_compatibility": [
            "parent_wall_id",
            "host_face_id",
            "required_directed_host_opposite_relationship",
        ],
        "same_nearest_event": "exactly_one_compatible_directed_continuation_required_else_fail_closed",
        "both_tangent_sides": "required_and_must_establish_same_unique_directed_host_opposite_continuation",
        "construction_band": "derived_virtual_pre_aperture_band_limited_to_registered_aperture_interval",
        "authority": [
            "derived_construction_topology_only",
            "never_write_accepted_physical_xy_wall_topology",
            "never_mutate_slice_1",
            "never_create_wall_owner",
            "never_alter_segment_gu_parent_wall_id_or_host_face_id",
        ],
        "fail_closed": [
            "missing_positive_area_physical_slice_1_wall_remnant",
            "nearest_positive_area_physical_slice_1_wall_remnant_is_incompatible",
            "same_nearest_event_does_not_leave_exactly_one_compatible_directed_continuation",
            "tangent_sides_fail_to_establish_same_unique_directed_host_opposite_continuation",
            "degenerate_pre_aperture_band",
            "requires_snapping_epsilon_coordinate_repair_or_override",
        ],
        "wall_band_geometry": "exact_tapered_or_non_parallel_opposite_rail_allowed_no_constant_thickness_assumption",
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"].__setitem__(
            "evidence_source", "derived_evidence_is_allowed"
        ),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "candidate_interval"
        ].__setitem__("containment", "may_cross_resolved_face_boundary"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "candidate_interval"
        ].__setitem__("registered_aperture_endpoint_boundaries", "zero_or_many"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "monotonic_search"
        ].__setitem__("decisive_candidate", "any_compatible_physical_remnant"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "monotonic_search"
        ].__setitem__("nearer_incompatible_remnant", "skip_for_farther_evidence"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "open_interval_interior_forbidden"
        ].remove("physical_slice_1_wall_remnant"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "open_interval_interior_forbidden"
        ].remove("registered_aperture_endpoint_or_interior"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "open_interval_interior_forbidden"
        ].remove("accepted_or_derived_junction"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "open_interval_interior_forbidden"
        ].remove("semantic_face_boundary"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "open_interval_interior_forbidden"
        ].remove("competing_directed_continuation"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "remnant_compatibility"
        ].remove("exact_source_contour_jamb_cap_provenance"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "ordering"
        ].__setitem__(3, "derived_outputs_may_supply_evidence"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "authority"
        ].remove("never_recursively_justify_geometry"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "fail_closed"
        ].__setitem__(6, "tolerance_allowed"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "exclusions"
        ].remove("physical_aperture_overlap_is_not_boundary_transition"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "exclusions"
        ].remove("front_door_remains_literal_two_jamb_traversal_and_requires_no_boundary_transition"),
        lambda d: d["semantic_face_resolution"]["registered_aperture_boundary_transition"][
            "exclusions"
        ].remove("fully_apertured_face_without_strict_in_face_interval_is_excluded"),
    ],
)
def test_registered_aperture_boundary_transition_contract_mutations_fail_closed(mutator):
    assert diagnostic_codes(mutator) == {"topology.face_policy"}


def test_registered_gap_reconstruction_is_global_derived_only_and_fail_closed():
    document = load_topology_authority(CONTRACTS).to_dict()
    face = document["semantic_face_resolution"]["registered_gap_continuity"]
    reconstruction = document["aperture_resolution"]["registered_gap_reconstruction"]

    assert face == {
        "semantic_face_may_span_registered_aperture_gaps": True,
        "physical_boundary_rail_may_be_interrupted_by_registered_aperture_gaps": True,
        "realized_physical_runs": "derived_around_registered_apertures",
    }
    assert set(document["aperture_resolution"]) == {
        "policy", "registered_gap_reconstruction", "overrides",
    }
    assert "aperture_id" not in reconstruction
    assert all(
        aperture["id"] not in json.dumps(reconstruction, sort_keys=True)
        for aperture in deep_thaw(bundle().aperture_registry)["apertures"]
    )
    assert set(reconstruction) == {
        "prerequisite",
        "evidence_source",
        "forbidden_evidence",
        "tangent_search",
        "candidate_compatibility",
        "same_nearest_event",
        "both_tangent_sides",
        "construction_band",
        "authority",
        "fail_closed",
        "wall_band_geometry",
    }
    assert reconstruction["evidence_source"] == "accepted_physical_slice_1_wall_body_topology_only"
    assert reconstruction["forbidden_evidence"] == [
        "registered_gap_reconstruction",
        "virtual_pre_aperture_band",
        "derived_semantic_face_runs",
        "future_construction_topology",
        "inferred_or_guessed_geometry",
    ]
    assert reconstruction["tangent_search"] == {
        "order": "monotonic_outward_from_registered_interval_on_each_open_tangent_side",
        "decisive_candidate": "first_positive_area_physical_slice_1_wall_remnant",
        "nearest_incompatible_remnant": "fail_closed_immediately",
        "farther_compatible_after_nearer_obstruction": "forbidden",
    }
    assert reconstruction["candidate_compatibility"] == [
        "parent_wall_id",
        "host_face_id",
        "required_directed_host_opposite_relationship",
    ]
    assert reconstruction["same_nearest_event"] == (
        "exactly_one_compatible_directed_continuation_required_else_fail_closed"
    )
    assert reconstruction["both_tangent_sides"] == (
        "required_and_must_establish_same_unique_directed_host_opposite_continuation"
    )
    assert reconstruction["authority"] == [
        "derived_construction_topology_only",
        "never_write_accepted_physical_xy_wall_topology",
        "never_mutate_slice_1",
        "never_create_wall_owner",
        "never_alter_segment_gu_parent_wall_id_or_host_face_id",
    ]
    assert reconstruction["fail_closed"] == [
        "missing_positive_area_physical_slice_1_wall_remnant",
        "nearest_positive_area_physical_slice_1_wall_remnant_is_incompatible",
        "same_nearest_event_does_not_leave_exactly_one_compatible_directed_continuation",
        "tangent_sides_fail_to_establish_same_unique_directed_host_opposite_continuation",
        "degenerate_pre_aperture_band",
        "requires_snapping_epsilon_coordinate_repair_or_override",
    ]
    assert reconstruction["wall_band_geometry"] == (
        "exact_tapered_or_non_parallel_opposite_rail_allowed_no_constant_thickness_assumption"
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"].__setitem__(
            "evidence_source", "derived_reconstruction_is_allowed"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"][
            "forbidden_evidence"
        ].remove("virtual_pre_aperture_band"),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"]["tangent_search"].__setitem__(
            "nearest_incompatible_remnant", "continue_search"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"]["tangent_search"].__setitem__(
            "farther_compatible_after_nearer_obstruction", "allowed"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"].__setitem__(
            "same_nearest_event", "multiple_compatible_continuations_allowed"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"].__setitem__(
            "both_tangent_sides", "one_side_is_enough"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"].__setitem__(
            "fail_closed", []
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"]["authority"].remove(
            "never_write_accepted_physical_xy_wall_topology"
        ),
        lambda d: d["aperture_resolution"]["registered_gap_reconstruction"].__setitem__(
            "wall_band_geometry", "constant_thickness_required"
        ),
    ],
)
def test_registered_gap_reconstruction_contract_mutations_fail_closed(mutator):
    assert diagnostic_codes(mutator) == {"topology.aperture_reconstruction"}


def test_authority_fingerprint_is_the_new_deterministic_provenance_channel():
    authority = load_topology_authority(CONTRACTS)
    expected = "b552cab7716ccc9bfbcecf4049a5b2f3d607db5b3b3e2681b773f42901024c62"
    assert fingerprint(authority.to_dict()) == expected
    assert authority.fingerprint == expected
    assert TOPOLOGY_AUTHORITY_DESCRIPTOR.fingerprint == expected


def test_geometry_scene_boundary_leaves_vertical_realization_undecided():
    spec = (CONTRACTS.parents[1] / "DASHBOARD_APARTMENT_CANVAS_SPEC.md").read_text(
        encoding="utf-8"
    )
    assert "derived pre-aperture construction topology suitable as an input to a future `GeometrySceneV1`" in spec
    assert "separate `GeometrySceneV1` design and authority decision" in spec
    assert "does not make provisional sill/head metadata final" in spec
    assert "defines no z geometry, extrusion algorithm, mesh topology, sill/lintel/header construction, or rendering behavior" in spec
    assert "derive wall below the sill" not in spec


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
