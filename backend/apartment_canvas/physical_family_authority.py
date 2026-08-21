"""Physical-only authority for exact wall-family continuation across voids.

The authority consumes only the accepted ArchitectureTopology Slice 1 physical
projection.  It deliberately does not compile semantic faces, apertures, Slice
2, reconstruction bands, or render geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from .contracts import ContractError, Diagnostic, canonical_json, fingerprint
from .exact_geometry import ExactGeometryError, Point, rational
from .models import deep_freeze, deep_thaw


AUTHORITY_FILENAME = "physical_family_authority_v1.json"
AUTHORITY_SCHEMA = "homehub.apartment-physical-family-authority.v1"
AUTHORITY_STATUS = "accepted_physical_gap_continuation_authority"
PHYSICAL_SOURCE_SCHEMA = "homehub.architecture-wall-topology.slice-1.physical-subset.v1"
PHYSICAL_SOURCE_SHA256 = "88979801ec535b816be189cf2438bf8feaa474cbb3618b6a24cd9f57ef00a3f8"

_SLICE1_SCHEMA = "homehub.architecture-wall-topology.slice-1.v1"
_SLICE1_ALGORITHM = "homehub.architecture-topology.slice-1.exact-arrangement.v1"
_SLICE1_STATUS = "derived_wall_body_only"

_ALGORITHM = {
    "id": "homehub.apartment-physical-family-preflight.exact-directed-rails.v1",
    "arithmetic": "fractions_only",
    "atom_identity": "maximal_directed_paired_rail_local_continuity_class",
    "directed_orientation": "ordered_tangent_normal_host_opposite",
    "undirected_certificate_expansion": "emit_forward_and_inverse_directed_edges",
}

_PERMITTED_LOCAL_EDGE_CLASSES = [
    "positive_area_strip_adjacency",
    "exact_order_preserving_contour_vertex_continuation",
    "accepted_exact_junction_unique_directed_continuation",
]

_FAIL_CLOSED = [
    "unknown_or_duplicate_certificate_id",
    "physical_source_sha256_mismatch",
    "missing_endpoint_cap_or_atomic_edge",
    "cap_or_germ_provenance_mismatch",
    "degenerate_host_or_opposite_germ",
    "host_opposite_order_mismatch",
    "tangent_or_normal_mismatch",
    "multiple_matching_endpoint_atoms",
    "competing_terminal_or_branch",
    "certificate_would_join_an_already_connected_family",
    "certificate_would_create_positive_area_geometry",
    "requires_tolerance_epsilon_snap_buffer_repair_or_approximation",
]

_AUTHORITY_LIMITATIONS = [
    "metadata_and_continuation_only",
    "never_positive_area_wall",
    "never_alter_slice_1",
    "never_modify_coordinates",
    "never_infer_missing_certificates",
    "never_use_semantic_face_aperture_transition_or_activity_room_identity",
    "never_use_reconstruction_cutter_transition_or_face_output_as_evidence",
    "absence_of_certificate_means_no_gap_edge",
    "no_tolerance_epsilon_snap_repair_or_approximate_adjacency",
]

_ASSERTIONS = {
    "both_endpoint_terminals_exist_exactly_in_accepted_physical_slice_1": True,
    "rail_germs_nonzero": True,
    "no_competing_complete_terminal": True,
    "no_branch_silently_crossed": True,
    "creates_positive_area_wall": False,
}

_TOP_LEVEL_KEYS = {"schema", "status", "identity_payload", "fingerprint"}
_IDENTITY_KEYS = {
    "physical_source",
    "algorithm",
    "permitted_local_edge_classes",
    "gap_continuation_certificates",
    "fail_closed",
    "authority_limitations",
}
_CERTIFICATE_KEYS = {
    "id", "orientation", "endpoint_a", "endpoint_b", "rail_mapping", "assertions",
}
_ENDPOINT_KEYS = {
    "terminal_kind",
    "host_point",
    "opposite_point",
    "cap_path",
    "atomic_cap_edges",
    "host_rail_germ",
    "opposite_rail_germ",
    "wall_body_polygon",
    "accepted_exact_junction",
}
_EDGE_KEYS = {"edge", "source_segments"}
_JUNCTION_KEYS = {"required", "events"}
_EVENT_KEYS = {"kind", "point", "source_segments"}
_RAIL_MAPPING = {
    "host": ["endpoint_a.host", "endpoint_b.host"],
    "opposite": ["endpoint_a.opposite", "endpoint_b.opposite"],
}
_FINGERPRINT = {
    "algorithm": "sha256",
    "canonicalization": "homehub.canonical-json.v1.physical-gap-set.v1",
    "included_projection": "identity_payload",
}

_SOURCE_ID = re.compile(r"wall\.contour\.c\d{3}\.segment\.s\d{3}\Z")
_POLYGON_ID = re.compile(r"wall_body\.apartment\.polygon\.[0-9a-f]{20}\Z")
_CERTIFICATE_ID = re.compile(r"physical_gap\.[0-9a-f]{20}\Z")
_FORBIDDEN_CERTIFICATE_KEYS = {
    "semantic_face_id", "parent_wall_id", "host_face_id", "resolved_face_id",
    "aperture_id", "aperture_type", "transition_id", "room_id", "activity_id",
    "reconstruction_id", "cutter_id", "face_output_id", "audit_label", "label",
}
_FORBIDDEN_ID_PREFIXES = (
    "aperture.", "transition.", "room.", "activity.", "semantic_face.",
    "parent_wall.", "host_face.", "resolved_face.", "reconstruction.", "cutter.",
)

# Populated with the physically derived IDs of the checked-in closed-world
# inventory.  Keeping only IDs here prevents semantic or coordinate authority
# from being duplicated in Python.
EXPECTED_CERTIFICATE_IDS: tuple[str, ...] = (
    "physical_gap.646cf1a01ffccf7cf896",
    "physical_gap.c1b14875aaceb17d81b0",
    "physical_gap.fb0b72a9a9941e211c6c",
    "physical_gap.b4b46cd5d0f3ab38e1a2",
    "physical_gap.89a323d82cacc5e28dd0",
    "physical_gap.e1bfb5d835228eb0a5a0",
    "physical_gap.6000c80a2ad4bfdcd960",
    "physical_gap.d0d733e18eff25d70aef",
    "physical_gap.a0bbd75e2d66da562f95",
    "physical_gap.647eecd57a9e6ed0f4c2",
    "physical_gap.b78fe900b85b775ca70c",
)


@dataclass(frozen=True)
class PhysicalFamilyAuthorityV1:
    schema: str
    status: str
    document: Any
    identity_payload: Any
    certificates: tuple[Any, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return deep_thaw(self.document)


@dataclass(frozen=True)
class _PhysicalIndex:
    polygon_edges: dict[str, dict[tuple[Point, Point], tuple[str, ...]]]
    polygon_incidence: dict[str, dict[Point, frozenset[Point]]]
    global_incidence: dict[Point, frozenset[Point]]
    proper_crossings: frozenset[tuple[Point, tuple[str, ...]]]


@dataclass(frozen=True)
class _EndpointEvidence:
    host: Point
    opposite: Point
    host_end: Point
    opposite_end: Point
    cap_points: tuple[Point, ...]
    cap_edges: tuple[tuple[tuple[Point, Point], tuple[str, ...]], ...]
    host_germ: tuple[tuple[Point, Point], tuple[str, ...]]
    opposite_germ: tuple[tuple[Point, Point], tuple[str, ...]]
    polygon_id: str
    declared_events: tuple[tuple[str, Point, tuple[str, ...]], ...]


def _default_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "docs/dashboard/apartment_canvas"


def physical_slice1_projection(slice1: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic accepted physical-only Slice 1 projection."""
    if not isinstance(slice1, dict):
        raise ContractError([Diagnostic("physical_family.slice1", "slice1", "must be an object")])
    required = ("schema", "algorithm", "status", "arrangement_audit", "wall_body")
    try:
        projection = {key: slice1[key] for key in required}
    except KeyError as exc:
        raise ContractError([
            Diagnostic("physical_family.slice1", f"slice1.{exc.args[0]}", "required physical field is missing")
        ]) from exc
    if (
        projection["schema"] != _SLICE1_SCHEMA
        or projection["algorithm"] != _SLICE1_ALGORITHM
        or projection["status"] != _SLICE1_STATUS
    ):
        raise ContractError([
            Diagnostic("physical_family.slice1", "slice1", "incompatible Slice 1 identity")
        ])
    return json.loads(canonical_json(projection))


