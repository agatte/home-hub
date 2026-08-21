from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys

import pytest

from backend.apartment_canvas.architecture_topology import (
    compile_wall_body_slice1,
    document_fingerprint,
)
from backend.apartment_canvas.compiler import compile_scene
from backend.apartment_canvas.contracts import ContractError, canonical_json, fingerprint, load_contracts
from backend.apartment_canvas.physical_family_authority import (
    AUTHORITY_SCHEMA,
    AUTHORITY_STATUS,
    EXPECTED_CERTIFICATE_IDS,
    PHYSICAL_SOURCE_SHA256,
    authority_fingerprint,
    canonical_undirected_certificate_json,
    derive_certificate_id,
    load_physical_family_authority,
    physical_slice1_fingerprint,
    physical_slice1_projection,
    reverse_certificate_record,
    validate_physical_family_authority,
)
from backend.apartment_canvas.topology_authority import load_topology_authority


CONTRACTS = Path(__file__).resolve().parents[1] / "docs/dashboard/apartment_canvas"
TOPOLOGY_SHA256 = "f1c63e03fffa35362163068b4aec86152912e4c5805a0390c67137442d1478bd"
SLICE1_SHA256 = "2d6717bd2569be7dc09b7c0fcb89e6ff88c12a49da4c3f3b011925a7839ae727"


@pytest.fixture(scope="module")
def slice1():
    bundle = load_contracts(CONTRACTS)
    return compile_wall_body_slice1(
        compile_scene(bundle), load_topology_authority(CONTRACTS), bundle,
    )


def authority_document():
    return json.loads(
        (CONTRACTS / "physical_family_authority_v1.json").read_text(encoding="utf-8")
    )


def certificates(document=None):
    return (document or authority_document())["identity_payload"][
        "gap_continuation_certificates"
    ]


def refresh(document, *certificate_indexes):
    for index in certificate_indexes:
        certificate = certificates(document)[index]
        certificate["id"] = derive_certificate_id(certificate)
    document["fingerprint"]["value"] = authority_fingerprint(document["identity_payload"])
    return document


def diagnostic_codes(document, slice1):
    with pytest.raises(ContractError) as raised:
        validate_physical_family_authority(document, slice1)
    return {item.code for item in raised.value.diagnostics}


def test_schema_status_inventory_and_future_directed_expansion(slice1):
    authority = load_physical_family_authority(slice1, CONTRACTS)
    assert authority.schema == AUTHORITY_SCHEMA
    assert authority.status == AUTHORITY_STATUS
    assert len(authority.certificates) == 11
    assert len(authority.certificates) * 2 == 22


def test_physical_projection_is_exact_and_excludes_all_slice1_provenance(slice1):
    projection = physical_slice1_projection(slice1)
    assert set(projection) == {
        "schema", "algorithm", "status", "arrangement_audit", "wall_body",
    }
    assert "provenance" not in projection
    assert physical_slice1_fingerprint(slice1) == PHYSICAL_SOURCE_SHA256
    assert fingerprint(projection) == PHYSICAL_SOURCE_SHA256


def test_every_certificate_id_is_physical_and_derived_from_complete_record():
    values = certificates()
    assert set(item["id"] for item in values) == set(EXPECTED_CERTIFICATE_IDS)
    assert all(re.fullmatch(r"physical_gap\.[0-9a-f]{20}", item["id"]) for item in values)
    assert all(item["id"] == derive_certificate_id(item) for item in values)


@pytest.mark.parametrize("certificate", certificates())
def test_forward_and_reverse_have_identical_undirected_identity(certificate):
    reverse = reverse_certificate_record(certificate)
    assert derive_certificate_id(reverse) == certificate["id"]
    assert canonical_undirected_certificate_json(reverse) == canonical_undirected_certificate_json(
        certificate
    )


