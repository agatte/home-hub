"""Conservative local-Windows Obsidian process observation for HomeHub #399.

Only a *point-in-time advisory* from the process table, never a guarantee that
Obsidian cannot launch after the check, never a host write authorization.
Unknown or invalid enumeration always abstains (including non-Windows).
No shell, WMI, taskkill, tokens, elevation, process handles or service writes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, Iterable


_OBSIDIAN_EXE = "obsidian.exe"


@dataclass(frozen=True)
class ProcessObservation:
    state: str
    matched_pids: tuple[int, ...] = ()
    reason: str = "process_snapshot_not_verified"
    authorizes_host_refresh: bool = False


def classify_snapshot(rows: Iterable[tuple[int, str]]) -> ProcessObservation:
    """Classify a *complete* OS snapshot; invalid inputs must fail closed.

    A snapshot is complete only if its producer successfully reached the
    explicit end-of-list status. Do not use this with partial WMI/tasklist
    data or with app names inferred from window captions.
    """
    seen = []
    try:
        for pid, name in rows:
            # Toolhelp includes Windows PID 0 (the kernel idle process).
            # It is not an application and must not imply corruption.
            if pid == 0 and name in ("[System Process]", "System Idle Process"):
                continue
            if (
                not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
                or not isinstance(name, str) or not name
            ):
                return ProcessObservation("unknown", reason="invalid_process_snapshot_entry")
            if name.casefold() == _OBSIDIAN_EXE:
                seen.append(pid)
        if seen:
            return ProcessObservation("open", tuple(sorted(set(seen))), "obsidian_process_seen")
        return ProcessObservation("closed", reason="complete_snapshot_has_no_obsidian_process")
    except Exception:
        return ProcessObservation("unknown", reason="process_snapshot_unavailable")


def _toolhelp_windows_snapshot() -> list[tuple[int, str]]:
    """Enumerate every process, not just the current user's session.

    This avoids false closed reports from filtering out another user or
    disconnected session. A renamed executable is not identifiable here.
    """
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    # TH32CS_SNAPPROCESS, zero process ID selects all processes.
    handle = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if handle == ctypes.c_void_p(-1).value or not handle:
        raise OSError(ctypes.get_last_error(), "process_snapshot_failed")
    try:
        row = PROCESSENTRY32W()
        row.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel.Process32FirstW(handle, ctypes.byref(row)):
            raise OSError(ctypes.get_last_error(), "process_snapshot_first_failed")
        names = []
        while True:
            names.append((int(row.th32ProcessID), str(row.szExeFile)))
            ctypes.set_last_error(0)
            if not kernel.Process32NextW(handle, ctypes.byref(row)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise OSError(ctypes.get_last_error(), "process_snapshot_incomplete")
                break
        return names
    finally:
        kernel.CloseHandle(handle)


def observe_windows_obsidian(
    *,
    snapshot: Callable[[], Iterable[tuple[int, str]]] | None = None,
) -> ProcessObservation:
    """Conservative process-name check, never a release of the host gate."""
    if snapshot is None:
        if os.name != "nt":
            return ProcessObservation("unknown", reason="not_windows")
        snapshot = _toolhelp_windows_snapshot
    try:
        return classify_snapshot(snapshot())
    except Exception:
        return ProcessObservation("unknown", reason="process_snapshot_unavailable")


def probe_windows_obsidian_state() -> str:
    """Compatible with the candidate's preflight/swap advisory callback."""
    return observe_windows_obsidian().state
