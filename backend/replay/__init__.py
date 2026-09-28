"""Offline navigation replay contracts, virtual time, and closed-root support.

The data-layer modules remain production-service-free. The optional navigation
composition root imports only the reviewed decision participants named by the
accepted navigation-v1 architecture.
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