def test_certificate_ids_and_serialization_contain_no_audit_labels():
    serialized = canonical_json(authority_document())
    forbidden = [
        *(f"C{index:02d}" for index in range(1, 12)),
        "bedroom_window_left", "front_door", "closet_opening",
    ]
    assert not any(label in serialized for label in forbidden)


def test_certificate_identity_has_no_semantic_aperture_transition_or_future_ids():
    forbidden_keys = {
        "semantic_face_id", "parent_wall_id", "host_face_id", "resolved_face_id",
        "aperture_id", "aperture_type", "transition_id", "room_id", "activity_id",
        "reconstruction_id", "cutter_id", "face_output_id", "audit_label", "label",
    }
    identity_prefixes = (
        "aperture.", "transition.", "room.", "activity.", "semantic_face.",
        "parent_wall.", "host_face.", "resolved_face.", "reconstruction.", "cutter.",
    )

    def walk(value):
        if isinstance(value, dict):
            assert not (set(value) & forbidden_keys)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and "." in value:
            assert not value.startswith(identity_prefixes)

    for certificate in certificates():
        walk(certificate)


def test_all_caps_germs_provenance_order_orientation_uniqueness_and_branches_validate(slice1):
    # The loader independently checks every cap point/atomic edge, source
    # segment, germ, polygon match, ordered rail, exact primitive vector,
    # branch event, local disconnection, and no-geometry assertion.
    authority = load_physical_family_authority(slice1, CONTRACTS)
    for certificate in authority.to_dict()["identity_payload"]["gap_continuation_certificates"]:
        for endpoint_name in ("endpoint_a", "endpoint_b"):
            endpoint = certificate[endpoint_name]
            assert endpoint["cap_path"][0] == endpoint["host_point"]
            assert endpoint["cap_path"][-1] == endpoint["opposite_point"]
            assert len(endpoint["atomic_cap_edges"]) == len(endpoint["cap_path"]) - 1
            assert endpoint["host_rail_germ"]["edge"][0] == endpoint["host_point"]
            assert endpoint["opposite_rail_germ"]["edge"][0] == endpoint["opposite_point"]
            assert endpoint["host_rail_germ"]["edge"][0] != endpoint["host_rail_germ"]["edge"][1]
            assert endpoint["opposite_rail_germ"]["edge"][0] != endpoint["opposite_rail_germ"]["edge"][1]


def test_inverse_duplicate_is_rejected(slice1):
    document = authority_document()
    document["identity_payload"]["gap_continuation_certificates"][-1] = (
        reverse_certificate_record(certificates(document)[0])
    )
    refresh(document, 10)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.inverse_duplicate" in codes
    assert "physical_family.inventory" in codes


def test_duplicate_certificate_is_rejected(slice1):
    document = authority_document()
    certificates(document)[-1] = deepcopy(certificates(document)[0])
    refresh(document)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.duplicate" in codes
    assert "physical_family.inverse_duplicate" in codes


def test_unknown_certificate_id_is_rejected(slice1):
    document = authority_document()
    certificates(document)[0]["id"] = "physical_gap.ffffffffffffffffffff"
    refresh(document)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.certificate_id" in codes
    assert "physical_family.inventory" in codes


def test_physical_source_sha_mismatch_fails_closed(slice1):
    document = authority_document()
    document["identity_payload"]["physical_source"]["sha256"] = "0" * 64
    refresh(document)
    assert "physical_family.source" in diagnostic_codes(document, slice1)
    mutated_slice = deepcopy(slice1)
    mutated_slice["arrangement_audit"]["atomic_edges"] += 1
    assert "physical_family.source" in diagnostic_codes(authority_document(), mutated_slice)


def test_cap_mutation_fails_closed(slice1):
    document = authority_document()
    endpoint = certificates(document)[0]["endpoint_a"]
    endpoint["cap_path"][1] = ["11799/100", "297/5"]
    endpoint["atomic_cap_edges"][0]["edge"][1] = ["11799/100", "297/5"]
    endpoint["atomic_cap_edges"][1]["edge"][0] = ["11799/100", "297/5"]
    refresh(document, 0)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.endpoint_match" in codes
    assert "physical_family.edge_missing" in codes


