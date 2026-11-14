"""Disposable fake data only; Windows tests model directory durability explicitly."""
import hashlib
import json
import struct
import threading

import pytest

from security.homehub_identity_broker import runtime as r
from backend.identity_policy import PROFILES
from security.homehub_identity_broker.offline_fixture import offline_fixture_bootstrap

TOKEN = "a" * 32 + "." + "B" * 43
GEN = "c" * 32


def fixture_state():
    p = r.PROFILES["owner_browser"]
    return {"version": 1, "minimum_code": 1, "generation": GEN, "revision": 1,
            "rotations": [], "pending_delivery": [], "credentials": {"a" * 32: {
                "principal_id": "d" * 32, "profile": "owner_browser", "source": p.source,
                "grants": [list(g) for g in sorted(p.grants)], "kind": "browser_session",
                "expires_at": 2000, "revoked": False, "salt": "e" * 32,
                "iterations": r.ITERATIONS, "verifier": hashlib.pbkdf2_hmac(
                    "sha256", b"B" * 43, bytes.fromhex("e" * 32), r.ITERATIONS).hex()}}}


def request(**changes):
    return {"version": 1, "method": "verify", "nonce": "f" * 32, "token": TOKEN,
            "operation": "WS /ws:light_command", "lane": "browser", "generation": GEN,
            "revision": 1, **changes}


@pytest.fixture
def rig(tmp_path):
    def opened(**kwargs):
        return r.Broker(tmp_path / "private" / "registry.sqlite", tmp_path / "anchor" / "journal.json",
                        b"synthetic-key-only" * 2, directory_barrier=lambda p: None,
                        clock=kwargs.pop("clock", lambda: 1000), **kwargs)
    (tmp_path / "private").mkdir()
    (tmp_path / "anchor").mkdir()
    broker = opened()
    offline_fixture_bootstrap(broker, fixture_state(), trusted_fixture=True)
    return broker, opened


def status(broker, **kwargs):
    return r.unframe(broker.process(r.frame(request(**kwargs))))["status"]


def test_policy_parity():
    assert {k: (p.source, p.grants) for k, p in r.PROFILES.items()} == {
        k: (p.source, p.grants) for k, p in PROFILES.items()}


def test_absent_never_bootstraps(tmp_path):
    b = r.Broker(tmp_path / "absent", tmp_path / "journal", b"x" * 32)
    assert status(b) == "quarantined"
    assert list(tmp_path.iterdir()) == []


def test_bootstrap_reopen_and_no_secrets(rig, caplog):
    b, opened = rig
    assert status(opened()) == "verified"
    assert status(b, token="a" * 32 + "." + "X" * 43) == "denied"
    assert TOKEN not in repr(b) + caplog.text
    assert TOKEN.encode() not in b.process(r.frame(request()))
    assert TOKEN.encode() not in b._db.read_bytes() + b._journal.read_bytes()
    with pytest.raises(r.Denied) as caught:
        offline_fixture_bootstrap(b, fixture_state(), trusted_fixture=True)
    assert TOKEN not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("changes", [{"operation": "admin"}, {"lane": "lifecycle"},
    {"generation": "0" * 32}, {"revision": 2}, {"token": "0" * 32 + "." + "B" * 43}])
def test_unknown_stale_and_grants(rig, changes):
    assert status(rig[0], **changes) == "denied"


@pytest.mark.parametrize("changes", [{"nonce": "bad"}, {"revision": True}, {"revision": 0},
    {"version": True}, {"version": 2}, {"method": "revoke"}, {"status": "verified"},
    {"source": "root"}, {"token": "bad"}, {"generation": "bad"}, {"lane": []}])
def test_malformed_exact_envelope(rig, changes):
    with pytest.raises(r.Denied):
        rig[0].process(r.frame(request(**changes)))


@pytest.mark.parametrize("raw", [b"", b"\0\0\0\0", b"\0\0\x08\x01" + b"x" * 2049,
    b"\0\0\0\x02{}extra", struct.pack("!I", 13) + b'{"x":1,"x":2}',
    struct.pack("!I", 2) + b"[]", struct.pack("!I", 1) + b"\xff"])
