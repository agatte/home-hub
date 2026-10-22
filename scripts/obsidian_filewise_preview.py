"""Read-only filewise refresh feasibility preview for HomeHub #399.

A planning experiment, NOT an updater. In particular this module never
changes a Vault, stages files, takes a lock or grants write authorization.
It evaluates whether preserving the existing managed directory can avoid the
two-directory-rename gap. It does NOT claim a multi-file atomic transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from manage_obsidian_vault import MANAGED
from obsidian_github_docs_source import PreparedDocs
from obsidian_refresh_preflight import _verified_manifest
from obsidian_source_verifier import _safe_markdown_path, validate_tree, verify_all
from obsidian_verified_stage import expected_generated_pages


@dataclass(frozen=True)
class FilewisePreview:
    state: str
    old_commit: str
    new_commit: str
    added: tuple[str, ...]
    modified: tuple[str, ...]
    retired: tuple[str, ...]
    unchanged: tuple[str, ...]
    manifest_replacement_last: bool = True
    managed_directory_remains_present: bool = True
    multi_file_atomic: bool = False
    host_refresh_authorized: bool = False


def _allowed_managed_markdown(path: str) -> bool:
    return path in {"00-START-HERE.md", "SNAPSHOT.md"} or _safe_markdown_path(path)


def preview_filewise_refresh(
    *, vault: Path, expected_vault: Path, prepared: PreparedDocs,
) -> FilewisePreview:
    """Compute the exact existing/new file set without writing anything.

    Only verified source evidence and a fully sealed old managed subtree may
    enter. Existing unexpected managed files are a refusal, never silently
    retired. The generated pages are treated like ordinary verified content.
    A manifest-last idea cannot guarantee atomicity across multiple files;
    interrupted publishing would leave a hash-inconsistent old manifest.
    """
    if not isinstance(prepared, PreparedDocs) or prepared.refresh_authorized:
        raise ValueError("untrusted_or_write_authorized_prepared_source")
    if (
        not prepared.source_ref_stable
        or prepared.docs.commit != prepared.intended_commit
        or prepared.ancestry not in ("identical", "forward")
    ):
        raise ValueError("non_forward_or_unstable_source")
    if (prepared.intended_commit == prepared.previously_sealed_commit) != (
        prepared.ancestry == "identical"
    ):
        raise ValueError("source_ancestry_state_mismatch")

    old = _verified_manifest(vault, expected_vault)
    if old["source_commit"] != prepared.previously_sealed_commit:
        raise ValueError("old_managed_commit_changed")
    old_hashes = old["sha256"]
    if not isinstance(old_hashes, dict) or not all(
        _allowed_managed_markdown(name) for name in old_hashes
    ):
        raise ValueError("unexpected_old_managed_content")
    if not {"AGENTS.md", "00-START-HERE.md", "SNAPSHOT.md"}.issubset(old_hashes):
        raise ValueError("missing_old_managed_core")
    checked = validate_tree(
        {"path": b.path, "type": "blob", "mode": b.mode, "sha": b.oid, "size": b.size}
        for b in prepared.docs.files
    )
    if checked != prepared.docs.files:
        raise ValueError("source_membership_or_order_unverified")
    verify_all(checked, prepared.docs.contents)
    generated = expected_generated_pages(prepared.docs)
    if set(generated) & set(prepared.docs.contents):
        raise ValueError("generated_page_source_collision")
    new_contents = {**prepared.docs.contents, **generated}
    new_hashes = {
        name: sha256(content).hexdigest()
        for name, content in new_contents.items()
    }
    if not all(_allowed_managed_markdown(name) for name in new_hashes):
        raise ValueError("unexpected_new_managed_content")

    previous = set(old_hashes)
    current = set(new_hashes)
    old_prefixes = {}
    for name in previous:
        parts = name.split("/")
        for i in range(len(parts)):
            prefix = "/".join(parts[:i + 1])
            old_prefixes[prefix.casefold()] = (
                prefix, "file" if i == len(parts) - 1 else "directory"
            )
    for name in current:
        parts = name.split("/")
        for i in range(len(parts)):
            prefix = "/".join(parts[:i + 1])
            prior = old_prefixes.get(prefix.casefold())
            if prior is not None and prior != (
                prefix, "file" if i == len(parts) - 1 else "directory"
            ):
                raise ValueError("cross_generation_windows_namespace_transition")
    added = tuple(sorted(current - previous))
    retired = tuple(sorted(previous - current))
    modified = tuple(sorted(
        name for name in previous & current
        if old_hashes[name] != new_hashes[name]
    ))
    unchanged = tuple(sorted(
        name for name in previous & current
        if old_hashes[name] == new_hashes[name]
    ))
    if prepared.ancestry == "identical" and (added or retired or modified):
        raise ValueError("same_commit_but_changed_content")
    return FilewisePreview(
        state="no_change" if not (added or retired or modified) else "review_required",
        old_commit=old["source_commit"],
        new_commit=prepared.intended_commit,
        added=added, modified=modified,
        retired=retired, unchanged=unchanged,
    )