def test_germ_mutation_fails_closed(slice1):
    document = authority_document()
    certificates(document)[1]["endpoint_a"]["host_rail_germ"]["edge"][1] = [
        "5593/25", "6509/100",
    ]
    refresh(document, 1)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.endpoint_match" in codes
    assert "physical_family.edge_missing" in codes


def test_provenance_mutation_fails_closed(slice1):
    document = authority_document()
    certificates(document)[2]["endpoint_a"]["atomic_cap_edges"][0][
        "source_segments"
    ] = ["wall.contour.c004.segment.s012"]
    refresh(document, 2)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.endpoint_match" in codes
    assert "physical_family.provenance" in codes


def test_host_opposite_swap_fails_closed(slice1):
    document = authority_document()
    endpoint = certificates(document)[4]["endpoint_a"]
    endpoint["host_point"], endpoint["opposite_point"] = (
        endpoint["opposite_point"], endpoint["host_point"],
    )
    refresh(document, 4)
    assert "physical_family.cap" in diagnostic_codes(document, slice1)


def test_orientation_mutation_fails_closed(slice1):
    document = authority_document()
    certificates(document)[5]["orientation"]["normal"] = [0, 1]
    refresh(document, 5)
    assert "physical_family.order" in diagnostic_codes(document, slice1)


def test_c01_diagonal_orientation_with_rederived_id_fails_physical_validation(slice1):
    document = authority_document()
    certificate = certificates(document)[0]
    certificate["orientation"] = {"tangent": [1, 1], "normal": [-1, 1]}
    refresh(document, 0)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.orientation" in codes
    assert "physical_family.certificate_id" not in codes


def test_tangent_reversal_with_rederived_id_fails_physical_validation(slice1):
    document = authority_document()
    certificate = certificates(document)[0]
    certificate["orientation"] = {"tangent": [-1, 0], "normal": [0, -1]}
    refresh(document, 0)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.order" in codes
    assert "physical_family.certificate_id" not in codes


def test_host_opposite_normal_reversal_with_rederived_id_fails_physical_validation(slice1):
    document = authority_document()
    certificates(document)[0]["orientation"]["normal"] = [0, -1]
    refresh(document, 0)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.order" in codes
    assert "physical_family.certificate_id" not in codes


def test_competing_branch_requires_explicit_accepted_event(slice1):
    document = authority_document()
    certificates(document)[3]["endpoint_b"]["accepted_exact_junction"] = {
        "required": False, "events": [],
    }
    refresh(document, 3)
    assert "physical_family.junction" in diagnostic_codes(document, slice1)


def test_already_locally_connected_certificate_fails_closed(slice1):
    document = authority_document()
    certificate = certificates(document)[0]
    certificate["endpoint_b"] = deepcopy(certificate["endpoint_a"])
    refresh(document, 0)
    assert "physical_family.already_connected" in diagnostic_codes(document, slice1)


def test_certificate_cannot_create_positive_area_or_add_geometry_fields(slice1):
    document = authority_document()
    assert all(
        certificate["assertions"]["creates_positive_area_wall"] is False
        for certificate in certificates(document)
    )
    certificates(document)[0]["polygon"] = [["0/1", "0/1"]]
    refresh(document, 0)
    assert "physical_family.shape" in diagnostic_codes(document, slice1)


def test_no_tolerance_epsilon_snap_buffer_or_repair_semantics():
    document = authority_document()
    identity = document["identity_payload"]
    assert identity["algorithm"]["arithmetic"] == "fractions_only"
    assert not any(
        key in canonical_json(certificates(document))
        for key in ("tolerance", "epsilon", "snap", "buffer", "repair", "approximate")
    )
    assert identity["authority_limitations"][-1] == (
        "no_tolerance_epsilon_snap_repair_or_approximate_adjacency"
    )


