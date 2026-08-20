"""Compile reconciled contracts into a deterministic semantic scene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ContractBundle, canonical_json, load_contracts
from .models import SemanticSceneV1, deep_freeze, deep_thaw
from .validation import validate, validate_scene


def _by_id(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(sorted(items, key=lambda item: item["id"]))


def _assemblies() -> tuple[dict[str, Any], ...]:
    return _by_id(
        [
            {
                "id": "assembly.bed",
                "members": ["bedroom.bed"],
                "requirements": ["base", "mattress", "headboard", "exactly_two_pillows"],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.workstation",
                "members": [
                    "bedroom.desk_main",
                    "bedroom.desk_return",
                    "bedroom.chair",
                    "bedroom.monitor",
                    "bedroom.pc",
                    "bedroom.projector",
                ],
                "relationships": ["pc_under_opposite_left_desk_side", "projector_on_desk_return"],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.shower",
                "members": ["bath.shower"],
                "requirements": [
                    "tray",
                    "named_enclosure",
                    "glass_front_role",
                    "opaque_fixed_side_back_roles",
                ],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.vanity",
                "members": ["bath.vanity"],
                "requirements": ["visible_basin", "upright_back_side_faucet_facing_basin"],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.toilet",
                "members": ["bath.toilet"],
                "requirements": ["tank", "pedestal", "bowl"],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.laundry",
                "members": ["service.laundry"],
                "requirements": [
                    "washer",
                    "dryer",
                    "arrangement_provisional",
                    "form_factor_provisional",
                ],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.cooking",
                "members": ["kitchen.stove", "kitchen.microwave"],
                "relationships": ["microwave_above_stove_oven"],
                "provenance": "owner_verified",
            },
            {
                "id": "assembly.kitchen_pendants",
                "members": ["kitchen.pendant_1", "kitchen.pendant_2"],
                "requirements": ["exactly_two", "suspended", "island_thirds"],
                "provenance": "source_proven",
            },
        ]
    )


def compile_scene(bundle: ContractBundle) -> SemanticSceneV1:
    validate(bundle)
    amendments = deep_thaw(bundle.patch)["contract_amendments"]
    geometry = deep_thaw(bundle.geometry)
    visibility = deep_thaw(bundle.visibility)["accepted_direction"]
    treatments = _by_id(
        [
            {"id": "visibility.global_cutaway", **visibility["global_cutaway"]},
            {"id": "visibility.bedroom_front_wall", **visibility["bedroom_front_wall"]},
            {"id": "visibility.projector_wall", **visibility["projector_wall"]},
        ]
    )
    scene = SemanticSceneV1(
        schema="homehub.apartment-semantic-scene.v1",
        version="v1",
        source_manifest=deep_freeze(bundle.source_manifest),
        coordinate_system=deep_freeze({
            "canonical": True,
            "axes": {"x": "right", "y": "down", "z": "up"},
            "render_transform": "deferred_to_geometry_scene_renderer_adapter",
        }),
        architecture=deep_freeze({
            "wall_contours_gu": geometry["architecture"]["wall_polygons_gu"],
            "rooms": _by_id(geometry["rooms"]),
            "semantic_edges": _by_id(amendments["semantic_wall_edges_gu"]),
            "provenance_policy": amendments["provenance_policy"],
            "wall_volume_contract": amendments["wall_volume_contract"],
        }),
        wall_volumes=deep_freeze(_by_id(amendments["semantic_wall_volumes"])),
        balcony_footprint=deep_freeze(amendments["balcony_semantics"]),
        apertures=deep_freeze(_by_id(deep_thaw(bundle.aperture_registry)["apertures"])),
        objects=deep_freeze(_by_id(geometry["objects"])),
        unplaced_objects=deep_freeze(_by_id(geometry["unplaced_objects"])),
        assemblies=deep_freeze(_assemblies()),
        visibility_treatments=deep_freeze(treatments),
        projection_contract=deep_freeze(bundle.projection),
        camera=deep_freeze(deep_thaw(bundle.camera)["camera"]),
        unresolved_metadata=deep_freeze({
            "vertical_geometry": "provisional",
            "mesh_topology": "not_compiled",
            "renderer_adapter": "deferred",
            "object_z_and_silhouette": "provisional",
        }),
    )
    validate_scene(scene)
    return scene


def compile_scene_from_directory(directory: str | Path | None = None) -> SemanticSceneV1:
    return compile_scene(load_contracts(directory))


def canonical_scene_json(scene: SemanticSceneV1) -> str:
    return canonical_json(scene.to_dict()) + "\n"
