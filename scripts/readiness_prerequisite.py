"""Inactive readiness migration primitives. No CLI, service or Git mutations.

Not wired into deploy/backup/hostctl. Admission evidence must be independently
reviewed; matching hashes establish source identity, not runtime correctness.
"""
from dataclasses import dataclass
import hashlib
import re
import subprocess
from typing import Callable, Mapping


URL = "http://localhost:8000/api/readiness"
CONTRACT = "homehub-bootstrap-readiness-v1"
# Pin Host while avoiding DNS/proxy routing. Never accept a caller URL or query.
CURL = (
    "curl", "--disable", "--silent", "--show-error", "--proxy", "",
    "--noproxy", "*", "--proto", "=http", "--max-redirs", "0",
    "--connect-timeout", "1", "--max-time", "2", "--max-filesize", "1024",
    "--resolve", "localhost:8000:127.0.0.1", "--request", "GET",
    "--header", "Host: localhost:8000", "--header", "Accept: application/json",
    "--write-out", "\n%{http_code}\n%{content_type}\n%{num_redirects}", URL,
)
ARTIFACTS = (
    "backend/api/routes/health.py", "backend/bootstrap.py", "backend/main.py",
    "scripts/readiness_prerequisite.py",
)


def evaluate_response(status: str, content_type: str, redirects: str, body: bytes) -> bool:
    """Require the fixed wire representation; no JSON coercion/duplicate keys."""
    return (
        status == "200" and content_type == "application/json"
        and redirects == "0" and body == b'{"ready":true}'
    )


def probe(*, run: Callable = subprocess.run) -> bool:
    """One bounded attempt; every failure is unavailable, with no fallback.

    Curl config is disabled as its first option. No cookies, credentials,
    X-Source, redirects or environment proxy are used. stderr is never exposed.
    Caller owns retry budget. This function must not be called during import.
    """
    try:
        result = run(CURL, capture_output=True, timeout=3, check=False)
        if result.returncode != 0 or len(result.stdout) > 1200:
            return False
        body, status, media, redirects = result.stdout.rsplit(b"\n", 3)
        return evaluate_response(status.decode("ascii"), media.decode("ascii"),
                                 redirects.decode("ascii"), body)
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return False


@dataclass(frozen=True)
class ReviewedTarget:
    """Owner-authored exact-target evidence, not a self-declared source flag.

    The reviewer must prove route admission, lifespan ordering and the response
    contract offline before supplying hashes. No live acceptance is implied.
    """
    sha: str
    contract: str
    digests: Mapping[str, str]


def admit_targets(last_deployed: str, forward: str, rollback: str,
                  reviewed: Mapping[str, ReviewedTarget],
                  read_blob: Callable[[str, str], bytes]) -> bool:
    """Read-only prerequisite for a FUTURE controller, before any side effect.

    read_blob must read only the named committed blob at the full SHA, never
    the working tree. No revision aliases, marker normalization or old-target
    fallback. Same-head baseline is valid. Missing evidence refuses admission.
    This deliberately cannot restart, reset, migrate, fetch or approve a target.
    """
    targets = (last_deployed, forward, rollback)
    if any(not isinstance(s, str) or not re.fullmatch(r"[0-9a-f]{40}", s)
           for s in targets) or last_deployed != rollback:
        return False
    try:
        for sha in set(targets):
            record = reviewed[sha]
            if (record.sha != sha or record.contract != CONTRACT
                    or set(record.digests) != set(ARTIFACTS)):
                return False
            for path in ARTIFACTS:
                expected = record.digests[path]
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    return False
                if hashlib.sha256(read_blob(sha, path)).hexdigest() != expected:
                    return False
        return True
    except (KeyError, OSError, ValueError, TypeError):
        return False
