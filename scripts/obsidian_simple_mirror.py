"""Opt-in local evaluation of #399's rebuildable mirror; no CLI or scheduling.

run_once acquires source evidence through the existing GitHub verifier.
Direct mirror_once callers authenticate source evidence independently.
Verified former managed Markdown may be retired. Obsidian may remain open: mixed
versions and a check/replace race remain possible. This is cooperative ownership,
not a security boundary, globally atomic transaction, crash-safe directory fsync,
or automatic recovery. Failure evidence requires manual reviewed rebuild/repair.
Personal notes, settings and historical backups are never traversed or cleaned.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from manage_obsidian_vault import MANAGED, MANIFEST, verify_sealed
from obsidian_github_docs_source import VerifiedDocs, github_json, prepare_current_docs
from obsidian_source_verifier import OID, _safe_markdown_path, validate_tree, verify_all
from obsidian_verified_stage import expected_generated_pages, stage_only_verified_docs


@dataclass(frozen=True)
class MirrorResult:
    commit: str
    backup: Path
    completed_stage: Path
    receipt: Path



@dataclass(frozen=True)
class RunOutcome:
    state: str
    previous_commit: str
    commit: str
    mirror_result: MirrorResult | None = None


def run_once(
    *, vault: Path, expected_vault: Path, local_evaluation_approved: bool,
    fetch=github_json, blob_source=None,
) -> RunOutcome:
    """Explicit library evaluation only; SourceUnavailable propagates without writes.

    Acquisition uses the existing HTTPS verifier (or an injected test transport).
    Local integrity, staging and mirror failures propagate with evidence intact.
    No bootstrap, host selection, scheduling or recovery is implied.
    """
    if local_evaluation_approved is not True:
        raise ValueError("local_evaluation_approval_missing")
    managed = _guard(vault, expected_vault)
    _refuse_active_evidence(vault)
    old = _sealed(managed)["source_commit"]
    prepared = prepare_current_docs(old, fetch=fetch, blob_source=blob_source)
    if (prepared.previously_sealed_commit != old
            or prepared.docs.commit != prepared.intended_commit
            or not isinstance(prepared.intended_commit, str)
            or not OID.fullmatch(prepared.intended_commit)
            or prepared.source_ref_stable is not True):
        raise ValueError("acquired_source_identity_mismatch")
    intended = prepared.intended_commit
    if intended == old:
        if prepared.ancestry != "identical":
            raise ValueError("acquired_ancestry_mismatch")
        return RunOutcome("no_change", old, intended)
    if prepared.ancestry != "forward":
        raise ValueError("acquired_ancestry_mismatch")
    result = mirror_once(
        vault=vault, expected_vault=expected_vault, docs=prepared.docs,
        authenticated_sha=intended, source_identity_verified=True,
        source_ref_stable=True, authenticated_forward_from=old,
        local_evaluation_approved=local_evaluation_approved,
    )
    return RunOutcome("updated", old, intended, result)


def _plain(path: Path) -> None:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise ValueError("linked_or_reparse_path_refused")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("non_regular_path_refused")


def _guard(vault: Path, expected: Path) -> Path:
    if (not isinstance(vault, Path) or not isinstance(expected, Path)
            or not vault.is_absolute() or str(vault) != str(expected)
            or vault == vault.parent or ".." in vault.parts):
        raise ValueError("unexpected_or_invalid_exact_vault")
    if any(p.endswith((".", " ")) or any(c in p for c in '<>:"|?*')
           for p in vault.parts[1:]):
        raise ValueError("ambiguous_vault_path")
    for part in (vault, *vault.parents):
        _plain(part)
    managed = vault / MANAGED
    _plain(managed)
    if not vault.is_dir() or not managed.is_dir():
        raise ValueError("missing_vault_or_managed_directory")
    return managed


def _refuse_active_evidence(vault: Path) -> None:
    prefix = f".{vault.name}-homehub-"
    # Only sibling names are inspected; no personal note/settings traversal.
    for path in vault.parent.iterdir():
        name = path.name.casefold()
        if name.startswith(prefix.casefold()) and (
            "stage-" in name and "completed-stage-" not in name
            or "pending" in name or "incomplete" in name
            or name.endswith(".lock")
        ):
            raise ValueError("active_or_incomplete_evidence_requires_review")


def _sealed(root: Path) -> dict:
    """Strengthen the existing seal: reject reparse points and rogue directories."""
    _plain(root)
    # Walk without following links; inspect each directory before descending.
    def walk_error(error: OSError) -> None:
        raise error

    actual_dirs = set()
    actual_files = set()
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(parent) / name
            _plain(path)
            if name in dirs:
                actual_dirs.add(path.relative_to(root).as_posix())
            else:
                actual_files.add(path.relative_to(root).as_posix())
    manifest = root / MANIFEST
    if manifest.stat().st_size > 128 * 1024:
        raise ValueError("oversized_manifest")
    metadata = json.loads(manifest.read_bytes())
    entries = metadata.get("sha256") if isinstance(metadata, dict) else None
    if not isinstance(entries, dict) or any(
        n not in {"00-START-HERE.md", "SNAPSHOT.md"} and not _safe_markdown_path(n)
        for n in entries
    ):
        raise ValueError("unsafe_manifest_namespace")
    if actual_files != set(entries) | {MANIFEST}:
        raise ValueError("unexpected_managed_file_spellings")
    _namespace(set(entries))
    data = verify_sealed(root)
    allowed_dirs = set()
    for name in data["sha256"]:
        allowed_dirs.update(p.as_posix() for p in Path(name).parents if str(p) != ".")
    if actual_dirs != allowed_dirs:
        raise ValueError("unexpected_managed_directories")
    return data


def _directories(names: set[str]) -> set[str]:
    return {p.as_posix() for name in names for p in Path(name).parents
            if str(p) != "."}


def _check_layout(root: Path, names: set[str]) -> None:
    """Check the new exact namespace before publishing its manifest."""
    files, directories = set(), set()

    def walk_error(error: OSError) -> None:
        raise error

    _plain(root)
    for parent, dirs, members in os.walk(root, followlinks=False, onerror=walk_error):
        for name in dirs + members:
            path = Path(parent) / name
            _plain(path)
            relative = path.relative_to(root).as_posix()
            (directories if name in dirs else files).add(relative)
    if files != names | {MANIFEST} or directories != _directories(names):
        raise ValueError("unexpected_managed_layout")


def _namespace(names: set[str]) -> None:
    """Validate files and all ancestor spellings as one Windows namespace."""
    namespace = {}
    for name in names:
        if name not in {"00-START-HERE.md", "SNAPSHOT.md"} and not _safe_markdown_path(name):
            raise ValueError("unsafe_manifest_namespace")
        parts = name.split("/")
        for index, part in enumerate(parts):
            # Reject DOS short-name spellings and additional Win32 device aliases.
            stem = part.split(".", 1)[0]
            if ("~" in part or stem.endswith((" ", "."))
                    or stem.upper() in {"CONIN$", "CONOUT$", *(f"COM{i}" for i in "???"),
                                       *(f"LPT{i}" for i in "???")}):
                raise ValueError("windows_path_alias")
            prefix = "/".join(parts[:index + 1])
            kind = "file" if index == len(parts) - 1 else "directory"
            previous = namespace.setdefault(prefix.casefold(), (prefix, kind))
            if previous != (prefix, kind):
                raise ValueError("windows_path_namespace_collision")


def _addition_target(root: Path, name: str, *, create_dirs: bool = False) -> Path:
    """Only exact, plain ancestors; never follow aliases or replace a new target."""
    current = root
    parts = name.split("/")
    for index, part in enumerate(parts):
        _plain(current)
        if not current.is_dir():
            raise ValueError("addition_ancestor_not_directory")
        matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()]
        target = current / part
        if matches:
            if len(matches) != 1 or matches[0].name != part:
                raise ValueError("windows_path_alias")
            _plain(target)
            if index == len(parts) - 1:
                raise ValueError("addition_target_not_absent")
            if not target.is_dir():
                raise ValueError("addition_ancestor_not_directory")
        elif index < len(parts) - 1:
            if not create_dirs:
                return root / name
            target.mkdir()  # Exact vetted ancestor, after backup and pending marker.
            _plain(target)
        current = target
    return current


def _create(path: Path, data: bytes) -> tuple[int, int]:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino


def _owned(path: Path, identity: tuple[int, int], data: bytes) -> None:
    _plain(path)
    info = path.lstat()
    if (info.st_dev, info.st_ino) != identity or path.read_bytes() != data:
        raise ValueError("ownership_evidence_changed_preserved")


def _same(path: Path, expected: bytes) -> None:
    for part in (path, *path.parents):
        _plain(part)
    if path.read_bytes() != expected:
        raise ValueError("managed_bytes_changed")


def mirror_once(
    *, vault: Path, expected_vault: Path, docs: VerifiedDocs,
    authenticated_sha: str, source_identity_verified: bool,
    source_ref_stable: bool, authenticated_forward_from: str,
    local_evaluation_approved: bool,
) -> MirrorResult:
    """Apply one explicitly approved evaluation; never infer source/host authority.

    ``authenticated_forward_from`` must be the caller's independently verified
    ancestor of ``authenticated_sha``, not a guessed SHA or timestamp comparison.
    No bootstrap, scheduling, rollback or stale-lock repair.
    A read-only generated file's Windows read-only attribute may be cleared for
    replacement or retirement after backup. No ACL or host process coordination is performed.
    """
    if (local_evaluation_approved is not True or source_identity_verified is not True
            or source_ref_stable is not True):
        raise ValueError("approval_or_source_evidence_missing")
    if (not isinstance(authenticated_sha, str) or not OID.fullmatch(authenticated_sha)
            or docs.commit != authenticated_sha or not OID.fullmatch(docs.tree)):
        raise ValueError("invalid_pinned_source")
    # Freeze mutable caller content before validation and any filesystem writes.
    docs = VerifiedDocs(docs.commit, docs.tree, tuple(docs.files), dict(docs.contents))
    checked = validate_tree(
        {"path": b.path, "type": "blob", "mode": b.mode, "sha": b.oid, "size": b.size}
        for b in docs.files
    )
    if checked != docs.files:
        raise ValueError("invalid_bundle_membership")
    verify_all(checked, docs.contents)
    managed = _guard(vault, expected_vault)
    prefix = f".{vault.name}-homehub-"
    lock = vault.parent / (prefix + "refresh.lock")
    pending = vault.parent / (prefix + "simple.pending")
    _refuse_active_evidence(vault)
    old = _sealed(managed)
    if old["source_commit"] == docs.commit:
        raise ValueError("no_op_source")
    if authenticated_forward_from != old["source_commit"]:
        raise ValueError("no_authenticated_forward_ancestry")
    new_bytes = {**docs.contents, **expected_generated_pages(docs)}
    old_members, new_members = set(old["sha256"]), set(new_bytes)
    _namespace(old_members | new_members)
    removals = old_members - new_members
    if any(not _safe_markdown_path(name) for name in removals):
        raise ValueError("unsafe_retirement")
    old_dirs = _directories(old_members)
    new_dirs = _directories(new_members)
    additions = new_members - old_members
    for name in additions:
        _addition_target(managed, name)
    old_bytes = {name: (managed / name).read_bytes() for name in old["sha256"]}
    for name, raw in old_bytes.items():
        if sha256(raw).hexdigest() != old["sha256"][name]:
            raise ValueError("managed_bytes_changed")
    old_manifest = (managed / MANIFEST).read_bytes()
    suffix = uuid4().hex
    stage = vault.parent / (prefix + "stage-" + suffix)
    backup = vault.parent / (prefix + "backup-" + suffix)
    completed = vault.parent / (prefix + "completed-stage-" + suffix)
    receipt = vault.parent / (prefix + "complete-" + suffix + ".json")
    if any(p.exists() or p.is_symlink() for p in (stage, backup, completed, receipt)):
        raise ValueError("unique_evidence_target_exists")
    record = (json.dumps({"token": suffix, "from": old["source_commit"],
                          "to": docs.commit, "backup": backup.name}) + "\n").encode()
    lock_id = _create(lock, record)
    # From here every exception preserves the lock and all partial evidence.
    stage_only_verified_docs(vault=vault, docs=docs, stage_suffix=suffix,
                             source_identity_verified=True)
    new = _sealed(stage)
    if new["sha256"] != {n: sha256(b).hexdigest() for n, b in new_bytes.items()}:
        raise ValueError("unexpected_staged_bytes")
    backup.mkdir()
    for name, raw in {**old_bytes, MANIFEST: old_manifest}.items():
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        _create(dest, raw)
    if _sealed(backup) != old or (backup / MANIFEST).read_bytes() != old_manifest:
        raise ValueError("backup_verification_failed")
    if _sealed(managed) != old:
        raise ValueError("managed_changed_before_update")
    _same(managed / MANIFEST, old_manifest)
    pending_id = _create(pending, record)
    for name, raw in {**new_bytes, MANIFEST: (stage / MANIFEST).read_bytes()}.items():
        if name == MANIFEST:
            for rel in sorted(removals):
                target = managed / rel
                _same(target, old_bytes[rel])
                # Exact file attribute only; no ACL changes. A sharing error or
                # check/unlink race leaves pending evidence for manual review.
                if not target.stat().st_mode & stat.S_IWRITE:
                    target.chmod(target.stat().st_mode | stat.S_IWRITE)
                _same(target, old_bytes[rel])
                target.unlink()
            for rel in sorted(old_dirs - new_dirs,
                              key=lambda n: (-n.count("/"), n)):
                target = managed / rel
                for part in (target, *target.parents):
                    _plain(part)
                if not target.is_dir() or list(target.iterdir()):
                    raise ValueError("retired_directory_not_empty")
                target.rmdir()  # Exact enumerated empty ancestor, never recursive.
            _check_layout(managed, new_members)
            for rel, content in new_bytes.items():
                _same(managed / rel, content)
        expected = old_manifest if name == MANIFEST else old_bytes.get(name)
        target = managed / name
        if name in additions:
            target = _addition_target(managed, name, create_dirs=True)
        if raw == expected:
            continue
        temp = target.with_name(target.name + ".simple-" + suffix)
        _create(temp, raw)
        if name in additions:
            _addition_target(managed, name)
        else:
            _same(target, expected)  # Cooperative check/replace race remains.
        if name not in additions and not target.stat().st_mode & stat.S_IWRITE:
            target.chmod(target.stat().st_mode | stat.S_IWRITE)
        os.replace(temp, target)
    if _sealed(managed) != new:
        raise ValueError("final_snapshot_mismatch")
    _owned(pending, pending_id, record)
    _owned(lock, lock_id, record)
    stage.rename(completed)
    pending.rename(receipt)
    _owned(lock, lock_id, record)
    lock.unlink()
    return MirrorResult(docs.commit, backup, completed, receipt)