def test_absent_certificate_means_no_inferred_gap_edge(slice1):
    document = authority_document()
    document["identity_payload"]["gap_continuation_certificates"].pop()
    refresh(document)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.inventory" in codes
    assert document["identity_payload"]["authority_limitations"][-2] == (
        "absence_of_certificate_means_no_gap_edge"
    )


def test_c04_crossing_selects_main_polygon_and_rejects_isolated_triangle(slice1):
    endpoint = certificates()[3]["endpoint_b"]
    crossing = ["22583401/28450", "6627201/28450"]
    assert endpoint["wall_body_polygon"] == "wall_body.apartment.polygon.ef37dfe6480608de1060"
    assert endpoint["accepted_exact_junction"] == {
        "required": True,
        "events": [{
            "kind": "accepted_proper_crossing",
            "point": crossing,
            "source_segments": [
                "wall.contour.c002.segment.s003", "wall.contour.c002.segment.s005",
            ],
        }],
    }
    document = authority_document()
    original_id = certificates(document)[3]["id"]
    certificates(document)[3]["endpoint_b"]["wall_body_polygon"] = (
        "wall_body.apartment.polygon.0ae6707e5829757f3e5a"
    )
    # Polygon labels are provenance-only and deliberately excluded from ID.
    assert derive_certificate_id(certificates(document)[3]) == original_id
    refresh(document)
    assert "physical_family.endpoint_match" in diagnostic_codes(document, slice1)


def test_c09_tapered_nonparallel_rails_need_no_constant_width(slice1):
    certificate = certificates()[8]

    def horizontal_cap_width(endpoint):
        host, opposite = endpoint["host_point"], endpoint["opposite_point"]
        return abs(Fraction(host[0]) - Fraction(opposite[0]))

    assert horizontal_cap_width(certificate["endpoint_a"]) != horizontal_cap_width(
        certificate["endpoint_b"]
    )
    load_physical_family_authority(slice1, CONTRACTS)
def test_c10_cap_plus_local_junction_endpoint_remains_nondegenerate(slice1):
    endpoint = certificates()[9]["endpoint_b"]
    assert endpoint["atomic_cap_edges"] == [{
        "edge": [["7018/25", "51139/50"], ["28153/100", "2083/2"]],
        "source_segments": ["wall.contour.c006.segment.s051"],
    }]
    assert endpoint["host_point"] != endpoint["opposite_point"]
    assert endpoint["accepted_exact_junction"]["required"] is True
    load_physical_family_authority(slice1, CONTRACTS)


def test_c10_local_junction_is_mandatory_from_physical_terminal_evidence(slice1):
    document = authority_document()
    certificates(document)[9]["endpoint_b"]["accepted_exact_junction"] = {
        "required": False, "events": [],
    }
    refresh(document, 9)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.junction" in codes
    assert "physical_family.certificate_id" not in codes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("point", ["0/1", "0/1"]),
        ("source_segments", ["wall.contour.c006.segment.s050", "wall.contour.c006.segment.s052"]),
    ],
)
def test_c10_junction_mutations_with_rederived_id_fail(field, value, slice1):
    document = authority_document()
    event = certificates(document)[9]["endpoint_b"]["accepted_exact_junction"]["events"][0]
    event[field] = value
    refresh(document, 9)
    codes = diagnostic_codes(document, slice1)
    assert "physical_family.junction" in codes
    assert "physical_family.certificate_id" not in codes


def test_fabricated_junction_on_nonjunction_terminal_fails(slice1):
    document = authority_document()
    endpoint = certificates(document)[0]["endpoint_a"]
    endpoint["accepted_exact_junction"] = {
        "required": True,
        "events": [{
            "kind": "accepted_exact_junction_unique_directed_continuation",
            "point": endpoint["host_point"],
            "source_segments": [
                "wall.contour.c006.segment.s099",
                "wall.contour.c006.segment.s100",
            ],
        }],
    }
    refresh(document, 0)
    assert "physical_family.junction" in diagnostic_codes(document, slice1)


