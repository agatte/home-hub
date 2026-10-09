"""Test-only protocol, not an OS boundary or production credential implementation.

The fixture owns paths, peer provenance, approval and the single shared gate.
JSON hashes are integrity comparisons, not authenticated or monotonic anchors.
"""
from dataclasses import dataclass, field
from contextlib import closing
import copy
import hashlib
import json
import math
import os
import sqlite3
import uuid


class Quarantined(RuntimeError):
    def __init__(self):
        super().__init__("synthetic broker unavailable")


class Crash(BaseException):
    pass


@dataclass(frozen=True)
class Peer:
    uid: int


@dataclass(frozen=True)
class Issued:
    id: str
    token: str = field(repr=False)


def canonical(state):
    return json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(state):
    return hashlib.sha256(canonical(state).encode()).hexdigest()


class Broker:
    BACKEND = 100
    ADMIN = 200
    PROTOCOL = 2
    PROFILES = {"synthetic_owner": ("synthetic_browser", {"read", "write"}),
                "synthetic_display": ("synthetic_display", {"read"})}

    def __init__(self, root, gate, *, code=2, deployment="synthetic-instance",
                 startup_floor=2, directory_barrier=lambda: None, hook=lambda point: None):
        self.root, self.gate = root, gate
        self.db = root / "registry.sqlite"
        self.journal = root / "journal.json"
        self.guard = root / "deny.guard"
        self.code, self.deployment, self.floor = code, deployment, startup_floor
        self.directory_barrier, self.hook = directory_barrier, hook

    def __repr__(self):
        return "<SyntheticBroker offline>"

    def _admin(self, peer, approved):
        if type(peer) is not Peer or peer.uid not in (0, self.ADMIN) or approved is not True:
            raise PermissionError("modeled interactive admin approval required")

    def _read(self):
        # mode=rw forbids accidental creation on open, including recovery.
        with closing(sqlite3.connect(self.db.as_uri() + "?mode=rw", uri=True)) as db:
            rows = db.execute("SELECT state FROM security_state").fetchall()
            if len(rows) != 1:
                raise Quarantined()
            return json.loads(rows[0][0])

    def _record(self, state, status):
        return {"status": status, "target": state, "digest": digest(state)}

    def _anchor(self, record, *, guard=False):
        destination = self.guard if guard else self.journal
        temp = self.root / ("guard.next" if guard else "journal.next")
        with temp.open("w", encoding="utf-8") as stream:
            stream.write(canonical(record))
            stream.flush()
            os.fsync(stream.fileno())
        self.hook("before_guard_replace" if guard else "before_replace")
        os.replace(temp, destination)
        # Explicit model barrier: real directory fsync needs platform validation.
        self.directory_barrier()

    def _sqlite(self, state, *, create=False):
        uri = self.db.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        with closing(sqlite3.connect(uri, uri=True)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            if create:
                db.execute("CREATE TABLE security_state (state TEXT NOT NULL)")
                db.execute("INSERT INTO security_state VALUES (?)", (canonical(state),))
            else:
                db.execute("UPDATE security_state SET state=?", (canonical(state),))
                if db.execute("SELECT count(*) FROM security_state").fetchone()[0] != 1:
                    raise Quarantined()

    def _compatible(self, state):
        return (self.code >= self.floor and self.code >= state["minimum_code"]
                and state["protocol"] == self.PROTOCOL
                and state["instance"] == self.deployment)

    def _checked(self, *, recovery=False):
        try:
            record = json.loads(self.journal.read_text(encoding="utf-8"))
            state = self._read()
            if not recovery and self.guard.exists():
                raise Quarantined()
            if recovery:
                guard = json.loads(self.guard.read_text(encoding="utf-8"))
                if guard != self._record(state, "PENDING"):
                    raise Quarantined()
            if (record["status"] not in (("PENDING", "COMMITTED") if recovery else ("COMMITTED",))
                    or record != self._record(state, record["status"])
                    or not self._compatible(state)):
                raise Quarantined()
            return state
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
            raise Quarantined() from None

    def _empty(self, revision):
        return {"instance": self.deployment, "generation": uuid.uuid4().hex,
                "revision": revision, "protocol": self.PROTOCOL, "minimum_code": 2,
                "credentials": {}, "sessions": {}, "tickets": {}}

    def _finalize(self, state):
        # Visible COMMITTED bytes never override the independently protected guard.
        self._anchor(self._record(state, "COMMITTED"))
        self._checked(recovery=True)
        self.hook("before_guard_clear")
        self.guard.unlink()
        try:
            self.directory_barrier()  # modeled durability of guard deletion
        except BaseException:
            # Preserve denial for fresh objects in this exception model. Real power
            # loss during unlink/fsync requires platform-specific crash validation.
            self._anchor(self._record(state, "PENDING"), guard=True)
            raise
        self.hook("after_finalization")
        self._checked()
        self.hook("before_ack")

    def _transition(self, state, *, create=False):
        self.hook("before_pending")  # command NOT ACCEPTED yet
        self._anchor(self._record(state, "PENDING"), guard=True)
        self.hook("after_intent")  # durable stop-serving acceptance boundary
        self._anchor(self._record(state, "PENDING"))
        self.hook("after_pending")
        self._sqlite(state, create=create)
        self.hook("after_sqlite")
        self._finalize(state)

    def admin(self, peer, approved, command, **args):
        self._admin(peer, approved)
        with self.gate:
            if self.code < self.floor or self.code < 2:
                raise Quarantined()
            if command == "bootstrap":
                if self.db.exists() or self.journal.exists() or self.guard.exists():
                    raise Quarantined()
                self._transition(self._empty(0), create=True)
                return None
            if command == "recover_pending":
                state = self._checked(recovery=True)
                # Explicit recovery reestablishes SQLite durability too; visibility
                # alone is insufficient evidence of a completed previous mutation.
                self._sqlite(state)
                self._finalize(state)
                return None
            if command in ("fresh_empty", "restore_intent_invalidate"):
                # Invalidation only: backup validation/import is deliberately deferred.
                if args:
                    raise ValueError("invalidation accepts no backup or other arguments")
                # Separately approved recovery, never import backup verifiers.
                # When anchor is unreadable a new random generation replaces unknown history;
                # no claim of reconstructing a lost monotonic revision is made.
                try:
                    record = json.loads(self.journal.read_text(encoding="utf-8"))
                    revision = record["target"]["revision"] + 1
                except (OSError, ValueError, KeyError, TypeError):
                    revision = 0
                self._transition(self._empty(revision), create=not self.db.exists())
                return None
            if command not in ("enroll", "revoke", "rotate", "delivery_confirmed"):
                raise PermissionError("unknown synthetic command")
            state = copy.deepcopy(self._checked())
            credentials = state["credentials"]
            result = None
            if command in ("enroll", "rotate"):
                if any(c["uncertain"] and not c["revoked"] for c in credentials.values()):
                    raise Quarantined()
                profile = args.get("profile", "synthetic_owner")
                if command == "rotate":
                    old = credentials[args["id"]]
                    if old["revoked"]:
                        raise Quarantined()
                    profile = old["profile"]
                    old["revoked"] = True  # deliberately zero-overlap rotation
                if profile not in self.PROFILES:
                    raise ValueError("unknown synthetic profile")
                expiry = args.get("expiry", 2000)
                if type(expiry) not in (int, float) or not math.isfinite(expiry) or not 1000 < expiry <= 3000:
                    raise ValueError("invalid synthetic expiry")
                ident, token = uuid.uuid4().hex, "fake-" + uuid.uuid4().hex
                credentials[ident] = {"profile": profile, "source": self.PROFILES[profile][0],
                    "verifier": hashlib.sha256(token.encode()).hexdigest(), "expiry": expiry,
                    "revoked": False, "uncertain": True}
                result = Issued(ident, token)
            else:
                credential = credentials[args["id"]]
                if command == "revoke":
                    credential["revoked"] = True
                elif credential["revoked"]:
                    raise Quarantined()
                else:
                    credential["uncertain"] = False
            state["revision"] += 1
            self._transition(state)
            return result

    def verify(self, peer, token, operation="read", *, now=1000, claimed_source=None):
        if type(peer) is not Peer or peer.uid != self.BACKEND:
            return False
        with self.gate:
            try:
                state = self._checked()
                self.hook("verify_locked")
                if not isinstance(token, str) or not math.isfinite(now):
                    return False
                candidate = hashlib.sha256(token.encode()).hexdigest()
                for c in state["credentials"].values():
                    policy = self.PROFILES.get(c["profile"])
                    if (policy and c["source"] == policy[0] and operation in policy[1]
                            and (claimed_source is None or claimed_source == c["source"])
                            and not c["revoked"] and not c["uncertain"] and now < c["expiry"]
                            and candidate == c["verifier"]):
                        return True
                return False
            except (Quarantined, KeyError, TypeError, ValueError):
                return False

    def diagnostics(self):
        with self.gate:
            try:
                self._checked()
                return "committed synthetic state"
            except Quarantined:
                return "quarantined synthetic state"