def test_bad_frames(rig, raw):
    with pytest.raises(r.Denied):
        rig[0].process(raw)


def test_expiry_revoke_restore_and_app_restore(rig, tmp_path):
    b, opened = rig
    assert status(opened(clock=lambda: 2000)) == "denied"


def test_revoke_and_restore(rig, tmp_path):
    b, opened = rig
    old_db = b._db.read_bytes()
    b._revoke("a" * 32)
    assert status(opened(), revision=2) == "denied"
    app = tmp_path / "home_hub.db"
    app.write_bytes(b"synthetic application restore")
    assert status(opened(), revision=2) == "denied"
    b._restore_empty("1" * 32)
    assert status(opened(), generation="1" * 32, revision=3) == "denied"
    b._db.write_bytes(old_db)
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("target", ["_journal", "_guard", "_db"])
def test_missing_stores_do_not_repair(rig, target):
    b, opened = rig
    path = getattr(b, target)
    path.rename(path.with_suffix(".evidence"))
    assert status(opened()) == "quarantined"
    assert not path.exists()


@pytest.mark.parametrize("field,value", [("version", 0), ("minimum_code", 2),
    ("generation", "2" * 32), ("revision", 9), ("rotations", ["forged"]),
    ("pending_delivery", ["forged"]), ("credentials", {})])
def test_complete_state_tampering(rig, field, value):
    b, opened = rig
    state = b._read_db()
    state[field] = value
    b._write_db(state)
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("field,value", [("profile", "root"), ("source", "root"),
    ("grants", [["admin", "root"]]), ("expires_at", 900), ("revoked", True),
    ("kind", "native_bearer"), ("salt", "0" * 32), ("verifier", "0" * 64),
    ("iterations", 1)])
def test_credential_tampering(rig, field, value):
    b, opened = rig
    state = b._read_db()
    state["credentials"]["a" * 32][field] = value
    b._write_db(state)
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("field,value", [("profile", "root"), ("source", "root"),
    ("grants", [["admin", "root"]]), ("kind", "native_bearer")])
def test_invalid_policy_even_with_authentic_anchor(rig, field, value):
    b, opened = rig
    state = b._read_db()
    state["credentials"]["a" * 32][field] = value
    b._write_db(state)
    for path in (b._journal, b._guard):
        b._anchor(path, b._record(state, "COMMITTED"))
    assert status(opened()) == "quarantined"


class Crash(BaseException):
    pass


@pytest.mark.parametrize("point", ["before_pending", "after_deny", "after_pending", "after_db",
                                   "after_journal", "before_ack"])
def test_crash_boundaries(rig, point):
    b, opened = rig
    def crash(actual):
        if point == actual:
            raise Crash()
    b._hook = crash
    with pytest.raises(Crash):
        b._revoke("a" * 32)
    assert status(opened()) == "quarantined"
    with pytest.raises(r.Denied):
        opened()._restore_empty("1" * 32)


@pytest.mark.parametrize("operation", ["fsync", "sqlite", "directory"])
def test_io_failures_quarantine(rig, monkeypatch, operation):
    b, opened = rig
    def fail(*args, **kwargs):
        raise OSError("synthetic failure")
    if operation == "fsync":
        monkeypatch.setattr(r.os, "fsync", fail)
    elif operation == "sqlite":
        monkeypatch.setattr(b, "_write_db", fail)
    else:
        b._barrier = fail
    with pytest.raises(r.Denied):
        b._revoke("a" * 32)
    assert status(b) == "quarantined"
    assert status(opened()) == "quarantined"


