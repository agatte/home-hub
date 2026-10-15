"""Constrained *stage-only* adapter for a future HomeHub #399 executor.

This is NOT a scheduler, updater, or permission to touch the real Windows Vault.
Callers must already possess separately trusted exact-GitHub evidence and may
use this only against a specifically approved disposable/host staging target.
The function never swaps the existing managed source or deletes any path.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat

from obsidian_github_docs_source import VerifiedDocs
from obsidian_source_verifier import OID, validate_tree, verify_all

STAGE_SUFFIX = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True)
class StagedDocs:
    commit: str
    location: Path
    document_count: int
    refresh_authorized: bool = False


def expected_generated_pages(docs: VerifiedDocs) -> dict[str, bytes]:
    """Pure deterministic generated pages shared by stage creation and swap."""
    from create_obsidian_pilot import LANDING

    return {
        "00-START-HERE.md": LANDING.encode("utf-8"),
        "SNAPSHOT.md": (
            f"# Preview provenance\n\nSource Git commit: {chr(96)}{docs.commit}{chr(96)}.\n\n"
            f"Exported Git-tracked Markdown files: **{len(docs.files)}**.\n\n"
            "This is an isolated copy, not a live-status verification.\n"
        ).encode("utf-8"),
    }


def stage_only_verified_docs(
    *, vault: Path, docs: VerifiedDocs, stage_suffix: str,
    source_identity_verified: bool,
) -> StagedDocs:
    """Write only a *new sibling stage*, compatible with the existing seal.

    No existing vault subtree is opened, renamed, removed or overwritten. This
    adapter does not authorize a later swap and does not inspect personal notes.
    Its exact Windows host identity/ACL/concurrency/app-closure preflights are
    expressly NOT implemented and must not be inferred from a successful stage.
    """
    if not source_identity_verified:
        raise ValueError("source_identity_unverified")
    if not isinstance(docs.commit, str) or not OID.fullmatch(docs.commit):
        raise ValueError("invalid_exact_source_sha")
    if not isinstance(stage_suffix, str) or not STAGE_SUFFIX.fullmatch(stage_suffix):
        raise ValueError("invalid_stage_suffix")
    if not vault.is_absolute() or not vault.is_dir() or vault == vault.parent:
        raise ValueError("invalid_existing_vault_path")
    # Do not resolve a redirected Vault or Documents parent into another target.
    from manage_obsidian_vault import reject_link, seal, verify_sealed
    for part in (vault, *vault.parents):
        reject_link(part)
    parent = vault.parent
    if not parent.is_dir():
        raise ValueError("vault_parent_missing")
    checked = validate_tree(
        {"path": b.path, "type": "blob", "mode": b.mode, "sha": b.oid, "size": b.size}
        for b in docs.files
    )
    if checked != docs.files:
        raise ValueError("unverified_bundle_membership")
    verify_all(checked, docs.contents)

    generated = expected_generated_pages(docs)

    stage = parent / f".{vault.name}-homehub-stage-{stage_suffix}"
    if stage.exists() or stage.is_symlink():
        raise FileExistsError("stage_target_already_exists")
    stage.mkdir(mode=0o777 if os.name == "nt" else 0o700)
    # A failed partial stage is intentionally left for a separately authorized,
    # *exact-target* investigation. Never clean it with recursive deletion.
    for blob in checked:
        dest = stage.joinpath(*blob.path.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(docs.contents[blob.path])
        dest.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    for page, data in generated.items():
        (stage / page).write_bytes(data)
    seal(stage, docs.commit)
    verified = verify_sealed(stage)
    if verified["source_commit"] != docs.commit:
        raise ValueError("staged_manifest_source_mismatch")
    return StagedDocs(docs.commit, stage, len(checked))
