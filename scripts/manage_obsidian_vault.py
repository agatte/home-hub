#!/usr/bin/env python3
"""Safely initialize and manually refresh a persistent HomeHub Obsidian Vault.

Vault root and personal notes are never overwritten. Only the sealed, managed
"HomeHub Source" subtree is swapped on refresh, after hash verification.
Previous managed snapshots are preserved outside the Vault, never deleted.
No fetching, Git writes, install, sync, service work, or automatic scheduling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from uuid import uuid4

from create_obsidian_pilot import create, git

MANAGED = "HomeHub Source"
MANIFEST = ".homehub-snapshot-manifest.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
MAX_MANAGED_FILES = 500


def reject_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError(f"Refusing linked path: {path}")


def safe_vault_path(repo: Path, vault: Path) -> None:
    if not repo.is_absolute() or not vault.is_absolute():
        raise ValueError("Repo and Vault paths must be absolute")
    if vault == vault.parent:
        raise ValueError("Refusing a filesystem root as Vault")
    repo = repo.resolve(strict=True)
    # Resolve only after refusing symlinks/junctions anywhere in the target
    # ancestry, including a redirected Documents directory.
    for component in (vault, *vault.parents):
        reject_link(component)
    resolved = vault.resolve(strict=False)
    if resolved == repo or repo in resolved.parents or resolved in repo.parents:
        raise ValueError("Vault must not overlap the source checkout")
    # HomeHub's repo checkout and worktrees share the same project root.
    # Prevent a Vault in worktrees/ even when it isn't an active Git checkout.
    project_root = repo.parent if repo.name.lower() == "main" else None
    if project_root is not None and (resolved == project_root or project_root in resolved.parents):
        raise ValueError("Vault must be outside the HomeHub project workspace")
    if not vault.parent.is_dir():
        raise ValueError("The Vault's parent directory must already exist")
    # Also exclude sibling worktrees. Probe *parent*, because vault might not exist.
    probe = subprocess.run(
        ["git", "-C", str(vault.parent), "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if probe.returncode == 0:
        raise ValueError("Vault must be outside every Git worktree")


def current_head(repo: Path, expected: str) -> str:
    if not SHA40.fullmatch(expected):
        raise ValueError("Require exact 40-character expected Git HEAD SHA")
    head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    if head != expected:
        raise ValueError(f"Source HEAD mismatch: expected {expected}, actual {head}")
    return head


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def seal(snapshot: Path, sha: str) -> int:
    paths = {}
    for path in sorted(snapshot.rglob("*")):
        reject_link(path)
        if path.is_file():
            rel = path.relative_to(snapshot).as_posix()
            if rel == MANIFEST:
                raise ValueError("Reserved filename in snapshot")
            paths[rel] = sha256_file(path)
    if len(paths) > MAX_MANAGED_FILES:
        raise ValueError("Snapshot has too many files")
    if not {"00-START-HERE.md", "SNAPSHOT.md", "AGENTS.md", "docs/PROJECT_SPEC.md"}.issubset(paths):
        raise ValueError("Incomplete preview snapshot")
    metadata = {"schema": 1, "source_commit": sha, "sha256": paths}
    (snapshot / MANIFEST).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return len(paths)


def verify_sealed(snapshot: Path) -> dict:
    reject_link(snapshot)
    if not snapshot.is_dir():
        raise ValueError("Managed snapshot directory missing")
    manifest = snapshot / MANIFEST
    reject_link(manifest)
    if not manifest.is_file() or manifest.stat().st_size > 128 * 1024:
        raise ValueError("Missing/oversized managed manifest")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unexpected managed manifest schema")
    sha = data.get("source_commit")
    stored = data.get("sha256")
    if not isinstance(sha, str) or not SHA40.fullmatch(sha):
        raise ValueError("Invalid source SHA in manifest")
    if not isinstance(stored, dict) or not 3 <= len(stored) <= MAX_MANAGED_FILES:
        raise ValueError("Unexpected managed manifest entries")
    for rel, value in stored.items():
        if not isinstance(rel, str) or not isinstance(value, str) or not SHA64.fullmatch(value):
            raise ValueError("Malformed managed manifest entry")
        pure = PurePosixPath(rel)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or "\\" in rel
            or pure.as_posix() != rel
            or pure.suffix.lower() != ".md"
        ):
            raise ValueError("Unsafe path in managed manifest")
    actual = set()
    for path in snapshot.rglob("*"):
        reject_link(path)
        if path.is_file():
            actual.add(path.relative_to(snapshot).as_posix())
    if actual != set(stored) | {MANIFEST}:
        raise ValueError("Untracked, missing, or unexpected files in managed snapshot")
    for rel, digest in stored.items():
        if sha256_file(snapshot.joinpath(*PurePosixPath(rel).parts)) != digest:
            raise ValueError(f"Managed file changed: {rel}")
    return data


def initialize(repo: Path, vault: Path, expected: str) -> str:
    safe_vault_path(repo, vault)
    head = current_head(repo, expected)
    if vault.exists() or vault.is_symlink():
        raise FileExistsError("Vault already exists; refusing to overwrite")
    vault.mkdir(mode=0o700)
    # If export fails, leave a visible partial directory for investigation.
    managed = vault / MANAGED
    exported, _ = create(repo, managed)
    if exported != head:
        raise ValueError("Source HEAD unexpectedly moved during initial snapshot")
    seal(managed, head)
    verify_sealed(managed)
    return f"Created {vault}; managed source SHA {head}. Open '{MANAGED}/00-START-HERE.md'."


def refresh(repo: Path, vault: Path, expected: str) -> str:
    safe_vault_path(repo, vault)
    head = current_head(repo, expected)
    if not vault.is_dir():
        raise ValueError("Vault does not exist; use --initialize")
    managed = vault / MANAGED
    existing = verify_sealed(managed)
    if existing["source_commit"] == head:
        return f"Already at Git {head}; no changes made."
    # Stage on same parent filesystem OUTSIDE the Vault to avoid duplicate notes.
    # No cleanup, overwrites, or recursive deletions on any error.
    suffix = uuid4().hex
    staged = vault.parent / f".{vault.name}-homehub-stage-{suffix}"
    backup = vault.parent / f".{vault.name}-homehub-backup-{suffix}"
    if staged.exists() or backup.exists():
        raise FileExistsError("Unexpected staging/backup path already exists")
    exported, _ = create(repo, staged)
    if exported != head:
        raise ValueError("Source HEAD unexpectedly moved during staging")
    seal(staged, head)
    verify_sealed(staged)
    # Check managed subtree once more before moving; no user notes are ever moved.
    verify_sealed(managed)
    os.rename(managed, backup)
    try:
        os.rename(staged, managed)
    except OSError:
        if not managed.exists():
            try:
                os.rename(backup, managed)
            except OSError as restore_error:
                raise RuntimeError(
                    f"Refresh interrupted; previous snapshot preserved at {backup}"
                ) from restore_error
        raise
    return f"Refreshed to {head}. Previous managed snapshot preserved at {backup}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--initialize", action="store_true")
    choice.add_argument("--refresh", action="store_true")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    opts = parser.parse_args(argv)
    try:
        msg = (initialize if opts.initialize else refresh)(
            opts.repo, opts.vault, opts.expected_head
        )
    except (
        ValueError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
