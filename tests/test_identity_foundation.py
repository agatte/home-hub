"""Synthetic offline registry tests; never import runtime settings or devices."""
import shutil
import hashlib
import threading
import sqlite3

import pytest

from backend.identity_core import IdentityStore, MAX_OVERLAP
from backend.identity_policy import PROFILES, STATUS, WS, HEALTH, OVERRIDE


@pytest.fixture
def registry(tmp_path):
    cap = object()
    now = [1000.0]
    path = tmp_path / "identity.sqlite"
    store = IdentityStore(path, local_capability=cap, clock=lambda: now[0])
    yield store, cap, now, path
    store.close()


@pytest.mark.parametrize("profile", PROFILES)
def test_fixed_matrix(registry, profile):
    store, cap, _, _ = registry
    enrolled = store.enroll(profile, capability=cap)
    for operation, lane in PROFILES[profile].grants:
        identity = store.authorize(enrolled.token, operation, lane=lane)
        assert identity.profile == profile
        assert identity.source == PROFILES[profile].source
        assert identity.principal_id == enrolled.principal_id
    assert store.authorize(enrolled.token, "unknown", lane="browser") is None
    assert store.authorize(enrolled.token, STATUS, lane="unknown") is None
    assert store.authorize(enrolled.token, OVERRIDE, lane="skill") is None or profile == "alexa"


def test_source_and_private_ip_cannot_grant(registry):
    store, cap, _, _ = registry
    e = store.enroll("windows_desktop", capability=cap)
    assert store.authorize(e.token, HEALTH, lane="activity", claimed_source="desktop")
    for source in ("owner", "latitude", "127.0.0.1", "192.168.86.30"):
        assert store.authorize(e.token, HEALTH, lane="activity", claimed_source=source) is None
    assert store.authorize(e.token, OVERRIDE, lane="browser", claimed_source="owner") is None
    assert store.authorize(None, HEALTH, lane="activity", claimed_source="desktop") is None


@pytest.mark.parametrize("token", [None, "", "192.168.86.30", "x" * 10000, "a.b", "é"])
def test_malformed_credentials(registry, token):
    assert registry[0].authorize(token, STATUS, lane="browser") is None


def test_verifier_and_persistence(registry):
    store, cap, now, path = registry
    a = store.enroll("owner_browser", capability=cap)
    b = store.enroll("owner_browser", capability=cap)
    assert a.token not in repr(a)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT salt,verifier FROM identity_credentials").fetchall()
        assert len(rows[0][0]) == len(rows[0][1]) == 32
        assert rows[0] != rows[1]
        assert a.token.encode() not in path.read_bytes()
        assert a.token.split(".")[1].encode() not in path.read_bytes()
    reopened = IdentityStore(path, local_capability=object(), clock=lambda: now[0])
    try:
        assert reopened.authorize(a.token, STATUS, lane="browser")
        bad = a.credential_id + "." + b.token.split(".")[1]
        assert reopened.authorize(bad, STATUS, lane="browser") is None
    finally:
        reopened.close()


def test_rotation_expiry_and_revoke(registry):
    store, cap, now, _ = registry
    a = store.enroll("owner_browser", capability=cap, lifetime=100)
    b = store.rotate(a.principal_id, capability=cap, overlap=10, lifetime=100)
    assert store.authorize(a.token, STATUS, lane="browser")
    now[0] += 5
    c = store.rotate(a.principal_id, capability=cap, overlap=10, lifetime=100)
    now[0] += 5
    assert store.authorize(a.token, STATUS, lane="browser") is None
    assert store.authorize(b.token, STATUS, lane="browser")
    store.revoke(a.principal_id, capability=cap)
    for e in (a, b, c):
        assert store.authorize(e.token, STATUS, lane="browser") is None
    with pytest.raises(ValueError):
        store.rotate(a.principal_id, capability=cap)


