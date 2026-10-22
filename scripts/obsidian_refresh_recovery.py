"""Read-only interrupted-refresh diagnosis for HomeHub #399.

This module only reads exact named managed/stage/backup/lock targets under an
already approved Vault path. It NEVER repairs, renames, deletes, clears stale
locks, issues a write capability or enumerates personal notes/.obsidian.
An absent/ambiguous target is always a stop-and-review event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from manage_obsidian_vault import MANAGED, reject_link, verify_sealed
from obsidian_refresh_lock import _guard_existing_vault

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class RecoveryObservation:
    state: str
    reason: str
    managed_commit: str | None = None
    stage_commit: str | None = None
    backup_commit: str | None = None
    manual_review_required: bool = True
    authorizes_repair_or_refresh: bool = False


def _sealed_commit_if_present(path: Path) -> str | None:
    # Keep the link check ahead of exists() to catch dangling symlinks.
    reject_link(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise ValueError("expected_sealed_directory")
    return verify_sealed(path)["source_commit"]


def inspect_exact_swap_recovery(
    *,
    vault: Path,
    expected_vault: Path,
    suffix: str,
    previously_sealed_commit: str,
    intended_commit: str,
) -> RecoveryObservation:
    """Diagnose only one exact transaction suffix; never mutate its targets.

    A valid manifest proves *internal hash consistency*, NOT independent
    GitHub provenance or ownership/ACL/launch-safety.
    """
    if (
        not isinstance(suffix, str) or not _HEX32.fullmatch(suffix)
        or not isinstance(previously_sealed_commit, str)
        or not _SHA40.fullmatch(previously_sealed_commit)
        or not isinstance(intended_commit, str)
        or not _SHA40.fullmatch(intended_commit)
        or previously_sealed_commit == intended_commit
    ):
        return RecoveryObservation("unknown", "invalid_exact_transaction_identity")
    try:
        _guard_existing_vault(vault, expected_vault)
        parent = vault.parent
        managed = vault / MANAGED
        staged = parent / f".{vault.name}-homehub-stage-{suffix}"
        backup = parent / f".{vault.name}-homehub-backup-{suffix}"
        lock = parent / f".{vault.name}-homehub-refresh.lock"
        for path in (managed, staged, backup, lock):
            reject_link(path)
        # Do not open or parse an unknown lock. Even after a crash its owner
        # token may be stale; only a separate reviewed operator may release it.
        if lock.exists():
            return RecoveryObservation("manual_review_required", "refresh_lock_present")
        managed_sha = _sealed_commit_if_present(managed)
        stage_sha = _sealed_commit_if_present(staged)
        backup_sha = _sealed_commit_if_present(backup)
    except Exception:
        return RecoveryObservation("unknown", "recovery_target_or_integrity_unverified")

    evidence = dict(
        managed_commit=managed_sha,
        stage_commit=stage_sha,
        backup_commit=backup_sha,
    )
    if managed_sha not in (None, previously_sealed_commit, intended_commit):
        return RecoveryObservation("manual_review_required", "unexpected_managed_commit", **evidence)
    if stage_sha not in (None, intended_commit):
        return RecoveryObservation("manual_review_required", "unexpected_stage_commit", **evidence)
    if backup_sha not in (None, previously_sealed_commit):
        return RecoveryObservation("manual_review_required", "unexpected_backup_commit", **evidence)

    if (managed_sha, stage_sha, backup_sha) == (previously_sealed_commit, intended_commit, None):
        return RecoveryObservation("prepared_only", "staged_and_old_untouched", **evidence)
    if (managed_sha, stage_sha, backup_sha) == (None, intended_commit, previously_sealed_commit):
        return RecoveryObservation("manual_review_required", "interrupted_after_first_rename", **evidence)
    if (managed_sha, stage_sha, backup_sha) == (intended_commit, None, previously_sealed_commit):
        return RecoveryObservation(
            "completed_backup_preserved", "managed_new_and_old_backup_intact",
            manual_review_required=False, **evidence
        )
    if (managed_sha, stage_sha, backup_sha) == (previously_sealed_commit, None, None):
        return RecoveryObservation(
            "old_snapshot_intact", "no_known_transaction_artifacts",
            manual_review_required=False, **evidence
        )
    # Other states include a missing managed folder, failed rollback with
    # spare stage/backup, or a leftover stage from a previous attempt.
    return RecoveryObservation("manual_review_required", "ambiguous_transaction_state", **evidence)
