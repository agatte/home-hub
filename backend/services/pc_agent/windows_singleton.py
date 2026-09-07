"""Windows named-mutex ownership with a diagnostic PID breadcrumb."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Callable


def _kernel32():
    """Return kernel32 with pointer-sized ctypes signatures configured."""
    kernel32 = ctypes.windll.kernel32
    signatures = (
        (kernel32.CreateMutexW, [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p], ctypes.c_void_p),
        (kernel32.ReleaseMutex, [ctypes.c_void_p], ctypes.c_int),
        (kernel32.CloseHandle, [ctypes.c_void_p], ctypes.c_int),
        (kernel32.GetLastError, [], ctypes.c_ulong),
    )
    for func, argtypes, restype in signatures:
        if hasattr(func, "argtypes"):
            func.argtypes = argtypes
            func.restype = restype
    return kernel32


class WindowsPidBreadcrumbLock:
    """Kernel-owned Windows singleton plus a human-readable PID file.

    The named mutex is authoritative. The PID file is only a diagnostic
    breadcrumb, so stale/reused PIDs can never block a new process.
    """

    def __init__(
        self,
        name: str,
        pid_file: Path,
        pid_getter: Callable[[], int] = os.getpid,
    ) -> None:
        self.name = name
        self.pid_file = pid_file
        self._pid_getter = pid_getter
        self._handle = None
    def acquire(self) -> bool:
        """Acquire ownership; return False when another instance owns it."""
        if self._handle is not None:
            return True
        if sys.platform != "win32":
            raise RuntimeError("WindowsPidBreadcrumbLock requires Windows")

        kernel32 = _kernel32()
        handle = kernel32.CreateMutexW(None, True, self.name)
        if not handle:
            raise OSError(f"CreateMutexW failed for {self.name}")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False

        self._handle = handle
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.pid_file.write_text(str(self._pid_getter()))
        except Exception:
            self.release()
            raise
        return True
    def release(self) -> None:
        """Remove only this owner's breadcrumb and release its mutex."""
        try:
            if self.pid_file.exists():
                stored = int(self.pid_file.read_text().strip())
                if stored == self._pid_getter():
                    self.pid_file.unlink()
        except (OSError, ValueError):
            pass

        handle = self._handle
        self._handle = None
        if handle is None:
            return
        kernel32 = _kernel32()
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