def test_individual_revocation_and_zero_overlap(registry):
    store, cap, _, _ = registry
    a = store.enroll("owner_browser", capability=cap)
    store.revoke_credential(a.credential_id, capability=cap)
    b = store.rotate(a.principal_id, capability=cap, overlap=10)
    assert store.authorize(a.token, STATUS, lane="browser") is None
    assert store.authorize(b.token, STATUS, lane="browser")
    c = store.rotate(a.principal_id, capability=cap)
    assert store.authorize(b.token, STATUS, lane="browser") is None
    assert store.authorize(c.token, STATUS, lane="browser")


def test_exact_expiry(registry):
    store, cap, now, _ = registry
    e = store.enroll("kiosk", capability=cap, lifetime=1)
    now[0] += 1
    assert store.authorize(e.token, WS, lane="display") is None


@pytest.mark.parametrize("bad", [None, True, "local", "127.0.0.1", object()])
def test_local_capability_misuse(registry, bad):
    store, _, _, _ = registry
    with pytest.raises(PermissionError):
        store.enroll("owner_browser", capability=bad)
    with pytest.raises(PermissionError):
        store.rotate("missing", capability=bad)
    with pytest.raises(PermissionError):
        store.revoke("missing", capability=bad)
    with pytest.raises(PermissionError):
        store.revoke_credential("missing", capability=bad)


@pytest.mark.parametrize("bad", [None, True, "localhost"])
def test_constructor_requires_opaque_capability(tmp_path, bad):
    with pytest.raises(ValueError):
        IdentityStore(tmp_path / "unused.db", local_capability=bad)


@pytest.mark.parametrize("duration", [-1, 0, float("nan"), float("inf"), 10**10])
def test_invalid_durations_do_not_write(registry, duration):
    store, cap, _, _ = registry
    with pytest.raises(ValueError):
        store.enroll("owner_browser", capability=cap, lifetime=duration)
    assert store._db.execute("SELECT count(*) FROM identity_principals").fetchone()[0] == 0


def test_invalid_profile_overlap_and_atomic_failure(registry, monkeypatch):
    store, cap, _, _ = registry
    with pytest.raises(ValueError):
        store.enroll("admin", capability=cap)
    a = store.enroll("owner_browser", capability=cap)
    with pytest.raises(ValueError):
        store.rotate(a.principal_id, capability=cap, overlap=MAX_OVERLAP + 1)
    before = store._db.execute("SELECT expires FROM identity_credentials").fetchone()[0]
    def fail(*args):
        raise RuntimeError("synthetic insert failure")
    monkeypatch.setattr(store, "_issue", fail)
    with pytest.raises(RuntimeError):
        store.rotate(a.principal_id, capability=cap)
    assert store._db.execute("SELECT expires FROM identity_credentials").fetchone()[0] == before
    with pytest.raises(RuntimeError):
        store.enroll("kiosk", capability=cap)
    assert store._db.execute("SELECT count(*) FROM identity_principals").fetchone()[0] == 1


def test_unknown_or_mismatched_persisted_binding_denies(registry):
    store, cap, _, _ = registry
    a = store.enroll("owner_browser", capability=cap)
    store._db.execute("UPDATE identity_principals SET source='latitude'")
    assert store.authorize(a.token, STATUS, lane="browser") is None
    store._db.execute("UPDATE identity_principals SET profile='admin'")
    assert store.authorize(a.token, STATUS, lane="browser") is None


def test_backup_rollback_is_explicit_activation_blocker(registry, tmp_path):
    store, cap, now, path = registry
    a = store.enroll("owner_browser", capability=cap)
    backup = tmp_path / "synthetic-backup.db"
    # No concurrent writers in this synthetic copy; production backup needs an owned protocol.
    shutil.copyfile(path, backup)
    store.revoke(a.principal_id, capability=cap)
    assert store.authorize(a.token, STATUS, lane="browser") is None
    restored = IdentityStore(backup, local_capability=object(), clock=lambda: now[0])
    try:
        # HONEST limitation: a whole-DB backup contains the old valid verifier.
        assert restored.authorize(a.token, STATUS, lane="browser")
    finally:
        restored.close()


