"""Non-actuating Windows run-as and Vault-owner evidence for #399.

SID/owner checks are necessary evidence, NOT proof that the effective Windows
DACL, app coordination, or stable handle identities permit unattended writes.
This code never changes ACLs, opens a Vault for writing, or authorizes refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Callable

from manage_obsidian_vault import MANAGED, reject_link

SID = re.compile(r"S-1-[0-9]+(?:-[0-9]+){1,14}\Z")


@dataclass(frozen=True)
class IdentityEvidence:
    state: str  # "matched", "refused", or "unknown"
    reason: str
    process_sid_matches: bool | None = None
    vault_owner_matches: bool | None = None
    managed_owner_matches: bool | None = None
    process_elevated: bool | None = None
    dacl_evaluated: bool = False
    process_launch_coordinated: bool = False
    authorizes_host_refresh: bool = False


def _sid_string(sid_pointer: int) -> str:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    result = ctypes.c_wchar_p()
    if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), "sid_conversion_failed")
    try:
        return result.value
    finally:
        kernel.LocalFree(ctypes.cast(result, ctypes.c_void_p))


def _windows_current_identity() -> tuple[str, bool]:
    """Read the primary process token; no privilege changes."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi.GetTokenInformation.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "open_process_token_failed")
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 8 <= size.value <= 4096:
            raise ValueError("invalid_token_user_buffer")
        raw = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, raw, size.value, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "get_token_user_failed")
        pointer = ctypes.cast(raw, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not pointer:
            raise ValueError("token_user_sid_missing")
        sid = _sid_string(pointer)
        elevated = wintypes.DWORD()
        if not advapi.GetTokenInformation(
            token, 20, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)
        ):
            raise OSError(ctypes.get_last_error(), "get_token_elevation_failed")
        if elevated.value not in (0, 1):
            raise ValueError("unexpected_elevation_state")
        return sid, bool(elevated.value)
    finally:
        kernel.CloseHandle(token)


def _windows_path_owner(path: Path) -> str:
    """Read only OWNER_SECURITY_INFORMATION for an exact existing path."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    )
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    err = advapi.GetNamedSecurityInfoW(
        str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)
    )
    if err != 0:
        raise OSError(err, "vault_owner_unavailable")
    try:
        if not owner.value:
            raise ValueError("vault_owner_missing")
        return _sid_string(owner.value)
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)


def inspect_host_identity_readonly(
    *,
    vault: Path,
    expected_vault: Path,
    expected_user_sid: str,
    current_identity: Callable[[], tuple[str, bool]] = _windows_current_identity,
    path_owner: Callable[[Path], str] = _windows_path_owner,
) -> IdentityEvidence:
    """Require exact path/owner/user identity, abstain on uncertainty.

    No 'matched' outcome is authorization: full effective ACL/reparse/TOCTOU
    analysis and Obsidian launch coordination remain separate host gates.
    """
    if (
        not isinstance(vault, Path) or not isinstance(expected_vault, Path)
        or not vault.is_absolute() or vault == vault.parent
        or vault != expected_vault
        or not isinstance(expected_user_sid, str) or not SID.fullmatch(expected_user_sid)
    ):
        return IdentityEvidence("refused", "invalid_exact_host_contract")
    if os.name != "nt":
        return IdentityEvidence("unknown", "not_windows")
    try:
        for path in (vault, *vault.parents, vault / MANAGED):
            reject_link(path)
        managed = vault / MANAGED
        if not vault.is_dir() or not managed.is_dir():
            return IdentityEvidence("refused", "vault_or_managed_missing")
        user_sid, elevated = current_identity()
        vault_sid = path_owner(vault)
        managed_sid = path_owner(managed)
        if not all(isinstance(x, str) and SID.fullmatch(x) for x in
                   (user_sid, vault_sid, managed_sid)):
            return IdentityEvidence("unknown", "malformed_security_identity")
        user_match = user_sid == expected_user_sid
        vault_match = vault_sid == expected_user_sid
        managed_match = managed_sid == expected_user_sid
        if elevated or not (user_match and vault_match and managed_match):
            return IdentityEvidence(
                "refused", "elevated_or_identity_owner_mismatch",
                user_match, vault_match, managed_match, elevated,
            )
        return IdentityEvidence("matched", "owner_and_token_match_acl_not_evaluated",
                                True, True, True, False)
    except Exception:
        return IdentityEvidence("unknown", "host_security_observation_unavailable")