def physical_slice1_fingerprint(slice1: dict[str, Any]) -> str:
    return fingerprint(physical_slice1_projection(slice1))


def _without_certificate_nonidentity(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_certificate_nonidentity(item)
            for key, item in value.items()
            if key not in {"id", "wall_body_polygon"}
        }
    if isinstance(value, list):
        return [_without_certificate_nonidentity(item) for item in value]
    return value


def reverse_certificate_record(certificate: dict[str, Any]) -> dict[str, Any]:
    """Reverse one ordered-rail correspondence without changing its meaning."""
    value = json.loads(canonical_json(certificate))
    value["endpoint_a"], value["endpoint_b"] = value["endpoint_b"], value["endpoint_a"]
    tangent = value["orientation"]["tangent"]
    value["orientation"]["tangent"] = [-component for component in tangent]
    return value


def canonical_undirected_certificate_json(certificate: dict[str, Any]) -> str:
    """Canonicalize a complete physical certificate independent of direction."""
    forward = canonical_json(_without_certificate_nonidentity(certificate))
    reverse = canonical_json(_without_certificate_nonidentity(reverse_certificate_record(certificate)))
    return min(forward, reverse)


def derive_certificate_id(certificate: dict[str, Any]) -> str:
    digest = sha256(canonical_undirected_certificate_json(certificate).encode("utf-8")).hexdigest()
    return f"physical_gap.{digest[:20]}"


