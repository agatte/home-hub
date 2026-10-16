"""HomeHub #399 offline integration experiment; never a real-Vault updater.

Composes existing fixture-only preview, filewise publication and read-only
transaction inspection. Cannot install a task, fetch GitHub or bypass the
synthetic path guard. No automatic recovery or lock breaking.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from hashlib import sha256

from obsidian_filewise_fixture_transaction import (
    _fixture_vault, _paths, _read_journal,
    inspect_fixture_recovery, publish_disposable_fixture,
)
from obsidian_filewise_preview import preview_filewise_refresh
from obsidian_github_docs_source import PreparedDocs
from manage_obsidian_vault import MANIFEST, reject_link, verify_sealed
from obsidian_cycle_lease import (
    CycleLeaseOccupied, exclusive_cycle_lease, lease_path,
)


@dataclass(frozen=True)
class PriorTransaction:
    suffix: str
    old_commit: str
    new_commit: str


@dataclass(frozen=True)
class CycleStatus:
    outcome: str
    reason: str
    old_commit: str | None = None
    target_commit: str | None = None
    requires_review: bool = False
    host_refresh_authorized: bool = False
    pre_cleanup_outcome: str | None = None


def _needs_review(vault: Path, suffix: str) -> bool:
    backup, stage, journal, pending = _paths(vault, suffix)
    lock = vault.parent / f".{vault.name}-homehub-refresh.lock"
    evidence = vault.parent / f".{vault.name}-homehub-filewise-artifacts-{suffix}"
    paths = (backup, stage, journal, pending, lock, evidence)
    for path in paths:
        reject_link(path)
    return any(p.exists() for p in paths)


def _unexpected_sibling_evidence(
    vault: Path, suffix: str, history: tuple[PriorTransaction, ...]
) -> bool:
    """Strict fixture-parent transaction namespace inventory, no modifications.

    Unknown/ambiguous transaction identities always block. This recognizes
    exact known candidate names, not a source for authorizing any recovery.
    """
    known = set()
    for item_suffix in (suffix, *(txn.suffix for txn in history)):
        backup, stage, journal, pending = _paths(vault, item_suffix)
        known.update(p.name.casefold() for p in (backup, stage, journal, pending))
        known.add(
            f".{vault.name}-homehub-filewise-artifacts-{item_suffix}".casefold()
        )
    known.add(f".{vault.name}-homehub-refresh.lock".casefold())
    known.add(lease_path(vault).name.casefold())
    prefix = f".{vault.name}-homehub".casefold()
    for entry in vault.parent.iterdir():
        if not entry.name.casefold().startswith(prefix):
            continue
        reject_link(entry)
        if entry.name.casefold() not in known:
            return True
    return False


def _verify_retained_published(vault: Path, txn: PriorTransaction) -> bool:
    """Verify a *historical* completed transaction without assuming the
    currently managed tree is still its new generation.

    Previous generations can no longer pass inspect_fixture_recovery()
    once a later generation is published. All their retained evidence
    must still match the exact sealed old and new manifests and journal.
    This is consistency checking, not authentication against a writer
    who can tamper with both journal and content.
    """
    backup, stage, journal, pending = _paths(vault, txn.suffix)
    evidence = (
        vault.parent / f".{vault.name}-homehub-filewise-artifacts-{txn.suffix}"
    )
    for path in (backup, stage, journal, pending, evidence):
        reject_link(path)
    if pending.exists() or evidence.exists():
        return False
    record = _read_journal(
        journal, txn.old_commit, txn.new_commit, txn.suffix
    )
    if record["phase"] != "published":
        return False
    old_meta = verify_sealed(backup)
    new_meta = verify_sealed(stage)
    if (old_meta["source_commit"] != txn.old_commit
            or new_meta["source_commit"] != txn.new_commit
            or sorted(old_meta["sha256"]) != record["old_paths"]
            or sorted(new_meta["sha256"]) != record["new_paths"]):
        return False
    if (sha256((backup / MANIFEST).read_bytes()).hexdigest()
            != record["old_manifest_sha256"]):
        return False
    if (sha256((stage / MANIFEST).read_bytes()).hexdigest()
            != record["new_manifest_sha256"]):
        return False
    return True


def _run_fixture_cycle_in_lease(
    *, vault: Path, expected_vault: Path, prepared: PreparedDocs, suffix: str,
    prior: PriorTransaction | None = None,
    history: tuple[PriorTransaction, ...] | None = None,
) -> CycleStatus:
    """Attempt one fixture cycle; do not repair or clear transaction evidence.

    Caller must supply the identity of a previously known transaction.
    Unrecognized sibling artifacts cause refusal. Caller must hold the
    cooperative cycle lease. External writers remain uncontrolled.
    """
    _fixture_vault(vault, expected_vault)
    _paths(vault, suffix)  # Check format even for no-change.
    if not isinstance(prepared, PreparedDocs) or prepared.refresh_authorized:
        return CycleStatus("blocked", "untrusted_prepared_input")
    if prior is not None and not isinstance(prior, PriorTransaction):
        return CycleStatus("blocked", "invalid_prior_transaction")
    if history is None:
        known_history = (prior,) if prior is not None else ()
    elif (not isinstance(history, tuple) or len(history) > 4096
          or any(not isinstance(item, PriorTransaction) for item in history)):
        return CycleStatus("blocked", "invalid_history")
    else:
        known_history = history
        if prior is not None and (not history or prior != history[-1]):
            return CycleStatus("blocked", "history_prior_disagreement")
    # The caller must supply the complete ordered chain of retained evidence,
    # not merely the last successful suffix. Anything unrecognized is refused.
    seen = set()
    for index, item in enumerate(known_history):
        if (item.suffix == suffix or item.suffix in seen
                or (index > 0 and known_history[index - 1].new_commit
                    != item.old_commit)):
            return CycleStatus("blocked", "invalid_retained_history_chain",
                               requires_review=True)
        seen.add(item.suffix)
        try:
            _paths(vault, item.suffix)
        except (ValueError, OSError):
            return CycleStatus("blocked", "invalid_retained_history_suffix",
                               requires_review=True)
    try:
        if _unexpected_sibling_evidence(vault, suffix, known_history):
            return CycleStatus("recovery_required", "unknown_transaction_artifacts",
                               requires_review=True)
    except (ValueError, OSError):
        return CycleStatus("recovery_required", "transaction_inventory_unverified",
                           requires_review=True)

    # All historical evidence must remain fully sealed and journal-bound.
    # Only the most recent generation can use the present managed-tree inspector.
    for item in known_history[:-1]:
        try:
            verified = _verify_retained_published(vault, item)
        except (ValueError, OSError):
            verified = False
        if not verified:
            return CycleStatus("recovery_required", "retained_history_unverified",
                               requires_review=True)
    if known_history:
        latest = known_history[-1]
        try:
            status = inspect_fixture_recovery(
                vault=vault, expected_vault=expected_vault,
                suffix=latest.suffix, old_commit=latest.old_commit,
                new_commit=latest.new_commit,
            )
        except (OSError, ValueError):
            return CycleStatus("recovery_required", "prior_inspection_failed",
                               requires_review=True)
        if (status.requires_operator_review or not status.backup_verified
                or status.state != "published"):
            return CycleStatus("recovery_required", "prior_" + status.reason,
                               requires_review=True)

    # Incomplete prior evidence takes precedence over comparing an intended
    # future source SHA. A mixed/unfinished managed tree needs review first.
    if (known_history and isinstance(prepared, PreparedDocs)
            and known_history[-1].new_commit != prepared.previously_sealed_commit):
        return CycleStatus("blocked", "source_history_mismatch",
                           requires_review=True)

    try:
        busy = _needs_review(vault, suffix)
    except (ValueError, OSError):
        return CycleStatus("recovery_required", "target_evidence_unverified",
                           requires_review=True)
    if busy:
        return CycleStatus("recovery_required", "target_transaction_evidence_present",
                           requires_review=True)

    try:
        plan = preview_filewise_refresh(
            vault=vault, expected_vault=expected_vault, prepared=prepared
        )
    except (ValueError, OSError):
        return CycleStatus("blocked", "preview_not_verified", requires_review=True)

    if plan.state == "no_change":
        return CycleStatus("up_to_date", "verified_no_change",
                           old_commit=plan.old_commit, target_commit=plan.new_commit)

    if plan.state != "review_required":
        return CycleStatus("blocked", "unrecognized_preview_state",
                           requires_review=True)

    try:
        status = publish_disposable_fixture(
            vault=vault, expected_vault=expected_vault,
            prepared=prepared, suffix=suffix,
        )
    except (ValueError, OSError, RuntimeError):
        return CycleStatus("recovery_required", "publication_incomplete",
                           old_commit=plan.old_commit,
                           target_commit=plan.new_commit, requires_review=True)

    if (status.state != "published" or not status.backup_verified
            or status.requires_operator_review):
        return CycleStatus("recovery_required", "postflight_requires_review",
                           old_commit=plan.old_commit,
                           target_commit=plan.new_commit, requires_review=True)

    return CycleStatus("published", "verified_fixture_publication",
                       old_commit=plan.old_commit, target_commit=plan.new_commit)


def run_fixture_cycle(
    *, vault: Path, expected_vault: Path, prepared: PreparedDocs, suffix: str,
    prior: PriorTransaction | None = None,
    history: tuple[PriorTransaction, ...] | None = None,
) -> CycleStatus:
    """Serialize cooperating fixture cycles from inspection through publication.

    An exact exclusive sibling lease is acquired before any prior evidence
    inventory, source preview, or no-change decision. The underlying publisher
    also acquires its own refresh lock. Both locks are preserved after abrupt
    process exit. This is NOT independent-reader write exclusion: Windows ACL,
    parent namespace, open handles and malicious writers remain unresolved.
    """
    _fixture_vault(vault, expected_vault)
    _paths(vault, suffix)
    result: CycleStatus | None = None
    body_exception: str | None = None

    def lease_failure(reason: str) -> CycleStatus:
        # A completed managed publish must never become an unexplained
        # "preflight failure" when cleanup encounters a changed lease.
        return CycleStatus(
            "recovery_required", reason,
            old_commit=result.old_commit if result else None,
            target_commit=result.target_commit if result else None,
            requires_review=True,
            pre_cleanup_outcome=(
                result.outcome if result else
                f"exception:{body_exception}" if body_exception else None
            ),
        )

    try:
        with exclusive_cycle_lease(vault, expected_vault=expected_vault):
            try:
                result = _run_fixture_cycle_in_lease(
                    vault=vault, expected_vault=expected_vault,
                    prepared=prepared, suffix=suffix,
                    prior=prior, history=history,
                )
            except Exception as exc:
                body_exception = type(exc).__name__
                raise
        if result is None:
            raise RuntimeError("cycle_without_result")
        return result
    except CycleLeaseOccupied:
        return lease_failure("cycle_lease_live_or_stale")
    except OSError:
        return lease_failure("cycle_lease_io_failure")
    except RuntimeError as exc:
        if str(exc) == "cycle_lease_changed_preserved":
            return lease_failure("cycle_lease_integrity_failure")
        raise