def test_verify_revocation_serializes(rig):
    b, _ = rig
    entered, release, revoked = threading.Event(), threading.Event(), threading.Event()
    results = []
    def hook(point):
        if point == "verify_locked":
            entered.set()
            assert release.wait(5)
    b._hook = hook
    verify = threading.Thread(target=lambda: results.append(status(b)))
    def revoke():
        b._revoke("a" * 32)
        revoked.set()
    mutation = threading.Thread(target=revoke)
    verify.start()
    assert entered.wait(5)
    mutation.start()
    assert not revoked.wait(.05)
    release.set()
    verify.join(5)
    mutation.join(5)
    assert not verify.is_alive() and not mutation.is_alive()
    assert results == ["verified"] and revoked.is_set()
    assert status(b, revision=2) == "denied"


def test_wrong_key_and_journal_mac(rig):
    b, opened = rig
    other = opened()
    other._key = b"wrong" * 8
    assert status(other) == "quarantined"
    record = json.loads(b._journal.read_bytes())
    record["mac"] = "0" * 64
    b._journal.write_bytes(r.canonical(record))
    assert status(opened()) == "quarantined"

def test_rotation_zero_overlap(rig):
    b, opened = rig
    replacement = b._read_db()["credentials"]["a" * 32].copy()
    replacement["salt"] = "9" * 32
    replacement["verifier"] = hashlib.pbkdf2_hmac(
        "sha256", b"C" * 43, bytes.fromhex(replacement["salt"]), r.ITERATIONS).hex()
    b._rotate("a" * 32, "8" * 32, replacement)
    assert status(opened(), revision=2) == "denied"
    assert status(opened(), revision=2, token="8" * 32 + "." + "C" * 43) == "verified"
    replacement["profile"] = "root"
    assert status(opened(), revision=2, token="8" * 32 + "." + "C" * 43) == "verified"


@pytest.mark.parametrize("index", range(1, 5))
def test_directory_failures_at_each_anchor(rig, index):
    b, opened = rig
    calls = 0
    def barrier(path):
        nonlocal calls
        if path == b._journal.parent:
            calls += 1
            if calls == index:
                raise OSError("synthetic directory failure")
    b._barrier = barrier
    with pytest.raises(r.Denied):
        b._revoke("a" * 32)
    assert status(b) == "quarantined"
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("point", ["after_deny", "after_pending", "after_db", "after_journal"])
def test_restore_interruption_never_revives_old_credentials(rig, point):
    b, opened = rig
    def crash(actual):
        if actual == point:
            raise Crash()
    b._hook = crash
    with pytest.raises(Crash):
        b._restore_empty("1" * 32)
    assert status(opened()) == "quarantined"
    assert status(opened(), generation="1" * 32, revision=2) == "quarantined"


@pytest.mark.parametrize("point", ["after_deny", "after_pending", "after_db", "after_journal"])
def test_rotation_interruption_denies_both(rig, point):
    b, opened = rig
    replacement = b._read_db()["credentials"]["a" * 32].copy()
    replacement["salt"] = "9" * 32
    replacement["verifier"] = hashlib.pbkdf2_hmac(
        "sha256", b"C" * 43, bytes.fromhex(replacement["salt"]), r.ITERATIONS).hex()
    def crash(actual):
        if actual == point:
            raise Crash()
    b._hook = crash
    with pytest.raises(Crash):
        b._rotate("a" * 32, "8" * 32, replacement)
    assert status(opened()) == "quarantined"
    assert status(opened(), revision=2, token="8" * 32 + "." + "C" * 43) == "quarantined"


def test_native_bearer(rig):
    b, opened = rig
    state = b._read_db()
    c = state["credentials"]["a" * 32]
    c.update(profile="mcp", source="mcp", kind="native_bearer",
             grants=[list(g) for g in sorted(r.PROFILES["mcp"].grants)])
    b._transition(state)
    response = r.unframe(opened().process(r.frame(request(operation="GET /api/automation/status", lane="tools"))))
    assert response["status"] == "verified" and response["kind"] == "native_bearer"
    assert status(opened()) == "denied"


