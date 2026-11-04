"""Synthetic #461 continuity evidence; no application fixtures or physical I/O."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from backend.services import quiet_atlas_manual_session_proposal as model
from backend.services.quiet_atlas_manual_session_proposal import (
    Event, Hold, Lineage, Owner, Phase, Reason, Snapshot, SourceFingerprint,
    Status, assess, reduce_handoff,
)


def lineage(**changes):
    return replace(Lineage("2", "session-a", "boot-a", 4, 7, 100, 110, True), **changes)


def source(**changes):
    return replace(SourceFingerprint("desktop", "watching", "stream-a", 5), **changes)


def snapshot(**changes):
    if changes.get("owner") in (Owner.SCREEN_SYNC, Owner.SCENE, Owner.EFFECT):
        changes.setdefault("source", source())
    return replace(Snapshot(
        "2", "boot-a", 4, 7, Owner.MANUAL, 100, 110,
        True, True, True, True, lineage=lineage(),
    ), **changes)


def evaluate(current=None, witness=None, now=101):
    return assess("2", snapshot() if current is None else current,
                  lineage() if witness is None else witness, now=now)


def test_repeat_is_only_hypothetical_server_continuity():
    current = snapshot()
    for now in (100, 101, 109):
        result = evaluate(current, now=now)
        assert result.status is Status.REPEAT
        assert result.permits_write is False
        with pytest.raises(TypeError):
            bool(result)
    assert current == snapshot()


@pytest.mark.parametrize("owner,reason,status", [
    (Owner.UNOWNED, Reason.SELECTION, Status.REVIEW),
    (Owner.SCREEN_SYNC, Reason.TAKE_CONTROL, Status.REVIEW),
    (Owner.SCENE, Reason.TAKE_CONTROL, Status.REVIEW),
    (Owner.EFFECT, Reason.TAKE_CONTROL, Status.REVIEW),
    (Owner.TRANSIT, Reason.SOURCE_SCOPE, Status.BLOCKED),
    (Owner.EXTERNAL, Reason.SOURCE_SCOPE, Status.BLOCKED),
    (Owner.UNKNOWN, Reason.UNKNOWN_OWNER, Status.ABSTAIN),
    (Owner.MULTIPLE, Reason.UNKNOWN_OWNER, Status.ABSTAIN),
])
def test_source_specific_review_even_with_old_matching_lineage(owner, reason, status):
    result = evaluate(snapshot(owner=owner))
    assert (result.status, result.reason) == (status, reason)
    assert result.permits_write is False


@pytest.mark.parametrize("hold", list(Hold))
def test_hard_holds_remain_distinct_and_cannot_be_confirmed(hold):
    current = snapshot(owner=Owner.SCREEN_SYNC, holds=frozenset({hold}))
    result = evaluate(current)
    assert result.status is Status.BLOCKED
    assert result.holds == frozenset({hold})
    assert reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101).phase is (
        Phase.INVALIDATED
    )


@pytest.mark.parametrize("changes,reason", [
    ({"fixture": "3"}, Reason.FIXTURE_CHANGED),
    ({"epoch": "boot-b"}, Reason.LINEAGE_CHANGED),
    ({"generation": 5}, Reason.LINEAGE_CHANGED),
    ({"intent_generation": 8}, Reason.LINEAGE_CHANGED),
    ({"lineage": None}, Reason.LINEAGE_REQUIRED),
    ({"lineage": lineage(session="superseded")}, Reason.LINEAGE_CHANGED),
    ({"server_qualified": False}, Reason.UNQUALIFIED),
    ({"connected": False}, Reason.UNQUALIFIED),
    ({"safety_known": False}, Reason.UNQUALIFIED),
    ({"scope_known": False}, Reason.SOURCE_SCOPE),
    ({"observed_at": 102}, Reason.STALE),
    ({"valid_until": 101}, Reason.STALE),
])
def test_changed_evidence_closes_repeat_path(changes, reason):
    assert evaluate(snapshot(**changes)).reason is reason


@pytest.mark.parametrize("changes,reason", [
    ({"fixture": "3"}, Reason.LINEAGE_CHANGED),
    ({"session": "client-hint"}, Reason.LINEAGE_CHANGED),
    ({"epoch": "boot-b"}, Reason.LINEAGE_CHANGED),
    ({"generation": 5}, Reason.LINEAGE_CHANGED),
    ({"intent_generation": 8}, Reason.LINEAGE_CHANGED),
    ({"issued_at": 102}, Reason.STALE),
    ({"valid_until": 101}, Reason.STALE),
    ({"server_qualified": False}, Reason.UNQUALIFIED),
])
def test_client_hint_old_stamp_and_superseded_witness_cannot_prove_continuity(changes, reason):
    assert evaluate(witness=lineage(**changes)).reason is reason


def test_legacy_timestamp_target_is_insufficient():
    assert assess("2", snapshot(lineage=None), None, now=101).reason is Reason.LINEAGE_REQUIRED
    with pytest.raises(ValueError):
        assess("2", snapshot(), {"session": "session-a", "timestamp": 100}, now=101)
    with pytest.raises(TypeError):
        Lineage("2", "s", "b", 1, 1, 100, 110, client_hint="session-a")


@pytest.mark.parametrize("owner", [Owner.SCREEN_SYNC, Owner.SCENE, Owner.EFFECT])
def test_review_reservation_retains_claim_and_does_not_create_manual_lineage(owner):
    current = snapshot(owner=owner, lineage=None)
    reserved = reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101)
    assert reserved.phase is Phase.RESERVED
    reconfirmed = reduce_handoff(reserved, Event.REVIEW_CONFIRMED, current, now=101)
    assert reconfirmed == reserved
    for result in (reserved, reconfirmed):
        assert result.claim == current
        assert result.claim.owner is owner
        assert result.claim.lineage is None
        assert result.permits_write is False
        with pytest.raises(TypeError):
            bool(result)
    assert evaluate(current).reason is Reason.TAKE_CONTROL
    assert list(Phase) == [Phase.RESERVED, Phase.INVALIDATED]


@pytest.mark.parametrize("event", [Event.CANCEL, Event.RESTART, Event.AWAITED])
def test_invalidation_is_terminal_even_when_old_snapshot_returns(event):
    current = snapshot(owner=Owner.SCREEN_SYNC)
    reserved = reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101)
    invalid = reduce_handoff(reserved, event, current, now=101)
    assert invalid.phase is Phase.INVALIDATED
    for later in Event:
        assert reduce_handoff(invalid, later, current, now=101) == invalid


@pytest.mark.parametrize("changes", [
    {"fixture": "3"}, {"epoch": "boot-b"}, {"generation": 5},
    {"intent_generation": 8}, {"owner": Owner.SCENE}, {"owner": Owner.MANUAL},
    {"owner": Owner.MULTIPLE}, {"connected": False}, {"scope_known": False},
    {"observed_at": 101}, {"holds": frozenset({Hold.DND})},
])
def test_source_reacquisition_concurrent_intent_and_changed_evidence_invalidate(changes):
    original = snapshot(owner=Owner.SCREEN_SYNC)
    reserved = reduce_handoff(None, Event.REVIEW_CONFIRMED, original, now=101)
    result = reduce_handoff(reserved, Event.REVIEW_CONFIRMED,
                            replace(original, **changes), now=101)
    assert result.phase is Phase.INVALIDATED
    assert result.claim == original


def test_expiry_and_no_review_cannot_simulate_commit():
    current = snapshot(owner=Owner.SCENE)
    assert reduce_handoff(None, Event.AWAITED, current, now=101).phase is (
        Phase.INVALIDATED
    )
    reserved = reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101)
    assert reduce_handoff(reserved, Event.REVIEW_CONFIRMED, current, now=110).phase is (
        Phase.INVALIDATED
    )
    assert not hasattr(Event, "VERIFIED_COMMIT")
    assert not hasattr(Phase, "VERIFIED")


@pytest.mark.parametrize("bad", [True, -1, float("inf"), float("nan"), 10**400, "101"])
def test_strict_supplied_time(bad):
    with pytest.raises(ValueError):
        evaluate(now=bad)
    with pytest.raises(ValueError):
        lineage(issued_at=bad)


@pytest.mark.parametrize("changes", [
    {"fixture": ""}, {"fixture": "a" * 65}, {"fixture": "<script>"},
    {"fixture": "灯"}, {"generation": True}, {"intent_generation": 1.0},
    {"server_qualified": 1}, {"valid_until": 100},
])
def test_strict_bounded_lineage(changes):
    with pytest.raises(ValueError):
        lineage(**changes)


@pytest.mark.parametrize("changes", [
    {"owner": "manual"}, {"holds": set()}, {"holds": frozenset({"dnd"})},
    {"connected": 1}, {"lineage": {}}, {"scope_known": None},
    {"source": {"producer": "desktop"}},
])
def test_strict_snapshot(changes):
    with pytest.raises(ValueError):
        snapshot(**changes)


def test_immutable_and_no_identity_display():
    for value in (lineage(), snapshot(), evaluate()):
        with pytest.raises((FrozenInstanceError, AttributeError)):
            value.fixture = "changed"
    assert set(evaluate().__dataclass_fields__) == {"status", "reason", "holds"}


@pytest.mark.parametrize("owner", [Owner.SCREEN_SYNC, Owner.SCENE, Owner.EFFECT])
def test_owner_review_needs_exact_server_source_fingerprint(owner):
    current = snapshot(owner=owner, source=None)
    assert evaluate(current).status is Status.ABSTAIN
    assert evaluate(current).reason is Reason.UNQUALIFIED
    assert reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101).phase is (
        Phase.INVALIDATED
    )


@pytest.mark.parametrize("change", [
    {"producer": "laptop"}, {"stream_kind": "gaming"},
    {"incarnation": "stream-b"}, {"generation": 6},
])
def test_same_fixture_generation_but_different_producer_stream_or_reboot_invalidates(change):
    current = snapshot(owner=Owner.SCREEN_SYNC)
    reserved = reduce_handoff(None, Event.REVIEW_CONFIRMED, current, now=101)
    assert reserved.phase is Phase.RESERVED
    changed = replace(current, source=source(**change))
    assert changed.fixture == current.fixture
    assert changed.generation == current.generation
    assert changed.intent_generation == current.intent_generation
    assert reduce_handoff(reserved, Event.REVIEW_CONFIRMED, changed, now=101).phase is (
        Phase.INVALIDATED
    )
    assert reserved.claim == current  # Existing owner remains protected


@pytest.mark.parametrize("change", [
    {"producer": ""}, {"stream_kind": "x" * 65}, {"incarnation": "<script>"},
    {"producer": "灯"}, {"generation": True}, {"generation": -1},
])
def test_source_fingerprint_requires_bounded_typed_parts(change):
    with pytest.raises(ValueError):
        source(**change)


@pytest.mark.parametrize("event", [None, "review_confirmed", 1, True])
def test_unrecognized_events_do_not_create_reservations(event):
    current = snapshot(owner=Owner.SCREEN_SYNC)
    with pytest.raises(ValueError):
        reduce_handoff(None, event, current, now=101)


def test_invalid_reservation_input_cannot_become_a_review():
    with pytest.raises(ValueError):
        reduce_handoff({"phase": "reserved"}, Event.REVIEW_CONFIRMED,
                       snapshot(owner=Owner.SCENE), now=101)


def test_static_no_io_registration_or_active_imports():
    path = Path(model.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(n, ast.ImportFrom) for n in imports)
    assert {n.module for n in imports} == {"dataclasses", "enum", "math"}
    assert not any(isinstance(n, (ast.AsyncFunctionDef, ast.Await)) for n in ast.walk(tree))
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert {n.id for n in calls if isinstance(n, ast.Name)} <= {
        "type", "len", "all", "any", "isfinite", "ValueError", "TypeError",
        "dataclass", "frozenset", "_identity", "_number", "_generation", "assess",
        "Assessment", "Reservation",
    }
    assert all(isinstance(n.value, ast.Name) and n.value.id == "c"
               and n.attr in {"isascii", "isalnum"}
               for n in calls if isinstance(n, ast.Attribute))
    for other in path.parents[1].rglob("*.py"):
        if other != path:
            assert path.stem not in other.read_text(encoding="utf-8")
