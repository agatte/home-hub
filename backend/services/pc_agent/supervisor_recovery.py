"""Detached, identity-safe recovery for a poisoned desktop supervisor.

This module deliberately has no dependency on the supervisor's logging or
network stack.  It is run in a separate process when a managed thread is
blocked in native code, so that recovery can still finish after the original
Python process is no longer able to make orderly progress.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Protocol


PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CREATE_NO_WINDOW = 0x08000000
ERROR_INVALID_PARAMETER = 87
MAX_BREADCRUMB_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProcessIdentity:
    """A PID together with its Windows creation FILETIME.

    A PID by itself is unsafe: Windows may reuse it between a failed stop and
    the force-kill fallback.  A process handle plus this start identity makes
    the fallback target the same process instance that reported the hang.
    """

    pid: int
    creation_filetime: int

    @property
    def value(self) -> str:
        return f"{self.pid}:{self.creation_filetime}"


class IdentityInspection(Enum):
    EXACT = auto()
    ABSENT_OR_DIFFERENT = auto()
    INDETERMINATE = auto()


class TerminationResult(Enum):
    TERMINATED = auto()
    ABSENT_OR_DIFFERENT = auto()
    INDETERMINATE = auto()
    FAILED = auto()


class RecoveryOperations(Protocol):
    def inspect_identity(self, identity: ProcessIdentity) -> IdentityInspection: ...

    def terminate_exact(self, identity: ProcessIdentity) -> TerminationResult: ...

    def kick_canonical_launcher(self) -> None: ...


class FileBreadcrumbs:
    """Small bounded incident trail independent of shared logging handlers."""

    def __init__(
        self,
        path: Path,
        now: Callable[[], float] = time.time,
        max_bytes: int = MAX_BREADCRUMB_BYTES,
    ) -> None:
        self._path = path
        self._now = now
        self._max_bytes = max_bytes

    def write(self, recovery_id: str, stage: str, detail: str = "") -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = f"{self._now():.3f} {recovery_id} {stage} {detail}\n".encode()
            if self._path.exists() and self._path.stat().st_size + len(line) > self._max_bytes:
                os.replace(self._path, self._path.with_suffix(self._path.suffix + ".1"))
            fd = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            # Recovery cannot be made contingent on observability storage.
            pass


def current_process_identity() -> ProcessIdentity | None:
    """Return this Windows process's PID/start identity, or ``None`` off Win32."""
    if sys.platform != "win32":
        return None
    return WindowsRecoveryOperations.identity_for_pid(os.getpid())


