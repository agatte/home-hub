"""Transactional #399 candidate swap for disposable fixtures only.

No real-host ACL/reparse/identity/process-lifecycle acceptance. No unattended
task or production Vault usage until separately reviewed and authorized.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
from typing import Callable

from manage_obsidian_vault import MANAGED, reject_link, verify_sealed
from obsidian_github_docs_source import PreparedDocs
from obsidian_refresh_lock import exclusive_refresh_lock
from obsidian_source_verifier import verify_all
from obsidian_verified_stage import expected_generated_pages

SUFFIX = re.compile(r"[0-9a-f]{32}\Z")


def _verify_exact_stage(staged: Path, prepared: PreparedDocs) -> None:
    """Recheck both signed-content membership and deterministic page bytes.

    Repeated checks can catch callback-time changes but do NOT exclude a
    concurrent writer after this check; real-host activation remains blocked.
    """
    reject_link(staged)
    new = verify_sealed(staged)
    if new["source_commit"] != prepared.intended_commit:
        raise ValueError("staged_source_mismatch")
    generated = expected_generated_pages(prepared.docs)
    expected_paths = set(prepared.docs.contents) | set(generated)
    # Re-sealing arbitrary Markdown is not GitHub provenance: reject any
    # unexpected/missing entry and altered generated landing/provenance.
    if set(new["sha256"]) != expected_paths:
        raise ValueError("staged_unexpected_or_missing_paths")
    for page, expected in generated.items():
        target = staged / page
        if not target.is_file() or target.is_symlink() or target.read_bytes() != expected:
            raise ValueError("staged_generated_page_changed")
    for doc in prepared.docs.files:
        p = staged.joinpath(*doc.path.split("/"))
        if not p.is_file() or p.is_symlink():
            raise ValueError("staged_document_missing_or_linked")
        if sha256(p.read_bytes()).digest() != sha256(prepared.docs.contents[doc.path]).digest():
            raise ValueError("staged_blob_content_mismatch")


@dataclass(frozen=True)
class SwapResult:
    commit: str
    backup: Path
    managed: Path
    authorized_host_automation: bool = False


def swap_only_after_rechecks(
    *, vault: Path, expected_vault: Path, staged: Path, prepared: PreparedDocs,
    suffix: str, app_probe: Callable[[], str], head_probe: Callable[[], str],
) -> SwapResult:
    """Fixture-only exact managed-subtree rename with rollback and no cleanup."""
    if not isinstance(suffix, str) or not SUFFIX.fullmatch(suffix):
        raise ValueError("invalid_exact_swap_suffix")
    if vault != expected_vault or not vault.is_absolute() or vault == vault.parent:
        raise ValueError("mismatched_exact_vault")
    parent = vault.parent
    if staged != parent / f".{vault.name}-homehub-stage-{suffix}":
        raise ValueError("unexpected_stage_target")
    backup = parent / f".{vault.name}-homehub-backup-{suffix}"
    if backup.exists() or backup.is_symlink():
        raise FileExistsError("backup_target_occupied")
    if not prepared.source_ref_stable or prepared.ancestry != "forward":
        raise ValueError("unverified_forward_source")
    if prepared.docs.commit != prepared.intended_commit:
        raise ValueError("source_commit_mismatch")
    verify_all(prepared.docs.files, prepared.docs.contents)

    with exclusive_refresh_lock(vault, expected_vault=expected_vault):
        for part in (staged, backup, vault / MANAGED):
            reject_link(part)
        if not staged.is_dir() or not (vault / MANAGED).is_dir():
            raise ValueError("missing_managed_or_staged_dir")
        if staged.stat().st_dev != (vault / MANAGED).stat().st_dev:
            raise ValueError("stage_not_on_same_filesystem")
        old = verify_sealed(vault / MANAGED)
        if old["source_commit"] != prepared.previously_sealed_commit:
            raise ValueError("old_source_moved_since_fetch")
        _verify_exact_stage(staged, prepared)
        if app_probe() != "closed":
            raise ValueError("obsidian_not_proven_closed_at_swap")
        if head_probe() != prepared.intended_commit:
            raise ValueError("github_master_changed_before_swap")
        verify_sealed(vault / MANAGED)
        # Callbacks and other processes may change a valid stage after the
        # initial check. Revalidate exact GitHub membership and generated pages
        # just before rename. This remains a best-effort, not a host lock.
        _verify_exact_stage(staged, prepared)
        if backup.exists() or backup.is_symlink():
            raise FileExistsError("backup_target_occupied_at_swap")
        os.rename(vault / MANAGED, backup)
        try:
            os.rename(staged, vault / MANAGED)
        except OSError as error:
            if not (vault / MANAGED).exists():
                try:
                    os.rename(backup, vault / MANAGED)
                except OSError as rollback_error:
                    raise RuntimeError(f"rollback_failed_previous_snapshot_preserved:{backup}") from rollback_error
            raise error
        return SwapResult(prepared.intended_commit, backup, vault / MANAGED)
