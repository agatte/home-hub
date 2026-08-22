"""Compile the accepted Apartment Canvas XY authority into a 3-D whitebox artifact.

This module intentionally has no renderer dependency.  It carries exact plan-space
footprints forward as reduced rational tokens and records the small set of required
vertical choices as explicitly provisional policy.  It deliberately does not use
physical-family or wall-band authority: the accepted Slice 1 visible wall body is
the sole wall-mass input.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .architecture_topology import compile_wall_body_slice1
from .compiler import compile_scene
from .contracts import ContractBundle, canonical_json, load_contracts
from .exact_geometry import Point, rational, rational_text
from .models import deep_thaw
from .topology_authority import TopologyAuthorityV1, load_topology_authority


SCHEMA = "homehub.apartment-geometry-scene.v1"
STATUS = "derived_whitebox_geometry_scene"
ALGORITHM = "accepted_slice1_wall_body_vertical_extrusion.v1"

# No accepted vertical measurement exists in the current contracts.  These values
# are deliberately simple GU defaults, isolated here so a later z-authority update
# changes policy rather than any accepted XY geometry.
_FLOOR_Z_MIN = "-4/1"
_FLOOR_Z_MAX = "0/1"
_WALL_Z_MIN = "0/1"
_WALL_Z_MAX = "240/1"


def _canonical_decimal(value: Any) -> Any:
    """Recover exact JSON numeric tokens before converting plan coordinates."""
    return json.loads(
        canonical_json(value), parse_float=Decimal, parse_int=Decimal,
    )


def _exact_ring(ring: Any) -> list[list[str]]:
    values = _canonical_decimal(ring)
    return [Point.from_value(point).to_tokens() for point in values]


def _exact_segment(segment: Any) -> list[list[str]]:
    return _exact_ring(segment)


def _exact_number(value: Any) -> str:
    return rational_text(rational(_canonical_decimal(value)))


def _source(bundle: ContractBundle, filename: str) -> dict[str, str]:
    source = next(item for item in bundle.source_manifest if item["id"] == filename)
    return {"id": source["id"], "schema": source["schema"], "sha256": source["sha256"]}


def _provisional_z_policy() -> dict[str, Any]:
    return {
        "status": "provisional",
        "unit": "GU",
        "reason": "No accepted surveyed vertical dimensions exist in the current Apartment Canvas contracts.",
        "floor_slab": {
            "z_min_gu": _FLOOR_Z_MIN,
            "z_max_gu": _FLOOR_Z_MAX,
            "thickness_gu": "4/1",
            "status": "provisional_whitebox_default",
        },
        "wall_body": {
            "z_min_gu": _WALL_Z_MIN,
            "z_max_gu": _WALL_Z_MAX,
            "height_gu": "240/1",
            "status": "provisional_whitebox_default",
        },
        "apertures": {
            "status": "registry_provisional_vertical_values",
            "rule": "Use each registered sill_gu/head_gu unchanged as an opening descriptor; do not treat it as accepted measured z geometry.",
        },
        "presentation": {
            "status": "provisional",
            "values": [
                "south_front_cutaway_lip_height_gu",
                "bedroom_solid_base_height_gu",
                "bedroom_upper_wall_opacity",
            ],
        },
    }


def _floor_slabs(authority: TopologyAuthorityV1, bundle: ContractBundle) -> list[dict[str, Any]]:
    topology = deep_thaw(authority.document)
    slab = topology["apartment_slab"]
    balcony = deep_thaw(bundle.patch)["contract_amendments"]["balcony_semantics"]
    z = _provisional_z_policy()["floor_slab"]
    return [
        {
            "id": slab["id"],
            "kind": "apartment_floor_slab",
            "source": {
                "topology_authority_pointer": "#/apartment_slab",
                "balcony_excluded": True,
            },
            "source_ring_gu": slab["ring_gu"],
            "footprint_ring_gu": _exact_ring(slab["ring_gu"]),
            "z_min_gu": z["z_min_gu"],
            "z_max_gu": z["z_max_gu"],
            "z_status": z["status"],
            "whitebox_classification": "structural_floor_slab",
        },
        {
            "id": balcony["id"],
            "kind": "balcony_floor_slab",
            "source": {
                "patch_pointer": "#/contract_amendments/balcony_semantics",
                "shared_architecture_edge_id": balcony["shared_architecture_edge_id"],
                "shared_aperture_ids": sorted(balcony["shared_aperture_ids"]),
            },
            "source_ring_gu": balcony["ring_gu"],
            "footprint_ring_gu": _exact_ring(balcony["ring_gu"]),
            "z_min_gu": z["z_min_gu"],
            "z_max_gu": z["z_max_gu"],
            "z_status": z["status"],
            "whitebox_classification": "structural_balcony_slab",
        },
    ]


def _wall_extrusions(wall_body: dict[str, Any]) -> list[dict[str, Any]]:
    z = _provisional_z_policy()["wall_body"]
    polygons = wall_body["polygons"]
    return [
        {
            "id": f"geometry_scene.extrusion.{polygon['id'].removeprefix('wall_body.')}",
            "kind": "vertical_wall_body_extrusion",
            "source_polygon_id": polygon["id"],
            "footprint_gu": {
                "outer": polygon["outer"],
                "holes": polygon["holes"],
            },
            "polygon_provenance": polygon["provenance"],
            "z_min_gu": z["z_min_gu"],
            "z_max_gu": z["z_max_gu"],
            "z_status": z["status"],
            "whitebox_classification": "opaque_wall_body_with_named_presentation_overrides",
            "presentation_selector": "deferred_to_named_visibility_contract_face_ids",
        }
        for polygon in sorted(polygons, key=lambda item: item["id"])
    ]


def _semantic_wall_volumes(bundle: ContractBundle) -> list[dict[str, Any]]:
    """Forward accepted host-wall/face geometry required by renderers.

    Slice 1 remains the one and only wall-mass owner.  This is deliberately
    narrower than a new topology layer: it carries the already-accepted stable
    wall-volume and bearing-face identities so a renderer can bind aperture
    cutters and presentation selectors without reopening upstream contracts.
    """
    volumes = deep_thaw(bundle.patch)["contract_amendments"]["semantic_wall_volumes"]
    return [
        {
            "id": volume["id"],
            "semantic_edge_id": volume["semantic_edge_id"],
            "faces": [
                {
                    "id": face["id"],
                    "bearing_line_gu": _exact_segment(face["bearing_line_gu"]),
                    "plan_normal": face["plan_normal"],
                    "role": face["role"],
                }
                for face in sorted(volume["faces"], key=lambda item: item["id"])
            ],
        }
        for volume in sorted(volumes, key=lambda item: item["id"])
    ]


def _inspection_annotations(bundle: ContractBundle) -> dict[str, Any]:
    """Forward accepted plan annotations without creating render authority.

    These are deliberately annotations, not a room-topology or object-mesh
    contract.  The local whitebox may use them to explain already accepted XY
    data, but its labels and fixture blocks must remain optional debug aids.
    """
    geometry = deep_thaw(bundle.geometry)
    rooms = []
    for room in sorted(geometry["rooms"], key=lambda item: item["id"]):
        rooms.append({
            "id": room["id"],
            "label": room["label"],
            "label_gu": _exact_segment([room["label_gu"]])[0],
            "source": "geometry_v1.json#/rooms",
            "xy_status": "accepted_approximate_label_position",
        })
    objects = []
    for item in sorted(geometry["objects"], key=lambda value: value["id"]):
        rectangle = item.get("rect")
        if not rectangle:
            continue
        objects.append({
            "id": item["id"],
            "label": item["label"],
            "room": item["room"],
            "shape": item["shape"],
            "rect_gu": {key: _exact_number(rectangle[key]) for key in ("x", "y", "w", "h")},
            "placement_status": item["placement_status"],
            "source": item["source"],
            "note": item.get("note"),
            "xy_status": "accepted_approximate_object_placement",
        })
    return {
        "status": "accepted_annotation_forwarding_for_local_debug_only",
        "rooms": rooms,
        "objects": objects,
    }


def _openings(bundle: ContractBundle) -> list[dict[str, Any]]:
    registry = deep_thaw(bundle.aperture_registry)
    openings = []
    for aperture in sorted(registry["apertures"], key=lambda item: item["id"]):
        vertical = aperture["vertical"]
        openings.append({
            "id": f"geometry_scene.opening.{aperture['id']}",
            "source_aperture_id": aperture["id"],
            "kind": aperture["type"],
            "subtype": aperture.get("subtype"),
            "connects": sorted(aperture["connects"]),
            "parent_wall_id": aperture["parent_wall_id"],
            "host_face_id": aperture["host_face_id"],
            "orientation": aperture["orientation"],
            "source_segment_gu": aperture["segment_gu"],
            "segment_gu": _exact_segment(aperture["segment_gu"]),
            "vertical": {
                "z_min_gu": _exact_number(vertical["sill_gu"]),
                "z_max_gu": _exact_number(vertical["head_gu"]),
                "status": vertical["status"],
                "source": "aperture_registry_v1.json#/apertures/*/vertical",
            },
            "realization": {
                "kind": "registered_opening_cutter_descriptor",
                "boolean_wall_cut_applied": False,
                "rule": "A later renderer cuts this exact host-face span through its named parent wall; no wall family or hidden seam is inferred here.",
            },
            "preservation": aperture["preservation"],
            "visibility_exclusion": aperture.get("visibility_exclusion"),
        })
    return openings


def _visibility(bundle: ContractBundle) -> list[dict[str, Any]]:
    accepted = deep_thaw(bundle.visibility)["accepted_direction"]
    return [
        {
            "id": "visibility.global_cutaway",
            "presentation_only": True,
            "selector": {
                "wall_ids": sorted(accepted["global_cutaway"]["target_wall_ids"]),
                "face_ids": sorted(accepted["global_cutaway"]["target_face_ids"]),
            },
            "rule": accepted["global_cutaway"]["rule"],
            "parameters": {
                "lip_height_gu": accepted["global_cutaway"]["exact_lip_height_gu"],
                "inspection_lip_height_gu": accepted["global_cutaway"]["inspection_value_gu"],
                "inspection_lip_status": "provisional",
            },
            "status": "accepted_selector_provisional_parameter",
        },
        {
            "id": "visibility.bedroom_front_wall",
            "presentation_only": True,
            "selector": {
                "wall_id": accepted["bedroom_front_wall"]["target_wall_id"],
                "face_id": accepted["bedroom_front_wall"]["target_face_id"],
                "solid_face_id": accepted["bedroom_front_wall"]["solid_face_id"],
                "translucent_face_id": accepted["bedroom_front_wall"]["translucent_face_id"],
            },
            "rule": accepted["bedroom_front_wall"]["rule"],
            "excluded_wall_ids": sorted(accepted["bedroom_front_wall"]["excluded_wall_ids"]),
            "excluded_aperture_ids": sorted(accepted["bedroom_front_wall"]["excluded_aperture_ids"]),
            "opaque_architecture": sorted(accepted["bedroom_front_wall"]["opaque_architecture"]),
            "parameters": {
                "solid_base_height_gu": accepted["bedroom_front_wall"]["exact_base_height_gu"],
                "upper_opacity": accepted["bedroom_front_wall"]["exact_opacity"],
            },
            "status": "accepted_selector_provisional_parameters",
        },
    ]


def _payload_fingerprint(scene: dict[str, Any]) -> str:
    payload = {key: value for key, value in scene.items() if key != "fingerprint"}
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def geometry_scene_fingerprint(scene: dict[str, Any]) -> str:
    """Return the canonical artifact hash, excluding its self-referential field."""
    return _payload_fingerprint(scene)


def _physical_slice1_source(slice1: dict[str, Any]) -> dict[str, str]:
    """Identify the exact Slice 1 wall-body data consumed by this artifact.

    Slice 1 also carries semantic-scene audit metadata.  That metadata is
    useful to its own compiler, but GeometrySceneV1 consumes only its accepted
    dissolved physical wall body; including the aggregate result would couple
    this artifact to unrelated semantic inputs such as projection policy.
    """
    wall_body = slice1["wall_body"]
    return {
        "id": "architecture_wall_topology_slice_1.wall_body",
        "schema": slice1["schema"],
        "sha256": sha256(canonical_json(wall_body).encode("utf-8")).hexdigest(),
    }


def compile_geometry_scene(bundle: ContractBundle, authority: TopologyAuthorityV1) -> dict[str, Any]:
    """Return a deterministic, renderer-neutral GeometrySceneV1 artifact."""
    semantic_scene = compile_scene(bundle)
    slice1 = compile_wall_body_slice1(semantic_scene, authority, bundle)
    wall_body = slice1["wall_body"]
    topology = deep_thaw(authority.document)
    floor_slabs = _floor_slabs(authority, bundle)
    wall_extrusions = _wall_extrusions(wall_body)
    semantic_wall_volumes = _semantic_wall_volumes(bundle)
    inspection_annotations = _inspection_annotations(bundle)
    openings = _openings(bundle)
    scene = {
        "schema": SCHEMA,
        "status": STATUS,
        "algorithm": ALGORITHM,
        "provenance": {
            "physical_xy": {
                "sources": [
                    _source(bundle, "geometry_v1.json"),
                    _source(bundle, "geometry_v1_6_patch.json"),
                    {
                        "id": "topology_authority_v1.json",
                        "schema": authority.schema,
                        "sha256": authority.fingerprint,
                    },
                    _physical_slice1_source(slice1),
                ],
                "wall_body_source": "accepted_even_odd_dissolved_slice_1_polygons",
                "slab_source": "topology_authority_v1.json#/apartment_slab",
                "topology_authority_status": topology["status"],
            },
            "aperture_semantic": {
                "sources": [_source(bundle, "aperture_registry_v1.json")],
            },
            "camera": {"source": _source(bundle, "camera_v2.json")},
            "visibility": {"source": _source(bundle, "visibility_contract_v2.json")},
            "excluded_dependencies": [
                "PhysicalWallBandAuthorityV1",
                "PhysicalFamilyPreflight",
                "PhysicalFamilyAuthorityV1",
            ],
        },
        "coordinate_system": {
            "plan_axes": {"x": "right", "y": "down"},
            "z_axis": "up",
            "xy_representation": "reduced_rational_gu_tokens_preserving_accepted_plan_space",
            "renderer_transform": "deferred",
        },
        "z_policy": _provisional_z_policy(),
        "floor_slabs": floor_slabs,
        "wall_extrusions": wall_extrusions,
        "semantic_wall_volumes": semantic_wall_volumes,
        "inspection_annotations": inspection_annotations,
        "openings": openings,
        "camera": deep_thaw(bundle.camera),
        "visibility_treatments": _visibility(bundle),
        "whitebox_summary": {
            "floor_slab_count": len(floor_slabs),
            "wall_body_polygon_count": len(wall_extrusions),
            "wall_extrusion_count": len(wall_extrusions),
            "registered_aperture_count": len(deep_thaw(bundle.aperture_registry)["apertures"]),
            "opening_descriptor_count": len(openings),
            "balcony_representation": "separate_closed_balcony_floor_slab",
            "furniture": "excluded",
            "renderer": "excluded",
        },
    }
    scene["fingerprint"] = _payload_fingerprint(scene)
    return json.loads(canonical_json(scene))


def compile_geometry_scene_from_directory(directory: str | Path | None = None) -> dict[str, Any]:
    """Load accepted sources and compile GeometrySceneV1 in one offline call."""
    bundle = load_contracts(directory)
    authority = load_topology_authority(directory)
    return compile_geometry_scene(bundle, authority)


def canonical_geometry_scene_json(scene: dict[str, Any]) -> str:
    return canonical_json(scene) + "\n"
