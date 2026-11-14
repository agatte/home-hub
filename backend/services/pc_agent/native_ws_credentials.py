"""Read-only, fixed-profile native WS credentials. No provisioning authority.

The operator-configured server URL is trusted configuration, never event input.
Only Windows Generic Credentials at the two exact targets below are read.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import re
import sys
from typing import Literal
from urllib.parse import urlsplit

Profile = Literal["windows_desktop", "desktop_notifier"]
_TARGETS = {
    "windows_desktop": "HomeHub/identity/windows_desktop/ws",
    "desktop_notifier": "HomeHub/identity/desktop_notifier/ws",
}
_TOKEN = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}\Z")
# websockets DEBUG logging includes handshake headers. Never use its default logger.
WS_LOGGER = logging.Logger("homehub.native_ws.private", level=logging.CRITICAL + 1)
WS_LOGGER.addHandler(logging.NullHandler())
WS_LOGGER.propagate = False


class NativeCredentialError(Exception):
    """Static, non-secret failure status; callers must not log underlying errors."""


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _read_windows(target: str) -> str | None:
    # Load the system DLL by trusted System32 search only, not PATH/current directory.
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True, winmode=0x800)
    pointer = ctypes.POINTER(_Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(ctypes.POINTER(_Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND only
            return None
        raise NativeCredentialError("credential unavailable")
    try:
        credential = pointer.contents
        # Provisioning contract: exact UTF-16LE token, no terminator or padding.
        if (credential.Type != 1 or credential.TargetName != target
                or credential.CredentialBlobSize != 152 or not credential.CredentialBlob):
            raise NativeCredentialError("credential invalid")
        return ctypes.string_at(credential.CredentialBlob, 152).decode("utf-16-le")
    finally:
        api.CredFree(pointer)


def connection_options(profile: Profile, url: str) -> dict:
    """Read afresh at each connect. Absence preserves legacy no-header behavior.

    Bad credentials/URLs refuse the attempt, rather than downgrading to anonymous.
    No URL userinfo, query or fragment is accepted, even in legacy mode.
    """
    if profile not in _TARGETS:
        raise NativeCredentialError("profile denied")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"ws", "wss"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in url or "#" in url
                or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
            raise NativeCredentialError("endpoint denied")
        parsed.port  # Validate malformed ports before touching the credential store.
    except Exception:
        raise NativeCredentialError("endpoint denied") from None
    token = None
    failed = False
    try:
        if sys.platform == "win32":
            token = _read_windows(_TARGETS[profile])
    except Exception:
        failed = True
    # Raise outside the handler so the original secret-bearing exception is discarded.
    if failed:
        raise NativeCredentialError("credential unavailable")
    options = {"logger": WS_LOGGER}
    if token is None:
        return options
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise NativeCredentialError("credential invalid")
    if parsed.scheme != "wss":
        raise NativeCredentialError("credential requires TLS")
    options["additional_headers"] = {"Authorization": "Bearer " + token}
    return options
