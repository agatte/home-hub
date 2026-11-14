"""Read-only Hue v1 fixture identity audit; never performs a bridge write.

This audits structure of an operator-enrolled v1 ID -> Hue uniqueid binding
against a raw get_api() snapshot. It does not enroll a bulb, prove bridge TLS
identity, authenticate an API caller, or authorize actuation. The public
result contains only reviewed L1-L6 numbers and status enums; never return,
log, or expose bridge identifiers, names or the full raw inventory.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from backend.services.light_state_calculator import ALL_LIGHT_IDS

# All statuses are non-authorizing observations. "matched" is structural
# comparison only; a compromised/unauthenticated bridge could forge the input.
MATCHED = "matched"
UNENROLLED = "unenrolled"
INVALID_ENROLLMENT = "invalid_enrollment"
INVENTORY_UNAVAILABLE = "inventory_unavailable"
MISSING = "missing"
MISSING_UNIQUEID = "missing_uniqueid"
DUPLICATE_UNIQUEID = "duplicate_uniqueid"
REINDEXED = "reindexed"
MISMATCHED = "mismatched"


def _stable_identifier(value: object) -> bool:
    """Reject malformed evidence without normalizing away an identity change."""
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value == value.strip()
        and value.isascii()
        and all(32 < ord(char) < 127 for char in value)
    )


def audit_hue_v1_fixture_bindings(
    enrolled: Mapping[str, str] | None,
    bridge_api: object,
) -> dict[str, str]:
    """Compare operator-approved bindings with an untrusted read-only snapshot.

    Enrolled bindings must come from a separately approved enrollment process,
    never this bridge payload. The bridge_api argument is the original Hue v1
    get_api() response, not HomeHub's stripped public light list. No new bridge
    ID is auto-enrolled, and changed mappings are never accepted by name.
    Structural results cannot prove trusted transport or authorize lighting.
    """
    ids = tuple(ALL_LIGHT_IDS)
    if not isinstance(enrolled, Mapping):
        return dict.fromkeys(ids, UNENROLLED if enrolled is None else INVALID_ENROLLMENT)
    if (
        any(type(k) is not str or k not in ids or not _stable_identifier(v)
            for k, v in enrolled.items())
        or len(set(enrolled.values())) != len(enrolled)
    ):
        return dict.fromkeys(ids, INVALID_ENROLLMENT)

    if not isinstance(bridge_api, Mapping):
        return dict.fromkeys(ids, INVENTORY_UNAVAILABLE)
    observed = bridge_api.get("lights")
    if not isinstance(observed, Mapping):
        return dict.fromkeys(ids, INVENTORY_UNAVAILABLE)

    # Inspect ALL bridge rows for duplicate identifiers, even unexpected IDs.
    # An unexpected ID must never be auto-enrolled as a HomeHub fixture.
    current: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for key, row in observed.items():
        if type(key) is not str or not isinstance(row, Mapping):
            continue
        candidate = row.get("uniqueid")
        if _stable_identifier(candidate):
            current[key] = candidate
            counts[candidate] += 1

    enrolled_owner = {uid: lid for lid, uid in enrolled.items()}
    statuses: dict[str, str] = {}
    for lid in ids:
        if lid not in enrolled:
            statuses[lid] = UNENROLLED
        elif lid not in observed:
            statuses[lid] = MISSING
        elif lid not in current:
            statuses[lid] = MISSING_UNIQUEID
        elif counts[current[lid]] != 1:
            statuses[lid] = DUPLICATE_UNIQUEID
        elif current[lid] == enrolled[lid]:
            statuses[lid] = MATCHED
        elif current[lid] in enrolled_owner:
            statuses[lid] = REINDEXED
        else:
            statuses[lid] = MISMATCHED
    return statuses
