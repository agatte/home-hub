"""Offline #461 UX proposal; no source pause capability or writer exists here.

Witnesses are hypothetical trusted-adapter obligations, not authentication.
Production timestamp/target manual stamps cannot supply session lineage today.
Client hints are deliberately absent. Reservations retain the existing claim;
even a simulated verified commit neither releases a source nor creates a manual
owner. Future integration requires separately approved owner policy and the
existing final transition boundary/authority, never this model as a permit.
All times and validity windows are supplied; no duration policy is accepted.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class Owner(Enum):
    UNOWNED = "unowned"
    MANUAL = "manual"
    SCREEN_SYNC = "screen_sync"
    SCENE = "scene"
    EFFECT = "effect"
    TRANSIT = "transit"
    EXTERNAL = "external"
    UNKNOWN = "unknown"
    MULTIPLE = "multiple"


class Hold(Enum):
    SLEEPING = "sleeping"
    DND = "dnd"
    AWAY = "away"
    TRAVEL = "travel"
    EXTERNAL_OFF = "external_off"
    HOST_RETURNING = "host_returning"
    PROTECTED = "protected"
    PENDING_TRANSITION = "pending_transition"
    KITCHEN_FUNCTIONAL_PAIR = "kitchen_functional_pair"


class Status(Enum):
    ABSTAIN = "abstain"
    BLOCKED = "blocked"
    REVIEW = "review"
    REPEAT = "advisory_repeat"


class Reason(Enum):
    UNQUALIFIED = "unqualified"
    STALE = "stale"
    FIXTURE_CHANGED = "fixture_changed"
    HOLD = "hard_hold"
    UNKNOWN_OWNER = "unknown_owner"
    SOURCE_SCOPE = "source_scope_unapproved"
    TAKE_CONTROL = "take_control_review"
    SELECTION = "selection_review"
    LINEAGE_REQUIRED = "server_lineage_required"
    LINEAGE_CHANGED = "lineage_changed"
    SAME_SESSION = "hypothetical_same_session"


def _identity(value):
    if (type(value) is not str or not 1 <= len(value) <= 64
            or not all(c.isascii() and (c.isalnum() or c in "_-.:") for c in value)):
        raise ValueError("invalid bounded identity")


def _number(value):
    if type(value) not in (int, float) or not 0 <= value <= 2**53 or not isfinite(value):
        raise ValueError("invalid supplied time")


def _generation(value):
    if type(value) is not int or not 0 <= value <= 2**53:
        raise ValueError("invalid generation")


@dataclass(frozen=True, slots=True)
class Lineage:
    fixture: str
    session: str
    epoch: str
    generation: int
    intent_generation: int
    issued_at: float
    valid_until: float
    server_qualified: bool = False

    def __post_init__(self):
        for value in (self.fixture, self.session, self.epoch):
            _identity(value)
        for value in (self.generation, self.intent_generation):
            _generation(value)
        _number(self.issued_at)
        _number(self.valid_until)
        if self.issued_at >= self.valid_until or type(self.server_qualified) is not bool:
            raise ValueError("invalid lineage window or qualification")


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Hypothetical source-qualified producer identity, not authentication."""

    producer: str
    stream_kind: str
    incarnation: str
    generation: int

    def __post_init__(self):
        for value in (self.producer, self.stream_kind, self.incarnation):
            _identity(value)
        _generation(self.generation)


@dataclass(frozen=True, slots=True)
class Snapshot:
    fixture: str
    epoch: str
    generation: int
    intent_generation: int
    owner: Owner
    observed_at: float
    valid_until: float
    server_qualified: bool = False
    connected: bool = False
    safety_known: bool = False
    scope_known: bool = False
    holds: frozenset[Hold] = frozenset()
    lineage: Lineage | None = None
    source: SourceFingerprint | None = None

    def __post_init__(self):
        _identity(self.fixture)
        _identity(self.epoch)
        _generation(self.generation)
        _generation(self.intent_generation)
        _number(self.observed_at)
        _number(self.valid_until)
        if (self.observed_at >= self.valid_until or type(self.owner) is not Owner
                or any(type(v) is not bool for v in (
                    self.server_qualified, self.connected, self.safety_known, self.scope_known))
                or type(self.holds) is not frozenset
                or any(type(v) is not Hold for v in self.holds)
                or (self.lineage is not None and type(self.lineage) is not Lineage)
                or (self.source is not None and type(self.source) is not SourceFingerprint)):
            raise ValueError("invalid snapshot")


