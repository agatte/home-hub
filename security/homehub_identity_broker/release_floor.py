"""Pure diagnostic contract, NOT a launcher, signature verifier or trust provider.

Expected floor/provenance must ultimately come from independently authenticated
OS policy outside the checkout and app backups. This module cannot obtain that
trust: even matching injected fixtures remain BLOCKED. No IO or execution.
"""
from dataclasses import dataclass
from hashlib import sha256
import re


SURFACES = (
    "boot", "service-restart", "deploy-forward", "rollback",
    "failed-deploy-recovery", "return-home", "direct-user-restart",
    "linger-alternate-user-service", "restored-checkout", "manual-process",
)
GATES = (
    "independent-authenticated-floor-unavailable",
    "independent-os-launcher-enforcement-unavailable",
    "installed-units-dropins-aliases-and-manual-processes-unverified",
)
PACKAGE = "homehub-backend-sealed-v1"
PATH = "/opt/homehub-backend/package"
IDENTITY = "homehub-backend"
_KEYS = {"schema", "epoch", "generation", "commit_sha", "artifact_sha256",
         "provenance_sha256", "package", "path", "identity", "surfaces"}


@dataclass(frozen=True)
class Report:
    issues: tuple[str, ...]
    evidence: tuple = ()

    @property
    def runtime_authorized(self):
        return False

    @property
    def status(self):
        return "BLOCKED"

    @property
    def fixture_consistent(self):
        return self.issues == GATES


def _uint(value):
    return type(value) is int and 0 <= value < 2**64


def _record(value):
    return (
        type(value) is dict and set(value) == _KEYS
        and type(value["schema"]) is int and value["schema"] == 1
        and _uint(value["epoch"]) and _uint(value["generation"])
        and all(type(value[k]) is str and re.fullmatch(pattern, value[k])
                for k, pattern in (("commit_sha", r"[0-9a-f]{40}"),
                                   ("artifact_sha256", r"[0-9a-f]{64}"),
                                   ("provenance_sha256", r"[0-9a-f]{64}")))
        and value["package"] == PACKAGE and type(value["package"]) is str
        and value["path"] == PATH and type(value["path"]) is str
        and value["identity"] == IDENTITY and type(value["identity"]) is str
        and type(value["surfaces"]) is tuple and value["surfaces"] == SURFACES
        and all(type(s) is str for s in value["surfaces"])
    )


def evaluate(candidate, stored_floor, *, expected_floor, expected_release, surface):
    """Compare fixed-schema snapshots without interpreting SHA as version order.

    expected_floor/release are EXTERNAL expectations in the proposed protocol,
    not authenticated by injection here. A provenance digest is an exact binding
    to a future signed release inventory, NOT proof of a signature. No reviewed,
    signed, override or approval boolean is accepted. All four records are needed.
    Generation must equal fresh independent floor generation; epoch may advance
    only to the exact independently approved release, never below minimum.
    """
    issues = list(GATES)
    if not all(_record(v) for v in
               (candidate, stored_floor, expected_floor, expected_release)):
        return Report(tuple(issues + ["record-schema"]))
    if type(surface) is not str or surface not in SURFACES:
        issues.append("launch-surface")
    if stored_floor != expected_floor:
        issues.append("stale-or-mismatched-floor")
    if candidate != expected_release:
        issues.append("unapproved-release-or-provenance")
    if candidate["epoch"] < expected_floor["epoch"]:
        issues.append("below-floor")
    if candidate["generation"] != expected_floor["generation"]:
        issues.append("stale-generation")
    return Report(tuple(issues))