def test_other_connection_revocation_is_seen(registry):
    store, cap, now, path = registry
    a = store.enroll("owner_browser", capability=cap)
    other_cap = object()
    other = IdentityStore(path, local_capability=other_cap, clock=lambda: now[0])
    try:
        assert store.authorize(a.token, STATUS, lane="browser")
        other.revoke(a.principal_id, capability=other_cap)
        assert store.authorize(a.token, STATUS, lane="browser") is None
        with pytest.raises(ValueError):
            store.rotate(a.principal_id, capability=cap)
    finally:
        other.close()


def test_writer_reservation_blocks_stale_authorization(registry):
    store, cap, now, path = registry
    a = store.enroll("owner_browser", capability=cap)
    other = IdentityStore(path, local_capability=object(), clock=lambda: now[0])
    other._db.execute("PRAGMA busy_timeout=0")
    try:
        with store._transaction():
            store._db.execute("UPDATE identity_principals SET revoked=1 WHERE id=?", (a.principal_id,))
            # Fail closed by raising, rather than reading the old committed grant.
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.authorize(a.token, STATUS, lane="browser")
        assert other.authorize(a.token, STATUS, lane="browser") is None
    finally:
        other.close()


# Independent least-privilege snapshot: intentionally NOT derived from PROFILES.
# Any new action/profile grant must be reviewed and reflected explicitly here.
def test_reviewed_profile_grant_snapshot():
    expected = {
        "owner_browser": {
            ("GET /api/automation/status", "browser"),
            ("POST /api/automation/override", "browser"),
            ("WS /ws:mode_update", "browser"),
        },
        "kiosk": {
            ("GET /api/automation/status", "display"),
            ("WS /ws:mode_update", "display"),
        },
        "windows_desktop": {
            ("POST /api/automation/activity", "activity"),
            ("POST /api/learning/audio-decision", "audio"),
            ("POST /api/automation/screen-color", "screen"),
            ("POST /api/personality/blendshape", "camera"),
            ("POST /api/camera/desktop/lux", "camera"),
            ("GET /api/camera/status", "display"),
            ("WS /ws:mode_update", "display"),
            ("WS /ws:mode_update", "sleep"),
            *(( "POST /api/automation/agent-health", lane) for lane in
              ("activity", "audio", "screen", "camera", "display", "sleep")),
        },
        "desktop_notifier": {
            ("GET /api/automation/status", "notifier"),
            ("WS /ws:mode_update", "notifier"),
        },
        "mcp": {("GET /api/automation/status", "tools")},
        "latitude": {
            ("POST /api/automation/activity", "streaming"),
            ("POST /api/automation/agent-health", "streaming"),
        },
        "guest_gateway": set(),
        "alexa": {("POST /api/automation/override", "skill")},
        "shortcuts": {("POST /api/presence/geofence", "geofence")},
        "local_operator": {("POST /api/host/travel", "lifecycle")},
    }
    assert set(PROFILES) == set(expected)
    for name, grants in expected.items():
        assert PROFILES[name].grants == frozenset(grants), name


