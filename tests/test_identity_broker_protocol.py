"""Disposable offline fixtures only; no runtime imports, identities or secrets."""
import json
import shutil
import sqlite3
import threading
from contextlib import closing

import pytest

from tests.support.synthetic_broker import Broker, Crash, Peer, Quarantined, digest

ADMIN, BACKEND = Peer(200), Peer(100)


@pytest.fixture
def rig(tmp_path):
    gate = threading.Lock()
    def opened(**kwargs):
        return Broker(tmp_path, gate, **kwargs)
    opened().admin(ADMIN, True, "bootstrap")
    return tmp_path, opened


def issue(opened, confirmed=True):
    result = opened().admin(ADMIN, True, "enroll")
    if confirmed:
        opened().admin(ADMIN, True, "delivery_confirmed", id=result.id)
    return result


def crash_at(point):
    def hook(actual):
        if actual == point:
            raise Crash()
    return hook


def edit_state(path, change):
    with closing(sqlite3.connect(path / "registry.sqlite")) as db, db:
        state = json.loads(db.execute("SELECT state FROM security_state").fetchone()[0])
        change(state)
        db.execute("UPDATE security_state SET state=?", (json.dumps(state),))


def test_no_implicit_bootstrap(tmp_path):
    broker = Broker(tmp_path, threading.Lock())
    assert not broker.verify(BACKEND, "fake")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(PermissionError):
        broker.admin(BACKEND, True, "bootstrap")
    broker.admin(Peer(0), True, "bootstrap")
    with pytest.raises(Quarantined):
        broker.admin(ADMIN, True, "bootstrap")


@pytest.mark.parametrize("damage", ["missing", "corrupt", "mismatch", "pending", "registry_missing", "registry_corrupt"])
def test_broken_stores_never_auto_repair(rig, damage):
    path, opened = rig
    credential = issue(opened)
    if damage == "missing":
        (path / "journal.json").rename(path / "journal.evidence")
    elif damage == "corrupt":
        (path / "journal.json").write_text("broken")
    elif damage == "registry_missing":
        (path / "registry.sqlite").rename(path / "registry.evidence")
    elif damage == "registry_corrupt":
        (path / "registry.sqlite").write_bytes(b"not sqlite")
    else:
        record = json.loads((path / "journal.json").read_text())
        record["digest" if damage == "mismatch" else "status"] = "bad" if damage == "mismatch" else "PENDING"
        (path / "journal.json").write_text(json.dumps(record))
    before = (path / "journal.json").read_bytes() if (path / "journal.json").exists() else None
    for _ in range(3):
        assert not opened().verify(BACKEND, credential.token)
        assert "quarantined" in opened().diagnostics()
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "enroll")
    assert ((path / "journal.json").read_bytes() if (path / "journal.json").exists() else None) == before


@pytest.mark.parametrize("field", ["instance", "generation", "revision", "protocol", "minimum_code", "credentials", "sessions", "tickets"])
def test_complete_state_digest(rig, field):
    path, opened = rig
    credential = issue(opened)
    def mutate(state):
        state[field] = {"forged": True} if isinstance(state[field], dict) else "forged"
    edit_state(path, mutate)
    assert not opened().verify(BACKEND, credential.token)
    with pytest.raises(Quarantined):
        opened().admin(ADMIN, True, "revoke", id=credential.id)


@pytest.mark.parametrize("field,value", [("profile", "synthetic_display"), ("source", "forged"),
    ("expiry", 3000), ("revoked", True), ("verifier", "forged"), ("uncertain", True)])
def test_all_credential_fields_bound(rig, field, value):
    path, opened = rig
    credential = issue(opened)
    edit_state(path, lambda state: state["credentials"][credential.id].update({field: value}))
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("options", [{"code": 1}, {"deployment": "other"}, {"startup_floor": 3}])
def test_independent_fixture_startup_floor(rig, options):
    _, opened = rig
    credential = issue(opened)
    assert not opened(**options).verify(BACKEND, credential.token)
    with pytest.raises(Quarantined):
        opened(**options).admin(ADMIN, True, "enroll")


