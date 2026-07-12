"""Peripheral RGB singleton lock behavior."""

import importlib
import sys
import types


def _install_openrgb_stub() -> None:
    if "openrgb" not in sys.modules:
        openrgb = types.ModuleType("openrgb")

        class _OpenRGBClient:
            pass

        openrgb.OpenRGBClient = _OpenRGBClient
        sys.modules["openrgb"] = openrgb
    if "openrgb.utils" not in sys.modules:
        utils = types.ModuleType("openrgb.utils")

        class _DeviceType:
            MOUSE = "mouse"
            KEYBOARD = "keyboard"

        class _RGBColor:
            def __init__(self, red, green, blue):
                self.red = red
                self.green = green
                self.blue = blue

        utils.DeviceType = _DeviceType
        utils.RGBColor = _RGBColor
        sys.modules["openrgb.utils"] = utils


_install_openrgb_stub()
rgb = importlib.import_module("backend.services.pc_agent.peripheral_rgb_agent")


class _FakeProcess:
    def __init__(self, *, running=True, status="running", cmdline=None):
        self._running = running
        self._status = status
        self._cmdline = cmdline or []

    def is_running(self):
        return self._running

    def status(self):
        return self._status

    def cmdline(self):
        return self._cmdline


def test_pid_live_owner_accepts_supervisor(monkeypatch):
    monkeypatch.setattr(
        rgb.psutil,
        "Process",
        lambda _pid: _FakeProcess(
            cmdline=[
                "pythonw.exe",
                "-m",
                "backend.services.pc_agent.supervisor",
            ],
        ),
    )

    assert rgb._pid_is_live_owner(1234) is True


def test_pid_live_owner_rejects_unrelated_process(monkeypatch):
    monkeypatch.setattr(
        rgb.psutil,
        "Process",
        lambda _pid: _FakeProcess(cmdline=["pythonw.exe", "other_module"]),
    )

    assert rgb._pid_is_live_owner(1234) is False


def test_pid_live_owner_rejects_missing_process(monkeypatch):
    def _missing(_pid):
        raise rgb.psutil.NoSuchProcess(_pid)

    monkeypatch.setattr(rgb.psutil, "Process", _missing)

    assert rgb._pid_is_live_owner(1234) is False