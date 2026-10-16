"""Cooperative whole-cycle mutex for HomeHub #399 synthetic Vault tests.

This is NOT a Win32 effective-permissions boundary. Only callers honoring this
lease exclude one another. Other processes with filesystem write permissions,
pre-existing handles, or permissions to rebind the parent remain uncontrolled.
The file is created ONLY beside an exact validated disposable Synthetic Vault.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Iterator

from manage_obsidian_vault import reject_link
from obsidian_filewise_fixture_transaction import _fixture_vault


class CycleLeaseOccupied(RuntimeError):
    """A live or stale lease exists; the caller cannot tell which."""


def lease_path(vault: Path) -> Path:
    return vault.parent / f".{vault.name}-homehub-cycle.lock"


def _verify_lease(path: Path, identity: tuple[int, int], token: str) -> None:
    try:
        reject_link(path)
        stat = path.lstat()
        if (stat.st_dev, stat.st_ino) != identity or not path.is_file():
            raise ValueError("lease_identity_mismatch")
        record = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("token") != token
                or record.get("schema") != 1):
            raise ValueError("lease_token_mismatch")
    except (OSError, ValueError) as exc:
        raise RuntimeError("cycle_lease_changed_preserved") from exc


@contextmanager
def exclusive_cycle_lease(vault: Path, *, expected_vault: Path) -> Iterator[Path]:
    """Keep one exact lease across inventory, preview, publish and postflight.

    Refuses an existing lease; NEVER guesses that it is stale or breaks it.
    Does not prevent an uncooperative or privileged process touching files.
    """
    _fixture_vault(vault, expected_vault)
    path = lease_path(vault)
    reject_link(path)
    token = secrets.token_hex(16)
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise CycleLeaseOccupied("cycle_lease_exists_live_or_stale") from exc
    completed_write = False
    try:
        # If fstat fails, the finally branch must still close the handle.
        stat = os.fstat(fd)
        identity = (stat.st_dev, stat.st_ino)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n", closefd=False) as output:
            json.dump({"schema": 1, "token": token, "pid": os.getpid(),
                       "created_utc": datetime.now(timezone.utc).isoformat()}, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        completed_write = True
        yield path
    finally:
        if completed_write:
            try:
                _verify_lease(path, identity, token)
            finally:
                os.close(fd)
            # Match the existing refresh-lock pattern. Noncooperating writers
            # remain an explicit unresolved race, not an implied guarantee.
            _verify_lease(path, identity, token)
            path.unlink()
        else:
            os.close(fd)
            # Preserve a partially written lock for independent inspection.