@pytest.mark.parametrize("peer,approval", [(BACKEND, True), (Peer(999), True), (ADMIN, False), (Peer(0), False), ("root", True)])
@pytest.mark.parametrize("command", ["enroll", "revoke", "rotate", "bootstrap", "recover_pending", "fresh_empty", "restore_intent_invalidate", "delivery_confirmed"])
def test_admin_role_boundary(rig, peer, approval, command):
    _, opened = rig
    with pytest.raises(PermissionError):
        opened().admin(peer, approval, command)


def test_same_uid_unknown_commands_and_no_admin_in_verify(rig):
    _, opened = rig
    credential = issue(opened)
    assert opened().verify(Peer(100), credential.token) is True
    assert opened().verify(BACKEND, credential.token, "fresh_empty") is False
    assert opened().verify(ADMIN, credential.token) is False
    assert not opened().verify(BACKEND, credential.token, claimed_source="root")
    with pytest.raises(PermissionError):
        opened().admin(ADMIN, True, "arbitrary_sql")
    assert not hasattr(opened().verify(BACKEND, credential.token), "admin")


def test_enroll_rotate_revoke_expiry_and_diagnostics(rig):
    path, opened = rig
    first = issue(opened)
    assert opened().verify(BACKEND, first.token, "write")
    assert not opened().verify(BACKEND, first.token, now=2000)
    second = opened().admin(ADMIN, True, "rotate", id=first.id)
    assert not opened().verify(BACKEND, first.token)
    assert not opened().verify(BACKEND, second.token)
    opened().admin(ADMIN, True, "delivery_confirmed", id=second.id)
    assert opened().verify(BACKEND, second.token)
    opened().admin(ADMIN, True, "revoke", id=second.id)
    for _ in range(3):
        assert not opened().verify(BACKEND, second.token)
    assert second.token not in repr(second) + repr(opened()) + opened().diagnostics()
    assert second.token.encode() not in (path / "registry.sqlite").read_bytes()
    assert second.token not in (path / "journal.json").read_text()


@pytest.mark.parametrize("point,valid,recoverable", [
    ("before_pending", True, False), ("after_pending", False, False),
    ("after_sqlite", False, True), ("after_finalization", False, False),
    ("before_ack", False, False)])
def test_revocation_crash_windows(rig, point, valid, recoverable):
    _, opened = rig
    credential = issue(opened)
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "revoke", id=credential.id)
    assert opened().verify(BACKEND, credential.token) is valid
    if point in ("after_pending", "after_sqlite"):
        with pytest.raises(PermissionError):
            opened().admin(ADMIN, False, "recover_pending")
        if recoverable:
            opened().admin(ADMIN, True, "recover_pending")
            assert "committed" in opened().diagnostics()
        else:
            with pytest.raises(Quarantined):
                opened().admin(ADMIN, True, "recover_pending")
            opened().admin(ADMIN, True, "fresh_empty")
        assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("point", ["after_finalization", "before_ack"])
def test_lost_enrollment_ack_requires_revocation_before_replacement(rig, point):
    _, opened = rig
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "enroll")
    with pytest.raises(Quarantined):
        opened().admin(ADMIN, True, "enroll")
    # Trusted fixture reads non-secret ID to model operator incident handling.
    ident = next(iter(opened()._read()["credentials"]))
    opened().admin(ADMIN, True, "revoke", id=ident)
    replacement = issue(opened)
    assert opened().verify(BACKEND, replacement.token)


