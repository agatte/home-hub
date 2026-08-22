"""Offline compiler for the approved Apartment Canvas semantic contracts.

This package deliberately produces no render geometry.  A later adapter owns
the contract-space to renderer-space transform.
"""

from .compiler import compile_scene, compile_scene_from_directory
from .contracts import ContractBundle, ContractError, load_contracts
from .topology_authority import TopologyAuthorityV1, load_topology_authority
from .architecture_topology import compile_wall_body_slice1, derive_wall_body_polygons
from .geometry_scene import (
    canonical_geometry_scene_json,
    compile_geometry_scene,
    compile_geometry_scene_from_directory,
    geometry_scene_fingerprint,
)

__all__ = [
    "ContractBundle",
    "ContractError",
    "compile_scene",
    "compile_scene_from_directory",
    "load_contracts",
    "TopologyAuthorityV1",
    "load_topology_authority",
    "compile_wall_body_slice1",
    "derive_wall_body_polygons",
    "canonical_geometry_scene_json",
    "compile_geometry_scene",
    "compile_geometry_scene_from_directory",
    "geometry_scene_fingerprint",
]