def authority_fingerprint(identity_payload: dict[str, Any]) -> str:
    """Fingerprint identity with the closed-world certificate inventory as a set."""
    canonical_identity = json.loads(canonical_json(identity_payload))
    certificates = canonical_identity.get("gap_continuation_certificates")
    if isinstance(certificates, list):
        # Certificate ordering is not semantic.  Complete records, rather than
        # checked-in list positions, provide a deterministic physical order.
        canonical_identity["gap_continuation_certificates"] = sorted(
            certificates, key=canonical_json,
        )
    return fingerprint(canonical_identity)


def _key_error(value: Any, expected: set[str], path: str, errors: list[Diagnostic]) -> bool:
    if not isinstance(value, dict) or set(value) != expected:
        errors.append(Diagnostic("physical_family.shape", path, f"must contain exactly {sorted(expected)!r}"))
        return True
    return False


def _point(value: Any, path: str, errors: list[Diagnostic]) -> Point | None:
    try:
        point = Point.from_value(value)
    except (ExactGeometryError, TypeError, ValueError) as exc:
        errors.append(Diagnostic("physical_family.point", path, str(exc)))
        return None
    if not isinstance(value, list) or any(not isinstance(token, str) for token in value):
        errors.append(Diagnostic("physical_family.point", path, "must use canonical rational string tokens"))
        return None
    if point.to_tokens() != value:
        errors.append(Diagnostic("physical_family.point", path, "must use reduced rational tokens"))
        return None
    return point


def _edge_key(first: Point, second: Point) -> tuple[Point, Point]:
    return tuple(sorted((first, second)))


def _physical_index(projection: dict[str, Any], errors: list[Diagnostic]) -> _PhysicalIndex:
    polygon_edges: dict[str, dict[tuple[Point, Point], tuple[str, ...]]] = {}
    polygon_incidence: dict[str, dict[Point, frozenset[Point]]] = {}
    global_mutable: dict[Point, set[Point]] = {}
    try:
        polygons = projection["wall_body"]["polygons"]
    except (KeyError, TypeError):
        errors.append(Diagnostic("physical_family.slice1", "wall_body.polygons", "missing physical polygons"))
        polygons = []
    for polygon in polygons if isinstance(polygons, list) else []:
        polygon_id = polygon.get("id") if isinstance(polygon, dict) else None
        if not isinstance(polygon_id, str) or polygon_id in polygon_edges:
            errors.append(Diagnostic("physical_family.slice1", "wall_body.polygons", "invalid or duplicate polygon id"))
            continue
        edges: dict[tuple[Point, Point], tuple[str, ...]] = {}
        incidence: dict[Point, set[Point]] = {}
        provenance = polygon.get("provenance", {})
        groups: list[Any] = [provenance.get("outer", [])]
        groups.extend(provenance.get("holes", []))
        for group in groups:
            for raw in group if isinstance(group, list) else []:
                try:
                    first, second = (Point.from_value(item) for item in raw["edge"])
                    sources = tuple(raw["source_segments"])
                except (KeyError, TypeError, ValueError, ExactGeometryError):
                    errors.append(Diagnostic("physical_family.slice1", polygon_id, "malformed physical edge provenance"))
                    continue
                key = _edge_key(first, second)
                if first == second or key in edges or not sources or not all(_SOURCE_ID.fullmatch(x) for x in sources):
                    errors.append(Diagnostic("physical_family.slice1", polygon_id, "invalid physical atomic edge"))
                    continue
                edges[key] = sources
                incidence.setdefault(first, set()).add(second)
                incidence.setdefault(second, set()).add(first)
                global_mutable.setdefault(first, set()).add(second)
                global_mutable.setdefault(second, set()).add(first)
        polygon_edges[polygon_id] = edges
        polygon_incidence[polygon_id] = {point: frozenset(values) for point, values in incidence.items()}
    crossings: set[tuple[Point, tuple[str, ...]]] = set()
    try:
        for crossing in projection["arrangement_audit"]["proper_crossings"]:
            crossings.add((Point.from_value(crossing["point"]), tuple(sorted(crossing["segments"]))))
    except (KeyError, TypeError, ValueError, ExactGeometryError):
        errors.append(Diagnostic("physical_family.slice1", "arrangement_audit.proper_crossings", "malformed crossing audit"))
    return _PhysicalIndex(
        polygon_edges,
        polygon_incidence,
        {point: frozenset(values) for point, values in global_mutable.items()},
        frozenset(crossings),
    )


