"""ArchitectureTopology Slice 1: exact derived wall-body planar topology.

This intentionally stops before semantic faces, apertures, z, extrusion, or
render geometry.  The only physical owner emitted here is ``wall_body.apartment``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cmp_to_key
from hashlib import sha256
import json
from itertools import combinations
from decimal import Decimal
from typing import Any, Iterable

from .contracts import ContractBundle, ContractError, Diagnostic, canonical_json
from .compiler import canonical_scene_json, compile_scene
from .exact_geometry import (
    ExactGeometryError, Point, classify_segments, interior_witness, point_in_contours_parity,
    on_segment, point_in_ring, segment_parameter, shoelace,
)
from .models import SemanticSceneV1, deep_freeze, deep_thaw
from .topology_authority import TopologyAuthorityV1, validate_topology_authority
from .validation import validate_scene


ALGORITHM_ID = "homehub.architecture-topology.slice-1.exact-arrangement.v1"


class ArchitectureTopologyError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSegment:
    stable_id: str
    contour_id: str
    index: int
    start: Point
    end: Point


@dataclass(frozen=True)
class AtomicEdge:
    key: tuple[Point, Point]
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class Arrangement:
    contours: tuple[tuple[Point, ...], ...]
    source_segments: tuple[SourceSegment, ...]
    vertices: tuple[Point, ...]
    edges: tuple[AtomicEdge, ...]
    faces: tuple[tuple[Point, ...], ...]
    face_edges: tuple[tuple[tuple[Point, Point], ...], ...]
    crossings: tuple[tuple[str, str, Point], ...]


def _segment_id(contour_id: str, index: int) -> str:
    return f"{contour_id}.segment.s{index + 1:03d}"


def _pair(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def _same_adjacent(first: SourceSegment, second: SourceSegment, size: int) -> bool:
    return first.contour_id == second.contour_id and (
        abs(first.index - second.index) == 1 or {first.index, second.index} == {0, size - 1}
    )


def _direction_compare(origin: Point, first: Point, second: Point) -> int:
    """Exact polar order; direction ties intentionally use point order only."""
    ax, ay = first.x - origin.x, first.y - origin.y
    bx, by = second.x - origin.x, second.y - origin.y
    ah = 0 if (ay > 0 or (ay == 0 and ax >= 0)) else 1
    bh = 0 if (by > 0 or (by == 0 and bx >= 0)) else 1
    if ah != bh:
        return -1 if ah < bh else 1
    determinant = ax * by - ay * bx
    if determinant:
        return -1 if determinant > 0 else 1
    return -1 if first < second else (1 if first > second else 0)


def _canonical_ring(ring: Iterable[Point], positive: bool) -> tuple[Point, ...]:
    result = tuple(ring)
    if (shoelace(result) > 0) != positive:
        result = tuple(reversed(result))
    least = min(range(len(result)), key=lambda index: result[index])
    return result[least:] + result[:least]


def _as_contours(values: Iterable[tuple[str, Iterable[Any]]]) -> tuple[tuple[str, tuple[Point, ...]], ...]:
    output = []
    for contour_id, raw_points in values:
        points = tuple(Point.from_value(point) for point in raw_points)
        if len(points) < 3 or len(set(points)) < 3:
            raise ArchitectureTopologyError(f"{contour_id}: invalid contour")
        output.append((contour_id, points))
    return tuple(output)


def build_arrangement(
    contour_values: Iterable[tuple[str, Iterable[Any]]], *, allowed_proper: Iterable[tuple[str, str]] = (), strict_contacts: bool = False
) -> Arrangement:
    """Node contours exactly and extract all directed face circuits.

    With ``strict_contacts`` this is the fail-closed authority arrangement:
    only ordinary same-contour adjacency and the supplied proper crossings can
    occur.  Synthetic tests can use the general noder without that policy.
    """
    named_contours = _as_contours(contour_values)
    source = tuple(
        SourceSegment(_segment_id(contour_id, index), contour_id, index, point, points[(index + 1) % len(points)])
        for contour_id, points in named_contours
        for index, point in enumerate(points)
    )
    allowed = {tuple(sorted(pair)) for pair in allowed_proper}
    parameters: dict[str, set[Point]] = {segment.stable_id: {segment.start, segment.end} for segment in source}
    crossings: list[tuple[str, str, Point]] = []
    sizes = {contour_id: len(points) for contour_id, points in named_contours}
    for first, second in combinations(source, 2):
        relation = classify_segments(first.start, first.end, second.start, second.end)
        if relation.kind == "disjoint" or _same_adjacent(first, second, sizes[first.contour_id]):
            continue
        pair = _pair(first.stable_id, second.stable_id)
        if strict_contacts and (relation.kind != "proper" or pair not in allowed):
            raise ArchitectureTopologyError(f"unexpected source {relation.kind}: {pair[0]} / {pair[1]}")
        if strict_contacts and relation.kind == "proper" and pair not in allowed:
            raise ArchitectureTopologyError(f"unexpected source proper crossing: {pair[0]} / {pair[1]}")
        if relation.kind == "proper":
            assert relation.point is not None
            parameters[first.stable_id].add(relation.point)
            parameters[second.stable_id].add(relation.point)
            crossings.append((pair[0], pair[1], relation.point))
        elif relation.kind == "contact":
            assert relation.point is not None
            parameters[first.stable_id].add(relation.point)
            parameters[second.stable_id].add(relation.point)
        elif relation.kind == "overlap":
            if strict_contacts:
                raise ArchitectureTopologyError(f"unexpected source collinear overlap: {pair[0]} / {pair[1]}")
            # Generic synthetic arrangements may use a shared edge to prove
            # dissolution.  Noding every endpoint on the opposite segment is
            # exact and creates one atomic edge with both provenances.
            for point in (first.start, first.end):
                if on_segment(point, second.start, second.end) and point != second.start and point != second.end:
                    parameters[second.stable_id].add(point)
            for point in (second.start, second.end):
                if on_segment(point, first.start, first.end) and point != first.start and point != first.end:
                    parameters[first.stable_id].add(point)
    if strict_contacts and {pair[:2] for pair in crossings} != allowed:
        raise ArchitectureTopologyError("accepted proper-crossing inventory does not match authority allowlist")
    edge_provenance: dict[tuple[Point, Point], set[str]] = defaultdict(set)
    for segment in source:
        nodes = sorted(parameters[segment.stable_id], key=lambda point: segment_parameter(point, segment.start, segment.end))
        for first, second in zip(nodes, nodes[1:]):
            if first == second:
                continue
            edge_provenance[tuple(sorted((first, second)))].add(segment.stable_id)
    edges = tuple(AtomicEdge(key, tuple(sorted(provenance))) for key, provenance in sorted(edge_provenance.items()))
    vertices = tuple(sorted({point for edge in edges for point in edge.key}))
    faces, face_edges = _extract_faces(edges)
    return Arrangement(
        tuple(points for _, points in named_contours), source, vertices, edges,
        tuple(faces), tuple(face_edges), tuple(sorted(crossings)),
    )


def _extract_faces(edges: Iterable[AtomicEdge]) -> tuple[list[tuple[Point, ...]], list[tuple[tuple[Point, Point], ...]]]:
    outgoing: dict[Point, list[Point]] = defaultdict(list)
    for edge in edges:
        first, second = edge.key
        outgoing[first].append(second)
        outgoing[second].append(first)
    for point, targets in outgoing.items():
        targets.sort(key=cmp_to_key(lambda first, second: _direction_compare(point, first, second)))
    visited: set[tuple[Point, Point]] = set()
    faces: list[tuple[Point, ...]] = []
    face_edges: list[tuple[tuple[Point, Point], ...]] = []
    for start in sorted((source, target) for source, targets in outgoing.items() for target in targets):
        if start in visited:
            continue
        current = start
        boundary: list[tuple[Point, Point]] = []
        while current not in visited:
            visited.add(current)
            source, target = current
            boundary.append(current)
            targets = outgoing[target]
            reverse_index = targets.index(source)
            # predecessor of the reverse half-edge: the face on the left of this arc.
            current = (target, targets[(reverse_index - 1) % len(targets)])
        if current != start:
            raise ArchitectureTopologyError("half-edge traversal entered a previous face")
        ring = tuple(source for source, _ in boundary)
        if shoelace(ring) != 0:
            faces.append(ring)
            face_edges.append(tuple(boundary))
    return faces, face_edges


def _retained_faces(arrangement: Arrangement) -> list[int]:
    # With the stated predecessor rule bounded cells have positive y-down area.
    selected = []
    for index, ring in enumerate(arrangement.faces):
        if shoelace(ring) > 0 and point_in_contours_parity(_face_witness(ring, arrangement.vertices), arrangement.contours):
            selected.append(index)
    return selected


def _face_witness(ring: tuple[Point, ...], vertices: Iterable[Point]) -> Point:
    """A ring witness refined by every arrangement ordinate.

    A disconnected nested boundary can sit inside an otherwise simple face
    circuit.  Its vertices must split the scan slabs too, otherwise a valid
    ring witness could land in the wrong global planar cell.
    """
    ys = sorted({point.y for point in vertices})
    for low, high in zip(ys, ys[1:]):
        y = (low + high) / 2
        xs = sorted(
            first.x + (y - first.y) * (second.x - first.x) / (second.y - first.y)
            for first, second in zip(ring, ring[1:] + ring[:1])
            if (first.y > y) != (second.y > y)
        )
        for left, right in zip(xs[::2], xs[1::2]):
            candidate = Point((left + right) / 2, y)
            if point_in_ring(candidate, ring):
                return candidate
    raise ArchitectureTopologyError("could not construct an exact face witness")


def _dissolved_rings(arrangement: Arrangement, retained: Iterable[int]) -> tuple[tuple[Point, ...], ...]:
    retained_set = set(retained)
    incidents: dict[tuple[Point, Point], list[int]] = defaultdict(list)
    directed: set[tuple[Point, Point]] = set()
    for face_index, arcs in enumerate(arrangement.face_edges):
        for arc in arcs:
            incidents[tuple(sorted(arc))].append(face_index)
        if face_index in retained_set:
            directed.update(arcs)
    removed_internal = False
    for key, incident_faces in incidents.items():
        if len(set(incident_faces) & retained_set) == 2:
            removed_internal = True
            first, second = key
            directed.discard((first, second))
            directed.discard((second, first))
    # This fast path is also semantically important: at a point touch two
    # independent retained cells share a vertex but not an edge, and must not
    # be stitched into one component merely because the graph is connected.
    if not removed_internal:
        return tuple(arrangement.faces[index] for index in retained_set)
    outgoing: dict[Point, list[Point]] = defaultdict(list)
    for first, second in directed:
        outgoing[first].append(second)
    for point, targets in outgoing.items():
        targets.sort(key=cmp_to_key(lambda first, second: _direction_compare(point, first, second)))
    walked: set[tuple[Point, Point]] = set()
    rings: list[tuple[Point, ...]] = []
    for start in sorted(directed):
        if start in walked:
            continue
        arc, arcs = start, []
        while arc not in walked:
            walked.add(arc)
            arcs.append(arc)
            first, target = arc
            targets = outgoing[target]
            reverse_index = targets.index(first) if first in targets else None
            if reverse_index is None:
                # At a dissolved junction the reverse is absent: choose the first
                # clockwise candidate after its exact geometric direction.
                ordered = sorted(targets, key=cmp_to_key(lambda a, b: _direction_compare(target, a, b)))
                incoming = Point(target.x - first.x, target.y - first.y)
                def compare_to_incoming(candidate: Point) -> int:
                    return _direction_compare(target, candidate, Point(target.x + incoming.x, target.y + incoming.y))
                candidates = [candidate for candidate in ordered if compare_to_incoming(candidate) < 0]
                next_target = candidates[-1] if candidates else ordered[-1]
            else:
                next_target = targets[(reverse_index - 1) % len(targets)]
            arc = (target, next_target)
        if arc != start:
            raise ArchitectureTopologyError("dissolved boundary does not close")
        ring = tuple(first for first, _ in arcs)
        if shoelace(ring):
            rings.append(ring)
    return tuple(rings)


def _provenance_for_ring(ring: tuple[Point, ...], edges: Iterable[AtomicEdge]) -> list[dict[str, Any]]:
    by_key = {edge.key: edge for edge in edges}
    return [
        {"edge": [first.to_tokens(), second.to_tokens()], "source_segments": list(by_key[tuple(sorted((first, second)))].provenance)}
        for first, second in zip(ring, ring[1:] + ring[:1])
    ]


def _identifier(prefix: str, geometry: Any, provenance: Any) -> str:
    content = canonical_json({"geometry": geometry, "provenance": provenance})
    return f"{prefix}.{sha256(content.encode('utf-8')).hexdigest()[:20]}"


def derive_wall_body_polygons(arrangement: Arrangement) -> list[dict[str, Any]]:
    """Turn retained exact cells into canonical dissolved owner polygons.

    Kept public to the package as the intentionally narrow Slice 1 handoff for
    synthetic and later Slice 2 consumers; it has no semantic-face contract.
    """
    retained = _retained_faces(arrangement)
    rings = _dissolved_rings(arrangement, retained)
    samples: dict[tuple[Point, ...], Point] = {
        arrangement.faces[index]: _face_witness(arrangement.faces[index], arrangement.vertices)
        for index in retained
        if arrangement.faces[index] in rings
    }
    # Face walks of disconnected components represent the annulus' inner
    # boundary as a separate clockwise circuit rather than a multi-boundary
    # face.  Reattach exactly those even interiors enclosed by a retained cell
    # as holes.  This is topological containment, not a geometric repair.
    retained_rings = tuple(arrangement.faces[index] for index in retained)
    for index, candidate in enumerate(arrangement.faces):
        if index in retained or shoelace(candidate) <= 0:
            continue
        witness = _face_witness(candidate, arrangement.vertices)
        if not point_in_contours_parity(witness, arrangement.contours) and any(
            point_in_ring(witness, ring) for ring in retained_rings
        ):
            rings += (candidate,)
            samples[candidate] = witness
    ring_infos = []
    for ring in rings:
        witness = samples.get(ring, interior_witness(ring))
        depth = sum(point_in_ring(witness, other) for other in rings if other != ring)
        outer = depth % 2 == 0
        canonical = _canonical_ring(ring, outer)
        geometry = [point.to_tokens() for point in canonical]
        provenance = _provenance_for_ring(canonical, arrangement.edges)
        ring_infos.append({"outer": outer, "ring": geometry, "provenance": provenance})
    outer_infos = sorted((info for info in ring_infos if info["outer"]), key=lambda info: info["ring"])
    hole_infos = [info for info in ring_infos if not info["outer"]]
    polygons = []
    for outer in outer_infos:
        outer_points = tuple(Point.from_value(point) for point in outer["ring"])
        holes = sorted(
            (hole for hole in hole_infos if point_in_ring(interior_witness(tuple(Point.from_value(p) for p in hole["ring"])), outer_points)),
            key=lambda info: info["ring"],
        )
        geometry = {"outer": outer["ring"], "holes": [hole["ring"] for hole in holes]}
        provenance = {"outer": outer["provenance"], "holes": [hole["provenance"] for hole in holes]}
        polygons.append({"id": _identifier("wall_body.apartment.polygon", geometry, provenance), **geometry, "provenance": provenance})
    return polygons


def semantic_scene_fingerprint(scene: SemanticSceneV1) -> str:
    """Return the SHA-256 of the canonical SemanticSceneV1 serialization."""
    return sha256(canonical_scene_json(scene).rstrip("\n").encode("utf-8")).hexdigest()


def _canonical_decimal_data(value: Any) -> Any:
    """Round-trip canonical JSON so topology ingests Decimal numeric tokens only."""
    return json.loads(
        canonical_json(value), parse_float=Decimal, parse_int=Decimal,
    )


def _validated_scene_contours(
    scene: SemanticSceneV1, authority: TopologyAuthorityV1, bundle: ContractBundle,
) -> tuple[list[Any], list[Any], str]:
    """Validate the SemanticScene authority and return its exact wall contours.

    The bundle is strictly subordinate source material: it revalidates the
    authority document and its pointers, while the actual topology coordinates
    are read from the canonical SemanticScene serialization.
    """
    if not isinstance(scene, SemanticSceneV1):
        raise ArchitectureTopologyError("SemanticSceneV1 is required")
    if scene.schema != "homehub.apartment-semantic-scene.v1":
        raise ArchitectureTopologyError("SemanticSceneV1 schema is incompatible")
    try:
        validate_scene(scene)
        validate_topology_authority(deep_thaw(authority.document), bundle)
    except ContractError as exc:
        raise ArchitectureTopologyError(f"accepted authority revalidation failed: {exc}") from exc
    document = deep_thaw(authority.document)
    if authority.fingerprint != document_fingerprint(document):
        raise ArchitectureTopologyError("TopologyAuthorityV1 hash drift")

    scene_data = json.loads(
        canonical_scene_json(scene), parse_float=Decimal, parse_int=Decimal,
    )
    expected_scene = compile_scene(bundle)
    scene_sha256 = semantic_scene_fingerprint(scene)
    if scene_sha256 != semantic_scene_fingerprint(expected_scene):
        raise ArchitectureTopologyError("SemanticSceneV1 canonical fingerprint is incompatible")

    scene_manifest = scene_data.get("source_manifest")
    authority_manifest = deep_thaw(authority.source_manifest)
    document_manifest = document.get("semantic_source_manifest")
    expected_manifest = [
        {"id": item["id"], "schema": item["schema"], "sha256": item["sha256"]}
        for item in bundle.source_manifest
    ]
    if (
        not isinstance(scene_manifest, list)
        or not scene_manifest
        or scene_manifest != authority_manifest
        or scene_manifest != document_manifest
        or scene_manifest != expected_manifest
    ):
        raise ArchitectureTopologyError("SemanticSceneV1 and TopologyAuthorityV1 source manifests are incompatible")

    try:
        scene_contours = scene_data["architecture"]["wall_contours_gu"]
        source_geometry = _canonical_decimal_data(deep_thaw(bundle.raw_documents)["geometry_v1.json"])
        source_contours = source_geometry["architecture"]["wall_polygons_gu"]
    except (KeyError, TypeError) as exc:
        raise ArchitectureTopologyError("SemanticSceneV1 wall contour source is malformed") from exc
    bindings = document["wall_body"]["contours"]
    if len(scene_contours) != len(bindings) or len(source_contours) != len(bindings):
        raise ArchitectureTopologyError("SemanticSceneV1 wall contour inventory is incompatible")
    for index, binding in enumerate(bindings):
        if scene_contours[index] != source_contours[index]:
            raise ArchitectureTopologyError(f"SemanticSceneV1 contour {binding['id']} does not match its source binding")
    return scene_contours, bindings, scene_sha256


def compile_wall_body_slice1(
    scene: SemanticSceneV1, authority: TopologyAuthorityV1, bundle: ContractBundle,
) -> dict[str, Any]:
    """Compile the incomplete-but-explicit Slice 1 wall-body internal result."""
    document = deep_thaw(authority.document)
    contours, bindings, scene_sha256 = _validated_scene_contours(scene, authority, bundle)
    contour_values = tuple((binding["id"], contours[index]) for index, binding in enumerate(bindings))
    allowlist = tuple(tuple(item["segment_refs"]) for item in document["wall_body"]["accepted_proper_self_crossings"])
    arrangement = build_arrangement(contour_values, allowed_proper=allowlist, strict_contacts=True)
    polygons = derive_wall_body_polygons(arrangement)
    result = {
        "schema": "homehub.architecture-wall-topology.slice-1.v1",
        "algorithm": ALGORITHM_ID,
        "status": "derived_wall_body_only",
        "provenance": {
            "semantic_scene_schema": scene.schema,
            "semantic_scene_sha256": scene_sha256,
            "semantic_source_manifest": scene.to_dict()["source_manifest"],
            "topology_authority_schema": authority.schema,
            "topology_authority_sha256": authority.fingerprint,
        },
        "arrangement_audit": {
            "source_segments": len(arrangement.source_segments), "noded_vertices": len(arrangement.vertices),
            "atomic_edges": len(arrangement.edges),
            "proper_crossings": [
                {"segments": [first, second], "point": point.to_tokens()} for first, second, point in arrangement.crossings
            ],
            "bounded_odd_cells": len(_retained_faces(arrangement)),
        },
        "wall_body": {"id": "wall_body.apartment", "physical_owner_count": 1, "polygons": polygons},
    }
    return json.loads(canonical_json(result))


def document_fingerprint(document: Any) -> str:
    return sha256(canonical_json(document).encode("utf-8")).hexdigest()
