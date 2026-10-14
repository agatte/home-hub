"""Read-only GitHub documentation discovery, independent of Obsidian state.

This HomeHub #399 candidate deliberately does not inspect Obsidian's process
table: a running application can coexist with source verification. It does
not stage, rename, schedule, mutate a Vault, or authorize host writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from obsidian_github_docs_source import github_json, prepare_current_docs
from obsidian_refresh_policy import assess_refresh
from obsidian_refresh_preflight import _verified_manifest
from obsidian_raw_blob_transport import github_raw_blob


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    reason: str
    existing_commit: str | None = None
    candidate_commit: str | None = None
    changes: dict[str, tuple[str, ...]] | None = None
    documents_verified: bool = False
    host_automation_authorized: bool = False
    stage_authorized: bool = False


def inspect_docs_discovery_readonly(
    *, vault: Path, expected_vault: Path,
    fetch: Callable[[str], dict] = github_json,
) -> DiscoveryResult:
    """Find safe *documentation provenance* only, never permission to swap.

    Existing sealed manifest is checked before network I/O. Current GitHub
    commit, allowlisted blobs, file hashes, ancestry and ref stability are
    verified by the same source and policy components used by preflight.
    On ambiguous input or network errors return unknown without side effects.
    Caller still must verify exact host user/ACL before host use.
    """
    try:
        manifest = _verified_manifest(vault, expected_vault)
    except Exception:
        return DiscoveryResult("unknown", "existing_managed_source_unverified")
    old = manifest["source_commit"]
    try:
        # Real transport: 6 bounded REST metadata calls + SHA-pinned raw files,
        # not one quota-limited REST API call per Markdown blob.
        # Injected fixture fetchers continue to use REST-shaped fake blobs.
        blob_source = github_raw_blob if fetch is github_json else None
        prepared = prepare_current_docs(old, fetch, blob_source=blob_source)
        assessment = assess_refresh(
            current_manifest=manifest,
            sealed_old_source_verified=True,
            docs=prepared.docs,
            history=prepared.ancestry,
            app_state="unknown",  # Never a claim about actual app closure.
            source_identity_verified=prepared.source_ref_stable,
        )
        if prepared.refresh_authorized or assessment.refresh_authorized:
            return DiscoveryResult("unknown", "unexpected_source_authorization")
        if assessment.state == "no_change":
            return DiscoveryResult(
                "no_change", "verified_documentation_already_current",
                old, prepared.intended_commit, assessment.paths, True,
            )
        if (assessment.state == "deferred" and
                assessment.reason == "obsidian_not_proven_closed" and
                prepared.ancestry == "forward" and prepared.source_ref_stable):
            return DiscoveryResult(
                "update_discovered", "verified_forward_update_not_authorized",
                old, prepared.intended_commit, assessment.paths, True,
            )
        return DiscoveryResult("blocked", "source_policy_refused")
    except Exception:
        return DiscoveryResult("unknown", "github_provenance_or_network_unverified")
