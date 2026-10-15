"""Read-only fail-closed HomeHub #399 unattended-refresh *preflight*.

This module NEVER stages, swaps, schedules, locks, or changes a real Vault.
An approved host worker must separately verify run-as identity, path ACLs,
Obsidian closure immediately before swap, ownership, and rollback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from manage_obsidian_vault import MANAGED, reject_link, verify_sealed
from obsidian_github_docs_source import PreparedDocs, prepare_current_docs, github_json
from obsidian_refresh_policy import RefreshAssessment, assess_refresh
from obsidian_raw_blob_transport import github_raw_blob


class PreflightRefused(ValueError):
    """A required host observation or exact target failed validation."""


def _verified_manifest(vault: Path, expected_vault: Path) -> Mapping[str, object]:
    """Read only the sealed, managed subtree; never walk personal notes."""
    if (
        not isinstance(vault, Path)
        or not isinstance(expected_vault, Path)
        or not vault.is_absolute()
        or not expected_vault.is_absolute()
        or vault != expected_vault
        or vault == vault.parent
    ):
        raise PreflightRefused("exact_vault_identity_missing_or_mismatched")
    for part in (vault, *vault.parents):
        reject_link(part)
    if not vault.is_dir() or not vault.parent.is_dir():
        raise PreflightRefused("vault_missing_or_parent_invalid")
    managed = vault / MANAGED
    reject_link(managed)
    return verify_sealed(managed)


def inspect_refresh_readonly(
    *,
    vault: Path,
    expected_vault: Path,
    app_state_probe: Callable[[], str],
    fetch: Callable[[str], dict] = github_json,
) -> tuple[RefreshAssessment, PreparedDocs]:
    """Return source-backed eligibility evidence; **never** authorize writes.

    ``app_state_probe`` must be an independently reviewed exact-host observation;
    ``closed`` is advisory requiring a fresh second probe at swap.
    The result is NOT a capability/token to run the host updater.
    All source paths must originate from the locked-down GitHub transport.
    """
    manifest = _verified_manifest(vault, expected_vault)
    previous = manifest["source_commit"]
    try:
        state = app_state_probe()
    except Exception:
        state = "unknown"
    if state not in ("open", "closed", "unknown"):
        state = "unknown"
    prepared = prepare_current_docs(previous, fetch, blob_source=(github_raw_blob if fetch is github_json else None))
    assessment = assess_refresh(
        current_manifest=manifest,
        sealed_old_source_verified=True,
        docs=prepared.docs,
        history=prepared.ancestry,
        app_state=state,
        source_identity_verified=prepared.source_ref_stable,
    )
    if assessment.refresh_authorized or prepared.refresh_authorized:
        raise PreflightRefused("unacceptable_host_write_authority_in_preview")
    return assessment, prepared
