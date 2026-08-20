"""Offline compiler for the approved Apartment Canvas semantic contracts.

This package deliberately produces no render geometry.  A later adapter owns
the contract-space to renderer-space transform.
"""

from .compiler import compile_scene, compile_scene_from_directory
from .contracts import ContractBundle, ContractError, load_contracts

__all__ = [
    "ContractBundle",
    "ContractError",
    "compile_scene",
    "compile_scene_from_directory",
    "load_contracts",
]