# Exact LF-normalized literal source snapshots, NOT approved release digests.
# Any source edit needs renewed analysis; no pattern absence can establish safety.
SOURCE_HASHES = (
    ("deployment/home-hub.service",
     "6ab7c3ea420d5f529828819c8cf3eb5e8644d0d9690b48bdb0d136e57542144d"),
    ("scripts/deploy.sh",
     "2398347dc2cdf447fe9ff8fb0c5b8b1c660d07c532ddaa1c6bd8f5a11eb16d72"),
    ("scripts/homehub-hostctl.sh",
     "dea4ea4f44cb0feb9c2ea2964a859e35db42068e2c479b9bdc215f61c2f8cd09"),
)
MATCHES = (
    (0, "mutable-user-exec", "ExecStart=%h/home-hub/venv/bin/python run.py"),
    (0, "user-unit-install", "WantedBy=default.target"),
    (1, "rollback-reset", 'git reset --hard "$target"'),
    (1, "user-restart", "systemctl --user restart home-hub.service"),
    (1, "failure-recovery", 'if rollback "$LAST_DEPLOYED"; then'),
    (1, "mutable-unit-copy", 'cp "deployment/$unit" "$HOME/.config/systemd/user/$unit"'),
    (2, "core-service", 'CORE_SERVICE="home-hub.service"'),
    (2, "user-enable", 'systemctl --user enable --now "$unit"'),
    (2, "return-home-start", 'if ! enable_start_if_known "$CORE_SERVICE" || ! wait_for_backend; then'),
)


@dataclass(frozen=True)
class Evidence:
    path: str
    label: str
    start: int  # Unicode character offsets in LF-normalized snapshot; end exclusive.
    end: int


def audit_entrypoints(snapshots):
    """Read-only TEXT audit; only three literal repo paths, no path IO or shell.

    Known legacy shapes positively prove bypass presence. Unknown/extra/rewritten
    shapes deny as uncertainty, never infer an OS guard from edited repo text.
    Does not inspect installed services, drop-ins, linger or manual processes.
    """
    issues = list(GATES)
    if type(snapshots) is not dict or set(snapshots) != {p for p, _ in SOURCE_HASHES}:
        return Report(tuple(issues + ["source-inventory"]))
    evidence = []
    for index, (path, digest) in enumerate(SOURCE_HASHES):
        source = snapshots[path]
        if type(source) is not str or len(source) > 128 * 1024:
            issues.append("source-type-or-size")
            continue
        source = source.replace("\r\n", "\n")
        try:
            matches_snapshot = sha256(source.encode("utf-8")).hexdigest() == digest
        except UnicodeError:
            matches_snapshot = False
        if not matches_snapshot:
            issues.append("unrecognized-source:" + path)
        for ordinal, label, literal in MATCHES:
            if ordinal != index:
                continue
            offset = source.find(literal)
            if offset == -1:
                issues.append("missing-shape:" + label)
                continue
            while offset != -1:
                evidence.append(Evidence(path, label, offset, offset + len(literal)))
                offset = source.find(literal, offset + len(literal))
            issues.append("bypass-present:" + label)
    return Report(tuple(issues), tuple(evidence))


@dataclass(frozen=True)
class Coverage:
    surface: str
    source_labels: tuple[str, ...]
    missing: str


def coverage():
    """Static source relationships, never installed-host execution proof.

    Labels refer to MATCHES only; audit evidence must separately confirm them.
    Every row requires external OS enforcement, including source-observed cases.
    """
    return (
        Coverage("boot", ("mutable-user-exec", "user-unit-install"),
                 "effective-installed-units-and-boot-enforcement"),
        Coverage("service-restart", ("mutable-user-exec",),
                 "effective-installed-unit-and-restart-enforcement"),
        Coverage("deploy-forward", ("user-restart", "mutable-unit-copy"),
                 "forward-target-and-launch-enforcement"),
        Coverage("rollback", ("rollback-reset", "user-restart", "mutable-unit-copy"),
                 "rollback-target-and-launch-enforcement"),
        Coverage("failed-deploy-recovery", ("failure-recovery", "rollback-reset", "user-restart"),
                 "health-failure-and-interrupted-recovery-enforcement"),
        Coverage("return-home", ("core-service", "user-enable", "return-home-start"),
                 "effective-hostctl-and-return-enforcement"),
        Coverage("direct-user-restart", ("mutable-user-exec",),
                 "manual-systemctl-and-effective-dropins-unverified"),
        Coverage("linger-alternate-user-service", (),
                 "all-user-managers-aliases-linger-and-units-unverified"),
        Coverage("restored-checkout", ("mutable-user-exec", "rollback-reset"),
                 "older-checkout-and-floor-restore-enforcement"),
        Coverage("manual-process", (), "direct-executable-and-interpreter-exclusion-unverified"),
    )