@pytest.mark.parametrize("point", ["before_pending", "after_pending", "after_sqlite", "after_finalization", "before_ack"])
def test_empty_recovery_crashes_never_reenable_old_credentials(rig, point):
    path, opened = rig
    credential = issue(opened)
    edit_state(path, lambda state: state.update(revision=-1))
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "fresh_empty")
    assert not opened().verify(BACKEND, credential.token)
    if point == "after_sqlite":
        opened().admin(ADMIN, True, "recover_pending")
    elif point in ("before_pending", "after_pending"):
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "recover_pending")
        opened().admin(ADMIN, True, "fresh_empty")
    assert opened()._read()["credentials"] == {}
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("damage", ["old", "mutated", "corrupt"])
def test_pending_recovery_requires_exact_target(rig, damage):
    path, opened = rig
    credential = issue(opened)
    snapshot = (path / "registry.sqlite").read_bytes()
    with pytest.raises(Crash):
        opened(hook=crash_at("after_sqlite")).admin(ADMIN, True, "revoke", id=credential.id)
    if damage == "old":
        (path / "registry.sqlite").write_bytes(snapshot)
    elif damage == "mutated":
        edit_state(path, lambda state: state.update(generation="forged"))
    else:
        (path / "journal.json").write_text("corrupt")
    with pytest.raises(Quarantined):
        opened().admin(ADMIN, True, "recover_pending")
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("current", [False, True])
def test_intentional_restore_always_empty_generation(rig, current):
    path, opened = rig
    credential = issue(opened)
    old = opened()._read()
    backup = path / "backup.sqlite"
    with closing(sqlite3.connect(path / "registry.sqlite")) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    if not current:
        opened().admin(ADMIN, True, "revoke", id=credential.id)
        shutil.copyfile(backup, path / "registry.sqlite")
        assert not opened().verify(BACKEND, credential.token)
    # Invalidation accepts no backup; validation is deferred and contents never served.
    opened().admin(ADMIN, True, "restore_intent_invalidate")
    state = opened()._read()
    assert state["generation"] != old["generation"]
    assert state["credentials"] == state["sessions"] == state["tickets"] == {}
    assert not opened().verify(BACKEND, credential.token)


def test_application_db_restore_independent(rig):
    path, opened = rig
    credential = issue(opened)
    app = path / "app.sqlite"
    with closing(sqlite3.connect(app)) as db, db:
        db.execute("CREATE TABLE app (value TEXT)")
        db.execute("INSERT INTO app VALUES ('fake home data')")
    backup = path / "app-backup.sqlite"
    shutil.copyfile(app, backup)
    opened().admin(ADMIN, True, "revoke", id=credential.id)
    before = ((path / "registry.sqlite").read_bytes(), (path / "journal.json").read_bytes())
    shutil.copyfile(backup, app)
    assert before == ((path / "registry.sqlite").read_bytes(), (path / "journal.json").read_bytes())
    assert not opened().verify(BACKEND, credential.token)


def test_verification_drains_before_revocation_and_new_decisions_wait(rig):
    _, opened = rig
    credential = issue(opened)
    entered, release, revoke_attempt, completed = (threading.Event() for _ in range(4))
    results, errors = [], []
    def paused(point):
        if point == "verify_locked":
            entered.set()
            assert release.wait(10)
    def verify():
        try:
            results.append(opened(hook=paused).verify(BACKEND, credential.token))
        except BaseException as exc:
            errors.append(exc)
    def revoke():
        revoke_attempt.set()
        try:
            opened().admin(ADMIN, True, "revoke", id=credential.id)
        except BaseException as exc:
            errors.append(exc)
        finally:
            completed.set()
    verifier, writer = threading.Thread(target=verify), threading.Thread(target=revoke)
    verifier.start()
    try:
        assert entered.wait(10)
        writer.start()
        assert revoke_attempt.wait(10)
        assert not completed.is_set()
    finally:
        release.set()
        verifier.join(10)
        if writer.ident is not None:
            writer.join(10)
    assert not verifier.is_alive() and not writer.is_alive()
    assert not errors
    assert results == [True]  # point-in-time decision completed before revocation
    assert completed.is_set()
    assert not opened().verify(BACKEND, credential.token)