def test_authority_fingerprint_is_identity_payload_only_and_deterministic(slice1):
    document = authority_document()
    expected = document["fingerprint"]["value"]
    assert authority_fingerprint(document["identity_payload"]) == expected
    assert document["fingerprint"]["value"] == expected
    assert load_physical_family_authority(slice1, CONTRACTS).fingerprint == expected
    reordered = {key: document["identity_payload"][key] for key in reversed(document["identity_payload"])}
    assert authority_fingerprint(reordered) == expected
    reversed_certificates = deepcopy(document["identity_payload"])
    reversed_certificates["gap_continuation_certificates"].reverse()
    assert authority_fingerprint(reversed_certificates) == expected
    reversed_document = deepcopy(document)
    reversed_document["identity_payload"]["gap_continuation_certificates"].reverse()
    refresh(reversed_document)
    validate_physical_family_authority(reversed_document, slice1)


def test_authority_fingerprint_is_invariant_under_deterministic_certificate_permutations():
    identity = authority_document()["identity_payload"]
    expected = authority_fingerprint(identity)
    for seed in range(8):
        permutation = deepcopy(identity)
        random.Random(seed).shuffle(permutation["gap_continuation_certificates"])
        assert authority_fingerprint(permutation) == expected


def test_certificate_identity_is_hash_seed_deterministic():
    expected = "\n".join(EXPECTED_CERTIFICATE_IDS)
    command = (
        "import json;from pathlib import Path;"
        "from backend.apartment_canvas.physical_family_authority import derive_certificate_id;"
        "d=json.loads(Path('docs/dashboard/apartment_canvas/physical_family_authority_v1.json').read_text());"
        "print(*[derive_certificate_id(x) for x in d['identity_payload']['gap_continuation_certificates']],sep='\\n')"
    )
    for seed in ("1", "982451653"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.stdout.strip() == expected


def test_authority_fingerprint_is_hash_seed_and_list_order_deterministic():
    expected = authority_fingerprint(authority_document()["identity_payload"])
    command = (
        "import json;from pathlib import Path;"
        "from backend.apartment_canvas.physical_family_authority import authority_fingerprint;"
        "d=json.loads(Path('docs/dashboard/apartment_canvas/physical_family_authority_v1.json').read_text());"
        "d['identity_payload']['gap_continuation_certificates'].reverse();"
        "print(authority_fingerprint(d['identity_payload']))"
    )
    for seed in ("1", "982451653"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert completed.stdout.strip() == expected


def test_topology_authority_and_full_slice1_are_unchanged(slice1):
    topology_document = json.loads(
        (CONTRACTS / "topology_authority_v1.json").read_text(encoding="utf-8")
    )
    assert fingerprint(topology_document) == TOPOLOGY_SHA256
    assert document_fingerprint(slice1) == SLICE1_SHA256


def test_slice1_counts_and_exact_crossing_are_unchanged(slice1):
    assert slice1["arrangement_audit"] == {
        "atomic_edges": 187,
        "bounded_odd_cells": 7,
        "noded_vertices": 186,
        "proper_crossings": [{
            "point": ["22583401/28450", "6627201/28450"],
            "segments": [
                "wall.contour.c002.segment.s003", "wall.contour.c002.segment.s005",
            ],
        }],
        "source_segments": 185,
    }
    assert len(slice1["wall_body"]["polygons"]) == 7


def test_fingerprint_uses_canonical_certificate_set_projection():
    identity = authority_document()["identity_payload"]
    canonical = json.loads(canonical_json(identity))
    canonical["gap_continuation_certificates"].sort(key=canonical_json)
    assert authority_fingerprint(identity) == sha256(canonical_json(canonical).encode("utf-8")).hexdigest()
