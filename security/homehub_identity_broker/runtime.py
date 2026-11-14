"""Protected-state algorithm; OS custody and a single process are external gates.

No automatic recovery, token minting, operator authentication or public admin API.
Private mutation methods are integration seams, NOT authorization mechanisms.
"""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import stat
import threading
import time
from contextlib import closing

from .policy import PROFILES

HEX = re.compile(r"[0-9a-f]{32}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}\Z")
VERSION = 1
MAX_FRAME = 2048
ITERATIONS = 600_000
MAX_STATE_BYTES = 256 * 1024
MAX_CREDENTIALS = 128
MAX_ANCHOR_BYTES = MAX_STATE_BYTES + 512
MAX_DB_BYTES = 1024 * 1024


def checked_metadata(metadata, limit):
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
        raise Denied()


def bounded_read(path, limit):
    checked_metadata(path.lstat(), limit)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        checked_metadata(before, limit)
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or len(raw) > limit
            or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)):
        raise Denied()
    return raw


class Denied(RuntimeError):
    def __init__(self):
        super().__init__("Broker unavailable")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Denied()
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(Denied()))


def frame(value):
    body = canonical(value)
    if not 1 <= len(body) <= MAX_FRAME:
        raise Denied()
    return struct.pack("!I", len(body)) + body


def unframe(raw):
    try:
        if (type(raw) is not bytes or not 5 <= len(raw) <= MAX_FRAME + 4
                or struct.unpack("!I", raw[:4])[0] != len(raw) - 4):
            raise Denied()
        value = parse(raw[4:])
        if type(value) is not dict:
            raise Denied()
        return value
    except Exception:
        pass
    raise Denied()


