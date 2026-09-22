"""Offline-only navigation replay bundle contracts.

This package is data/validation only and intentionally imports no production services.
"""

from .schema import PROFILE_ID, SCHEMA_ID
from .validate import (
    BundleErrorCode,
    BundleValidationError,
    IncidentBundleV1,
    load_fixture_bundle,
)

__all__ = [
    "BundleErrorCode",
    "BundleValidationError",
    "IncidentBundleV1",
    "PROFILE_ID",
    "SCHEMA_ID",
    "load_fixture_bundle",
]