def test_pending_delivery_not_accepted_even_authenticated(rig):
    b, opened = rig
    state = b._read_db()
    state["pending_delivery"] = [{"forged": "delivery"}]
    b._write_db(state)
    for path in (b._guard, b._journal):
        b._anchor(path, b._record(state, "COMMITTED"))
    assert status(opened()) == "quarantined"


def test_default_windows_directory_barrier_refuses(tmp_path):
    if r.os.name == "posix":
        pytest.skip("Windows refusal test")
    with pytest.raises(r.Denied):
        r.directory_sync(tmp_path)


@pytest.mark.skipif(r.os.name != "posix", reason="Linux/POSIX directory fsync proof required")
def test_posix_directory_barrier(tmp_path):
    r.directory_sync(tmp_path)

@pytest.mark.asyncio
async def test_existing_client_accepts_exact_broker_response(rig):
    from backend.services.identity_broker_verify_client import VerifyClient
    b, _ = rig
    class OfflineIO:
        async def exchange_verify(self, raw):
            return b.process(raw)
    client = VerifyClient(OfflineIO(), generation=lambda: GEN, revision=lambda: 1,
                          clock=lambda: 1000)
    identity = await client.authorize(TOKEN, "WS /ws:light_command", lane="browser", stage="active")
    assert identity is not None and identity.profile == "owner_browser"
    b._revoke("a" * 32)
    assert await client.authorize(TOKEN, "WS /ws:light_command", lane="browser", stage="active") is None


def test_sqlite_open_error_does_not_escape_or_log(rig, monkeypatch, caplog):
    b, _ = rig
    def fail(*args, **kwargs):
        raise r.sqlite3.DatabaseError(TOKEN)
    monkeypatch.setattr(r.sqlite3, "connect", fail)
    assert status(b) == "quarantined"
    with pytest.raises(r.Denied) as caught:
        b._revoke("a" * 32)
    assert TOKEN not in str(caught.value) + caplog.text
    assert caught.value.__context__ is None

@pytest.mark.parametrize("index", range(1, 5))
def test_file_fsync_failure_at_each_anchor(rig, monkeypatch, index):
    b, opened = rig
    original = r.os.fsync
    calls = 0
    def fail(fd):
        nonlocal calls
        calls += 1
        if calls == index:
            raise OSError("synthetic fsync failure")
        original(fd)
    monkeypatch.setattr(r.os, "fsync", fail)
    with pytest.raises(r.Denied):
        b._revoke("a" * 32)
    assert status(opened()) == "quarantined"


def test_explicit_offline_builder_intent_required(tmp_path):
    b = r.Broker(tmp_path / "registry", tmp_path / "journal", b"x" * 32,
                 directory_barrier=lambda path: None)
    with pytest.raises(r.Denied):
        offline_fixture_bootstrap(b, fixture_state(), trusted_fixture=False)
    assert list(tmp_path.iterdir()) == []


def test_expiry_during_verifier_work(rig):
    b, _ = rig
    times = iter([1000, 2000])
    b._clock = lambda: next(times)
    assert status(b) == "denied"


@pytest.mark.parametrize("target", ["_db", "_journal", "_guard"])
@pytest.mark.parametrize("damage", ["oversize", "empty", "malformed"])
def test_storage_bounds_quarantine(rig, target, damage):
    b, opened = rig
    path = getattr(b, target)
    limit = r.MAX_DB_BYTES if target == "_db" else r.MAX_ANCHOR_BYTES
    path.write_bytes(b"x" * (limit + 1) if damage == "oversize" else
                     b"" if damage == "empty" else b"malformed")
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("damage", ["extra", "oversize", "blob", "truncated", "inventory"])
def test_state_row_bounds(rig, damage):
    b, opened = rig
    if damage == "inventory":
        state = b._read_db()
        record = state["credentials"]["a" * 32]
        state["credentials"] = {f"{i:032x}": record for i in range(r.MAX_CREDENTIALS + 1)}
        b._write_db(state)
        for path in (b._guard, b._journal):
            b._anchor(path, b._record(state, "COMMITTED"))
    else:
        with r.sqlite3.connect(b._db) as db:
            if damage == "extra":
                db.execute("INSERT INTO security_state SELECT state FROM security_state")
            else:
                payload = "x" * (r.MAX_STATE_BYTES + 1) if damage == "oversize" else (
                    b"{}" if damage == "blob" else '{"version":')
                db.execute("UPDATE security_state SET state=?", (payload,))
    assert status(opened()) == "quarantined"