class WindowsRecoveryOperations:
    """Win32 handle operations used by the detached recovery worker.

    ``TerminateProcess`` is the native equivalent of the successful
    ``Win32_Process.Terminate`` incident recovery, but is safer here: it acts
    on the already-validated process handle rather than looking up a PID again.
    """

    @staticmethod
    def _kernel32():
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetProcessTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        kernel32.GetProcessTimes.restype = ctypes.c_int
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.TerminateProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        return kernel32

    @staticmethod
    def _creation_filetime(handle: int) -> int | None:
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel_time = ctypes.c_ulonglong()
        user_time = ctypes.c_ulonglong()
        ok = WindowsRecoveryOperations._kernel32().GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        return creation.value if ok else None

    @staticmethod
    def identity_for_pid(pid: int) -> ProcessIdentity | None:
        """Best-effort identity lookup for the caller's own known-live PID."""
        if sys.platform != "win32":
            return None
        kernel32 = WindowsRecoveryOperations._kernel32()
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if not handle:
            return None
        try:
            created = WindowsRecoveryOperations._creation_filetime(handle)
            return ProcessIdentity(pid, created) if created is not None else None
        finally:
            kernel32.CloseHandle(handle)

    def inspect_identity(self, identity: ProcessIdentity) -> IdentityInspection:
        if sys.platform != "win32":
            return IdentityInspection.INDETERMINATE
        ctypes.set_last_error(0)
        kernel32 = self._kernel32()
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, identity.pid,
        )
        if not handle:
            return (
                IdentityInspection.ABSENT_OR_DIFFERENT
                if ctypes.get_last_error() == ERROR_INVALID_PARAMETER
                else IdentityInspection.INDETERMINATE
            )
        try:
            created = self._creation_filetime(handle)
            if created is None:
                return IdentityInspection.INDETERMINATE
            if created == identity.creation_filetime:
                return IdentityInspection.EXACT
            return IdentityInspection.ABSENT_OR_DIFFERENT
        finally:
            kernel32.CloseHandle(handle)

    def terminate_exact(self, identity: ProcessIdentity) -> TerminationResult:
        if sys.platform != "win32":
            return TerminationResult.INDETERMINATE
        ctypes.set_last_error(0)
        kernel32 = self._kernel32()
        handle = kernel32.OpenProcess(
            PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            identity.pid,
        )
        if not handle:
            return (
                TerminationResult.ABSENT_OR_DIFFERENT
                if ctypes.get_last_error() == ERROR_INVALID_PARAMETER
                else TerminationResult.INDETERMINATE
            )
        try:
            created = self._creation_filetime(handle)
            if created is None:
                return TerminationResult.INDETERMINATE
            if created != identity.creation_filetime:
                return TerminationResult.ABSENT_OR_DIFFERENT
            if kernel32.TerminateProcess(handle, 1):
                return TerminationResult.TERMINATED
            return TerminationResult.FAILED
        finally:
            kernel32.CloseHandle(handle)

    def kick_canonical_launcher(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        launcher = project_root / "scripts" / "start-supervisor-hidden.vbs"
        subprocess.Popen(
            ["wscript.exe", str(launcher)],
            cwd=project_root,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )


def _launch_replacement(
    operations: RecoveryOperations,
    breadcrumbs: FileBreadcrumbs,
    recovery_id: str,
    reason: str,
) -> bool:
    breadcrumbs.write(recovery_id, "replacement-launch-attempted", reason)
    try:
        operations.kick_canonical_launcher()
    except Exception as exc:
        breadcrumbs.write(
            recovery_id, "replacement-launch-failed", f"{type(exc).__name__}: {exc}",
        )
        return False
    breadcrumbs.write(recovery_id, "replacement-launch-succeeded", reason)
    return True


def recover_supervisor(
    identity: ProcessIdentity,
    operations: RecoveryOperations,
    breadcrumbs: FileBreadcrumbs,
    *,
    recovery_id: str | None = None,
    grace_seconds: float = 3.0,
    verify_seconds: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Wait briefly, hard-kill the exact old owner, then launch its replacement."""
    recovery_id = recovery_id or uuid.uuid4().hex
    breadcrumbs.write(recovery_id, "worker-start", f"expected={identity.value}")

    deadline = monotonic() + grace_seconds
    while monotonic() < deadline:
        inspection = operations.inspect_identity(identity)
        if inspection is IdentityInspection.ABSENT_OR_DIFFERENT:
            breadcrumbs.write(recovery_id, "graceful-wait-outcome", "old identity gone")
            breadcrumbs.write(recovery_id, "old-identity-confirmed-gone", "graceful")
            return _launch_replacement(operations, breadcrumbs, recovery_id, "graceful")
        if inspection is IdentityInspection.EXACT:
            breadcrumbs.write(recovery_id, "exact-old-identity-observed", identity.value)
        sleep(0.1)

    inspection = operations.inspect_identity(identity)
    breadcrumbs.write(recovery_id, "graceful-wait-outcome", inspection.name.lower())
    if inspection is IdentityInspection.ABSENT_OR_DIFFERENT:
        breadcrumbs.write(recovery_id, "old-identity-confirmed-gone", "graceful-deadline")
        return _launch_replacement(operations, breadcrumbs, recovery_id, "graceful-deadline")
    if inspection is IdentityInspection.INDETERMINATE:
        breadcrumbs.write(recovery_id, "recovery-failed", "pre-terminate inspection indeterminate")
        return False

    breadcrumbs.write(recovery_id, "exact-old-identity-observed", identity.value)
    breadcrumbs.write(recovery_id, "force-termination-attempted", identity.value)
    termination = operations.terminate_exact(identity)
    breadcrumbs.write(recovery_id, "force-termination-result", termination.name.lower())
    deadline = monotonic() + verify_seconds
    while monotonic() < deadline:
        inspection = operations.inspect_identity(identity)
        if inspection is IdentityInspection.ABSENT_OR_DIFFERENT:
            breadcrumbs.write(recovery_id, "old-identity-confirmed-gone", "forced")
            return _launch_replacement(operations, breadcrumbs, recovery_id, "forced")
        sleep(0.1)

    inspection = operations.inspect_identity(identity)
    if inspection is IdentityInspection.ABSENT_OR_DIFFERENT:
        breadcrumbs.write(recovery_id, "old-identity-confirmed-gone", "forced-deadline")
        return _launch_replacement(operations, breadcrumbs, recovery_id, "forced-deadline")
    breadcrumbs.write(recovery_id, "recovery-failed", f"post-terminate {inspection.name.lower()}")
    return False


def launch_detached_recovery(identity: ProcessIdentity, breadcrumb_path: Path) -> None:
    """Start the external worker before the unhealthy owner calls ``os._exit``."""
    if sys.platform != "win32":
        return
    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "backend.services.pc_agent.supervisor_recovery",
            "--pid",
            str(identity.pid),
            "--creation-filetime",
            str(identity.creation_filetime),
            "--breadcrumb-path",
            str(breadcrumb_path),
        ],
        cwd=Path(__file__).resolve().parents[3],
        creationflags=CREATE_NO_WINDOW | 0x00000008 | 0x00000200,
        close_fds=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover a poisoned Home Hub supervisor")
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--creation-filetime", required=True, type=int)
    parser.add_argument("--breadcrumb-path", required=True, type=Path)
    args = parser.parse_args()
    identity = ProcessIdentity(args.pid, args.creation_filetime)
    return 0 if recover_supervisor(
        identity,
        WindowsRecoveryOperations(),
        FileBreadcrumbs(args.breadcrumb_path),
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
