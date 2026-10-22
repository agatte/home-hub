"""Pure non-actuating refresh eligibility assessment for HomeHub #399.

This module does not access the host, Vault, GitHub or credentials. In particular
``eligible_for_authorized_host_preflight`` is NOT permission to perform a swap.
The real-host executor must independently prove app closure, lock, ACL, identity,
old sealed integrity and rollback before a separately approved write.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from obsidian_github_docs_source import VerifiedDocs
from obsidian_source_verifier import OID, validate_tree, verify_all


@dataclass(frozen=True)
class RefreshAssessment:
    state: str
    reason: str
    old_commit: str
    new_commit: str
    paths: dict[str, tuple[str, ...]] | None
    # Always false: policy/preview cannot authorize real-host filesystem writes.
    refresh_authorized: bool = False


def assess_refresh(
    *,
    current_manifest: Mapping[str, object],
    sealed_old_source_verified: bool,
    docs: VerifiedDocs,
    history: str,
    app_state: str,
    source_identity_verified: bool,
) -> RefreshAssessment:
    """Fail-closed plan using independently established evidence, without I/O.

    ``sealed_old_source_verified`` must be determined by existing verify_sealed,
    not inferred from manifest presence. ``app_state`` must come from a trusted
    exact-host process inspection; missing/unknown means defer. ``history`` must
    be from verify_snapshot_ancestry against exact trusted commit SHAs.
    """
    old = current_manifest.get("source_commit")
    new = docs.commit
    if not isinstance(old, str) or not OID.fullmatch(old):
        return RefreshAssessment("refused", "invalid_existing_source_sha", "", new, None)
    if not isinstance(new, str) or not OID.fullmatch(new):
        return RefreshAssessment("refused", "invalid_target_source_sha", old, "", None)
    if not sealed_old_source_verified:
        return RefreshAssessment("refused", "managed_source_integrity_unverified", old, new, None)
    if not source_identity_verified:
        return RefreshAssessment("refused", "github_source_identity_unverified", old, new, None)
    # Recheck path/mode/mandatory-doc rules; never trust a forged dataclass from a
    # future transport or an untrusted local caller just because blobs hash.
    checked = validate_tree(
        ({"path": b.path, "mode": b.mode, "type": "blob", "sha": b.oid, "size": b.size}
         for b in docs.files)
    )
    if checked != docs.files:
        return RefreshAssessment("refused", "unverified_document_order_or_membership", old, new, None)
    verify_all(docs.files, docs.contents)
    stored = current_manifest.get("sha256")
    if not isinstance(stored, dict):
        return RefreshAssessment("refused", "invalid_existing_manifest", old, new, None)
    old_docs = {
        p: digest for p, digest in stored.items()
        if isinstance(p, str) and (p == "AGENTS.md" or p.startswith("docs/"))
    }
    new_docs = {p: sha256(data).hexdigest() for p, data in docs.contents.items()}
    if old == new:
        if history != "identical":
            return RefreshAssessment("refused", "inconsistent_noop_ancestry", old, new, None)
        # A self-consistent sealed manifest is not authenticated source truth.
        # Never hide incompatible content behind a matching commit label.
        if old_docs != new_docs:
            return RefreshAssessment("refused", "same_sha_document_content_mismatch", old, new, None)
        return RefreshAssessment("no_change", "already_current", old, new,
                                 {"added": (), "modified": (), "removed": ()})
    if history != "forward":
        return RefreshAssessment("refused", "no_verified_forward_ancestry", old, new, None)
    added = tuple(sorted(set(new_docs) - set(old_docs)))
    removed = tuple(sorted(set(old_docs) - set(new_docs)))
    modified = tuple(sorted(p for p in set(old_docs) & set(new_docs) if old_docs[p] != new_docs[p]))
    paths = {"added": added, "modified": modified, "removed": removed}
    if app_state != "closed":
        return RefreshAssessment("deferred", "obsidian_not_proven_closed", old, new, paths)
    return RefreshAssessment("eligible_for_authorized_host_preflight", "no_write_permission_granted", old, new, paths)
