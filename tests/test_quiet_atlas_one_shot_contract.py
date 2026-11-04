"""Synthetic offline proposals only; no application or bridge is started.

Isolated invocation (avoids importing the app conftest/config/.env):
python -B -m pytest --noconftest -p no:cacheprovider -q tests/test_quiet_atlas_one_shot_contract.py
The broader integration/authority suite requires the normal fake-fixture conftest.
"""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from backend.services import quiet_atlas_one_shot_contract as contract
from backend.services.quiet_atlas_one_shot_contract import (
    AbsoluteTarget, Assessment, Observation, ObservationSource, Owner, Reason,
    Status, assess_one_shot,
)


def snapshot(**changes):
    return replace(Observation(
        fixture_id="2", observed_at=100, source=ObservationSource.SERVER_QUALIFIED,
        connected=True, reachable=True, owners_known=True, protected=False,
        away=False, external_off=False, host_return=False, sleeping=False,
        automation_enabled=True, pending_scene=False, pending_transition=False, dnd=False,
    ), **changes)


def assess(observation=None, target=None, now=101):
    return assess_one_shot(
        AbsoluteTarget("2", bri=80) if target is None else target,
        snapshot() if observation is None else observation, now=now,
    )


@pytest.mark.parametrize("target", [
    AbsoluteTarget("2", on=True), AbsoluteTarget("2", on=False),
    AbsoluteTarget("2", bri=1), AbsoluteTarget("2", bri=254),
])
def test_positive_is_always_advisory(target):
    result = assess(target=target)
    assert result == Assessment(Status.ELIGIBLE, Reason.ADVISORY_ELIGIBLE)
    assert result.advisory_only is True
    assert result.permits_write is False
    with pytest.raises(TypeError, match="advisory"):
        bool(result)


@pytest.mark.parametrize("target", [
    {}, [], "2", AbsoluteTarget(""), AbsoluteTarget(" 2", on=True),
    AbsoluteTarget(2, on=True), AbsoluteTarget("2"),
    AbsoluteTarget("2", on=True, bri=80), AbsoluteTarget("2", on=1),
    *[AbsoluteTarget("2", bri=value) for value in (True, False, 0, -1, 255, 1.5, "80")],
])
def test_invalid_targets(target):
    assert assess(target=target) == Assessment(Status.BLOCKED, Reason.INVALID_TARGET)


@pytest.mark.parametrize("keyword", ["hue", "sat", "ct", "force", "bypass", "targets"])
def test_target_has_no_extra_payload_or_bypass(keyword):
    with pytest.raises(TypeError):
        AbsoluteTarget("2", **{keyword: 1})


@pytest.mark.parametrize("field,unsafe,status,reason", [
    ("connected", False, Status.UNAVAILABLE, Reason.DISCONNECTED),
    ("reachable", False, Status.UNAVAILABLE, Reason.UNREACHABLE),
    ("owners_known", False, Status.UNAVAILABLE, Reason.UNKNOWN_OWNER),
    ("protected", True, Status.BLOCKED, Reason.PROTECTED),
    ("away", True, Status.BLOCKED, Reason.AWAY),
    ("external_off", True, Status.BLOCKED, Reason.EXTERNAL_OFF),
    ("host_return", True, Status.BLOCKED, Reason.HOST_RETURN),
    ("sleeping", True, Status.BLOCKED, Reason.SLEEPING),
    ("automation_enabled", False, Status.BLOCKED, Reason.AUTOMATION_DISABLED),
    ("pending_scene", True, Status.BLOCKED, Reason.PENDING_SCENE),
    ("pending_transition", True, Status.BLOCKED, Reason.PENDING_TRANSITION),
    ("dnd", True, Status.BLOCKED, Reason.DND),
])
def test_all_hard_gates_and_unknowns(field, unsafe, status, reason):
    for value in (unsafe, None):
        result = assess(snapshot(**{field: value}, owners=frozenset({Owner.MANUAL})))
        assert result == Assessment(status, reason)
        assert result.permits_write is False


@pytest.mark.parametrize("owner,reason", [
    (Owner.MANUAL, Reason.MANUAL), (Owner.SCREEN_SYNC, Reason.SCREEN_SYNC),
    (Owner.TRANSIT, Reason.TRANSIT), (Owner.SCENE, Reason.SCENE),
    (Owner.EFFECT, Reason.EFFECT), (Owner.EXTERNAL, Reason.EXTERNAL_OWNER),
])
def test_owner_conflicts_are_distinct_and_never_allow_action(owner, reason):
    result = assess(snapshot(owners=frozenset({owner})))
    assert result == Assessment(Status.DECISION_REQUIRED, reason)
    assert result.permits_write is False


