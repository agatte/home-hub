"""Synthetic offline registry tests; never import runtime settings or devices."""
import shutil
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
