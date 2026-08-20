"""Small deeply immutable, JSON-safe scene model."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    return value


def deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class SemanticSceneV1:
    """Renderer-neutral semantic scene in canonical +x/right, +y/down, +z/up coordinates."""

    schema: str
    version: str
    source_manifest: tuple[Any, ...]
    coordinate_system: Any
    architecture: Any
    wall_volumes: tuple[Any, ...]
    balcony_footprint: Any
    apertures: tuple[Any, ...]
    objects: tuple[Any, ...]
    unplaced_objects: tuple[Any, ...]
    assemblies: tuple[Any, ...]
    visibility_treatments: tuple[Any, ...]
    projection_contract: Any
    camera: Any
    unresolved_metadata: Any

    def to_dict(self) -> dict[str, Any]:
        """Return a detached mutable serialization view, never internal references."""
        return deep_thaw({
            "schema": self.schema, "version": self.version, "source_manifest": self.source_manifest,
            "coordinate_system": self.coordinate_system, "architecture": self.architecture,
            "wall_volumes": self.wall_volumes, "balcony_footprint": self.balcony_footprint,
            "apertures": self.apertures, "objects": self.objects,
            "unplaced_objects": self.unplaced_objects, "assemblies": self.assemblies,
            "visibility_treatments": self.visibility_treatments,
            "projection_contract": self.projection_contract, "camera": self.camera,
            "unresolved_metadata": self.unresolved_metadata,
        })