@pytest.mark.parametrize("source", [ObservationSource.CLIENT_RECEIPT, ObservationSource.UNKNOWN])
def test_client_receipt_is_never_server_evidence(source):
    assert assess(snapshot(source=source)).reason is Reason.UNQUALIFIED_OBSERVATION


@pytest.mark.parametrize("now", [99, 105, float("nan"), float("inf"), True, "101", -1, 10**400])
def test_bad_or_expired_time_fails_closed(now):
    assert assess(now=now).status is Status.UNAVAILABLE


@pytest.mark.parametrize("change", [
    {"observed_at": float("nan")}, {"observed_at": float("inf")},
    {"observed_at": True}, {"source": "server_qualified"},
    {"owners": {Owner.MANUAL}}, {"owners": frozenset({"manual"})},
    {"fixture_id": []}, {"connected": 1}, {"protected": "false"},
])
def test_malformed_observation(change):
    assert assess(snapshot(**change)).reason is Reason.INVALID_OBSERVATION


def test_mismatch_and_stable_precedence():
    assert assess(snapshot(fixture_id="3")).reason is Reason.FIXTURE_MISMATCH
    many = snapshot(connected=False, protected=True, away=True,
                    owners=frozenset(Owner))
    assert assess(many).reason is Reason.DISCONNECTED
    assert assess(replace(many, connected=True)).reason is Reason.PROTECTED
    assert assess(replace(many, connected=True, protected=False)).reason is Reason.AWAY
    assert assess(snapshot(owners=frozenset(Owner))).reason is Reason.MANUAL
    assert assess(many, AbsoluteTarget("2")).reason is Reason.INVALID_TARGET
    assert assess(replace(many, source=ObservationSource.CLIENT_RECEIPT)).reason is (
        Reason.UNQUALIFIED_OBSERVATION
    )


def test_changed_observation_revokes_eligibility_without_mutation_or_lockout():
    original = snapshot()
    target = AbsoluteTarget("2", bri=80)
    before = replace(original)
    assert assess(original, target).status is Status.ELIGIBLE
    for changed in (replace(original, owners=frozenset({Owner.SCREEN_SYNC})),
                    replace(original, pending_transition=True),
                    replace(original, connected=False)):
        assert assess(changed, target).status is not Status.ELIGIBLE
    assert assess(original, target, now=105).status is Status.UNAVAILABLE
    assert assess(replace(original, observed_at=105), target, now=105).status is Status.ELIGIBLE
    assert original == before
    assert target == AbsoluteTarget("2", bri=80)


@pytest.mark.parametrize("value", [AbsoluteTarget("2", bri=80), snapshot(),
                                  Assessment(Status.ELIGIBLE, Reason.ADVISORY_ELIGIBLE)])
def test_values_are_immutable(value):
    with pytest.raises(FrozenInstanceError):
        setattr(value, fields(value)[0].name, None)


def test_module_has_no_io_writer_registration_or_shared_mutable_state():
    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    # Strict import allowlist excludes even transitive service/config/API imports.
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(node, ast.ImportFrom) for node in imports)
    assert {node.module for node in imports} == {"dataclasses", "enum", "math", "typing"}
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = [node.func for node in calls if isinstance(node.func, ast.Attribute)]
    assert all(isinstance(func.value, ast.Name) and func.value.id == "value"
               and func.attr == "strip" for func in attributes)
    assert all(isinstance(node.func, (ast.Name, ast.Attribute)) for node in calls)
    assert {node.func.id for node in calls if isinstance(node.func, ast.Name)} <= {
        "dataclass", "frozenset", "TypeError", "type", "bool", "isfinite", "any",
        "getattr", "fields", "_fixture_id", "_seconds", "Assessment",
    }
    assert not any(isinstance(value, (dict, list, set))
                   for name, value in vars(contract).items() if not name.startswith("__"))
    assert not hasattr(contract, "router")
    assert not hasattr(contract, "set_light")
    # No backend import or registration elsewhere in the application.
    backend = Path(contract.__file__).parents[1]
    for path in backend.rglob("*.py"):
        if path != Path(contract.__file__):
            assert "quiet_atlas_one_shot_contract" not in path.read_text(encoding="utf-8")