@pytest.mark.parametrize("point", ["before_pending", "after_deny", "after_pending", "after_db",
                                   "after_journal", "before_ack"])
def test_bootstrap_interrupted(tmp_path, point):
    def opened(**kwargs):
        return r.Broker(tmp_path / "registry", tmp_path / "journal.json", b"x" * 32,
                        directory_barrier=lambda p: None, clock=lambda: 1000, **kwargs)
    def crash(actual):
        if actual == point:
            raise Crash()
    with pytest.raises(Crash):
        offline_fixture_bootstrap(opened(hook=crash), fixture_state(), trusted_fixture=True)
    assert status(opened()) == "quarantined"
    with pytest.raises(r.Denied):
        offline_fixture_bootstrap(opened(), fixture_state(), trusted_fixture=True)


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize("boundary", ["open", "write", "rename"])
@pytest.mark.parametrize("index", range(1, 5))
def test_exact_anchor_io_fault(tmp_path, rig, monkeypatch, bootstrap, boundary, index):
    b, opened = rig
    if bootstrap:
        def opened():
            return r.Broker(tmp_path / "new-registry", tmp_path / "new-journal.json", b"x" * 32,
                            directory_barrier=lambda p: None, clock=lambda: 1000)
        b = opened()
    original_open, original_replace = r.Path.open, r.os.replace
    calls = 0
    targets = {p.with_suffix(p.suffix + ".next") for p in (b._journal, b._guard)}
    def fault():
        nonlocal calls
        calls += 1
        if calls == index:
            raise OSError(TOKEN)
    class Writer:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def write(self, raw):
            fault()
            return self.stream.write(raw)
        def flush(self):
            return self.stream.flush()
        def fileno(self):
            return self.stream.fileno()
    def targeted_open(path, mode="r", *args, **kwargs):
        if path in targets and mode == "xb":
            if boundary == "open":
                fault()
            stream = original_open(path, mode, *args, **kwargs)
            return Writer(stream) if boundary == "write" else stream
        return original_open(path, mode, *args, **kwargs)
    def targeted_replace(src, dst):
        if src in targets:
            fault()
        return original_replace(src, dst)
    with monkeypatch.context() as patch:
        if boundary == "rename":
            patch.setattr(r.os, "replace", targeted_replace)
        else:
            patch.setattr(r.Path, "open", targeted_open)
        with pytest.raises(r.Denied) as caught:
            if bootstrap:
                offline_fixture_bootstrap(b, fixture_state(), trusted_fixture=True)
            else:
                b._revoke("a" * 32)
    assert str(caught.value) == "Broker unavailable"
    assert caught.value.__context__ is None
    evidence = {p: p.read_bytes() for p in targets if p.exists()}
    assert status(b) == status(opened()) == "quarantined"
    assert all(p.read_bytes() == raw for p, raw in evidence.items())


@pytest.mark.parametrize("point", ["before_pending", "after_pending", "before_ack"])
def test_fallback_denial_failure(rig, monkeypatch, point):
    b, opened = rig
    def crash(actual):
        if actual == point:
            raise Crash()
    b._hook = crash
    original = b._anchor
    def anchor(path, record):
        if b._poisoned:
            raise OSError(TOKEN)
        return original(path, record)
    monkeypatch.setattr(b, "_anchor", anchor)
    with pytest.raises(Crash):
        b._revoke("a" * 32)
    assert status(b) == "quarantined"
    # No storage mutation permits old state; final committed state permits only
    # the exact new revision. Failed storage cannot promise persistent poisoning.
    if point == "before_pending":
        assert status(opened()) == "verified"
        assert opened()._checked()["revision"] == 1
    elif point == "before_ack":
        assert opened()._checked()["revision"] == 2
        assert status(opened(), revision=2) == "denied"  # revoked
    else:
        assert status(opened()) == "quarantined"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", sorted(PROFILES))
