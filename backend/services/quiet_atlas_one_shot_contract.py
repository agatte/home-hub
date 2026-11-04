"""PROPOSED offline policy only: no actuation, authority, receipts or I/O.

Inputs must eventually come from a trusted server adapter, never REST client
claims. This module authenticates nothing. Reassess changed observations; no
result reserves a fixture or survives as a commit-time permission. A future
writer must reuse LightingTransitionBoundary and LightingAuthority, including
AutomationEngine.validate_lighting_lease at delegated mutation, after policy
approval. No competing lock, lease, generation or operation identity lives here.
"""

from dataclasses import dataclass, fields
from enum import Enum
from math import isfinite
from typing import Literal


class Status(str, Enum):
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    DECISION_REQUIRED = "decision_required"
    ELIGIBLE = "eligible"


class Reason(str, Enum):
    INVALID_TARGET = "invalid_target"
    INVALID_OBSERVATION = "invalid_observation"
    FIXTURE_MISMATCH = "fixture_mismatch"
    UNQUALIFIED_OBSERVATION = "unqualified_observation"
    STALE_OBSERVATION = "stale_observation"
    DISCONNECTED = "disconnected"
    UNREACHABLE = "unreachable"
    UNKNOWN_OWNER = "unknown_owner"
    PROTECTED = "protected"
    AWAY = "away"
    EXTERNAL_OFF = "external_off"
    HOST_RETURN = "host_return"
    SLEEPING = "sleeping"
    AUTOMATION_DISABLED = "automation_disabled"
    PENDING_SCENE = "pending_scene"
    PENDING_TRANSITION = "pending_transition"
    DND = "dnd"
    MANUAL = "manual"
    SCREEN_SYNC = "screen_sync"
    TRANSIT = "transit"
    SCENE = "scene"
    EFFECT = "effect"
    EXTERNAL_OWNER = "external_owner"
    ADVISORY_ELIGIBLE = "advisory_eligible"


class Owner(str, Enum):
    MANUAL = "manual"
    SCREEN_SYNC = "screen_sync"
    TRANSIT = "transit"
    SCENE = "scene"
    EFFECT = "effect"
    EXTERNAL = "external"


class ObservationSource(str, Enum):
    SERVER_QUALIFIED = "server_qualified"
    CLIENT_RECEIPT = "client_receipt"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AbsoluteTarget:
    fixture_id: str
    on: bool | None = None
    bri: int | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """One coherent server snapshot, including fresh, source-qualified owners.

    Times use the same caller-supplied monotonic seconds domain as assessment.
    SERVER_QUALIFIED asserts both fixture telemetry and ownership provenance;
    it is an adapter obligation, not something a client may self-certify.
    None means unknown and fails closed. Empty owners means known unowned only
    when owners_known is True. SCREEN_SYNC means fresh source-qualified scope;
    expiry/release must be established by the existing owner, not inferred here.
    """

    fixture_id: str
    observed_at: float
    source: ObservationSource = ObservationSource.UNKNOWN
    owners: frozenset[Owner] = frozenset()
    connected: bool | None = None
    reachable: bool | None = None
    owners_known: bool | None = None
    protected: bool | None = None
    away: bool | None = None
    external_off: bool | None = None
    host_return: bool | None = None
    sleeping: bool | None = None
    automation_enabled: bool | None = None
    pending_scene: bool | None = None
    pending_transition: bool | None = None
    dnd: bool | None = None


@dataclass(frozen=True, slots=True)
class Assessment:
    status: Status
    reason: Reason

    @property
    def advisory_only(self) -> Literal[True]:
        return True

    @property
    def permits_write(self) -> Literal[False]:
        return False

    def __bool__(self) -> bool:
        raise TypeError("Assessment is advisory only; inspect status explicitly")


def _fixture_id(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _seconds(value: object) -> bool:
    # Bound integer conversion as well: malformed huge integers must not raise
    # OverflowError during float arithmetic or finite checks.
    return type(value) in (int, float) and 0 <= value <= 2**53 and isfinite(value)


def assess_one_shot(
    target: AbsoluteTarget, observation: Observation, *, now: float,
) -> Assessment:
    """Assess one absolute power OR brightness proposal; never grant a write.

    Stable first-reason precedence: target, observation shape/identity/source/
    age, availability, unknown owners, safety/lifecycle, then intent conflicts.
    Five seconds is a PROPOSED offline freshness ceiling, not accepted policy.
    Future code must collect/revalidate under the existing final-write boundary;
    calling this function outside it provides no race protection.
    """
    if (
        type(target) is not AbsoluteTarget or not _fixture_id(target.fixture_id)
        or not (
            (type(target.on) is bool and target.bri is None)
            or (target.on is None and type(target.bri) is int and 1 <= target.bri <= 254)
        )
    ):
        return Assessment(Status.BLOCKED, Reason.INVALID_TARGET)
    if (
        type(observation) is not Observation
        or not _fixture_id(observation.fixture_id)
        or not _seconds(now) or not _seconds(observation.observed_at)
        or type(observation.source) is not ObservationSource
        or type(observation.owners) is not frozenset
        or any(type(owner) is not Owner for owner in observation.owners)
        or any(
            getattr(observation, field.name) is not None
            and type(getattr(observation, field.name)) is not bool
            for field in fields(Observation)
            if field.name not in {"fixture_id", "observed_at", "source", "owners"}
        )
    ):
        return Assessment(Status.UNAVAILABLE, Reason.INVALID_OBSERVATION)
    if target.fixture_id != observation.fixture_id:
        return Assessment(Status.BLOCKED, Reason.FIXTURE_MISMATCH)
    if observation.source is not ObservationSource.SERVER_QUALIFIED:
        return Assessment(Status.UNAVAILABLE, Reason.UNQUALIFIED_OBSERVATION)
    if not 0 <= now - observation.observed_at < 5:
        return Assessment(Status.UNAVAILABLE, Reason.STALE_OBSERVATION)
    for value, reason in (
        (observation.connected, Reason.DISCONNECTED),
        (observation.reachable, Reason.UNREACHABLE),
        (observation.owners_known, Reason.UNKNOWN_OWNER),
    ):
        if value is not True:
            return Assessment(Status.UNAVAILABLE, reason)
    for value, safe, reason in (
        (observation.protected, False, Reason.PROTECTED),
        (observation.away, False, Reason.AWAY),
        (observation.external_off, False, Reason.EXTERNAL_OFF),
        (observation.host_return, False, Reason.HOST_RETURN),
        (observation.sleeping, False, Reason.SLEEPING),
        (observation.automation_enabled, True, Reason.AUTOMATION_DISABLED),
        (observation.pending_scene, False, Reason.PENDING_SCENE),
        (observation.pending_transition, False, Reason.PENDING_TRANSITION),
        (observation.dnd, False, Reason.DND),
    ):
        if value is not safe:
            return Assessment(Status.BLOCKED, reason)
    for owner, reason in (
        (Owner.MANUAL, Reason.MANUAL),
        (Owner.SCREEN_SYNC, Reason.SCREEN_SYNC),
        (Owner.TRANSIT, Reason.TRANSIT),
        (Owner.SCENE, Reason.SCENE),
        (Owner.EFFECT, Reason.EFFECT),
        (Owner.EXTERNAL, Reason.EXTERNAL_OWNER),
    ):
        if owner in observation.owners:
            return Assessment(Status.DECISION_REQUIRED, reason)
    return Assessment(Status.ELIGIBLE, Reason.ADVISORY_ELIGIBLE)