@pytest.mark.parametrize("mutation", [
    "principal_revoke", "credential_revoke", "rotate_zero", "rotate_overlap",
    "shorten_expiry", "profile", "source", "delete", "verifier", "salt",
    "principal_binding", "policy_grants", "clock_expiry", "unchanged",
])
def test_hash_phase_releases_locks_and_rechecks(registry, monkeypatch, mutation):
    store, cap, now, path = registry
    enrolled = store.enroll("owner_browser", capability=cap, lifetime=100)
    replacement = store.enroll("owner_browser", capability=cap)
    hashing = threading.Event()
    resume = threading.Event()
    finished = threading.Event()
    results, errors = [], []
    original = hashlib.pbkdf2_hmac

    def paused_hash(*args, **kwargs):
        if threading.current_thread() is worker:
            hashing.set()
            assert resume.wait(10), "test did not release hash barrier"
        return original(*args, **kwargs)

    def authorize():
        connection = None
        try:
            # SQLite connection is created, used and closed on its own thread.
            connection = IdentityStore(path, local_capability=object(), clock=lambda: now[0])
            results.append(connection.authorize(enrolled.token, STATUS, lane="browser"))
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                if connection is not None:
                    connection.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

    worker = threading.Thread(target=authorize, daemon=True)
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", paused_hash)
    worker.start()
    try:
        assert hashing.wait(10), "authorization did not reach hash barrier"
        # A distinct connection must COMMIT while hashing remains paused. Zero
        # busy timeout makes a retained read/write lock an immediate test failure.
        store._db.execute("PRAGMA busy_timeout=0")
        assert not store._db.in_transaction
        if mutation == "principal_revoke":
            store.revoke(enrolled.principal_id, capability=cap)
        elif mutation == "credential_revoke":
            store.revoke_credential(enrolled.credential_id, capability=cap)
        elif mutation.startswith("rotate_"):
            store.rotate(enrolled.principal_id, capability=cap,
                         overlap=0 if mutation == "rotate_zero" else 10)
        elif mutation == "shorten_expiry":
            store._db.execute("UPDATE identity_credentials SET expires=1050 WHERE id=?", (enrolled.credential_id,))
        elif mutation == "profile":
            store._db.execute("UPDATE identity_principals SET profile='kiosk',source='kiosk' WHERE id=?", (enrolled.principal_id,))
        elif mutation == "source":
            store._db.execute("UPDATE identity_principals SET source='latitude' WHERE id=?", (enrolled.principal_id,))
        elif mutation == "delete":
            store._db.execute("DELETE FROM identity_credentials WHERE id=?", (enrolled.credential_id,))
        elif mutation in ("verifier", "salt"):
            store._db.execute(f"UPDATE identity_credentials SET {mutation}=? WHERE id=?", (b"x" * 32, enrolled.credential_id))
        elif mutation == "principal_binding":
            store._db.execute("UPDATE identity_credentials SET principal_id=? WHERE id=?", (replacement.principal_id, enrolled.credential_id))
        elif mutation == "policy_grants":
            from backend import identity_core
            from backend.identity_policy import Profile
            monkeypatch.setattr(identity_core, "PROFILES", {"owner_browser": Profile("owner", frozenset())})
        elif mutation == "clock_expiry":
            now[0] = 1100
        else:
            # Even an unrelated committed write must be possible during hashing.
            store.revoke(replacement.principal_id, capability=cap)
    finally:
        resume.set()
        worker.join(10)
    assert not worker.is_alive(), "authorization worker must exit before fixture teardown"
    assert finished.is_set(), "authorization failed to finish"
    assert not errors, errors
    assert len(results) == 1
    if mutation == "unchanged":
        assert results[0].principal_id == enrolled.principal_id
        # Returned identity is not reused by subsequent authorize calls.
        store.revoke(enrolled.principal_id, capability=cap)
    else:
        assert results == [None]
    fresh = store.authorize(enrolled.token, STATUS, lane="browser")
    if mutation in ("rotate_overlap", "shorten_expiry", "principal_binding"):
        assert fresh is not None  # Changed snapshot denied only the in-flight attempt.
        assert fresh.principal_id == (replacement.principal_id if mutation == "principal_binding" else enrolled.principal_id)
    else:
        assert fresh is None