async def test_entire_client_profile_contract(rig, profile, caplog):
    from backend.services.identity_broker_verify_client import VerifyClient
    b, _ = rig
    state = b._read_db()
    policy = PROFILES[profile]
    kind = "browser_session" if profile in {"owner_browser", "kiosk"} else "native_bearer"
    state["credentials"]["a" * 32].update(
        profile=profile, source=policy.source, kind=kind,
        grants=[list(g) for g in sorted(policy.grants)])
    b._transition(state)
    class OfflineIO:
        response = None
        source = None
        async def exchange_verify(self, raw):
            response = r.unframe(b.process(raw))
            self.response = response
            if self.source is not None and response["status"] == "verified":
                response["source"] = self.source
            wire = r.frame(response)
            assert TOKEN.encode() not in wire
            return wire
    io = OfflineIO()
    generation, revision = GEN, 1
    client = VerifyClient(io, generation=lambda: generation, revision=lambda: revision,
                          clock=lambda: 1000)
    async def authorize(operation, lane):
        return await client.authorize(TOKEN, operation, lane=lane, stage="active")
    for operation, lane in sorted(policy.grants):
        identity = await authorize(operation, lane)
        assert identity is not None
        assert (identity.profile, identity.source, identity.lane) == (profile, policy.source, lane)
        assert io.response["kind"] == kind
        assert (io.response["operation"], io.response["lane"]) == (operation, lane)
        assert await authorize(operation, "invalid_lane") is None
        io.source = "wrong_source"
        assert await authorize(operation, lane) is None
        io.source = None
    operation, lane = next(iter(sorted(policy.grants)), ("GET /api/automation/status", "browser"))
    assert await authorize("unknown operation", lane) is None
    if not policy.grants:
        assert await authorize(operation, lane) is None  # guest_gateway grants nothing
    generation = "0" * 32
    assert await authorize(operation, lane) is None
    generation, revision = GEN, 2
    assert await authorize(operation, lane) is None
    revision = 1
    b._clock = lambda: 2000
    assert await authorize(operation, lane) is None
    b._clock = lambda: 1000
    b._revoke("a" * 32)
    revision = 2
    assert await authorize(operation, lane) is None
    assert TOKEN not in caplog.text


def test_oversized_files_refused_before_open(rig, monkeypatch):
    b, _ = rig
    b._db.write_bytes(b"x" * (r.MAX_DB_BYTES + 1))
    def forbidden(*args, **kwargs):
        pytest.fail("oversized input reached bulk read")
    with monkeypatch.context() as patch:
        patch.setattr(r.sqlite3, "connect", forbidden)
        with pytest.raises(r.Denied) as caught:
            b._read_db()
    assert caught.value.__context__ is None
    b._journal.write_bytes(b"x" * (r.MAX_ANCHOR_BYTES + 1))
    with monkeypatch.context() as patch:
        patch.setattr(r.Path, "open", forbidden)
        with pytest.raises(r.Denied):
            r.bounded_read(b._journal, r.MAX_ANCHOR_BYTES)


def test_regular_file_metadata_required(tmp_path):
    with pytest.raises(r.Denied):
        r.bounded_read(tmp_path, r.MAX_ANCHOR_BYTES)


def test_inventory_limit_inclusive(rig):
    b, _ = rig
    state = b._read_db()
    record = state["credentials"]["a" * 32]
    state["credentials"] = {f"{i:032x}": record for i in range(r.MAX_CREDENTIALS)}
    b._transition(state)
    assert len(b._checked()["credentials"]) == r.MAX_CREDENTIALS
    state["credentials"]["f" * 32] = record
    with pytest.raises(r.Denied):
        b._validate(state)