def test_whole_state_rollback_explicit_trust_limit(rig):
    path, opened = rig
    credential = issue(opened)
    registry, journal = (path / "registry.sqlite").read_bytes(), (path / "journal.json").read_bytes()
    opened().admin(ADMIN, True, "revoke", id=credential.id)
    (path / "registry.sqlite").write_bytes(registry)
    assert not opened().verify(BACKEND, credential.token)
    (path / "journal.json").write_bytes(journal)
    assert opened().verify(BACKEND, credential.token)  # no external monotonic authority


def test_atomic_replace_failure_and_uncertain_barrier(rig):
    _, opened = rig
    credential = issue(opened)
    with pytest.raises(Crash):
        opened(hook=crash_at("before_replace")).admin(ADMIN, True, "revoke", id=credential.id)
    assert not opened().verify(BACKEND, credential.token)  # durable guard precedes replacement
    opened().admin(ADMIN, True, "fresh_empty")
    credential = issue(opened)
    def failed_barrier():
        raise OSError("synthetic durability uncertainty")
    with pytest.raises(OSError):
        opened(directory_barrier=failed_barrier).admin(ADMIN, True, "revoke", id=credential.id)
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("field,value", [("protocol", 1), ("minimum_code", 3), ("instance", "other")])
def test_matching_journal_cannot_override_compatibility(rig, field, value):
    path, opened = rig
    credential = issue(opened)
    edit_state(path, lambda state: state.update({field: value}))
    state = opened()._read()
    (path / "journal.json").write_text(json.dumps({"status": "COMMITTED", "target": state, "digest": digest(state)}))
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("point", ["after_pending", "after_sqlite", "after_finalization"])
def test_rotation_failure_is_atomic_or_quarantined(rig, point):
    _, opened = rig
    credential = issue(opened)
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "rotate", id=credential.id)
    assert not opened().verify(BACKEND, credential.token)
    if point == "after_sqlite":
        opened().admin(ADMIN, True, "recover_pending")
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "enroll")


def test_durable_barriers_and_commit_before_ack(rig):
    _, opened = rig
    sequence = []
    broker = opened(hook=sequence.append, directory_barrier=lambda: sequence.append("durable_directory_model"))
    credential = broker.admin(ADMIN, True, "enroll")
    assert sequence == ["before_pending", "before_guard_replace", "durable_directory_model",
                        "after_intent", "before_replace", "durable_directory_model", "after_pending",
                        "after_sqlite", "before_replace", "durable_directory_model",
                        "before_guard_clear", "durable_directory_model", "after_finalization", "before_ack"]
    assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("damage", ["missing_journal", "corrupt_journal", "missing_registry", "corrupt_registry"])
def test_explicit_empty_recovery_or_unrecoverable_quarantine(rig, damage):
    path, opened = rig
    credential = issue(opened)
    if damage.startswith("missing"):
        name = "journal.json" if damage.endswith("journal") else "registry.sqlite"
        (path / name).rename(path / (name + ".evidence"))
    elif damage.endswith("journal"):
        (path / "journal.json").write_text("broken")
    else:
        (path / "registry.sqlite").write_bytes(b"broken")
    assert not opened().verify(BACKEND, credential.token)
    if damage == "corrupt_registry":
        with pytest.raises(sqlite3.DatabaseError):
            opened().admin(ADMIN, True, "fresh_empty")
        assert not opened().verify(BACKEND, credential.token)
        assert "quarantined" in opened().diagnostics()
    else:
        opened().admin(ADMIN, True, "fresh_empty")
        assert not opened().verify(BACKEND, credential.token)
        assert opened()._read()["credentials"] == {}


def test_enrollment_pending_recovery_keeps_lost_delivery_block(rig):
    _, opened = rig
    with pytest.raises(Crash):
        opened(hook=crash_at("after_sqlite")).admin(ADMIN, True, "enroll")
    opened().admin(ADMIN, True, "recover_pending")
    with pytest.raises(Quarantined):
        opened().admin(ADMIN, True, "enroll")
    ident = next(iter(opened()._read()["credentials"]))
    opened().admin(ADMIN, True, "revoke", id=ident)
    assert opened().verify(BACKEND, issue(opened).token)


