"""Deterministic, non-meshing validation for TopologyAuthorityV1.

This module intentionally stops before planar arrangement, wall-band resolution,
or any renderer geometry.  It protects the accepted physical-XY inputs those
later stages will consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import json
import math
from pathlib import Path
from typing import Any

from .contracts import (
    ContractBundle,
    ContractDescriptor,
    ContractError,
    Diagnostic,
    fingerprint,
    load_contracts,
)
from .models import deep_freeze, deep_thaw


TOPOLOGY_AUTHORITY_DESCRIPTOR = ContractDescriptor(
    "topology_authority_v1.json",
    "homehub.apartment-topology-authority.v1",
    "accepted_physical_xy_topology_authority",
    "780a945140fdde74b8efa39078f8ef93315a3548e40dc0eaec196ed2ecc8c3f5",
)


@dataclass(frozen=True)
class TopologyAuthorityV1:
    schema: str
    status: str
    document: Any
    source_manifest: tuple[Any, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return deep_thaw(self.document)


@dataclass(frozen=True)
class _ContourSegment:
    contour_id: str
    index: int
    start: list[float]
    end: list[float]

    @property
    def stable_id(self) -> str:
        return _segment_name(self.contour_id, self.index)


def _default_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "docs/dashboard/apartment_canvas"


def _point(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in value
        )
    )


def _cross(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p: list[float], a: list[float], b: list[float]) -> bool:
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _proper_cross(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return (ab_c > 0) != (ab_d > 0) and (cd_a > 0) != (cd_b > 0)


def _positive_collinear_overlap(
    a: list[float], b: list[float], c: list[float], d: list[float]
) -> bool:
    if _cross(a, b, c) != 0 or _cross(a, b, d) != 0:
        return False
    return max(min(a[0], b[0]), min(c[0], d[0])) < min(max(a[0], b[0]), max(c[0], d[0])) or max(
        min(a[1], b[1]), min(c[1], d[1])
    ) < min(max(a[1], b[1]), max(c[1], d[1]))


def _ring_area(ring: list[list[float]]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) / 2


def _strictly_inside(point: list[float], ring: list[list[float]]) -> bool:
    if any(_on_segment(point, a, b) for a, b in zip(ring, ring[1:])):
        return False
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]
            if x > point[0]:
                inside = not inside
    return inside


def _positive_area_overlap(first: list[list[float]], second: list[list[float]]) -> bool:
    return (
        any(
            _proper_cross(a, b, c, d)
            for a, b in zip(first, first[1:])
            for c, d in zip(second, second[1:])
        )
        or _strictly_inside(first[0], second)
        or _strictly_inside(second[0], first)
    )


def _validate_ring(ring: Any, path: str, errors: list[Diagnostic]) -> None:
    if (
        not isinstance(ring, list)
        or len(ring) < 4
        or not all(_point(p) for p in ring)
        or ring[0] != ring[-1]
    ):
        errors.append(Diagnostic("topology.ring", path, "must be a closed finite coordinate ring"))
        return
    if _ring_area(ring) == 0:
        errors.append(Diagnostic("topology.ring_area", path, "must have non-zero area"))
    edges = list(zip(ring, ring[1:]))
    for index, (a, b) in enumerate(edges):
        if a == b:
            errors.append(
                Diagnostic("topology.zero_length", f"{path}[{index}]", "zero-length edge")
            )
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if (
                _proper_cross(a, b, c, d)
                or _positive_collinear_overlap(a, b, c, d)
                or any(_on_segment(p, a, b) for p in (c, d))
                or any(_on_segment(p, c, d) for p in (a, b))
            ):
                errors.append(
                    Diagnostic(
                        "topology.ring_intersection",
                        path,
                        "ring has a non-adjacent intersection/contact",
                    )
                )


def _segment_name(contour_id: str, index: int) -> str:
    return f"{contour_id}.segment.s{index + 1:03d}"


def _same_contour_adjacent(first: _ContourSegment, second: _ContourSegment, size: int) -> bool:
    return first.contour_id == second.contour_id and (
        abs(first.index - second.index) == 1
        or {first.index, second.index} == {0, size - 1}
    )


def _validate_contours(contours: list[Any], allowlist: Any, errors: list[Diagnostic]) -> None:
    expected = {tuple(sorted(("wall.contour.c002.segment.s003", "wall.contour.c002.segment.s005")))}
    actual_allow = set()
    if isinstance(allowlist, list):
        for item in allowlist:
            pair = item.get("segment_refs") if isinstance(item, dict) else None
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, str) for v in pair):
                actual_allow.add(tuple(sorted(pair)))
    if actual_allow != expected:
        errors.append(
            Diagnostic(
                "topology.crossing_allowlist",
                "wall_body.accepted_proper_self_crossings",
                "must freeze exactly c002 s003/s005",
            )
        )
    seen_contours: set[str] = set()
    seen_edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    observed_proper_crossings: set[tuple[str, str]] = set()
    inventory: list[_ContourSegment] = []
    contour_sizes: dict[str, int] = {}
    for contour_index, contour in enumerate(contours):
        if not isinstance(contour, dict):
            continue
        cid, vertices = contour.get("id"), contour.get("vertices")
        if not isinstance(cid, str) or not isinstance(vertices, list):
            continue
        normalized = tuple(tuple(p) for p in vertices) if all(_point(p) for p in vertices) else ()
        reverse = tuple(reversed(normalized))
        if normalized in seen_contours or reverse in seen_contours:
            errors.append(
                Diagnostic(
                    "topology.duplicate_contour",
                    f"wall_body.contours[{contour_index}]",
                    "duplicate or reversed contour",
                )
            )
        seen_contours.add(normalized)
        segments = (
            list(zip(vertices, vertices[1:] + vertices[:1])) if isinstance(vertices, list) else []
        )
        contour_sizes[cid] = len(segments)
        for i, (a, b) in enumerate(segments):
            if not _point(a) or not _point(b) or a == b:
                errors.append(
                    Diagnostic(
                        "topology.segment",
                        _segment_name(cid or "unknown", i),
                        "segment must be finite and non-zero",
                    )
                )
                continue
            key = tuple(sorted((tuple(a), tuple(b))))
            if key in seen_edges:
                errors.append(
                    Diagnostic(
                        "topology.duplicate_edge",
                        _segment_name(cid, i),
                        "duplicate or reversed edge",
                    )
                )
            seen_edges.add(key)
            inventory.append(_ContourSegment(cid, i, a, b))
    for first, second in combinations(inventory, 2):
        if _same_contour_adjacent(first, second, contour_sizes[first.contour_id]):
            continue
        a, b, c, d = first.start, first.end, second.start, second.end
        pair = tuple(sorted((first.stable_id, second.stable_id)))
        path = ",".join(pair)
        cross_contour = first.contour_id != second.contour_id
        if _positive_collinear_overlap(a, b, c, d):
            errors.append(
                Diagnostic("topology.collinear_overlap", path, "positive-length collinear overlap")
            )
        if _proper_cross(a, b, c, d):
            if not cross_contour:
                observed_proper_crossings.add(pair)
            if cross_contour or pair not in expected:
                errors.append(
                    Diagnostic(
                        "topology.cross_contour_intersection"
                        if cross_contour
                        else "topology.self_crossing",
                        path,
                        "forbidden proper crossing",
                    )
                )
        elif any(_on_segment(p, a, b) for p in (c, d)) or any(
            _on_segment(p, c, d) for p in (a, b)
        ):
            errors.append(
                Diagnostic(
                    "topology.cross_contour_contact" if cross_contour else "topology.contact",
                    path,
                    "unlisted endpoint-on-segment contact",
                )
            )
    if observed_proper_crossings != expected:
        errors.append(
            Diagnostic(
                "topology.crossing_observation",
                "wall_body.accepted_proper_self_crossings",
                "source must contain exactly the frozen proper crossing pair",
            )
        )


def validate_topology_authority(document: dict[str, Any], bundle: ContractBundle) -> None:
    errors: list[Diagnostic] = []
    if (
        document.get("schema") != TOPOLOGY_AUTHORITY_DESCRIPTOR.schema
        or document.get("status") != TOPOLOGY_AUTHORITY_DESCRIPTOR.status
    ):
        errors.append(Diagnostic("topology.identity", "topology", "wrong schema or status"))
    sources = document.get("semantic_source_manifest")
    expected_manifest = [
        {"id": item["id"], "schema": item["schema"], "sha256": item["sha256"]}
        for item in bundle.source_manifest
    ]
    if sources != expected_manifest:
        errors.append(
            Diagnostic(
                "topology.source_manifest",
                "semantic_source_manifest",
                "must bind exact six semantic sources",
            )
        )
    slab = document.get("apartment_slab")
    if (
        not isinstance(slab, dict)
        or slab.get("id") != "slab.apartment"
        or slab.get("balcony_reference")
        != "geometry_v1_6_patch.json#/contract_amendments/balcony_semantics/ring_gu"
        or "balcony_ring_gu" in (slab or {})
    ):
        errors.append(
            Diagnostic(
                "topology.slab",
                "apartment_slab",
                "one continuous slab must reference, not copy, balcony authority",
            )
        )
    else:
        _validate_ring(slab.get("ring_gu"), "apartment_slab.ring_gu", errors)
        frozen = [
            [1.63, 46.38],
            [440.20, 46.38],
            [440.20, 214.81],
            [440.20, 222.13],
            [441.01, 222.13],
            [996.75, 222.13],
            [996.75, 1243.29],
            [999.19, 1244.10],
            [999.19, 1256.31],
            [997.56, 1257.12],
            [997.56, 1262.82],
            [1.63, 1262.82],
            [1.63, 1126.93],
            [0.00, 1124.49],
            [1.63, 1123.68],
            [1.63, 104.96],
            [0.00, 85.44],
            [1.63, 78.11],
            [1.63, 46.38],
        ]
        if slab.get("ring_gu") != frozen:
            errors.append(
                Diagnostic(
                    "topology.slab_frozen",
                    "apartment_slab.ring_gu",
                    "accepted slab footprint changed",
                )
            )
        balcony = deep_thaw(bundle.patch)["contract_amendments"]["balcony_semantics"]["ring_gu"]
        if _positive_area_overlap(slab.get("ring_gu", []), balcony):
            errors.append(
                Diagnostic(
                    "topology.balcony_overlap",
                    "apartment_slab",
                    "apartment and balcony may not have positive-area overlap",
                )
            )
    derived = document.get("derived_junctions", [])
    if not isinstance(derived, list) or len(derived) != 1 or not isinstance(derived[0], dict):
        errors.append(
            Diagnostic("topology.derived", "derived_junctions", "required derived junction missing")
        )
    else:
        d = derived[0]
        geometry, patch = deep_thaw(bundle.geometry), deep_thaw(bundle.patch)
        try:
            vertical = geometry["architecture"]["wall_polygons_gu"][3][16:18]
            horizontal = next(
                x["points"]
                for x in patch["contract_amendments"]["semantic_wall_edges_gu"]
                if x["id"] == "wall.living.balcony_north"
            )
            vertical_source = "geometry_v1.json#/architecture/wall_polygons_gu/3/16:18"
            horizontal_source = (
                "geometry_v1_6_patch.json#/contract_amendments/semantic_wall_edges_gu/"
                "wall.living.balcony_north/points/0"
            )
            valid_support_lines = (
                len(vertical) == 2
                and len(horizontal) == 2
                and all(_point(p) for p in vertical + horizontal)
                and vertical[0][0] == vertical[1][0]
                and vertical[0][1] != vertical[1][1]
                and horizontal[0][1] == horizontal[1][1]
                and horizontal[0][0] != horizontal[1][0]
            )
            point = [vertical[0][0], horizontal[0][1]] if valid_support_lines else None
            expected_point = [440.20, 222.13]
            if (
                d.get("id") != "junction.apartment.bedroom_living_balcony"
                or d.get("point_gu") != point
                or point != expected_point
                or d.get("derivation") != "intersection_of_support_lines"
                or d.get("vertical_source") != vertical_source
                or d.get("horizontal_source") != horizontal_source
            ):
                errors.append(
                    Diagnostic(
                        "topology.derived",
                        "derived_junctions[0]",
                        "frozen provenance or recomputed support-line intersection changed",
                    )
                )
        except (IndexError, KeyError, StopIteration, TypeError):
            errors.append(
                Diagnostic(
                    "topology.derived_source", "derived_junctions[0]", "source binding malformed"
                )
            )
    wall = document.get("wall_body")
    if (
        not isinstance(wall, dict)
        or wall.get("id") != "wall_body.apartment"
        or wall.get("fill_rule") != "even_odd"
        or wall.get("retain_odd_cells") is not True
        or wall.get("dissolve_internal_boundaries") is not True
        or wall.get("physical_owner_count") != 1
        or set(wall)
        != {
            "id",
            "physical_owner_count",
            "fill_rule",
            "retain_odd_cells",
            "dissolve_internal_boundaries",
            "contours",
            "accepted_proper_self_crossings",
        }
    ):
        errors.append(
            Diagnostic(
                "topology.wall_policy",
                "wall_body",
                "requires one dissolved even-odd physical owner",
            )
        )
        wall = {}
    bindings = wall.get("contours", [])
    expected_ids = [f"wall.contour.c{i:03d}" for i in range(1, 7)]
    if (
        not isinstance(bindings, list)
        or [x.get("id") for x in bindings if isinstance(x, dict)] != expected_ids
    ):
        errors.append(
            Diagnostic(
                "topology.contour_bindings",
                "wall_body.contours",
                "six ordered neutral contour bindings required",
            )
        )
    else:
        geometry = deep_thaw(bundle.geometry)["architecture"]["wall_polygons_gu"]
        copied = []
        for i, binding in enumerate(bindings):
            if binding.get(
                "source"
            ) != f"geometry_v1.json#/architecture/wall_polygons_gu/{i}" or binding.get(
                "vertex_sha256"
            ) != fingerprint(geometry[i]):
                errors.append(
                    Diagnostic(
                        "topology.contour_binding",
                        binding.get("id", "unknown"),
                        "pointer or vertex fingerprint changed",
                    )
                )
            copied.append({"id": binding["id"], "vertices": geometry[i]})
        _validate_contours(copied, wall.get("accepted_proper_self_crossings"), errors)
    face_policy, aperture_policy = (
        document.get("semantic_face_resolution"),
        document.get("aperture_resolution"),
    )
    if (
        not isinstance(face_policy, dict)
        or face_policy.get("policy") != "normal_directed_unique_wall_band"
        or face_policy.get("overrides") != []
    ):
        errors.append(
            Diagnostic(
                "topology.face_policy",
                "semantic_face_resolution",
                "v1 requires fail-closed policy and empty overrides",
            )
        )
    if (
        not isinstance(aperture_policy, dict)
        or aperture_policy.get("policy") != "unique_two_jamb_wall_band_traversal"
        or aperture_policy.get("overrides") != []
    ):
        errors.append(
            Diagnostic(
                "topology.aperture_policy",
                "aperture_resolution",
                "v1 requires fail-closed policy and empty overrides",
            )
        )
    if errors:
        raise ContractError(errors)


def load_topology_authority(
    directory: str | Path | None = None,
    *,
    document: dict[str, Any] | None = None,
    bundle: ContractBundle | None = None,
) -> TopologyAuthorityV1:
    directory = Path(directory or _default_directory())
    if document is None:
        try:
            document = json.loads(
                (directory / TOPOLOGY_AUTHORITY_DESCRIPTOR.filename).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(
                [Diagnostic("topology.read", TOPOLOGY_AUTHORITY_DESCRIPTOR.filename, str(exc))]
            ) from exc
    if not isinstance(document, dict):
        raise ContractError(
            [Diagnostic("topology.read", "topology", "required JSON object is missing")]
        )
    if fingerprint(document) != TOPOLOGY_AUTHORITY_DESCRIPTOR.fingerprint:
        raise ContractError(
            [
                Diagnostic(
                    "topology.authority",
                    TOPOLOGY_AUTHORITY_DESCRIPTOR.filename,
                    "canonical accepted authority fingerprint changed",
                )
            ]
        )
    bundle = bundle or load_contracts(directory)
    validate_topology_authority(document, bundle)
    manifest = tuple(
        deep_freeze({"id": item["id"], "schema": item["schema"], "sha256": item["sha256"]})
        for item in bundle.source_manifest
    )
    return TopologyAuthorityV1(
        document["schema"],
        document["status"],
        deep_freeze(document),
        manifest,
        fingerprint(document),
    )
