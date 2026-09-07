"""Regression coverage for Windows desktop singleton ownership (#223)."""
from types import SimpleNamespace

from backend.services.pc_agent import windows_singleton as singleton


class FakeKernel32:
    def __init__(self, *, last_error: int = 0, handle: int = 123) -> None:
        self.last_error = last_error
        self.handle = handle
        self.created = []
        self.closed = []
        self.released = []

    def CreateMutexW(self, security, initial_owner, name):
        self.created.append((security, initial_owner, name))
        return self.handle

    def GetLastError(self):
        return self.last_error

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def ReleaseMutex(self, handle):
        self.released.append(handle)
        return True


def _windows(monkeypatch, kernel: FakeKernel32) -> None:
    monkeypatch.setattr(singleton.sys, "platform", "win32")
    monkeypatch.setattr(
        singleton.ctypes,
        "windll",
        SimpleNamespace(kernel32=kernel),
        raising=False,
    )


def test_stale_reused_pid_is_replaced_when_mutex_is_free(tmp_path, monkeypatch):
    kernel = FakeKernel32()
    _windows(monkeypatch, kernel)
    pid_file = tmp_path / "desktop_notifier.pid"
    pid_file.write_text("5320")  # may belong to any unrelated live process
    lock = singleton.WindowsPidBreadcrumbLock(
        "HomeHub_DesktopNotifier", pid_file, pid_getter=lambda: 9001,
    )

    assert lock.acquire() is True
    assert pid_file.read_text() == "9001"
    assert kernel.created == [(None, True, "HomeHub_DesktopNotifier")]


def test_existing_mutex_blocks_duplicate_without_rewriting_pid(tmp_path, monkeypatch):
    kernel = FakeKernel32(last_error=183)
    _windows(monkeypatch, kernel)
    pid_file = tmp_path / "desktop_notifier.pid"
    pid_file.write_text("7777")
    lock = singleton.WindowsPidBreadcrumbLock(
        "HomeHub_DesktopNotifier", pid_file, pid_getter=lambda: 9001,
    )

    assert lock.acquire() is False
    assert pid_file.read_text() == "7777"
    assert kernel.closed == [123]
    assert kernel.released == []


def test_clean_release_removes_only_current_breadcrumb(tmp_path, monkeypatch):
    kernel = FakeKernel32()
    _windows(monkeypatch, kernel)
    pid_file = tmp_path / "desktop_notifier.pid"
    lock = singleton.WindowsPidBreadcrumbLock(
        "HomeHub_DesktopNotifier", pid_file, pid_getter=lambda: 9001,
    )
    assert lock.acquire() is True

    lock.release()
    assert not pid_file.exists()
    assert kernel.released == [123]
    assert kernel.closed == [123]


def test_release_preserves_foreign_breadcrumb(tmp_path, monkeypatch):
    kernel = FakeKernel32()
    _windows(monkeypatch, kernel)
    pid_file = tmp_path / "desktop_notifier.pid"
    lock = singleton.WindowsPidBreadcrumbLock(
        "HomeHub_DesktopNotifier", pid_file, pid_getter=lambda: 9001,
    )
    assert lock.acquire() is True
    pid_file.write_text("9100")  # a replacement owner wrote after us

    lock.release()
    assert pid_file.read_text() == "9100"
    assert kernel.released == [123]
    assert kernel.closed == [123]
