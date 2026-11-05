"""Windows Sandbox-only synthetic release-bundle staging rehearsal for #489.

This is not a host packager. No CLI, task update, native compilation, install,
Vault access, or host acceptance. It writes *only* a new synthetic fixture under
the WDAGUtilityAccount guest's fixed TEMP directory and preserves failures.
"""
from __future__ import annotations

import ctypes
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile

from prepare_obsidian_relocation import MODULE_FILES, PYTHON, USER
from review_obsidian_relocation_stage import review_offline_stage_plan

GUEST_TEMP = Path(r"C:\Users\WDAGUtilityAccount\AppData\Local\Temp")
SYNTHETIC_IDENTITY = {
    "user_root": USER, "python": PYTHON,
    "sid": "S-1-5-21-111-222-333-1001",
    "python_sha256": "a" * 64,
}
FIXTURE_PREFIX = "hh489-only-synthetic-stage-"
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
EXPECTED_NAMES = frozenset(MODULE_FILES) | {"manifest.json"}


def _guest_token() -> None:
    """Read actual Windows token name, not USERNAME/USERPROFILE environment."""
    if os.name != "nt":
        raise ValueError("sandbox_windows_guest_required")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    get_name = advapi.GetUserNameW
    get_name.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    get_name.restype = ctypes.c_int
    size = ctypes.c_ulong(256)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not get_name(buffer, ctypes.byref(size)) or buffer.value != "WDAGUtilityAccount":
        raise ValueError("sandbox_windows_guest_required")
    if Path(tempfile.gettempdir()) != GUEST_TEMP or Path.home() != GUEST_TEMP.parents[2]:
        raise ValueError("sandbox_fixed_profile_and_temp_required")


def _plain_dir_ancestry(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except OSError as exc:
            raise ValueError("missing_sandbox_temp_ancestor") from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("linked_or_non_directory_ancestor")


def _file_plain_and_exact(path: Path, expected: bytes) -> None:
    data = path.lstat()
    if (
        not stat.S_ISREG(data.st_mode)
        or stat.S_ISLNK(data.st_mode)
        or getattr(data, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        or path.stat().st_size != len(expected)
        or path.read_bytes() != expected
    ):
        raise ValueError("synthetic_stage_file_drift")


def rehearse_exclusive_sandbox_stage(
    old_modules: dict[str, bytes],
    old_pins: bytes,
    old_native: bytes,
    identity: dict[str, str],
    generated: dict,
    *,
    token: str,
    fail_after: int | None = None,
) -> dict:
    """Create exact, exclusive synthetic files in guest TEMP; never host bundle.

    On any failure *after* exclusive directory creation, preserve every file
    and the directory for investigation; never retry in place, replace, or
    clean partial evidence. This is a test fixture, not a security boundary
    granting host writes.
    """
    _guest_token()
    if type(token) is not str or TOKEN.fullmatch(token) is None:
        raise ValueError("synthetic_ticket_invalid")
    if identity != SYNTHETIC_IDENTITY:
        raise ValueError("synthetic_identity_only")
    if fail_after is not None and (type(fail_after) is not int or not 0 <= fail_after < len(EXPECTED_NAMES)):
        raise ValueError("invalid_injected_failure")
    plan = review_offline_stage_plan(old_modules, old_pins, old_native, identity, generated)
    if plan["installable"] is not False or plan["stage_authorized"] is not False:
        raise ValueError("review_did_not_refuse_host_install")
    directory = GUEST_TEMP / (FIXTURE_PREFIX + token)
    _plain_dir_ancestry(GUEST_TEMP)
    if directory.parent != GUEST_TEMP or directory.name != FIXTURE_PREFIX + token:
        raise ValueError("synthetic_destination_binding")
    members = {**generated["modules"], "manifest.json": generated["manifest"]}
    plan_members = {x["name"]: x for x in plan["members"]}
    if set(members) != EXPECTED_NAMES or set(plan_members) != EXPECTED_NAMES:
        raise ValueError("synthetic_membership")
    for name, data in members.items():
        if (
            type(data) is not bytes
            or "/" in name or "\\" in name or name.startswith(".")
            or sha256(data).hexdigest() != plan_members[name]["sha256"]
            or len(data) != plan_members[name]["byte_count"]
        ):
            raise ValueError("synthetic_plan_pin")
    # Exclusive mkdir refuses an occupied fixture path, with no deletion.
    # This is NOT a security guarantee against concurrent path replacement.
    directory.mkdir(exist_ok=False)
    created = 0
    for name in sorted(members):
        if created == fail_after:
            raise ValueError("synthetic_injected_failure_preserves_partial")
        dest = directory / name
        with dest.open("xb") as stream:
            stream.write(members[name])
            stream.flush()
            os.fsync(stream.fileno())
        _file_plain_and_exact(dest, members[name])
        created += 1
    if {p.name for p in directory.iterdir()} != EXPECTED_NAMES:
        raise ValueError("synthetic_stage_unexpected_membership")
    for name, data in members.items():
        _file_plain_and_exact(directory / name, data)
    return {
        "status": "SANDBOX_FIXTURE_ONLY",
        "files_written": created,
        "content_sha256": plan["manifest_sha256"],
        "installable": False,
        "host_stage_authorized": False,
        "task_update_authorized": False,
        "vault_move_authorized": False,
    }
