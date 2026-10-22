"""#399 filewise transaction experiment confined to disposable temp fixtures.

THIS IS NOT A PRODUCTION UPDATER. It refuses every target except a specifically
named Synthetic Vault immediately beneath a Python-system TEMP directory
prefixed hh399-filewise-txn-. It cannot operate on HomeHub Knowledge Vault.
The fixture protocol is non-atomic across files and intentionally leaves all
backups/journals/stages intact. No host-write authorization is ever produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from manage_obsidian_vault import MANAGED, MANIFEST, reject_link, verify_sealed
from obsidian_filewise_preview import preview_filewise_refresh, _allowed_managed_markdown
from obsidian_github_docs_source import PreparedDocs
from obsidian_refresh_lock import exclusive_refresh_lock
from obsidian_verified_stage import stage_only_verified_docs

SUFFIX = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class FixtureInterrupted(RuntimeError):
    """Injected failure, not a safe automated recovery decision."""


@dataclass(frozen=True)
class FixtureRecoveryReport:
    state: str
    reason: str
    backup_verified: bool = False
    requires_operator_review: bool = True
    authorizes_host_refresh: bool = False


def _fixture_vault(vault: Path, expected_vault: Path) -> Path:
    if (not isinstance(vault, Path) or not isinstance(expected_vault, Path)
        or vault != expected_vault or not vault.is_absolute()
        or vault.name != "Synthetic Vault"
        or not vault.parent.name.startswith("hh399-filewise-txn-")):
        raise ValueError("fixture_only_exact_target")
    # Do not allow an arbitrary directory tree which happens to use the name.
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if vault.parent.parent.resolve(strict=True) != temp:
        raise ValueError("fixture_outside_system_temp")
    for p in (vault, *vault.parents):
        reject_link(p)
    if not vault.is_dir() or not (vault / MANAGED).is_dir():
        raise ValueError("fixture_managed_missing")
    return vault.parent


def _paths(vault: Path, suffix: str) -> tuple[Path, Path, Path, Path]:
    if not isinstance(suffix, str) or not SUFFIX.fullmatch(suffix):
        raise ValueError("invalid_exact_suffix")
    parent = vault.parent
    stem = f".{vault.name}-homehub"
    return (
        parent / f"{stem}-old-{suffix}",
        parent / f"{stem}-stage-{suffix}",
        parent / f"{stem}-filewise-{suffix}.json",
        parent / f"{stem}-filewise-{suffix}.json.tmp",
    )


def _check_named_paths(*paths: Path) -> None:
    for path in paths:
        reject_link(path)


def _journal_write(journal: Path, pending: Path, record: dict, *, create: bool) -> None:
    """Persist a complete journal record; a leftover .tmp forces abstention."""
    _check_named_paths(journal, pending)
    if pending.exists():
        raise ValueError("pending_journal_temp_present")
    if create and journal.exists():
        raise ValueError("existing_journal_target")
    if not create and not journal.is_file():
        raise ValueError("journal_missing_during_update")
    data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > 64 * 1024:
        raise ValueError("journal_oversized")
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    finally:
        pass
    # File-level atomic replacement is NOT a guarantee of power-loss
    # durability on all Windows/filesystem/storage configurations.
    os.replace(pending, journal)


def _read_journal(journal: Path, old: str, new: str, suffix: str) -> dict:
    reject_link(journal)
    if not journal.is_file() or journal.stat().st_size > 64 * 1024:
        raise ValueError("journal_missing_or_oversized")
    record = json.loads(journal.read_bytes())
    if not isinstance(record, dict) or set(record) != {
        "schema", "old", "new", "suffix", "phase", "old_paths", "new_paths", "restore_attempts",
        "old_manifest_sha256", "new_manifest_sha256"
    }:
        raise ValueError("unknown_journal_schema")
    if (type(record["schema"]) is not int or record["schema"] != 2
        or record["old"] != old or record["new"] != new
        or record["suffix"] != suffix or old == new):
        raise ValueError("journal_identity_mismatch")
    if (type(record["restore_attempts"]) is not int
            or not 0 <= record["restore_attempts"] <= 10):
        raise ValueError("invalid_restore_attempt_count")
    if any(
        not isinstance(record[key], str) or not SHA256.fullmatch(record[key])
        for key in ("old_manifest_sha256", "new_manifest_sha256")
    ):
        raise ValueError("invalid_transaction_manifest_digest")
    for key in ("old_paths", "new_paths"):
        seq = record[key]
        if not isinstance(seq, list) or not all(isinstance(v, str) for v in seq):
            raise ValueError("invalid_journal_membership")
        if (seq != sorted(set(seq)) or len(seq) > 500
            or not all(_allowed_managed_markdown(path) for path in seq)):
            raise ValueError("invalid_journal_membership")
    if record["phase"] not in ("prepared", "applying", "published", "restoring", "restored"):
        raise ValueError("unknown_transaction_phase")
    return record


def _target_file(root: Path, rel: str) -> Path:
    # Paths come only from an exact sealed manifest or a validated Git tree.
    if not _allowed_managed_markdown(rel) or rel == MANIFEST:
        raise ValueError("unsafe_filewise_entry")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("unsafe_filewise_entry")
    target = root.joinpath(*parts)
    if not target.is_relative_to(root):
        raise ValueError("filewise_path_outside_root")
    for ancestor in (root, *target.parents):
        if ancestor == root.parent:
            break
        reject_link(ancestor)
    reject_link(target)
    return target


def _put_exact_file(src: Path, root: Path, rel: str, suffix: str) -> None:
    dest = _target_file(root, rel)
    reject_link(src)
    if not src.is_file():
        raise ValueError("verified_source_file_missing")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _target_file(root, rel)  # Recheck newly created ancestor.
    temporary = dest.parent / f".{dest.name}.filewise-{suffix}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("filewise_temp_occupied")
    # Copy, not move: a complete stage/backup always remains for review.
    with src.open("rb") as input, temporary.open("xb") as output:
        shutil.copyfileobj(input, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, dest)


def _read_fully_sealed_commit(path: Path) -> tuple[str, set[str]]:
    meta = verify_sealed(path)
    return meta["source_commit"], set(meta["sha256"])


def _fixture_report(vault: Path, expected_vault: Path, suffix: str, old: str, new: str) -> tuple[FixtureRecoveryReport, dict | None]:
    try:
        _fixture_vault(vault, expected_vault)
        if (not isinstance(old, str) or not SHA.fullmatch(old)
            or not isinstance(new, str) or not SHA.fullmatch(new) or old == new):
            raise ValueError("invalid_transaction_shas")
        backup, stage, journal, pending = _paths(vault, suffix)
        _check_named_paths(backup, stage, journal, pending)
        if pending.exists():
            return FixtureRecoveryReport("unknown", "unfinished_journal_write"), None
        record = _read_journal(journal, old, new, suffix)
        backup_commit, paths = _read_fully_sealed_commit(backup)
        if backup_commit != old or paths != set(record["old_paths"]):
            raise ValueError("backup_identity_or_membership_mismatch")
        if sha256((backup / MANIFEST).read_bytes()).hexdigest() != record["old_manifest_sha256"]:
            raise ValueError("backup_original_manifest_digest_mismatch")
        new_commit, new_paths = _read_fully_sealed_commit(stage)
        if new_commit != new or new_paths != set(record["new_paths"]):
            raise ValueError("new_stage_identity_or_membership_mismatch")
        if sha256((stage / MANIFEST).read_bytes()).hexdigest() != record["new_manifest_sha256"]:
            raise ValueError("stage_original_manifest_digest_mismatch")
        managed = vault / MANAGED
        evidence = vault.parent / f".{vault.name}-homehub-filewise-artifacts-{suffix}"
        lock = vault.parent / f".{vault.name}-homehub-refresh.lock"
        reject_link(lock)
        _validate_evidence_directory(evidence, _all_journal_bound_artifacts(record))
        outstanding = (
            lock.exists() or evidence.exists()
            or record["phase"] not in ("published", "restored")
        )
        try:
            managed_commit, names = _read_fully_sealed_commit(managed)
        except Exception:
            return FixtureRecoveryReport("interrupted_mixed", "managed_seal_invalid", True), record
        if managed_commit == new and names == set(record["new_paths"]):
            if sha256((managed / MANIFEST).read_bytes()).hexdigest() != record["new_manifest_sha256"]:
                return FixtureRecoveryReport(
                    "unknown", "managed_new_manifest_digest_mismatch", True
                ), record
            return FixtureRecoveryReport(
                "published", "new_seal_verified", True,
                requires_operator_review=outstanding or record["phase"] != "published",
            ), record
        if managed_commit == old and names == paths:
            if sha256((managed / MANIFEST).read_bytes()).hexdigest() != record["old_manifest_sha256"]:
                return FixtureRecoveryReport(
                    "unknown", "managed_old_manifest_digest_mismatch", True
                ), record
            return FixtureRecoveryReport(
                "old_intact", "old_seal_verified", True,
                requires_operator_review=outstanding or record["phase"] != "restored",
            ), record
        return FixtureRecoveryReport("unknown", "unexpected_managed_version", True), record
    except Exception:
        return FixtureRecoveryReport("unknown", "transaction_or_backup_unverified"), None


def inspect_fixture_recovery(
    *, vault: Path, expected_vault: Path, suffix: str, old_commit: str, new_commit: str,
) -> FixtureRecoveryReport:
    """Read-only, no repair or lock-breaking even after a crash."""
    report, _ = _fixture_report(vault, expected_vault, suffix, old_commit, new_commit)
    return report


def publish_disposable_fixture(
    *, vault: Path, expected_vault: Path, prepared: PreparedDocs, suffix: str,
    interrupt_after: int | None = None,
    after_write=None,
) -> FixtureRecoveryReport:
    """Unsafe for real hosts; experimental filewise transaction on *temp fixture*.

    The old backup, staged source, and journal survive ALL outcomes.
    Does not catch abrupt process death. A later read-only inspector must
    report ambiguity; recovery is separately operator-confirmed.
    """
    _fixture_vault(vault, expected_vault)
    if prepared.ancestry != "forward" or prepared.previously_sealed_commit == prepared.intended_commit:
        raise ValueError("fixture_requires_forward_change")
    plan = preview_filewise_refresh(vault=vault, expected_vault=expected_vault, prepared=prepared)
    if plan.state != "review_required":
        raise ValueError("fixture_requires_changed_document_content")
    backup, stage, journal, pending = _paths(vault, suffix)
    _check_named_paths(backup, stage, journal, pending)
    if any(p.exists() for p in (backup, stage, journal, pending)):
        raise FileExistsError("fixture_transaction_already_exists")
    with exclusive_refresh_lock(vault, expected_vault=expected_vault):
        old = vault / MANAGED
        verify_sealed(old)
        shutil.copytree(old, backup, symlinks=False)
        original = verify_sealed(backup)
        if original["source_commit"] != plan.old_commit:
            raise ValueError("old_backup_commit_mismatch")
        if original["sha256"] != verify_sealed(old)["sha256"]:
            raise ValueError("old_backup_files_changed")
        stage.mkdir()
        from obsidian_verified_stage import expected_generated_pages
        contents = {**prepared.docs.contents, **expected_generated_pages(prepared.docs)}
        for rel, data in contents.items():
            p = _target_file(stage, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        from manage_obsidian_vault import seal
        seal(stage, plan.new_commit)
        new_meta = verify_sealed(stage)
        if set(new_meta["sha256"]) != set(contents):
            raise ValueError("stage_membership_mismatch")
        record = {
            "schema": 2, "old": plan.old_commit, "new": plan.new_commit,
            "suffix": suffix, "phase": "prepared",
            "old_paths": sorted(original["sha256"]),
            "new_paths": sorted(new_meta["sha256"]),
            "restore_attempts": 0,
            "old_manifest_sha256": sha256((backup / MANIFEST).read_bytes()).hexdigest(),
            "new_manifest_sha256": sha256((stage / MANIFEST).read_bytes()).hexdigest(),
        }
        _journal_write(journal, pending, record, create=True)
        record["phase"] = "applying"
        _journal_write(journal, pending, record, create=False)
        changed = sorted((*plan.added, *plan.modified))
        actions = [("put", rel) for rel in changed] + [("retire", rel) for rel in plan.retired]
        for index, (action, rel) in enumerate(actions, start=1):
            if action == "put":
                _put_exact_file(_target_file(stage, rel), old, rel, suffix)
            else:
                candidate = _target_file(old, rel)
                if not candidate.is_file():
                    raise ValueError("retired_file_not_present")
                candidate.unlink()  # Exact known managed .md file only.
            if after_write is not None:
                after_write(index, rel)
            if interrupt_after == index:
                raise FixtureInterrupted("simulated_fixture_process_interruption")
        # Manifest is deliberately published LAST, after all source files.
        manifest_temp = old / f".{MANIFEST}.filewise-{suffix}.tmp"
        if manifest_temp.exists():
            raise ValueError("manifest_temp_occupied")
        with (stage / MANIFEST).open("rb") as src, manifest_temp.open("xb") as target:
            shutil.copyfileobj(src, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(manifest_temp, old / MANIFEST)
        final = verify_sealed(old)
        if final["source_commit"] != plan.new_commit or final["sha256"] != new_meta["sha256"]:
            raise ValueError("new_managed_seal_mismatch")
        record["phase"] = "published"
        _journal_write(journal, pending, record, create=False)
    return inspect_fixture_recovery(
        vault=vault, expected_vault=expected_vault, suffix=suffix,
        old_commit=plan.old_commit, new_commit=plan.new_commit
    )


def _exact_transaction_temporaries(managed: Path, record: dict, suffix: str) -> dict[Path, str]:
    """Recognize only own exact temporary-file paths; no filesystem scan/writes."""
    paths = set(record["old_paths"]) | set(record["new_paths"])
    attempt = record["restore_attempts"]
    indexed = {}
    for rel in sorted(paths):
        original = _target_file(managed, rel)
        temporary = original.parent / f".{original.name}.filewise-{suffix}.tmp"
        indexed[temporary] = sha256(rel.encode("utf-8")).hexdigest() + f"-attempt-{attempt}.preserved"
    manifest_temp = managed / f".{MANIFEST}.filewise-{suffix}.tmp"
    indexed[manifest_temp] = sha256(MANIFEST.encode("utf-8")).hexdigest() + f"-attempt-{attempt}.preserved"
    return indexed


def _all_journal_bound_artifacts(record: dict) -> set[str]:
    names = set(record["old_paths"]) | set(record["new_paths"]) | {MANIFEST}
    return {
        sha256(rel.encode("utf-8")).hexdigest() + f"-attempt-{i}.preserved"
        for rel in names for i in range(1, record["restore_attempts"] + 1)
    }


def _verify_known_managed_contents(
    *, managed: Path, backup: Path, stage: Path, record: dict,
) -> None:
    """Never overwrite or retire a known path if its actual bytes are unknown."""
    old_names = set(record["old_paths"])
    new_names = set(record["new_paths"])
    for rel in sorted(old_names | new_names):
        path = _target_file(managed, rel)
        exists = path.exists()
        if rel in old_names and rel in new_names and not exists:
            raise ValueError("known_managed_file_unexpectedly_missing")
        if not exists:
            continue
        if not path.is_file():
            raise ValueError("known_managed_path_not_regular")
        current_hash = sha256(path.read_bytes()).hexdigest()
        accepted = set()
        if rel in old_names:
            accepted.add(sha256(_target_file(backup, rel).read_bytes()).hexdigest())
        if rel in new_names:
            accepted.add(sha256(_target_file(stage, rel).read_bytes()).hexdigest())
        if current_hash not in accepted:
            raise ValueError("unexpected_known_managed_file_bytes")
    manifest = managed / MANIFEST
    reject_link(manifest)
    if not manifest.is_file() or manifest.read_bytes() not in (
        (backup / MANIFEST).read_bytes(), (stage / MANIFEST).read_bytes()
    ):
        raise ValueError("unexpected_managed_manifest_bytes")


def _validate_evidence_directory(evidence: Path, names: set[str]) -> None:
    reject_link(evidence)
    if not evidence.exists():
        return
    if not evidence.is_dir():
        raise ValueError("artifact_evidence_not_directory")
    for p in evidence.iterdir():
        reject_link(p)
        if not p.is_file() or p.name not in names:
            raise ValueError("unexpected_artifact_evidence_preserved")


def _preserve_exact_temporaries(
    *, managed: Path, vault: Path, suffix: str, record: dict,
) -> None:
    """Preserve only explicitly named transaction temp files outside Vault.

    This is a fixture-only action requiring the caller's explicit recovery
    approval, live lock, and previously verified journal, stage and backup.
    Retain evidence; do not delete or overwrite unknown material.
    """
    temporary_names = _exact_transaction_temporaries(managed, record, suffix)
    evidence = vault.parent / f".{vault.name}-homehub-filewise-artifacts-{suffix}"
    known_names = _all_journal_bound_artifacts(record)
    _validate_evidence_directory(evidence, known_names)
    present = []
    for source, archive_name in temporary_names.items():
        reject_link(source)
        if source.exists():
            if not source.is_file():
                raise ValueError("transaction_temp_not_regular_file")
            dest = evidence / archive_name
            reject_link(dest)
            if dest.exists():
                raise ValueError("transaction_artifact_conflict")
            present.append((source, dest))
    if not present:
        return
    if not evidence.exists():
        evidence.mkdir(exist_ok=False)
    for source, dest in present:
        reject_link(source)
        reject_link(dest)
        if not source.is_file() or dest.exists():
            raise ValueError("transaction_artifact_changed")
        os.rename(source, dest)


def restore_disposable_fixture_backup(
    *, vault: Path, expected_vault: Path, suffix: str,
    old_commit: str, new_commit: str, operator_confirmed: bool = False,
) -> FixtureRecoveryReport:
    """Explicit, non-atomic restore only after separate fixture confirmation.

    Refuse if stale lock present. Callers must separately establish dead owner;
    this module cannot authorize lock removal or real-host recovery.
    """
    _fixture_vault(vault, expected_vault)
    if operator_confirmed is not True:
        raise ValueError("operator_fixture_confirmation_required")
    backup, stage, journal, pending = _paths(vault, suffix)
    lock = vault.parent / f".{vault.name}-homehub-refresh.lock"
    if lock.exists() or lock.is_symlink():
        raise ValueError("stale_lock_requires_external_review")
    report, record = _fixture_report(vault, expected_vault, suffix, old_commit, new_commit)
    if record is None or not report.backup_verified or report.state != "interrupted_mixed":
        raise ValueError("not_verified_interrupted_fixture")
    allowed = set(record["old_paths"]) | set(record["new_paths"]) | {MANIFEST}
    managed = vault / MANAGED
    known_temp = _exact_transaction_temporaries(managed, record, suffix)
    evidence = vault.parent / f".{vault.name}-homehub-filewise-artifacts-{suffix}"
    _validate_evidence_directory(evidence, _all_journal_bound_artifacts(record))
    # Recognized filenames are not enough: user edits to any known file
    # must also be preserved. Revalidate inside the writer's lock below.
    _verify_known_managed_contents(managed=managed, backup=backup, stage=stage, record=record)
    # Unrecognized files could be user work: never erase or overwrite them.
    for p in managed.rglob("*"):
        reject_link(p)
        if p.is_file() and p.relative_to(managed).as_posix() not in allowed and p not in known_temp:
            raise ValueError("unknown_managed_file_refuse_restore")
    with exclusive_refresh_lock(vault, expected_vault=expected_vault):
        _verify_known_managed_contents(managed=managed, backup=backup, stage=stage, record=record)
        if record["restore_attempts"] >= 10:
            raise ValueError("too_many_restore_attempts_manual_review")
        record = {**record, "phase": "restoring",
                  "restore_attempts": record["restore_attempts"] + 1}
        _journal_write(journal, pending, record, create=False)
        _preserve_exact_temporaries(managed=managed, vault=vault,
                                    suffix=suffix, record=record)
        for rel in record["old_paths"]:
            _put_exact_file(_target_file(backup, rel), managed, rel, suffix)
        for rel in sorted(set(record["new_paths"]) - set(record["old_paths"])):
            target = _target_file(managed, rel)
            if target.exists():
                target.unlink()
        manifest_temp = managed / f".{MANIFEST}.filewise-{suffix}.tmp"
        if manifest_temp.exists():
            raise ValueError("manifest_temp_occupied")
        with (backup / MANIFEST).open("rb") as old_manifest, manifest_temp.open("xb") as out:
            shutil.copyfileobj(old_manifest, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(manifest_temp, managed / MANIFEST)
        if verify_sealed(managed)["sha256"] != verify_sealed(backup)["sha256"]:
            raise ValueError("restored_content_different_from_backup")
        _journal_write(journal, pending, {**record, "phase": "restored"}, create=False)
    return inspect_fixture_recovery(
        vault=vault, expected_vault=expected_vault, suffix=suffix,
        old_commit=old_commit, new_commit=new_commit,
    )
