"""Read-only profile AND endpoint-bound credentials. No provisioning authority."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ipaddress
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


def _endpoint(url: str) -> tuple[str, str]:
    """Strict ASCII URI; only omitted default ports are normalized.

    Reject alternate spellings rather than relying on URL/OS/IDNA normalization.
    The target includes the effective port even when omitted in the URI.
    """
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        raise ValueError
    match = re.fullmatch(r'(ws|wss)://(\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::([0-9]+))?/ws', url)
    if match is None:
        raise ValueError
    scheme, host, port_text = match.groups()
    if host.startswith('['):
        address = ipaddress.IPv6Address(host[1:-1])
        if host != '[' + address.compressed + ']':
            raise ValueError
    else:
        if len(host) > 253 or any(
            not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            or label.startswith('xn--') for label in host.split('.')
        ):
            raise ValueError
        # Numeric addresses must be canonical IPv4, never legacy numeric forms.
        if re.fullmatch(r'[0-9.]+', host):
            if str(ipaddress.IPv4Address(host)) != host:
                raise ValueError
    port = int(port_text) if port_text else (443 if scheme == 'wss' else 80)
    if not 1 <= port <= 65535 or (port_text and str(port) != port_text):
        raise ValueError
    # Independent parser agreement guards future changes to either parser.
    parsed = urlsplit(url)
    if parsed.hostname != host.strip('[]') or parsed.path != '/ws':
        raise ValueError
    return scheme, f'{host}:{port}/ws'


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
        scheme, endpoint = _endpoint(url)
    except Exception:
        raise NativeCredentialError("endpoint denied") from None
    options = {"logger": WS_LOGGER}
    if scheme == "ws":
        return options  # Legacy plaintext must NEVER touch the credential store.
    token = None
    failed = False
    try:
        if sys.platform == "win32":
            token = _read_windows(_TARGETS[profile] + '/' + endpoint)
    except Exception:
        failed = True
    # Raise outside the handler so the original secret-bearing exception is discarded.
    if failed:
        raise NativeCredentialError("credential unavailable")
    if token is None:
        return options
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise NativeCredentialError("credential invalid")
    options["additional_headers"] = {"Authorization": "Bearer " + token}
    return options