class Advisory:
    __slots__ = ()

    @property
    def permits_write(self):
        return False

    def __bool__(self):
        raise TypeError("proposal is not a physical permit")


@dataclass(frozen=True, slots=True)
class Assessment(Advisory):
    status: Status
    reason: Reason
    holds: frozenset[Hold] = frozenset()

    def __post_init__(self):
        if (type(self.status) is not Status or type(self.reason) is not Reason
                or type(self.holds) is not frozenset
                or any(type(v) is not Hold for v in self.holds)):
            raise ValueError("invalid assessment")


def assess(fixture: str, current: Snapshot, witness: Lineage | None, *, now: float):
    """Static reason codes only; never return identity inputs as display text."""
    _identity(fixture)
    _number(now)
    if type(current) is not Snapshot or (witness is not None and type(witness) is not Lineage):
        raise ValueError("invalid proposal input")
    if fixture != current.fixture:
        return Assessment(Status.ABSTAIN, Reason.FIXTURE_CHANGED)
    if not (current.server_qualified and current.connected and current.safety_known):
        return Assessment(Status.ABSTAIN, Reason.UNQUALIFIED)
    if not current.observed_at <= now < current.valid_until:
        return Assessment(Status.ABSTAIN, Reason.STALE)
    if current.holds:
        return Assessment(Status.BLOCKED, Reason.HOLD, current.holds)
    if current.owner in (Owner.UNKNOWN, Owner.MULTIPLE):
        return Assessment(Status.ABSTAIN, Reason.UNKNOWN_OWNER)
    if not current.scope_known or current.owner in (Owner.TRANSIT, Owner.EXTERNAL):
        return Assessment(Status.BLOCKED, Reason.SOURCE_SCOPE)
    if current.owner in (Owner.SCREEN_SYNC, Owner.SCENE, Owner.EFFECT):
        if current.source is None:
            return Assessment(Status.ABSTAIN, Reason.UNQUALIFIED)
        return Assessment(Status.REVIEW, Reason.TAKE_CONTROL)
    if current.owner is Owner.UNOWNED:
        return Assessment(Status.REVIEW, Reason.SELECTION)
    if witness is None or current.lineage is None:
        return Assessment(Status.REVIEW, Reason.LINEAGE_REQUIRED)
    if not (witness.server_qualified and current.lineage.server_qualified):
        return Assessment(Status.ABSTAIN, Reason.UNQUALIFIED)
    if not witness.issued_at <= now < witness.valid_until:
        return Assessment(Status.REVIEW, Reason.STALE)
    if (witness != current.lineage or witness.fixture != fixture
            or witness.epoch != current.epoch or witness.generation != current.generation
            or witness.intent_generation != current.intent_generation):
        return Assessment(Status.REVIEW, Reason.LINEAGE_CHANGED)
    return Assessment(Status.REPEAT, Reason.SAME_SESSION)


class Event(Enum):
    REVIEW_CONFIRMED = "review_confirmed"
    AWAITED = "awaited"
    CANCEL = "cancel"
    RESTART = "restart"


class Phase(Enum):
    RESERVED = "proposal_reserved"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class Reservation(Advisory):
    """Review bookkeeping only, not an owner lock or lease.

Original source claim is always retained. Pause/release and verified commit
capabilities are missing; no event here implements either. Terminal states
cannot be resurrected.
"""
    claim: Snapshot
    phase: Phase

    def __post_init__(self):
        if type(self.claim) is not Snapshot or type(self.phase) is not Phase:
            raise ValueError("invalid reservation state")


def reduce_handoff(reservation: Reservation | None, event: Event, current: Snapshot,
                   *, now: float) -> Reservation:
    if type(event) is not Event or type(current) is not Snapshot:
        raise ValueError("invalid handoff input")
    _number(now)
    if reservation is not None and type(reservation) is not Reservation:
        raise ValueError("invalid reservation")
    if reservation is not None and reservation.phase is not Phase.RESERVED:
        return reservation
    eligible = assess(current.fixture, current, None, now=now).reason is Reason.TAKE_CONTROL
    if reservation is None:
        phase = (Phase.RESERVED if eligible and event is Event.REVIEW_CONFIRMED
                 else Phase.INVALIDATED)
        return Reservation(current, phase)
    if (not eligible or current != reservation.claim
            or event in (Event.AWAITED, Event.CANCEL, Event.RESTART)):
        return Reservation(reservation.claim, Phase.INVALIDATED)
    # Review bookkeeping never fabricates a commit, source release, or owner.
    return reservation