def test_final_recheck_precedes_secret_ack(rig):
    path, opened = rig
    def corrupt_after_finalization(point):
        if point == "after_finalization":
            (path / "journal.json").write_text("synthetic corruption")
    with pytest.raises(Quarantined):
        opened(hook=corrupt_after_finalization).admin(ADMIN, True, "enroll")
    assert "quarantined" in opened().diagnostics()


def test_new_verification_waits_for_pending_mutation(rig):
    _, opened = rig
    credential = issue(opened)
    pending, release, attempting, finished = (threading.Event() for _ in range(4))
    errors, decisions = [], []
    def pause(point):
        if point == "after_pending":
            pending.set()
            assert release.wait(10)
    def mutate():
        try:
            opened(hook=pause).admin(ADMIN, True, "revoke", id=credential.id)
        except BaseException as exc:
            errors.append(exc)
    def verify():
        attempting.set()
        try:
            decisions.append(opened().verify(BACKEND, credential.token))
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()
    writer, reader = threading.Thread(target=mutate), threading.Thread(target=verify)
    writer.start()
    try:
        assert pending.wait(10)
        reader.start()
        assert attempting.wait(10)
        assert not finished.is_set()
    finally:
        release.set()
        writer.join(10)
        if reader.ident is not None:
            reader.join(10)
    assert not writer.is_alive() and not reader.is_alive()
    assert not errors
    assert decisions == [False]


@pytest.mark.parametrize("command,barrier", [
    (command, barrier) for command in ("enroll", "revoke", "delivery_confirmed")
    for barrier in (1, 2, 3, 4)] + [("recover_pending", 1), ("recover_pending", 2)])
def test_uncertain_barriers_deny_original_and_restart(rig, command, barrier):
    path, opened = rig
    credential = issue(opened, confirmed=command != "delivery_confirmed")
    if command == "recover_pending":
        with pytest.raises(Crash):
            opened(hook=crash_at("after_sqlite")).admin(ADMIN, True, "revoke", id=credential.id)
    calls = 0
    def fail():
        nonlocal calls
        calls += 1
        if calls == barrier:
            raise OSError("synthetic durability uncertainty")
    broker = opened(directory_barrier=fail)
    args = {} if command in ("enroll", "recover_pending") else {"id": credential.id}
    with pytest.raises(OSError):
        broker.admin(ADMIN, True, command, **args)
    assert (path / "deny.guard").exists()
    assert not broker.verify(BACKEND, credential.token)
    assert not opened().verify(BACKEND, credential.token)
    with pytest.raises(PermissionError):
        opened().admin(ADMIN, False, "recover_pending")
    if barrier >= 3 or command == "recover_pending":
        assert json.loads((path / "journal.json").read_text())["status"] == "COMMITTED"
        opened().admin(ADMIN, True, "recover_pending")
        assert not (path / "deny.guard").exists()
        assert opened().verify(BACKEND, credential.token) is (command in ("enroll", "delivery_confirmed"))
    else:
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "recover_pending")
        opened().admin(ADMIN, True, "fresh_empty")
        assert not opened().verify(BACKEND, credential.token)


@pytest.mark.parametrize("point", ["before_pending", "before_guard_replace", "after_intent",
    "after_pending", "after_sqlite", "before_guard_clear", "after_finalization", "before_ack"])
def test_current_restore_acceptance_boundary(rig, point):
    path, opened = rig
    credential = issue(opened)
    old = opened()._read()
    backup = path / "exact-current.sqlite"
    shutil.copyfile(path / "registry.sqlite", backup)
    evidence = backup.read_bytes()
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "restore_intent_invalidate")
    assert backup.read_bytes() == evidence
    accepted = point not in ("before_pending", "before_guard_replace")
    assert opened().verify(BACKEND, credential.token) is (not accepted)
    if point in ("after_sqlite", "before_guard_clear"):
        opened().admin(ADMIN, True, "recover_pending")
    elif point in ("after_intent", "after_pending"):
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "recover_pending")
        opened().admin(ADMIN, True, "fresh_empty")
    if accepted:
        assert opened()._read()["generation"] != old["generation"]
        assert opened()._read()["credentials"] == {}


