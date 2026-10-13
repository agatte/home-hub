"""Fail-closed per-Vault refresh mutex for a *future* explicitly approved host worker.

This is only an isolated library candidate. Acquiring the mutex creates ONE
sibling lock file; it does not read notes, stage snapshots, swap or clean up a
Vault. Do not deploy or call this against the live Windows Vault without the
separate host-automation approval tracked in HomeHub #399.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Iterator


class RefreshBusy(ValueError):
    """The target may already be refreshing; stale locks need human review."""


def _guard_existing_vault(vault: Path, expected_vault: Path) -> None:
    if (not isinstance(vault, Path) or not isinstance(expected_vault, Path)
            or not vault.is_absolute() or not expected_vault.is_absolute()
            or vault != expected_vault or vault == vault.parent):
        raise ValueError("unexpected_or_invalid_vault_path")
    # No implicit traversal through junctions or symlinked Documents ancestors.
    for component in (vault, *vault.parents):
        if component.is_symlink() or (
            hasattr(component, "is_junction") and component.is_junction()
        ):
            raise ValueError(f"Refusing linked path: {component}")
    if not vault.is_dir() or not vault.parent.is_dir():
        raise ValueError("vault_directory_missing")
    if not vault.name or any(ch in vault.name for ch in ("/", "\\")):
        raise ValueError("unsafe_vault_name")


@contextmanager
def exclusive_refresh_lock(vault: Path, *, expected_vault: Path) -> Iterator[Path]:
    """Acquire one exact sibling lock, never break a preexisting/stale lock.

    Existing locks are not timed out or automatically removed: a post-crash
    review must prove the writer is dead and the exact lock is safe to release.
    A live worker holds its open file descriptor for the lock lifetime, and
    verifies identity and owner token before releasing the one known file.
    """
    _guard_existing_vault(vault, expected_vault)
    lock = vault.parent / f".{vault.name}-homehub-refresh.lock"
    token = secrets.token_hex(16)
    fd: int | None = None
    identity: tuple[int, int] | None = None
    opened = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(lock, flags, 0o600)
        except FileExistsError as exc:
            raise RefreshBusy("refresh_lock_already_exists_or_stale") from exc
        opened = True
        stat = os.fstat(fd)
        identity = (stat.st_dev, stat.st_ino)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n", closefd=False) as output:
            json.dump(
                {"schema": 1, "token": token, "pid": os.getpid(),
                 "created_utc": datetime.now(timezone.utc).isoformat()},
                output,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        yield lock
    finally:
        # A failed lock write is deliberately NOT auto-cleaned: the exact file
        # needs inspection if ownership or file identity cannot be established.
        if opened and fd is not None:
            try:
                _assert_our_lock(lock, identity, token)
            finally:
                # Windows refuses unlink while Python's os.open descriptor is
                # still open. Release after verification, then re-verify before
                # touching this exact path. Never delete an altered lock.
                os.close(fd)
            _assert_our_lock(lock, identity, token)
            lock.unlink()


def _assert_our_lock(lock: Path, identity: tuple[int, int] | None, token: str) -> None:
    try:
        current = lock.lstat()
        if (identity != (current.st_dev, current.st_ino) or lock.is_symlink()
                or (hasattr(lock, "is_junction") and lock.is_junction())):
            raise RuntimeError("refresh_lock_path_changed_preserved")
        record = json.loads(lock.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise RuntimeError("refresh_lock_verification_failed_preserved") from exc
    if not isinstance(record, dict) or record.get("token") != token:
        raise RuntimeError("refresh_lock_ownership_changed_preserved")
