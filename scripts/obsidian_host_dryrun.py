"""Bounded, read-only #399 host-refresh *dry-run* orchestrator.

No scheduler, staging, swapping, lock creation, credential handling, or grants.
Passing this report is NOT permission to refresh a Windows Vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from obsidian_host_identity import IdentityEvidence, inspect_host_identity_readonly
from obsidian_process_probe import ProcessObservation, observe_windows_obsidian
from obsidian_refresh_preflight import inspect_refresh_readonly


@dataclass(frozen=True)
class HostDryRun:
    status: str
    reason: str
    existing_commit: str | None = None
    candidate_commit: str | None = None
    host_automation_authorized: bool = False


def inspect_host_refresh_dryrun(
    *, vault: Path, expected_vault: Path, expected_user_sid: str,
    identity_probe: Callable[[], IdentityEvidence] | None = None,
    process_probe: Callable[[], ProcessObservation] = observe_windows_obsidian,
    source_probe: Callable[[], object] | None = None,
) -> HostDryRun:
    """Fail closed at each read-only gate; produce no write-capability token.

    For live use this requires independently approved host identity and
    exact-Vault inputs. Here it is tested only on disposable fixtures.
    """
    if identity_probe is None:
        identity_probe = lambda: inspect_host_identity_readonly(
            vault=vault, expected_vault=expected_vault, expected_user_sid=expected_user_sid
        )
    try:
        identity = identity_probe()
    except Exception:
        return HostDryRun("unknown", "identity_observation_failed")
    if not isinstance(identity, IdentityEvidence) or identity.state != "matched":
        return HostDryRun("deferred", "identity_or_owner_not_verified")
    if (
        identity.process_sid_matches is not True
        or identity.vault_owner_matches is not True
        or identity.managed_owner_matches is not True
        or identity.process_elevated is not False
    ):
        return HostDryRun("deferred", "identity_details_inconsistent")
    try:
        process = process_probe()
    except Exception:
        return HostDryRun("unknown", "process_observation_failed")
    if not isinstance(process, ProcessObservation) or process.state != "closed":
        return HostDryRun("deferred", "obsidian_not_proven_closed")

    if source_probe is None:
        source_probe = lambda: inspect_refresh_readonly(
            vault=vault, expected_vault=expected_vault,
            app_state_probe=lambda: process.state
        )
    try:
        report, prepared = source_probe()
        if report.refresh_authorized or prepared.refresh_authorized:
            return HostDryRun("unknown", "unexpected_authorization_in_preview")
        current_sha = prepared.previously_sealed_commit
        candidate_sha = prepared.intended_commit
        if report.state == "no_change":
            return HostDryRun("no_change", "managed_source_already_current",
                              current_sha, candidate_sha)
        if report.state == "eligible_for_authorized_host_preflight":
            return HostDryRun("review_required", "acl_and_launch_coordination_unverified",
                              current_sha, candidate_sha)
        return HostDryRun("deferred", "source_policy_not_satisfied", current_sha, candidate_sha)
    except Exception:
        return HostDryRun("unknown", "read_only_source_preflight_failed")
