"""Stable semantic validation; deliberately excludes future mesh checks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .contracts import ContractBundle, ContractError, Diagnostic
from .models import SemanticSceneV1, deep_thaw

EPSILON = 1e-6


def _ids(items: Any, path: str, errors: list[Diagnostic]) -> set[str]:
    found: set[str] = set()
    if not isinstance(items, list):
        errors.append(Diagnostic("structure.list", path, "must be a list"))
        return found
    for index, item in enumerate(items):
        item_id = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(item_id, str) or item_id in found:
            errors.append(Diagnostic("id.duplicate", f"{path}[{index}].id", "stable ID missing or duplicated"))
        else:
            found.add(item_id)
    return found


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _point(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(_number(item) for item in value)


def _on_segment(point: list[float], a: list[float], b: list[float]) -> bool:
    cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0])
    return abs(cross) <= EPSILON and min(a[0], b[0]) - EPSILON <= point[0] <= max(a[0], b[0]) + EPSILON and min(a[1], b[1]) - EPSILON <= point[1] <= max(a[1], b[1]) + EPSILON


def validate(bundle: ContractBundle) -> None:
    """Validate reconciled semantic references after source authority was checked by loading."""
    errors: list[Diagnostic] = []
    geometry, patch, registry = (deep_thaw(bundle.geometry), deep_thaw(bundle.patch), deep_thaw(bundle.aperture_registry))
    objects = geometry.get("objects", [])
    _ids(objects, "geometry.objects", errors)
    amendments = patch.get("contract_amendments", {})
    edges = amendments.get("semantic_wall_edges_gu", []) if isinstance(amendments, dict) else []
    edge_ids = _ids(edges, "patch.semantic_wall_edges_gu", errors)
    volumes = amendments.get("semantic_wall_volumes", []) if isinstance(amendments, dict) else []
    volume_ids = _ids(volumes, "patch.semantic_wall_volumes", errors)
    faces: dict[str, tuple[str, list[list[float]]]] = {}
    face_ids: set[str] = set()
    if not isinstance(volumes, list):
        errors.append(Diagnostic("structure.list", "patch.semantic_wall_volumes", "must be a list"))
        volumes = []
    for vi, volume in enumerate(volumes):
        if not isinstance(volume, dict):
            errors.append(Diagnostic("wall.volume", f"wall_volumes[{vi}]", "must be an object"))
            continue
        if volume.get("semantic_edge_id") not in edge_ids:
            errors.append(Diagnostic("wall.edge", f"wall_volumes[{vi}].semantic_edge_id", "unknown semantic edge"))
        for fi, face in enumerate(volume.get("faces", [])):
            path = f"wall_volumes[{vi}].faces[{fi}]"
            if not isinstance(face, dict):
                errors.append(Diagnostic("wall.face", path, "must be an object"))
                continue
            fid, line, normal = face.get("id"), face.get("bearing_line_gu"), face.get("plan_normal")
            valid_line = isinstance(line, list) and len(line) == 2 and all(_point(point) for point in line) and line[0] != line[1]
            axis_aligned = valid_line and (line[0][0] == line[1][0] or line[0][1] == line[1][1])
            if not isinstance(fid, str) or fid in face_ids:
                errors.append(Diagnostic("id.duplicate", path + ".id", "face ID missing or duplicated"))
            else:
                face_ids.add(fid)
            if normal not in {"+x", "-x", "+y", "-y"} or not axis_aligned:
                errors.append(Diagnostic("wall.face", path, "invalid axis-aligned bearing line or plan normal"))
            elif isinstance(fid, str) and fid not in faces:
                faces[fid] = (volume.get("id"), line)
    apertures = registry.get("apertures", [])
    aperture_ids = _ids(apertures, "apertures", errors)
    if not isinstance(apertures, list):
        apertures = []
    for index, aperture in enumerate(apertures):
        path = f"apertures[{index}]"
        if not isinstance(aperture, dict):
            errors.append(Diagnostic("aperture.structure", path, "must be an object"))
            continue
        segment = aperture.get("segment_gu")
        valid_segment = isinstance(segment, list) and len(segment) == 2 and all(_point(point) for point in segment)
        if not valid_segment:
            errors.append(Diagnostic("aperture.segment", path + ".segment_gu", "must contain exactly two numeric coordinate pairs"))
            continue
        if segment[0] == segment[1]:
            errors.append(Diagnostic("aperture.segment", path + ".segment_gu", "must have non-zero length"))
            continue
        horizontal = segment[0][1] == segment[1][1]
        vertical = segment[0][0] == segment[1][0]
        if aperture.get("orientation") == "horizontal" and not horizontal or aperture.get("orientation") == "vertical" and not vertical or aperture.get("orientation") not in {"horizontal", "vertical"}:
            errors.append(Diagnostic("aperture.orientation", path + ".orientation", "must agree with segment geometry"))
            continue
        host, parent = aperture.get("host_face_id"), aperture.get("parent_wall_id")
        pair = faces.get(host)
        if parent not in volume_ids or pair is None or pair[0] != parent:
            errors.append(Diagnostic("aperture.host", path, "aperture must belong to its declared wall volume and face"))
            continue
        if not all(_on_segment(point, pair[1][0], pair[1][1]) for point in segment):
            errors.append(Diagnostic("aperture.trace", path + ".segment_gu", "trace is off or outside host bearing line"))
    balcony = amendments.get("balcony_semantics", {}) if isinstance(amendments, dict) else {}
    ring = balcony.get("ring_gu", []) if isinstance(balcony, dict) else []
    if not isinstance(ring, list) or len(ring) < 4 or not all(_point(point) for point in ring) or ring[0] != ring[-1]:
        errors.append(Diagnostic("balcony.closed", "patch.balcony_semantics.ring_gu", "footprint must be a closed coordinate ring"))
    if not isinstance(balcony, dict) or balcony.get("shared_architecture_edge_id") not in edge_ids:
        errors.append(Diagnostic("balcony.edge", "patch.balcony_semantics.shared_architecture_edge_id", "unknown edge"))
    if not isinstance(balcony, dict) or not set(balcony.get("shared_aperture_ids", [])).issubset(aperture_ids):
        errors.append(Diagnostic("balcony.aperture", "patch.balcony_semantics.shared_aperture_ids", "unknown aperture"))
    _validate_visibility(deep_thaw(bundle.visibility), volume_ids, face_ids, aperture_ids, errors)
    if len(objects) != 42 or len(geometry.get("unplaced_objects", [])) != 1 or len(geometry.get("architecture", {}).get("wall_polygons_gu", [])) != 6 or len(volumes) != 11 or len(face_ids) != 22 or len(apertures) != 11 or sum(item.get("type") == "window" for item in apertures if isinstance(item, dict)) != 4 or sum(item.get("type") == "door" for item in apertures if isinstance(item, dict)) != 7:
        errors.append(Diagnostic("inventory.accepted", "scene", "accepted inventory mismatch"))
    if errors:
        raise ContractError(errors)


def _validate_visibility(visibility: dict[str, Any], walls: set[str], faces: set[str], apertures: set[str], errors: list[Diagnostic]) -> None:
    direction = visibility.get("accepted_direction", {})
    c, global_cutaway = direction.get("bedroom_front_wall", {}), direction.get("global_cutaway", {})
    for field, values, known in (("target_wall_ids", global_cutaway.get("target_wall_ids", []), walls), ("target_face_ids", global_cutaway.get("target_face_ids", []), faces), ("excluded_wall_ids", global_cutaway.get("excluded_wall_ids", []), walls), ("excluded_wall_ids", c.get("excluded_wall_ids", []), walls), ("excluded_aperture_ids", c.get("excluded_aperture_ids", []), apertures)):
        if not isinstance(values, list) or not set(values).issubset(known):
            errors.append(Diagnostic("visibility.reference", "visibility." + field, "unknown referenced stable ID"))
    if c.get("target_wall_id") not in walls or c.get("target_face_id") not in faces:
        errors.append(Diagnostic("visibility.target", "visibility.bedroom_front_wall", "unknown treatment target"))
    if any("zone" in key.lower() or "coordinate" in key.lower() for key in c):
        errors.append(Diagnostic("visibility.coordinate_inference", "visibility.bedroom_front_wall", "treatments must select named IDs, never coordinate zones"))
    forbidden = {"bedroom_door.jambs_or_posts", "bedroom_door.corners", "bedroom_door.lintel", "bedroom_door.threshold"}
    if not forbidden.issubset(set(c.get("opaque_architecture", []))) or "wall_volume.bedroom_living.projector_divider" not in set(c.get("excluded_wall_ids", [])) or "wall_volume.bedroom.bath_hall_boundary" not in set(c.get("excluded_wall_ids", [])):
        errors.append(Diagnostic("visibility.treatment_c", "visibility.bedroom_front_wall", "treatment C leaks into excluded architecture"))


def validate_scene(scene: SemanticSceneV1) -> None:
    """Validate the actual compiler-emitted assembly inventory, not source guesses."""
    errors: list[Diagnostic] = []
    scene_data = scene.to_dict()
    object_ids = _ids(scene_data["objects"], "scene.objects", errors)
    assemblies = scene_data["assemblies"]
    assembly_ids = _ids(assemblies, "scene.assemblies", errors)
    expected = {
        "assembly.bed": (("bedroom.bed",), {"base", "mattress", "headboard", "exactly_two_pillows"}, set()),
        "assembly.workstation": (("bedroom.desk_main", "bedroom.desk_return", "bedroom.chair", "bedroom.monitor", "bedroom.pc", "bedroom.projector"), set(), {"pc_under_opposite_left_desk_side", "projector_on_desk_return"}),
        "assembly.shower": (("bath.shower",), {"tray", "named_enclosure", "glass_front_role", "opaque_fixed_side_back_roles"}, set()),
        "assembly.vanity": (("bath.vanity",), {"visible_basin", "upright_back_side_faucet_facing_basin"}, set()),
        "assembly.toilet": (("bath.toilet",), {"tank", "pedestal", "bowl"}, set()),
        "assembly.laundry": (("service.laundry",), {"washer", "dryer", "arrangement_provisional", "form_factor_provisional"}, set()),
        "assembly.cooking": (("kitchen.stove", "kitchen.microwave"), set(), {"microwave_above_stove_oven"}),
        "assembly.kitchen_pendants": (("kitchen.pendant_1", "kitchen.pendant_2"), {"exactly_two", "suspended", "island_thirds"}, set()),
    }
    if assembly_ids != set(expected):
        errors.append(Diagnostic("assembly.inventory", "scene.assemblies", "required stable assembly inventory mismatch"))
    for index, assembly in enumerate(assemblies if isinstance(assemblies, list) else []):
        if not isinstance(assembly, dict) or not isinstance(assembly.get("id"), str):
            continue
        required = expected.get(assembly["id"])
        members = assembly.get("members", [])
        if not isinstance(members, list) or not all(isinstance(member, str) and member in object_ids for member in members):
            errors.append(Diagnostic("assembly.member", f"scene.assemblies[{index}].members", "members must resolve to scene objects"))
            continue
        if required and (Counter(members) != Counter(required[0]) or not required[1].issubset(set(assembly.get("requirements", []))) or not required[2].issubset(set(assembly.get("relationships", [])))):
            errors.append(Diagnostic("assembly.required", f"scene.assemblies[{index}]", "required semantic members or relationships missing"))
    pendants = next((item for item in assemblies if isinstance(item, dict) and item.get("id") == "assembly.kitchen_pendants"), {})
    if len(pendants.get("members", [])) != 2:
        errors.append(Diagnostic("assembly.pendants", "scene.assemblies", "exactly two accepted kitchen pendants required"))
    if errors:
        raise ContractError(errors)