def test_cheap_denials_do_not_hash(registry, monkeypatch):
    store, cap, now, _ = registry
    enrolled = store.enroll("owner_browser", capability=cap, lifetime=10)
    def unexpected_hash(*args, **kwargs):
        pytest.fail("ineligible credential reached PBKDF2")
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", unexpected_hash)
    assert store.authorize("0" * 32 + "." + "a" * 43, STATUS, lane="browser") is None
    assert store.authorize(enrolled.token, "unknown", lane="browser") is None
    assert store.authorize(enrolled.token, STATUS, lane="browser", claimed_source="latitude") is None
    now[0] += 10
    assert store.authorize(enrolled.token, STATUS, lane="browser") is None


def test_authorize_refuses_caller_transaction(registry, monkeypatch):
    store, cap, _, _ = registry
    enrolled = store.enroll("owner_browser", capability=cap)
    def unexpected_hash(*args, **kwargs):
        pytest.fail("hash executed inside caller transaction")
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", unexpected_hash)
    with store._transaction():
        with pytest.raises(RuntimeError, match="idle connection"):
            store.authorize(enrolled.token, STATUS, lane="browser")


def test_revocation_commits_before_final_authorization_check(registry, monkeypatch):
    """A competing writer wins while the verifier reaches its final lock."""
    from contextlib import contextmanager

    store, cap, now, path = registry
    enrolled = store.enroll("owner_browser", capability=cap)
    hashing = threading.Event()
    release_hash = threading.Event()
    entering_final = threading.Event()
    completed = threading.Event()
    outcomes = []
    errors = []
    original_hash = hashlib.pbkdf2_hmac

    def paused_hash(*args, **kwargs):
        if threading.current_thread() is worker:
            hashing.set()
            if not release_hash.wait(10):
                raise AssertionError("hash barrier not released")
        return original_hash(*args, **kwargs)

    def attempt():
        connection = None
        try:
            connection = IdentityStore(path, local_capability=object(), clock=lambda: now[0])
            original_transaction = connection._transaction

            @contextmanager
            def marked_final_transaction():
                entering_final.set()
                with original_transaction():
                    yield

            connection._transaction = marked_final_transaction
            outcomes.append(connection.authorize(enrolled.token, STATUS, lane="browser"))
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                if connection is not None:
                    connection.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                completed.set()

    worker = threading.Thread(target=attempt, daemon=True)
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", paused_hash)
    worker.start()
    try:
        assert hashing.wait(10), "verification did not enter the hash phase"
        with store._transaction():
            release_hash.set()
            assert entering_final.wait(5), "verification did not reach final phase"
            assert not completed.is_set(), "final authorization skipped the writer lock"
            store._db.execute(
                "UPDATE identity_principals SET revoked=1 WHERE id=?",
                (enrolled.principal_id,),
            )
        # The verifier may only resume against the newly committed revocation.
    finally:
        release_hash.set()
        worker.join(10)
    assert not worker.is_alive(), "verification worker remained after test"
    assert completed.is_set()
    assert not errors, errors
    assert outcomes == [None]
    assert store.authorize(enrolled.token, STATUS, lane="browser") is None


@pytest.mark.parametrize("failure_point", ["snapshot", "eligibility"])
def test_final_phase_failure_rolls_back_and_connection_remains_usable(
    registry, monkeypatch, failure_point
):
    store, cap, _, _ = registry
    enrolled = store.enroll("owner_browser", capability=cap)
    method = "_credential_snapshot" if failure_point == "snapshot" else "_eligible"
    original = getattr(store, method)
    calls = [0]

    def fail_on_second_call(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("synthetic final phase failure")
        return original(*args, **kwargs)

    with monkeypatch.context() as edits:
        edits.setattr(store, method, fail_on_second_call)
        with pytest.raises(RuntimeError, match="synthetic final phase failure"):
            store.authorize(enrolled.token, STATUS, lane="browser")
    assert calls[0] == 2
    assert not store._db.in_transaction, "failed final check leaked a write reservation"
    # The same connection must still authorize fresh decisions after rollback.
    assert store.authorize(enrolled.token, STATUS, lane="browser")
