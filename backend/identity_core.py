"""OFFLINE ONLY. No HTTP, CLI, default DB path, settings, or runtime wiring.

The administrator capability is an opaque object supplied by trusted embedding
code. Its OS provenance is NOT established here. Never expose it to a network
adapter. Whole-database rollback is NOT detected; see foundation documentation.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import math
import re
import secrets
import sqlite3
import time
from types import MappingProxyType

from backend.identity_policy import PROFILES

ITERATIONS = 600_000
MAX_OVERLAP = 3600
MAX_LIFETIME = 366 * 86400
_TOKEN = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class Enrollment:
    principal_id: str
    credential_id: str
    token: str = field(repr=False)


@dataclass(frozen=True)
class Identity:
    principal_id: str
    profile: str
    source: str
    lane: str


class IdentityStore:
    def __init__(self, path, *, local_capability, clock=time.time):
        if local_capability is None or type(local_capability) is not object:
            raise ValueError("An opaque embedding-supplied local capability is required")
        self._capability = local_capability
        self._clock = clock
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS identity_principals (
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, source TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)));
            CREATE TABLE IF NOT EXISTS identity_credentials (
                id TEXT PRIMARY KEY, principal_id TEXT NOT NULL REFERENCES identity_principals(id),
                salt BLOB NOT NULL, verifier BLOB NOT NULL, expires REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)));
        """)

    def close(self):
        self._db.close()

    def _local(self, capability):
        if capability is not self._capability:
            raise PermissionError("Local administrative capability required")

    def _now(self):
        now = self._clock()
        if not math.isfinite(now):
            raise ValueError("Invalid clock")
        return now

    @contextmanager
    def _transaction(self):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    @staticmethod
    def _duration(value, maximum):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError("Invalid bounded duration")

    def _issue(self, principal_id, expires):
        credential_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(32)
        verifier = hashlib.pbkdf2_hmac("sha256", secret.encode("ascii"), salt, ITERATIONS)
        self._db.execute("INSERT INTO identity_credentials VALUES (?,?,?,?,?,0)",
                         (credential_id, principal_id, salt, verifier, expires))
        return Enrollment(principal_id, credential_id, f"{credential_id}.{secret}")

    def enroll(self, profile, *, capability, lifetime=86400):
        self._local(capability)
        if profile not in PROFILES:
            raise ValueError("Unknown fixed profile")
        self._duration(lifetime, MAX_LIFETIME)
        principal_id = secrets.token_hex(16)
        with self._transaction():
            self._db.execute("INSERT INTO identity_principals VALUES (?,?,?,0)",
                             (principal_id, profile, PROFILES[profile].source))
            result = self._issue(principal_id, self._now() + lifetime)
        return result

    def rotate(self, principal_id, *, capability, overlap=0, lifetime=86400):
        self._local(capability)
        self._duration(lifetime, MAX_LIFETIME)
        if not isinstance(overlap, (int, float)) or not math.isfinite(overlap) or not 0 <= overlap <= MAX_OVERLAP:
            raise ValueError("Invalid overlap")
        with self._transaction():
            row = self._db.execute("SELECT * FROM identity_principals WHERE id=?", (principal_id,)).fetchone()
            if row is None or row["revoked"] or row["profile"] not in PROFILES or row["source"] != PROFILES[row["profile"]].source:
                raise ValueError("Inactive principal")
            now = self._now()
            # Repeated rotation cannot extend any predecessor's overlap.
            self._db.execute("UPDATE identity_credentials SET expires=min(expires,?) WHERE principal_id=?",
                             (now + overlap, principal_id))
            result = self._issue(principal_id, now + lifetime)
        return result

    def revoke(self, principal_id, *, capability):
        self._local(capability)
        with self._transaction():
            self._db.execute("UPDATE identity_principals SET revoked=1 WHERE id=?", (principal_id,))
            self._db.execute("UPDATE identity_credentials SET revoked=1 WHERE principal_id=?", (principal_id,))

    def revoke_credential(self, credential_id, *, capability):
        self._local(capability)
        with self._transaction():
            self._db.execute("UPDATE identity_credentials SET revoked=1 WHERE id=?", (credential_id,))

    def authorize(self, token, operation, *, lane, claimed_source=None):
        """Revalidate every action. `lane`/operation MUST come from server code.

        Caller source can only constrain/deny; identity source comes from registry.
        The shared desktop credential does not cryptographically isolate its lanes.
        """
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return None
        # Refuse caller-owned transactions: hashing must never retain their locks.
        if self._db.in_transaction:
            raise RuntimeError("Authorization requires an idle connection")
        credential_id, secret = token.split(".")
        snapshot = self._credential_snapshot(credential_id)
        profile = self._eligible(snapshot, operation, lane, claimed_source)
        if profile is None:
            return None
        candidate = hashlib.pbkdf2_hmac("sha256", secret.encode("ascii"), snapshot["salt"], ITERATIONS)
        if not hmac.compare_digest(candidate, snapshot["verifier"]):
            return None
        # Only this short phase reserves the writer. Busy/locked errors propagate
        # fail-closed; callers must never turn an exception into a grant.
        with self._transaction():
            current = self._credential_snapshot(credential_id)
            if current != snapshot:
                return None
            if self._eligible(current, operation, lane, claimed_source) != profile:
                return None
            return Identity(current["principal_id"], current["profile"], current["source"], lane)

    def _credential_snapshot(self, credential_id):
        cursor = self._db.execute("""SELECT c.id, c.principal_id, c.salt, c.verifier,
            c.expires, c.revoked, p.profile, p.source,
            p.revoked AS principal_revoked FROM identity_credentials c
            JOIN identity_principals p ON p.id=c.principal_id WHERE c.id=?""", (credential_id,))
        try:
            row = cursor.fetchone()
            # Detached values only; finalize the statement before expensive work.
            return MappingProxyType(dict(row)) if row is not None else None
        finally:
            cursor.close()

    def _eligible(self, row, operation, lane, claimed_source):
        if row is None:
            return None
        profile = PROFILES.get(row["profile"])
        if (profile is None or row["source"] != profile.source or row["principal_revoked"]
                or row["revoked"] or not math.isfinite(row["expires"]) or self._now() >= row["expires"]
                or (operation, lane) not in profile.grants
                or claimed_source is not None and claimed_source != row["source"]):
            return None
        return profile