def hex32(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1e12


def directory_sync(path):
    """Production default refuses unsupported platforms; Windows fixtures inject."""
    if os.name != "posix":
        raise Denied()
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Broker:
    def __init__(self, registry, journal, key, *, directory_barrier=directory_sync,
                 hook=lambda point: None, clock=time.time):
        # key is separately protected injected material, never read from registry.
        if type(key) is not bytes or len(key) < 32:
            raise Denied()
        self._db, self._journal = Path(registry), Path(journal)
        self._guard = self._journal.with_suffix(".deny")
        self._key = key
        self._barrier, self._hook, self._clock = directory_barrier, hook, clock
        self._lock = threading.Lock()
        self._poisoned = False

    def __repr__(self):
        return "<Broker source-only>"

    def _validate(self, state):
        if (set(state) != {"version", "minimum_code", "generation", "revision", "credentials",
                          "rotations", "pending_delivery"}
                or type(state["version"]) is not int or state["version"] != VERSION
                or type(state["minimum_code"]) is not int or state["minimum_code"] != VERSION
                or not hex32(state["generation"]) or type(state["revision"]) is not int
                or not 1 <= state["revision"] <= 2**53 - 1
                or type(state["credentials"]) is not dict
                or len(state["credentials"]) > MAX_CREDENTIALS
                or state["rotations"] != [] or state["pending_delivery"] != []):
            raise Denied()
        if len(canonical(state)) > MAX_STATE_BYTES:
            raise Denied()
        # Rotation/delivery inventories are reserved and must remain empty until
        # recipient-bound delivery is implemented. No inert unvalidated records.
        for cid, c in state["credentials"].items():
            if (not hex32(cid) or type(c) is not dict or set(c) != {
                    "principal_id", "profile", "source", "grants", "kind", "expires_at",
                    "revoked", "salt", "verifier", "iterations"}
                    or not hex32(c["principal_id"]) or type(c["profile"]) is not str
                    or c["profile"] not in PROFILES):
                raise Denied()
            p = PROFILES[c["profile"]]
            if (c["source"] != p.source or c["grants"] != [list(g) for g in sorted(p.grants)]
                    or c["kind"] != ("browser_session" if c["profile"] in {
                        "owner_browser", "kiosk"} else "native_bearer")
                    or not timestamp(c["expires_at"]) or type(c["revoked"]) is not bool
                    or not hex32(c["salt"]) or type(c["verifier"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", c["verifier"]) is None
                    or type(c["iterations"]) is not int or c["iterations"] != ITERATIONS):
                raise Denied()

    def _record(self, state, status):
        payload = {"status": status, "state": state}
        return {**payload, "mac": hmac.new(self._key, canonical(payload), "sha256").hexdigest()}

    def _read_db(self):
        try:
            checked_metadata(self._db.lstat(), MAX_DB_BYTES)
            with closing(sqlite3.connect(self._db.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_STATE_BYTES + 1024)
                # Bound row enumeration and inspect bytes/type before selecting payload.
                rows = db.execute(
                    "SELECT typeof(state), length(CAST(state AS BLOB)) "
                    "FROM security_state LIMIT 2").fetchmany(2)
                if (len(rows) != 1 or rows[0][0] != "text"
                        or not 0 < rows[0][1] <= MAX_STATE_BYTES):
                    raise Denied()
                row = db.execute(
                    "SELECT substr(CAST(state AS BLOB), 1, ?) FROM security_state LIMIT 1",
                    (MAX_STATE_BYTES + 1,)).fetchone()
                if row is None or len(row[0]) != rows[0][1]:
                    raise Denied()
                state = parse(row[0])
            return state
        except Exception:
            pass
        raise Denied()

    def _checked(self):
        if self._poisoned:
            raise Denied()
        # An incomplete exclusive write is persistent evidence of uncertainty.
        # Never clean or finish it automatically, even if committed bytes match.
        if any(p.with_suffix(p.suffix + ".next").exists()
               for p in (self._guard, self._journal)):
            raise Denied()
        state = self._read_db()
        self._validate(state)
        expected = self._record(state, "COMMITTED")
        for path in (self._guard, self._journal):
            actual = parse(bounded_read(path, MAX_ANCHOR_BYTES))
            if not hmac.compare_digest(canonical(actual), canonical(expected)):
                raise Denied()
        return state

    def _anchor(self, destination, record):
        # Exclusive temp creation preserves uncertain artifacts, never overwrites.
        temp = destination.with_suffix(destination.suffix + ".next")
        with temp.open("xb") as stream:
            stream.write(canonical(record))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
        self._barrier(destination.parent)

    def _write_db(self, state, create=False):
        mode = "rwc" if create else "rw"
        with closing(sqlite3.connect(self._db.resolve().as_uri() + "?mode=" + mode,
                                     uri=True)) as db, db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if create:
                db.execute("CREATE TABLE security_state (state TEXT NOT NULL)")
                db.execute("INSERT INTO security_state VALUES (?)", (canonical(state).decode(),))
            else:
                if db.execute("UPDATE security_state SET state=?",
                              (canonical(state).decode(),)).rowcount != 1:
                    raise Denied()
        self._barrier(self._db.parent)

    def _transition(self, state, *, create=False):
        self._validate(state)
        pending = self._record(state, "PENDING")
        try:
            self._hook("before_pending")
            self._anchor(self._guard, pending)
            self._hook("after_deny")
            self._anchor(self._journal, pending)
            self._hook("after_pending")
            self._write_db(state, create)
            self._hook("after_db")
            self._anchor(self._journal, self._record(state, "COMMITTED"))
            self._hook("after_journal")
            # Re-read DB before opening the final denial fence.
            if canonical(self._read_db()) != canonical(state):
                raise Denied()
            self._anchor(self._guard, self._record(state, "COMMITTED"))
            self._checked()
            self._hook("before_ack")
        except BaseException:
            self._poisoned = True
            # Best-effort persistent denial for ordinary I/O exceptions. Power
            # loss / failed storage cannot be repaired or proven by Python.
            try:
                self._anchor(self._guard, pending)
            except BaseException:
                pass
            raise

    def _mutate(self, change):
        try:
            with self._lock:
                state = self._checked()
                change(state)
                state["revision"] += 1
                self._transition(state)
                return state["generation"], state["revision"]
        except Exception:
            pass
        raise Denied()

    def _revoke(self, credential_id):
        def change(state):
            state["credentials"][credential_id]["revoked"] = True
        return self._mutate(change)

    def _rotate(self, old_id, new_id, new_record):
        """Private prehashed-record transition; no minting or delivery channel.

        Future privileged owner must authenticate recipient before enabling this
        seam. Rotation revokes old material atomically with installing replacement.
        """
        def change(state):
            old = state["credentials"][old_id]
            if (not hex32(new_id) or new_id in state["credentials"]
                    or new_record["principal_id"] != old["principal_id"]
                    or new_record["profile"] != old["profile"]
                    or new_record["revoked"] is not False
                    or new_record["verifier"] == old["verifier"]):
                raise Denied()
            old["revoked"] = True
            # Canonical roundtrip prevents caller-owned mutable aliases.
            state["credentials"][new_id] = parse(canonical(new_record))
        return self._mutate(change)

    def _restore_empty(self, new_generation):
        # Does not import any restored credential bytes. Re-enrollment separate.
        def change(state):
            if not hex32(new_generation) or new_generation == state["generation"]:
                raise Denied()
            state.update(generation=new_generation, credentials={}, rotations=[], pending_delivery=[])
        return self._mutate(change)

    def process(self, raw):
        """One complete bounded frame. Malformed envelopes close via fixed error.

        Transport must bound allocation/read/deadline before calling this method.
        No administrative opcode and no authority derived from claimed operation.
        """
        request = unframe(raw)
        if (set(request) != {"version", "method", "nonce", "token", "operation", "lane",
                             "generation", "revision"}
                or type(request["version"]) is not int or request["version"] != VERSION
                or request["method"] != "verify" or not hex32(request["nonce"])
                or not hex32(request["generation"]) or type(request["revision"]) is not int
                or not 1 <= request["revision"] <= 2**53 - 1
                or type(request["token"]) is not str or TOKEN.fullmatch(request["token"]) is None
                or type(request["operation"]) is not str or type(request["lane"]) is not str):
            raise Denied()
        response = {k: request[k] for k in ("version", "nonce", "generation", "revision")}
        response["status"] = "denied"
        try:
            with self._lock:
                state = self._checked()
                self._hook("verify_locked")
                if (request["generation"], request["revision"]) == (
                        state["generation"], state["revision"]):
                    cid, secret = request["token"].split(".")
                    c = state["credentials"].get(cid)
                    now = self._clock()
                    if c and timestamp(now) and not c["revoked"] and c["expires_at"] > now:
                        verifier = hashlib.pbkdf2_hmac("sha256", secret.encode("ascii"),
                                                      bytes.fromhex(c["salt"]), ITERATIONS).hex()
                        decision_time = self._clock()
                        if (timestamp(decision_time) and c["expires_at"] > decision_time
                                and hmac.compare_digest(verifier, c["verifier"])
                                and (request["operation"], request["lane"]) in PROFILES[c["profile"]].grants):
                            response.update({k: c[k] for k in (
                                "principal_id", "profile", "source", "kind", "expires_at")})
                            response.update(status="verified", operation=request["operation"], lane=request["lane"])
                # Every decision rechecks protected state; no positive cache.
                self._checked()
        except Exception:
            response = {k: request[k] for k in ("version", "nonce", "generation", "revision")}
            response["status"] = "quarantined"
        return frame(response)