def _walk_strings(value: Any) -> Iterable[tuple[str | None, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                yield key, item
            else:
                yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield None, item
            else:
                yield from _walk_strings(item)


def _validate_no_semantic_identity(certificate: dict[str, Any], path: str, errors: list[Diagnostic]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _FORBIDDEN_CERTIFICATE_KEYS:
                    errors.append(Diagnostic("physical_family.semantic_identity", f"{path}.{key}", "forbidden identity key"))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(certificate)
    for key, value in _walk_strings(certificate):
        if key in {"id", "wall_body_polygon", "source_segments", "kind", "terminal_kind"}:
            if any(value.startswith(prefix) for prefix in _FORBIDDEN_ID_PREFIXES):
                errors.append(Diagnostic("physical_family.semantic_identity", path, "forbidden semantic identity value"))


def _validate_orientation(certificate: dict[str, Any], path: str, errors: list[Diagnostic]) -> tuple[Point, Point] | None:
    orientation = certificate.get("orientation")
    if _key_error(orientation, {"tangent", "normal"}, f"{path}.orientation", errors):
        return None
    try:
        tangent = Point(rational(orientation["tangent"][0]), rational(orientation["tangent"][1]))
        normal = Point(rational(orientation["normal"][0]), rational(orientation["normal"][1]))
    except (ExactGeometryError, IndexError, TypeError, ValueError):
        errors.append(Diagnostic("physical_family.orientation", f"{path}.orientation", "invalid exact vectors"))
        return None
    raw = orientation["tangent"] + orientation["normal"] if all(isinstance(x, list) for x in orientation.values()) else []
    integers = all(isinstance(item, int) and not isinstance(item, bool) for item in raw)
    tangent_gcd = math.gcd(abs(tangent.x.numerator), abs(tangent.y.numerator))
    normal_gcd = math.gcd(abs(normal.x.numerator), abs(normal.y.numerator))
    if (
        not integers or tangent == Point(Fraction(0), Fraction(0)) or normal == Point(Fraction(0), Fraction(0))
        or tangent.x.denominator != 1 or tangent.y.denominator != 1
        or normal.x.denominator != 1 or normal.y.denominator != 1
        or tangent_gcd != 1 or normal_gcd != 1
        or tangent.x * normal.x + tangent.y * normal.y != 0
    ):
        errors.append(Diagnostic("physical_family.orientation", f"{path}.orientation", "tangent and normal must be exact perpendicular primitive integer vectors"))
        return None
    return tangent, normal


def _validate_edge_record(
    raw: Any, expected_first: Point, expected_second: Point, path: str, errors: list[Diagnostic],
) -> tuple[tuple[Point, Point], tuple[str, ...]] | None:
    if _key_error(raw, _EDGE_KEYS, path, errors):
        return None
    try:
        edge_values = raw["edge"]
        first = _point(edge_values[0], f"{path}.edge[0]", errors)
        second = _point(edge_values[1], f"{path}.edge[1]", errors)
    except (IndexError, TypeError):
        errors.append(Diagnostic("physical_family.edge", path, "edge must have two exact points"))
        return None
    sources = raw.get("source_segments")
    if (
        first is None or second is None or first != expected_first or second != expected_second
        or not isinstance(sources, list) or not sources or not all(isinstance(x, str) and _SOURCE_ID.fullmatch(x) for x in sources)
        or sources != sorted(set(sources))
    ):
        errors.append(Diagnostic("physical_family.edge", path, "ordered edge or source provenance is invalid"))
        return None
    return _edge_key(first, second), tuple(sources)


def _validate_junctions(
    raw: Any,
    path: str,
    cap_points: tuple[Point, ...],
    polygon_id: str,
    index: _PhysicalIndex,
    errors: list[Diagnostic],
) -> tuple[tuple[str, Point, tuple[str, ...]], ...]:
    if _key_error(raw, _JUNCTION_KEYS, path, errors):
        return ()
    events = raw.get("events")
    if not isinstance(raw.get("required"), bool) or not isinstance(events, list) or raw["required"] != bool(events):
        errors.append(Diagnostic("physical_family.junction", path, "required must exactly reflect a nonempty event list"))
        return ()
    points: set[Point] = set()
    validated: list[tuple[str, Point, tuple[str, ...]]] = []
    for event_index, event in enumerate(events):
        event_path = f"{path}.events[{event_index}]"
        if _key_error(event, _EVENT_KEYS, event_path, errors):
            continue
        point = _point(event.get("point"), f"{event_path}.point", errors)
        sources = event.get("source_segments")
        kind = event.get("kind")
        if (
            point is None or point not in cap_points or point in points
            or kind not in {"accepted_proper_crossing", "accepted_exact_junction_unique_directed_continuation"}
            or not isinstance(sources, list) or len(sources) != 2
            or sources != sorted(set(sources)) or not all(_SOURCE_ID.fullmatch(x) for x in sources)
        ):
            errors.append(Diagnostic("physical_family.junction", event_path, "invalid accepted exact event"))
            continue
        if kind == "accepted_proper_crossing" and (point, tuple(sources)) not in index.proper_crossings:
            errors.append(Diagnostic("physical_family.junction", event_path, "proper crossing is not in accepted Slice 1 audit"))
        incident_sources = sorted({
            source
            for edge, provenance in index.polygon_edges.get(polygon_id, {}).items()
            if point in edge
            for source in provenance
        })
        if incident_sources != sources:
            errors.append(Diagnostic("physical_family.junction", event_path, "event sources do not prove the selected polygon continuation"))
        points.add(point)
        validated.append((kind, point, tuple(sources)))
    return tuple(validated)


def _validate_endpoint(
    endpoint: Any, path: str, index: _PhysicalIndex, errors: list[Diagnostic],
) -> _EndpointEvidence | None:
    if _key_error(endpoint, _ENDPOINT_KEYS, path, errors):
        return None
    if endpoint.get("terminal_kind") != "exact_ordered_rail_cap":
        errors.append(Diagnostic("physical_family.terminal", f"{path}.terminal_kind", "unknown terminal kind"))
    host = _point(endpoint.get("host_point"), f"{path}.host_point", errors)
    opposite = _point(endpoint.get("opposite_point"), f"{path}.opposite_point", errors)
    raw_path = endpoint.get("cap_path")
    if not isinstance(raw_path, list) or len(raw_path) < 2:
        errors.append(Diagnostic("physical_family.cap", f"{path}.cap_path", "cap path must contain at least two points"))
        return None
    cap_points = tuple(
        point for i, value in enumerate(raw_path)
        if (point := _point(value, f"{path}.cap_path[{i}]", errors)) is not None
    )
    if host is None or opposite is None or len(cap_points) != len(raw_path):
        return None
    if cap_points[0] != host or cap_points[-1] != opposite or any(a == b for a, b in zip(cap_points, cap_points[1:])):
        errors.append(Diagnostic("physical_family.cap", f"{path}.cap_path", "must run nondegenerately from host to opposite"))
        return None
    raw_cap_edges = endpoint.get("atomic_cap_edges")
    if not isinstance(raw_cap_edges, list) or len(raw_cap_edges) != len(cap_points) - 1:
        errors.append(Diagnostic("physical_family.cap", f"{path}.atomic_cap_edges", "must enumerate every cap edge exactly once"))
        return None
    cap_edges = []
    for edge_index, (first, second) in enumerate(zip(cap_points, cap_points[1:])):
        validated = _validate_edge_record(raw_cap_edges[edge_index], first, second, f"{path}.atomic_cap_edges[{edge_index}]", errors)
        if validated:
            cap_edges.append(validated)
    host_raw = endpoint.get("host_rail_germ")
    opposite_raw = endpoint.get("opposite_rail_germ")
    try:
        host_end = _point(host_raw["edge"][1], f"{path}.host_rail_germ.edge[1]", errors)
        opposite_end = _point(opposite_raw["edge"][1], f"{path}.opposite_rail_germ.edge[1]", errors)
    except (KeyError, IndexError, TypeError):
        errors.append(Diagnostic("physical_family.germ", path, "rail germ edge is malformed"))
        return None
    if host_end is None or opposite_end is None:
        return None
    host_germ = _validate_edge_record(host_raw, host, host_end, f"{path}.host_rail_germ", errors)
    opposite_germ = _validate_edge_record(opposite_raw, opposite, opposite_end, f"{path}.opposite_rail_germ", errors)
    if host == host_end or opposite == opposite_end:
        errors.append(Diagnostic("physical_family.germ", path, "host and opposite germs must be nondegenerate"))
    polygon_id = endpoint.get("wall_body_polygon")
    if not isinstance(polygon_id, str) or not _POLYGON_ID.fullmatch(polygon_id) or polygon_id not in index.polygon_edges:
        errors.append(Diagnostic("physical_family.polygon", f"{path}.wall_body_polygon", "unknown physical polygon provenance"))
        return None
    evidence = [*cap_edges]
    if host_germ:
        evidence.append(host_germ)
    if opposite_germ:
        evidence.append(opposite_germ)
    matching = [
        candidate for candidate, edges in index.polygon_edges.items()
        if all(edges.get(edge) == sources for edge, sources in evidence)
    ]
    if matching != [polygon_id]:
        errors.append(Diagnostic("physical_family.endpoint_match", path, "complete terminal must match exactly one wall-body polygon"))
    polygon_edges = index.polygon_edges.get(polygon_id, {})
    for edge, sources in evidence:
        actual = polygon_edges.get(edge)
        if actual is None:
            errors.append(Diagnostic("physical_family.edge_missing", path, "cap or germ atomic edge is absent"))
        elif actual != sources:
            errors.append(Diagnostic("physical_family.provenance", path, "cap or germ source provenance differs"))
    declared_events = _validate_junctions(
        endpoint.get("accepted_exact_junction"),
        f"{path}.accepted_exact_junction",
        cap_points,
        polygon_id,
        index,
        errors,
    )
    incidence = index.polygon_incidence.get(polygon_id, {})
    expected_incidence: dict[Point, set[Point]] = {}
    for first, second in zip(cap_points, cap_points[1:]):
        expected_incidence.setdefault(first, set()).add(second)
        expected_incidence.setdefault(second, set()).add(first)
    expected_incidence.setdefault(host, set()).add(host_end)
    expected_incidence.setdefault(opposite, set()).add(opposite_end)
    for point, expected_neighbors in expected_incidence.items():
        if incidence.get(point) != frozenset(expected_neighbors):
            errors.append(Diagnostic("physical_family.branch", path, "terminal crosses or admits a competing polygon branch"))
    return _EndpointEvidence(
        host,
        opposite,
        host_end,
        opposite_end,
        cap_points,
        tuple(cap_edges),
        host_germ,
        opposite_germ,
        polygon_id,
        declared_events,
    )


def _vector(first: Point, second: Point) -> Point:
    return Point(second.x - first.x, second.y - first.y)


def _undirected_primitive_line(vector: Point) -> tuple[int, int]:
    """Return the canonical exact primitive line through a nonzero vector."""
    denominator = math.lcm(vector.x.denominator, vector.y.denominator)
    x = vector.x.numerator * (denominator // vector.x.denominator)
    y = vector.y.numerator * (denominator // vector.y.denominator)
    divisor = math.gcd(abs(x), abs(y))
    x //= divisor
    y //= divisor
    if x < 0 or (x == 0 and y < 0):
        x, y = -x, -y
    return x, y


def _line_of(vector: Point) -> tuple[int, int] | None:
    if vector == Point(Fraction(0), Fraction(0)):
        return None
    return _undirected_primitive_line(vector)


def _orientation_witness_line(
    endpoint_a: _EndpointEvidence,
    endpoint_b: _EndpointEvidence,
    path: str,
    errors: list[Diagnostic],
) -> tuple[int, int] | None:
    """Derive the one repeated continuation line from raw Slice 1 terminals.

    A host/host or opposite/opposite bridge directly witnesses tangent.  A cap
    chord directly witnesses host-to-opposite normal and therefore its exact
    perpendicular tangent.  No cap-perpendicular or parallel-rail premise is
    made: only an actually collinear raw vector contributes a vote.
    """
    votes: dict[tuple[int, int], int] = {}

    def vote(vector: Point, *, normal: bool = False) -> None:
        if normal:
            vector = Point(-vector.y, vector.x)
        line = _line_of(vector)
        if line is not None:
            votes[line] = votes.get(line, 0) + 1

    vote(_vector(endpoint_a.host, endpoint_b.host))
    vote(_vector(endpoint_a.opposite, endpoint_b.opposite))
    for endpoint in (endpoint_a, endpoint_b):
        vote(_vector(endpoint.host, endpoint.opposite), normal=True)
    repeated = [line for line, count in votes.items() if count >= 2]
    if len(repeated) != 1:
        errors.append(Diagnostic(
            "physical_family.orientation",
            path,
            "raw terminals do not uniquely establish one repeated continuation orientation",
        ))
        return None
    return repeated[0]


def _is_parallel(vector: Point, direction: Point) -> bool:
    return vector.x * direction.y - vector.y * direction.x == 0


def _expected_junction_events(
    endpoint: _EndpointEvidence,
    tangent: Point,
    normal: Point,
    index: _PhysicalIndex,
    path: str,
    errors: list[Diagnostic],
) -> tuple[tuple[str, Point, tuple[str, ...]], ...]:
    """Derive the exact endpoint junction assertions demanded by Slice 1."""
    expected: dict[Point, tuple[str, Point, tuple[str, ...]]] = {}
    incidence = index.polygon_incidence.get(endpoint.polygon_id, {})
    polygon_edges = index.polygon_edges.get(endpoint.polygon_id, {})

    for point in endpoint.cap_points:
        if len(index.global_incidence.get(point, ())) <= len(incidence.get(point, ())):
            continue
        sources = tuple(sorted({
            source
            for edge, provenance in polygon_edges.items()
            if point in edge
            for source in provenance
        }))
        crossing = (point, sources) in index.proper_crossings
        if len(sources) != 2:
            errors.append(Diagnostic(
                "physical_family.junction", path,
                "required global terminal event has no exact two-source authority record",
            ))
            continue
        expected[point] = (
            "accepted_proper_crossing" if crossing else "accepted_exact_junction_unique_directed_continuation",
            point,
            sources,
        )

    local_vectors = [
        _vector(endpoint.host, endpoint.host_end),
        _vector(endpoint.opposite, endpoint.opposite_end),
        *[_vector(first, second) for first, second in zip(endpoint.cap_points, endpoint.cap_points[1:])],
    ]
    # If this exact local terminal contains no atom aligned with the already
    # derived physical frame, only an explicit source-incidence event proves
    # which directed continuation reaches the host rail.  This is the general
    # C10-shaped case, not an ID-specific exception.
    if not any(_is_parallel(vector, tangent) or _is_parallel(vector, normal) for vector in local_vectors):
        sources = tuple(sorted(set(endpoint.host_germ[1]) | set(endpoint.cap_edges[0][1])))
        if len(sources) != 2:
            errors.append(Diagnostic(
                "physical_family.junction", path,
                "required local terminal event has no exact two-source authority record",
            ))
        else:
            expected[endpoint.host] = (
                "accepted_exact_junction_unique_directed_continuation",
                endpoint.host,
                sources,
            )
    return tuple(sorted(
        expected.values(),
        key=lambda item: (item[1].x, item[1].y, item[0], item[2]),
    ))


def _validate_certificate(certificate: Any, path: str, index: _PhysicalIndex, errors: list[Diagnostic]) -> None:
    if _key_error(certificate, _CERTIFICATE_KEYS, path, errors):
        return
    _validate_no_semantic_identity(certificate, path, errors)
    certificate_id = certificate.get("id")
    if not isinstance(certificate_id, str) or not _CERTIFICATE_ID.fullmatch(certificate_id):
        errors.append(Diagnostic("physical_family.certificate_id", f"{path}.id", "invalid physical certificate id"))
    else:
        try:
            derived = derive_certificate_id(certificate)
        except (KeyError, TypeError, ValueError):
            errors.append(Diagnostic("physical_family.certificate_id", f"{path}.id", "record cannot be canonicalized"))
        else:
            if certificate_id != derived:
                errors.append(Diagnostic("physical_family.certificate_id", f"{path}.id", "does not derive from the complete physical record"))
    vectors = _validate_orientation(certificate, path, errors)
    endpoint_a = _validate_endpoint(certificate.get("endpoint_a"), f"{path}.endpoint_a", index, errors)
    endpoint_b = _validate_endpoint(certificate.get("endpoint_b"), f"{path}.endpoint_b", index, errors)
    if certificate.get("rail_mapping") != _RAIL_MAPPING:
        errors.append(Diagnostic("physical_family.rail_mapping", f"{path}.rail_mapping", "must preserve ordered host and opposite rails"))
    if certificate.get("assertions") != _ASSERTIONS:
        errors.append(Diagnostic("physical_family.assertions", f"{path}.assertions", "accepted fail-closed assertions changed"))
    if vectors and endpoint_a and endpoint_b:
        tangent, normal = vectors
        derived_line = _orientation_witness_line(endpoint_a, endpoint_b, f"{path}.orientation", errors)
        if derived_line != _undirected_primitive_line(tangent):
            errors.append(Diagnostic(
                "physical_family.orientation", f"{path}.orientation",
                "declared tangent is not the repeated exact Slice 1 terminal orientation",
            ))
        a_host, a_opposite = endpoint_a.host, endpoint_a.opposite
        b_host, b_opposite = endpoint_b.host, endpoint_b.opposite
        normal_a = (a_host.x - a_opposite.x) * normal.x + (a_host.y - a_opposite.y) * normal.y
        normal_b = (b_host.x - b_opposite.x) * normal.x + (b_host.y - b_opposite.y) * normal.y
        tangent_host = (b_host.x - a_host.x) * tangent.x + (b_host.y - a_host.y) * tangent.y
        tangent_opposite = (b_opposite.x - a_opposite.x) * tangent.x + (b_opposite.y - a_opposite.y) * tangent.y
        if normal_a <= 0 or normal_b <= 0 or tangent_host <= 0 or tangent_opposite <= 0:
            errors.append(Diagnostic("physical_family.order", path, "host/opposite ordering conflicts with tangent/normal orientation"))
        for endpoint_name, endpoint in (("endpoint_a", endpoint_a), ("endpoint_b", endpoint_b)):
            expected_events = _expected_junction_events(
                endpoint, tangent, normal, index, f"{path}.{endpoint_name}.accepted_exact_junction", errors,
            )
            if endpoint.declared_events != expected_events:
                errors.append(Diagnostic(
                    "physical_family.junction", f"{path}.{endpoint_name}.accepted_exact_junction",
                    "junction evidence must exactly equal the physical terminal events required by Slice 1",
                ))
        physical_edges = {edge for edges in index.polygon_edges.values() for edge in edges}
        if (
            a_host == b_host or a_opposite == b_opposite
            or _edge_key(a_host, b_host) in physical_edges
            or _edge_key(a_opposite, b_opposite) in physical_edges
        ):
            errors.append(Diagnostic("physical_family.already_connected", path, "certificate endpoints are already locally connected"))


def validate_physical_family_authority(document: dict[str, Any], physical_slice1: dict[str, Any]) -> None:
    """Validate the closed-world authority solely against physical Slice 1."""
    errors: list[Diagnostic] = []
    if _key_error(document, _TOP_LEVEL_KEYS, "physical_family_authority", errors):
        raise ContractError(errors)
    if document.get("schema") != AUTHORITY_SCHEMA or document.get("status") != AUTHORITY_STATUS:
        errors.append(Diagnostic("physical_family.identity", "physical_family_authority", "wrong schema or status"))
    try:
        projection = physical_slice1_projection(physical_slice1)
    except ContractError as exc:
        errors.extend(exc.diagnostics)
        projection = {}
    projection_sha = fingerprint(projection) if projection else None
    if projection_sha != PHYSICAL_SOURCE_SHA256:
        errors.append(Diagnostic("physical_family.source", "physical_source.sha256", "accepted physical Slice 1 projection changed"))
    identity = document.get("identity_payload")
    if _key_error(identity, _IDENTITY_KEYS, "identity_payload", errors):
        raise ContractError(errors)
    if identity.get("physical_source") != {"schema": PHYSICAL_SOURCE_SCHEMA, "sha256": PHYSICAL_SOURCE_SHA256}:
        errors.append(Diagnostic("physical_family.source", "identity_payload.physical_source", "physical source binding changed"))
    if identity.get("algorithm") != _ALGORITHM:
        errors.append(Diagnostic("physical_family.algorithm", "identity_payload.algorithm", "accepted algorithm metadata changed"))
    if identity.get("permitted_local_edge_classes") != _PERMITTED_LOCAL_EDGE_CLASSES:
        errors.append(Diagnostic("physical_family.local_edges", "identity_payload.permitted_local_edge_classes", "local edge allowlist changed"))
    if identity.get("fail_closed") != _FAIL_CLOSED or identity.get("authority_limitations") != _AUTHORITY_LIMITATIONS:
        errors.append(Diagnostic("physical_family.policy", "identity_payload", "fail-closed policy or limitations changed"))
    fingerprint_record = document.get("fingerprint")
    if _key_error(fingerprint_record, {*_FINGERPRINT, "value"}, "fingerprint", errors):
        fingerprint_record = {}
    if (
        any(fingerprint_record.get(key) != value for key, value in _FINGERPRINT.items())
        or fingerprint_record.get("value") != authority_fingerprint(identity)
    ):
        errors.append(Diagnostic("physical_family.fingerprint", "fingerprint", "identity_payload fingerprint mismatch"))
    certificates = identity.get("gap_continuation_certificates")
    if not isinstance(certificates, list) or len(certificates) != 11:
        errors.append(Diagnostic("physical_family.inventory", "gap_continuation_certificates", "closed-world inventory must contain exactly 11 certificates"))
        certificates = certificates if isinstance(certificates, list) else []
    index = _physical_index(projection, errors) if projection else _PhysicalIndex({}, {}, {}, frozenset())
    for certificate_index, certificate in enumerate(certificates):
        _validate_certificate(certificate, f"identity_payload.gap_continuation_certificates[{certificate_index}]", index, errors)
    ids = [item.get("id") for item in certificates if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append(Diagnostic("physical_family.duplicate", "gap_continuation_certificates", "duplicate or inverse-duplicate certificate"))
    if set(ids) != set(EXPECTED_CERTIFICATE_IDS):
        errors.append(Diagnostic("physical_family.inventory", "gap_continuation_certificates", "unknown or missing certificate id"))
    canonical_records: set[str] = set()
    for certificate in certificates:
        if not isinstance(certificate, dict):
            continue
        try:
            representation = canonical_undirected_certificate_json(certificate)
        except (KeyError, TypeError, ValueError):
            continue
        if representation in canonical_records:
            errors.append(Diagnostic("physical_family.inverse_duplicate", "gap_continuation_certificates", "duplicate undirected physical record"))
        canonical_records.add(representation)
    if errors:
        raise ContractError(errors)


def load_physical_family_authority(
    physical_slice1: dict[str, Any],
    directory: str | Path | None = None,
    *,
    document: dict[str, Any] | None = None,
) -> PhysicalFamilyAuthorityV1:
    """Load and validate PhysicalFamilyAuthorityV1 against accepted Slice 1."""
    directory = Path(directory or _default_directory())
    if document is None:
        try:
            document = json.loads((directory / AUTHORITY_FILENAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError([Diagnostic("physical_family.read", AUTHORITY_FILENAME, str(exc))]) from exc
    if not isinstance(document, dict):
        raise ContractError([Diagnostic("physical_family.read", AUTHORITY_FILENAME, "required JSON object is missing")])
    validate_physical_family_authority(document, physical_slice1)
    identity = document["identity_payload"]
    certificates = identity["gap_continuation_certificates"]
    return PhysicalFamilyAuthorityV1(
        document["schema"],
        document["status"],
        deep_freeze(document),
        deep_freeze(identity),
        tuple(deep_freeze(item) for item in certificates),
        document["fingerprint"]["value"],
    )
