"""Windows Raw Input tracker for trusted desk wake devices.

The ordinary activity classifier intentionally keeps using GetLastInputInfo,
which is a global keyboard/mouse idle clock. Sleeping wake authority is
narrower: only intentional input from explicitly trusted desk devices may
prove a human wake. Key-downs and wired-mouse button/scroll actions count;
mouse movement never does. Wireless bed peripherals therefore remain ordinary
activity context but cannot wake Sleeping.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("home_hub.pc_agent.trusted_input")

TRUSTED_WAKE_DEVICE_IDS = {
    "VID_05AC&PID_024F": "keychron_k10",
    "VID_258A&PID_0036": "wired_gaming_mouse",
}

WM_INPUT = 0x00FF
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RI_KEY_BREAK = 0x0001
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800
TRUSTED_MOUSE_INTENT_FLAGS = (
    RI_MOUSE_LEFT_BUTTON_DOWN
    | RI_MOUSE_RIGHT_BUTTON_DOWN
    | RI_MOUSE_MIDDLE_BUTTON_DOWN
    | RI_MOUSE_BUTTON_4_DOWN
    | RI_MOUSE_BUTTON_5_DOWN
    | RI_MOUSE_WHEEL
    | RI_MOUSE_HWHEEL
)
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
HID_USAGE_GENERIC_KEYBOARD = 0x06


@dataclass(frozen=True)
class TrustedInputSnapshot:
    idle_seconds: Optional[float]
    valid: bool
    device: Optional[str]


def trusted_wake_device_label(device_name: str | None) -> Optional[str]:
    """Map a Raw Input device path to the approved desk-device label."""
    if not device_name:
        return None
    normalized = device_name.upper()
    for hardware_id, label in TRUSTED_WAKE_DEVICE_IDS.items():
        if hardware_id in normalized:
            return label
    return None


class _RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.wintypes.USHORT),
        ("usUsage", ctypes.wintypes.USHORT),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("hwndTarget", ctypes.wintypes.HWND),
    ]


class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", ctypes.wintypes.DWORD),
        ("dwSize", ctypes.wintypes.DWORD),
        ("hDevice", ctypes.wintypes.HANDLE),
        ("wParam", ctypes.wintypes.WPARAM),
    ]


class _RAWMOUSEBUTTONPAIR(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", ctypes.wintypes.USHORT),
        ("usButtonData", ctypes.wintypes.USHORT),
    ]


class _RAWMOUSEBUTTONS(ctypes.Union):
    _fields_ = [
        ("ulButtons", ctypes.wintypes.ULONG),
        ("pair", _RAWMOUSEBUTTONPAIR),
    ]


class _RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("buttons",)
    _fields_ = [
        ("usFlags", ctypes.wintypes.USHORT),
        ("buttons", _RAWMOUSEBUTTONS),
        ("ulRawButtons", ctypes.wintypes.ULONG),
        ("lLastX", ctypes.wintypes.LONG),
        ("lLastY", ctypes.wintypes.LONG),
        ("ulExtraInformation", ctypes.wintypes.ULONG),
    ]


class _RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", ctypes.wintypes.USHORT),
        ("Flags", ctypes.wintypes.USHORT),
        ("Reserved", ctypes.wintypes.USHORT),
        ("VKey", ctypes.wintypes.USHORT),
        ("Message", ctypes.wintypes.UINT),
        ("ExtraInformation", ctypes.wintypes.ULONG),
    ]


def trusted_mouse_flags_are_intentional(button_flags: int) -> bool:
    """Mouse motion alone is weak; button-down and wheel input are intentional."""
    return bool(button_flags & TRUSTED_MOUSE_INTENT_FLAGS)


def trusted_keyboard_event_is_intentional(
    *, flags: int, vkey: int, message: int,
) -> bool:
    """Require a real key-down message, not a generic keyboard HID packet."""
    return bool(
        not (flags & RI_KEY_BREAK)
        and vkey not in {0, 0xFF}
        and message in {WM_KEYDOWN, WM_SYSKEYDOWN}
    )


_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

_WNDPROC = _WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


def _configure_user32(user32) -> None:
    """Declare pointer-width-safe Win32 signatures used by the listener."""
    user32.DefWindowProcW.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.restype = ctypes.wintypes.HWND
    user32.GetRawInputData.argtypes = [
        ctypes.c_void_p, ctypes.wintypes.UINT, ctypes.c_void_p,
        ctypes.POINTER(ctypes.wintypes.UINT), ctypes.wintypes.UINT,
    ]
    user32.GetRawInputData.restype = ctypes.wintypes.UINT
    user32.GetRawInputDeviceInfoW.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.UINT, ctypes.c_void_p,
        ctypes.POINTER(ctypes.wintypes.UINT),
    ]
    user32.GetRawInputDeviceInfoW.restype = ctypes.wintypes.UINT


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("hCursor", ctypes.wintypes.HANDLE),
        ("hbrBackground", ctypes.wintypes.HANDLE),
        ("lpszMenuName", ctypes.wintypes.LPCWSTR),
        ("lpszClassName", ctypes.wintypes.LPCWSTR),
    ]


class TrustedWakeInputTracker:
    """Background Raw Input listener for the approved wired desk devices."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_input_monotonic: Optional[float] = None
        self._last_device: Optional[str] = None
        self._active = False
        self._thread_id: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._device_cache: dict[int, Optional[str]] = {}
        self._wndproc_ref = None

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        if self._thread and self._thread.is_alive():
            return self._active
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._message_loop,
            name="homehub-trusted-input",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self._active

    def close(self) -> None:
        thread_id = self._thread_id
        if sys.platform == "win32" and thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def snapshot(self) -> TrustedInputSnapshot:
        with self._lock:
            active = self._active
            last_input = self._last_input_monotonic
            device = self._last_device
        if not active:
            return TrustedInputSnapshot(None, False, None)
        if last_input is None:
            return TrustedInputSnapshot(None, True, None)
        return TrustedInputSnapshot(
            max(0.0, time.monotonic() - last_input),
            True,
            device,
        )

    def _set_active(self, active: bool) -> None:
        with self._lock:
            self._active = active
        self._ready.set()

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        _configure_user32(user32)
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"HomeHubTrustedInput_{self._thread_id}"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                self._handle_raw_input(lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = _WNDPROC(wndproc)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinstance
        wc.lpszClassName = class_name

        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            logger.warning("Raw Input wake tracker could not register window class")
            self._set_active(False)
            return

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "HomeHub Trusted Input",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            logger.warning("Raw Input wake tracker could not create hidden window")
            user32.UnregisterClassW(class_name, hinstance)
            self._set_active(False)
            return

        devices = (_RAWINPUTDEVICE * 2)(
            _RAWINPUTDEVICE(
                HID_USAGE_PAGE_GENERIC,
                HID_USAGE_GENERIC_MOUSE,
                RIDEV_INPUTSINK,
                hwnd,
            ),
            _RAWINPUTDEVICE(
                HID_USAGE_PAGE_GENERIC,
                HID_USAGE_GENERIC_KEYBOARD,
                RIDEV_INPUTSINK,
                hwnd,
            ),
        )
        if not user32.RegisterRawInputDevices(
            devices,
            len(devices),
            ctypes.sizeof(_RAWINPUTDEVICE),
        ):
            logger.warning("Raw Input wake tracker registration failed")
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, hinstance)
            self._set_active(False)
            return

        logger.info("Trusted Raw Input wake tracker active")
        self._set_active(True)
        msg = ctypes.wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            with self._lock:
                self._active = False
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, hinstance)

    def _handle_raw_input(self, raw_handle: int) -> None:
        user32 = ctypes.windll.user32
        _configure_user32(user32)
        size = ctypes.wintypes.UINT(0)
        header_size = ctypes.sizeof(_RAWINPUTHEADER)
        result = user32.GetRawInputData(
            ctypes.c_void_p(raw_handle),
            RID_INPUT,
            None,
            ctypes.byref(size),
            header_size,
        )
        if result == 0xFFFFFFFF or size.value < header_size:
            return
        buffer = ctypes.create_string_buffer(size.value)
        result = user32.GetRawInputData(
            ctypes.c_void_p(raw_handle),
            RID_INPUT,
            buffer,
            ctypes.byref(size),
            header_size,
        )
        if result == 0xFFFFFFFF:
            return
        header = ctypes.cast(buffer, ctypes.POINTER(_RAWINPUTHEADER)).contents
        if header.dwType == RIM_TYPEMOUSE:
            mouse = ctypes.cast(
                ctypes.byref(buffer, header_size), ctypes.POINTER(_RAWMOUSE),
            ).contents
            if not trusted_mouse_flags_are_intentional(mouse.pair.usButtonFlags):
                return
        elif header.dwType == RIM_TYPEKEYBOARD:
            keyboard = ctypes.cast(
                ctypes.byref(buffer, header_size), ctypes.POINTER(_RAWKEYBOARD),
            ).contents
            if not trusted_keyboard_event_is_intentional(
                flags=keyboard.Flags,
                vkey=keyboard.VKey,
                message=keyboard.Message,
            ):
                return
        else:
            return
        device_key = int(header.hDevice or 0)
        if not device_key:
            return
        label = self._device_cache.get(device_key)
        if device_key not in self._device_cache:
            label = trusted_wake_device_label(self._device_name(header.hDevice))
            self._device_cache[device_key] = label
        if label is None:
            return
        with self._lock:
            self._last_input_monotonic = time.monotonic()
            self._last_device = label

    @staticmethod
    def _device_name(device_handle) -> Optional[str]:
        user32 = ctypes.windll.user32
        _configure_user32(user32)
        chars = ctypes.wintypes.UINT(0)
        result = user32.GetRawInputDeviceInfoW(
            device_handle,
            RIDI_DEVICENAME,
            None,
            ctypes.byref(chars),
        )
        if result == 0xFFFFFFFF or chars.value == 0:
            return None
        buffer = ctypes.create_unicode_buffer(chars.value + 1)
        result = user32.GetRawInputDeviceInfoW(
            device_handle,
            RIDI_DEVICENAME,
            buffer,
            ctypes.byref(chars),
        )
        if result == 0xFFFFFFFF:
            return None
        return buffer.value