def test_unconfirmed_delivery_restart_and_backup_argument(rig):
    _, opened = rig
    credential = issue(opened, confirmed=False)
    assert not opened().verify(BACKEND, credential.token)
    for command in ("enroll", "rotate"):
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, command, id=credential.id)
    assert credential.token not in repr(credential) + repr(opened()) + opened().diagnostics()
    with pytest.raises(ValueError):
        opened().admin(ADMIN, True, "restore_intent_invalidate", backup="unused")
    opened().admin(ADMIN, True, "revoke", id=credential.id)
    assert opened().verify(BACKEND, issue(opened).token)


@pytest.mark.parametrize("point", ["after_intent", "after_pending", "after_sqlite", "before_guard_clear"])
def test_delivery_confirmation_crash_denies(rig, point):
    _, opened = rig
    credential = issue(opened, confirmed=False)
    broker = opened(hook=crash_at(point))
    with pytest.raises(Crash):
        broker.admin(ADMIN, True, "delivery_confirmed", id=credential.id)
    assert not broker.verify(BACKEND, credential.token)
    assert not opened().verify(BACKEND, credential.token)


def test_sqlite_error_preserves_guard(rig, monkeypatch):
    path, opened = rig
    credential = issue(opened)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic sqlite failure")
    monkeypatch.setattr(Broker, "_sqlite", fail)
    with pytest.raises(sqlite3.OperationalError):
        opened().admin(ADMIN, True, "revoke", id=credential.id)
    assert (path / "deny.guard").exists()
    assert not opened().verify(BACKEND, credential.token)
    with pytest.raises(Quarantined):
        opened().admin(ADMIN, True, "recover_pending")

@pytest.mark.parametrize("command", ["enroll", "revoke", "delivery_confirmed", "restore_intent_invalidate"])
@pytest.mark.parametrize("replacement", [1, 2])
def test_journal_replace_crashes_guard_all_commands(rig, command, replacement):
    path, opened = rig
    credential = issue(opened, confirmed=command != "delivery_confirmed")
    calls = 0
    def crash(point):
        nonlocal calls
        if point == "before_replace":
            calls += 1
            if calls == replacement:
                raise Crash()
    args = {"id": credential.id} if command in ("revoke", "delivery_confirmed") else {}
    broker = opened(hook=crash)
    with pytest.raises(Crash):
        broker.admin(ADMIN, True, command, **args)
    assert (path / "deny.guard").exists()
    assert not broker.verify(BACKEND, credential.token)
    assert not opened().verify(BACKEND, credential.token)
    if replacement == 2:
        opened().admin(ADMIN, True, "recover_pending")
    else:
        with pytest.raises(Quarantined):
            opened().admin(ADMIN, True, "recover_pending")


@pytest.mark.parametrize("point", ["after_finalization", "before_ack"])
def test_confirmed_delivery_after_durable_finalization_ack_loss(rig, point):
    _, opened = rig
    credential = issue(opened, confirmed=False)
    with pytest.raises(Crash):
        opened(hook=crash_at(point)).admin(ADMIN, True, "delivery_confirmed", id=credential.id)
    # Confirmation is already durable; a lost status acknowledgment is not rollback.
    assert opened().verify(BACKEND, credential.token)


def test_matching_unknown_profile_policy_denies(rig):
    path, opened = rig
    credential = issue(opened)
    edit_state(path, lambda state: state["credentials"][credential.id].update(profile="unknown"))
    state = opened()._read()
    (path / "journal.json").write_text(json.dumps(opened()._record(state, "COMMITTED")))
    assert not opened().verify(BACKEND, credential.token)
