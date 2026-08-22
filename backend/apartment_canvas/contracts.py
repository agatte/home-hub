"""Deterministic loading, authority checks, and explicit contract reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .models import deep_freeze, deep_thaw


@dataclass(frozen=True)
class ContractDescriptor:
    """Accepted authority metadata for one exact checked-in source document."""

    filename: str
    schema: str
    status: str
    fingerprint: str
    bindings: tuple[tuple[str, str], ...] = ()


PHYSICAL_SEMANTIC_CONTRACT_DESCRIPTORS = (
    ContractDescriptor("geometry_v1.json", "homehub.apartment-geometry.v1", "approved_top_down_geometry", "099e73be4c9140836ec28be203ffee4a60d2314f0f789dd6f866c8c3f613b481"),
    ContractDescriptor("geometry_v1_6_patch.json", "homehub.apartment-geometry-delta.v1.6", "approved", "88c72d267822a9fa0bc8d874ad4178101f166e05820e72086625a89ddf58f6d1", (("base", "geometry_v1.json"),)),
    ContractDescriptor("aperture_registry_v1.json", "homehub.apartment-aperture-registry.v1", "approved_xy_provisional_z", "e09211152b57b240132c56a9e92dc9c3d5b4d48fee69465a002a6d3ef68a256a", (("source", "canonical floor plan + approved geometry v1 + geometry v1.6 contract amendments"),)),
    ContractDescriptor("projection_contract_v1.json", "homehub.apartment-projection-contract.v1", "accepted_converter_contract", "ae31274efad175607420102f2a5b39c488dac35bd05a87790438711ed1a47cce", (("source_geometry", "geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json"),)),
)
CURRENT_CONTRACT_DESCRIPTORS = (
    *PHYSICAL_SEMANTIC_CONTRACT_DESCRIPTORS,
    ContractDescriptor("camera_v2.json", "homehub.apartment-camera-family.v2", "accepted_responsive_camera_family", "934fa4224dcc84e84854531b216e787c5594759961353824877e24c7f28b5e80", (("source_geometry", "geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json"),)),
    ContractDescriptor("visibility_contract_v2.json", "homehub.apartment-visibility-contract.v2", "accepted_bedroom_side_north_visibility_contract", "4002a010c31ef33b05b85377661bbe7f8d8bad218b065905a96ba02cfac17a21", (("source_geometry", "geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json"), ("camera", "camera_v2.json"))),
)
HISTORICAL_TOPOLOGY_CONTRACT_DESCRIPTORS = (
    *PHYSICAL_SEMANTIC_CONTRACT_DESCRIPTORS,
    ContractDescriptor("camera_v1.json", "homehub.apartment-camera-lock.v1", "accepted", "c92297f1b38cb63ae20a3a4130e12e062162c4d09c3388892355ce28938a637c", (("source_geometry", "geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json"),)),
    ContractDescriptor("visibility_contract_v1.json", "homehub.apartment-visibility-contract.v1", "accepted_conceptual_visibility_contract", "76e614c5b46b7ff61b28edc0fbba0334f7607793fef55ad44bcf73a3238dadfb", (("source_geometry", "geometry_v1.json + geometry_v1_6_patch.json + aperture_registry_v1.json"), ("camera", "camera_v1.json"))),
)
# Public aliases describe current compilation authority only. Historical v1
# presentation files are loaded solely through the explicit frozen-topology
# context below.
CONTRACT_DESCRIPTORS = CURRENT_CONTRACT_DESCRIPTORS
CONTRACT_FILENAMES = tuple(descriptor.filename for descriptor in CONTRACT_DESCRIPTORS)
EXPECTED_SCHEMAS = {descriptor.filename: descriptor.schema for descriptor in CONTRACT_DESCRIPTORS}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


class ContractError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = tuple(sorted(diagnostics, key=lambda item: (item.code, item.path, item.message)))
        super().__init__("; ".join(f"{d.code} {d.path}: {d.message}" for d in self.diagnostics))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(value: Any) -> str:
    """Hash parsed JSON canonically, independently of source checkout bytes."""
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContractBundle:
    """Raw authority is retained separately from reconciled effective geometry."""

    raw_documents: Any
    geometry: Any
    patch: Any
    aperture_registry: Any
    projection: Any
    camera: Any
    visibility: Any
    source_manifest: tuple[Any, ...]


def _read_directory(
    directory: Path, descriptors: tuple[ContractDescriptor, ...],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    errors: list[Diagnostic] = []
    for name in (descriptor.filename for descriptor in descriptors):
        try:
            values[name] = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(Diagnostic("contract.read", name, str(exc)))
    if errors:
        raise ContractError(errors)
    return values


def _validate_authority(
    raw: dict[str, Any], descriptors: tuple[ContractDescriptor, ...],
) -> None:
    errors: list[Diagnostic] = []
    for descriptor in descriptors:
        document = raw.get(descriptor.filename)
        if not isinstance(document, dict):
            errors.append(Diagnostic("contract.missing", descriptor.filename, "required JSON object is missing"))
            continue
        if document.get("schema") != descriptor.schema:
            errors.append(Diagnostic("contract.schema", f"{descriptor.filename}.schema", f"expected {descriptor.schema!r}"))
        if document.get("status") != descriptor.status:
            errors.append(Diagnostic("contract.status", f"{descriptor.filename}.status", f"expected {descriptor.status!r}"))
        for field, expected in descriptor.bindings:
            if document.get(field) != expected:
                errors.append(Diagnostic("contract.binding", f"{descriptor.filename}.{field}", f"expected {expected!r}"))
        if fingerprint(document) != descriptor.fingerprint:
            errors.append(Diagnostic("contract.authority", descriptor.filename, "canonical accepted source fingerprint changed"))
    if errors:
        raise ContractError(errors)


def _load_contracts(
    descriptors: tuple[ContractDescriptor, ...],
    directory: str | Path | None = None,
    *,
    documents: dict[str, Any] | None = None,
) -> ContractBundle:
    if documents is None:
        directory = Path(directory or Path(__file__).resolve().parents[2] / "docs/dashboard/apartment_canvas")
        documents = _read_directory(directory, descriptors)
    filenames = tuple(descriptor.filename for descriptor in descriptors)
    raw_plain = {
        name: json.loads(canonical_json(documents[name]))
        for name in filenames
        if name in documents
    }
    _validate_authority(raw_plain, descriptors)
    manifest = tuple(
        deep_freeze({
            "id": descriptor.filename,
            "schema": descriptor.schema,
            "sha256": fingerprint(raw_plain[descriptor.filename]),
        })
        for descriptor in descriptors
    )
    effective_geometry = _reconcile_geometry(deep_thaw(raw_plain["geometry_v1.json"]), raw_plain["geometry_v1_6_patch.json"])
    raw_documents = deep_freeze(raw_plain)
    return ContractBundle(
        raw_documents,
        deep_freeze(effective_geometry),
        raw_documents["geometry_v1_6_patch.json"],
        raw_documents["aperture_registry_v1.json"],
        raw_documents["projection_contract_v1.json"],
        raw_documents[descriptors[4].filename],
        raw_documents[descriptors[5].filename],
        manifest,
    )


def load_contracts(
    directory: str | Path | None = None, *, documents: dict[str, Any] | None = None,
) -> ContractBundle:
    """Load current v2 authority, then reconcile only a separate working copy."""
    return _load_contracts(CURRENT_CONTRACT_DESCRIPTORS, directory, documents=documents)


def load_historical_topology_contracts(
    directory: str | Path | None = None, *, documents: dict[str, Any] | None = None,
) -> ContractBundle:
    """Load the exact frozen six-source context accepted by TopologyAuthorityV1."""
    return _load_contracts(
        HISTORICAL_TOPOLOGY_CONTRACT_DESCRIPTORS, directory, documents=documents,
    )


def _reconcile_geometry(geometry: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    errors: list[Diagnostic] = []
    allowed = {"object_id", "rect", "reason"}
    objects = {item.get("id"): item for item in geometry.get("objects", []) if isinstance(item, dict)}
    seen: set[str] = set()
    for index, change in enumerate(patch.get("changes", [])):
        path = f"geometry_v1_6_patch.json.changes[{index}]"
        if not isinstance(change, dict) or set(change) - allowed:
            errors.append(Diagnostic("patch.allowlist", path, "only object_id, rect, and reason are allowed"))
            continue
        object_id, rect = change.get("object_id"), change.get("rect")
        if object_id not in objects or object_id in seen:
            errors.append(Diagnostic("patch.target", path + ".object_id", "must name one unique base object"))
            continue
        if not isinstance(rect, dict) or set(rect) != {"x", "y", "w", "h"} or not all(isinstance(rect[k], (int, float)) and not isinstance(rect[k], bool) for k in rect):
            errors.append(Diagnostic("patch.rect", path + ".rect", "must be a numeric x/y/w/h replacement"))
            continue
        seen.add(object_id)
        objects[object_id]["rect"] = rect
    if not isinstance(patch.get("contract_amendments"), dict):
        errors.append(Diagnostic("patch.amendments", "geometry_v1_6_patch.json.contract_amendments", "required"))
    if errors:
        raise ContractError(errors)
    return geometry
