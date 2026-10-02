"""Trusted Windows Sandbox guest broker for navigation-v1 replay."""

from __future__ import annotations

import ctypes
import hashlib
import json
import msvcrt
import os
import shutil
import subprocess
import threading
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any

STAGE_ROOT = Path(r"C:\HomeHubReplayStage")
LOCAL_STAGE_ROOT = Path(r"C:\HomeHubReplayLocal")
STATE_ROOT = Path(r"C:\HomeHubReplayState")
STATUS_PATH = STATE_ROOT / "status.json"
RESULT_PATH = STATE_ROOT / "result.json"
DONE_PATH = STATE_ROOT / "done.marker"

MAX_RESULT_BYTES = 8 * 1024 * 1024
CHILD_TIMEOUT_MS = 60_000
RESULT_SCHEMA_ID = "homehub.replay.navigation.result.v1"

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY = 0x00020007
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = 0x0002000E
PROCESS_CREATION_CHILD_PROCESS_RESTRICTED = 0x01
PROCESS_CREATION_MITIGATION_POLICY_WIN32K_SYSTEM_CALL_DISABLE_ALWAYS_ON = 0x10000000
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
HANDLE_FLAG_INHERIT = 0x00000001
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

LPVOID = wintypes.LPVOID
DWORD = wintypes.DWORD
SIZE_T = ctypes.c_size_t
HANDLE = wintypes.HANDLE
BOOL = wintypes.BOOL


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", LPVOID),
        ("bInheritHandle", BOOL),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", LPVOID), ("Attributes", DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", LPVOID),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", DWORD),
        ("Reserved", DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


userenv.CreateAppContainerProfile.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.POINTER(SID_AND_ATTRIBUTES),
    DWORD,
    ctypes.POINTER(LPVOID),
]
userenv.CreateAppContainerProfile.restype = ctypes.c_long
userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
userenv.DeleteAppContainerProfile.restype = ctypes.c_long
advapi32.ConvertSidToStringSidW.argtypes = [
    LPVOID,
    ctypes.POINTER(wintypes.LPWSTR),
]
advapi32.ConvertSidToStringSidW.restype = BOOL
advapi32.FreeSid.argtypes = [LPVOID]
kernel32.LocalFree.argtypes = [LPVOID]
kernel32.InitializeProcThreadAttributeList.argtypes = [
    LPVOID,
    DWORD,
    DWORD,
    ctypes.POINTER(SIZE_T),
]
kernel32.InitializeProcThreadAttributeList.restype = BOOL
kernel32.UpdateProcThreadAttribute.argtypes = [
    LPVOID,
    DWORD,
    SIZE_T,
    LPVOID,
    SIZE_T,
    LPVOID,
    ctypes.POINTER(SIZE_T),
]
kernel32.UpdateProcThreadAttribute.restype = BOOL
kernel32.DeleteProcThreadAttributeList.argtypes = [LPVOID]
kernel32.CreatePipe.argtypes = [
    ctypes.POINTER(HANDLE),
    ctypes.POINTER(HANDLE),
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    DWORD,
]
kernel32.CreatePipe.restype = BOOL
kernel32.SetHandleInformation.argtypes = [HANDLE, DWORD, DWORD]
kernel32.SetHandleInformation.restype = BOOL
kernel32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    LPVOID,
    LPVOID,
    BOOL,
    DWORD,
    LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = BOOL
kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
kernel32.WaitForSingleObject.restype = DWORD
kernel32.GetExitCodeProcess.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
kernel32.GetExitCodeProcess.restype = BOOL
kernel32.TerminateProcess.argtypes = [HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = BOOL
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = BOOL


def _check(ok: Any, label: str) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error(), label)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_stage(root: Path) -> None:
    manifest_path = root / "stage_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_id") != "homehub.replay.stage.v1":
        raise RuntimeError("unexpected replay stage manifest schema")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError("replay stage manifest has no files")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_paths != set(expected):
        raise RuntimeError("replay stage member set changed after staging")

    for relative, expected_hash in expected.items():
        path = root / Path(relative)
        if _sha256(path) != expected_hash:
            raise RuntimeError(f"replay stage hash mismatch: {relative}")


def _read_pipe(read_handle: HANDLE, output: dict[str, Any]) -> None:
    fd = msvcrt.open_osfhandle(int(read_handle.value), os.O_RDONLY)
    try:
        with os.fdopen(fd, "rb", closefd=True) as stream:
            data = stream.read(MAX_RESULT_BYTES + 1)
        if len(data) > MAX_RESULT_BYTES:
            output["error"] = "child result exceeded size limit"
        else:
            output["data"] = data
    except BaseException as exc:
        output["error"] = f"{type(exc).__name__}: {exc}"


def _grant_appcontainer_rx(root: Path, sid_text: str) -> None:
    completed = subprocess.run(
        [
            "icacls",
            str(root),
            "/grant",
            f"*{sid_text}:(OI)(CI)(RX)",
            "/T",
            "/C",
            "/Q",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to grant replay AppContainer RX access: "
            + (completed.stderr or completed.stdout).strip()
        )


def _deny_appcontainer_access(root: Path, sid_text: str) -> None:
    if not root.exists():
        return
    completed = subprocess.run(
        [
            "icacls",
            str(root),
            "/deny",
            f"*{sid_text}:(OI)(CI)(F)",
            "/T",
            "/C",
            "/Q",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to deny replay AppContainer control-plane access: "
            + (completed.stderr or completed.stdout).strip()
        )


def _run_child(local_stage: Path) -> tuple[int, bytes]:
    runtime = local_stage / "runtime"
    child_script = local_stage / "project" / "backend" / "replay" / "isolated_child.py"
    bundle_dir = local_stage / "bundle"
    pythonw = runtime / "pythonw.exe"
    if not pythonw.is_file() or not child_script.is_file() or not bundle_dir.is_dir():
        raise RuntimeError("replay stage lacks runtime, child, or bundle")

    identity = f"HomeHubReplay_{uuid.uuid4().hex}"
    app_sid = LPVOID()
    hr = userenv.CreateAppContainerProfile(
        identity,
        identity,
        "HomeHub navigation replay",
        None,
        0,
        ctypes.byref(app_sid),
    )
    if hr != 0:
        raise OSError(f"CreateAppContainerProfile failed HRESULT=0x{hr & 0xFFFFFFFF:08x}")

    sid_string = wintypes.LPWSTR()
    attr_ptr = None
    read_handle = HANDLE()
    write_handle = HANDLE()
    process_handle = HANDLE()
    try:
        _check(
            advapi32.ConvertSidToStringSidW(
                app_sid,
                ctypes.byref(sid_string),
            ),
            "ConvertSidToStringSidW",
        )
        sid_text = sid_string.value
        kernel32.LocalFree(sid_string)
        sid_string = None
        _grant_appcontainer_rx(local_stage, sid_text)
        _deny_appcontainer_access(STATE_ROOT, sid_text)

        security_attributes = SECURITY_ATTRIBUTES(
            ctypes.sizeof(SECURITY_ATTRIBUTES),
            None,
            True,
        )
        _check(
            kernel32.CreatePipe(
                ctypes.byref(read_handle),
                ctypes.byref(write_handle),
                ctypes.byref(security_attributes),
                0,
            ),
            "CreatePipe",
        )
        _check(
            kernel32.SetHandleInformation(
                read_handle,
                HANDLE_FLAG_INHERIT,
                0,
            ),
            "SetHandleInformation",
        )

        attr_size = SIZE_T()
        kernel32.InitializeProcThreadAttributeList(
            None,
            4,
            0,
            ctypes.byref(attr_size),
        )
        attr_buffer = ctypes.create_string_buffer(attr_size.value)
        attr_ptr = ctypes.cast(attr_buffer, LPVOID)
        _check(
            kernel32.InitializeProcThreadAttributeList(
                attr_ptr,
                4,
                0,
                ctypes.byref(attr_size),
            ),
            "InitializeProcThreadAttributeList",
        )

        security_caps = SECURITY_CAPABILITIES(app_sid, None, 0, 0)
        child_policy = DWORD(PROCESS_CREATION_CHILD_PROCESS_RESTRICTED)
        mitigation = ctypes.c_ulonglong(
            PROCESS_CREATION_MITIGATION_POLICY_WIN32K_SYSTEM_CALL_DISABLE_ALWAYS_ON
        )
        handles = (HANDLE * 1)(write_handle)
        _check(
            kernel32.UpdateProcThreadAttribute(
                attr_ptr,
                0,
                PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security_caps),
                ctypes.sizeof(security_caps),
                None,
                None,
            ),
            "security capabilities",
        )
        _check(
            kernel32.UpdateProcThreadAttribute(
                attr_ptr,
                0,
                PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,
                ctypes.byref(child_policy),
                ctypes.sizeof(child_policy),
                None,
                None,
            ),
            "child process policy",
        )
        _check(
            kernel32.UpdateProcThreadAttribute(
                attr_ptr,
                0,
                PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY,
                ctypes.byref(mitigation),
                ctypes.sizeof(mitigation),
                None,
                None,
            ),
            "Win32k mitigation",
        )
        _check(
            kernel32.UpdateProcThreadAttribute(
                attr_ptr,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.cast(handles, LPVOID),
                ctypes.sizeof(handles),
                None,
                None,
            ),
            "handle list",
        )

        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        startup.lpAttributeList = attr_ptr
        process_info = PROCESS_INFORMATION()
        command = ctypes.create_unicode_buffer(
            f'"{pythonw}" -I -S -B "{child_script}" {int(write_handle.value)} "{bundle_dir}"'
        )
        _check(
            kernel32.CreateProcessW(
                str(pythonw),
                command,
                None,
                None,
                True,
                EXTENDED_STARTUPINFO_PRESENT,
                None,
                str(local_stage),
                ctypes.cast(
                    ctypes.byref(startup),
                    ctypes.POINTER(STARTUPINFOW),
                ),
                ctypes.byref(process_info),
            ),
            "CreateProcessW",
        )
        process_handle = process_info.hProcess
        kernel32.CloseHandle(process_info.hThread)
        kernel32.CloseHandle(write_handle)
        write_handle = HANDLE()

        captured: dict[str, Any] = {}
        reader = threading.Thread(
            target=_read_pipe,
            args=(read_handle, captured),
            daemon=True,
        )
        reader.start()
        wait_status = kernel32.WaitForSingleObject(
            process_handle,
            CHILD_TIMEOUT_MS,
        )
        if wait_status == WAIT_TIMEOUT:
            kernel32.TerminateProcess(process_handle, 124)
            kernel32.WaitForSingleObject(process_handle, 5_000)
            raise TimeoutError("isolated replay child exceeded timeout")
        if wait_status != WAIT_OBJECT_0:
            raise RuntimeError(f"unexpected replay child wait status {wait_status}")

        exit_code = DWORD()
        _check(
            kernel32.GetExitCodeProcess(
                process_handle,
                ctypes.byref(exit_code),
            ),
            "GetExitCodeProcess",
        )
        reader.join(timeout=5)
        if reader.is_alive():
            raise RuntimeError("isolated replay result pipe did not close")
        if "error" in captured:
            raise RuntimeError(captured["error"])
        data = captured.get("data", b"")
        if not data:
            raise RuntimeError("isolated replay child produced no result")
        return int(exit_code.value), data
    finally:
        if process_handle:
            kernel32.CloseHandle(process_handle)
        if write_handle:
            kernel32.CloseHandle(write_handle)
        if attr_ptr:
            kernel32.DeleteProcThreadAttributeList(attr_ptr)
        if app_sid:
            advapi32.FreeSid(app_sid)
        userenv.DeleteAppContainerProfile(identity)


def _broker() -> dict[str, Any]:
    if not STAGE_ROOT.is_dir():
        raise RuntimeError("read-only replay stage is not mounted")
    _verify_stage(STAGE_ROOT)

    if LOCAL_STAGE_ROOT.exists() or STATE_ROOT.exists():
        raise RuntimeError("replay guest state unexpectedly already exists")
    shutil.copytree(STAGE_ROOT, LOCAL_STAGE_ROOT)
    _verify_stage(LOCAL_STAGE_ROOT)
    STATE_ROOT.mkdir(parents=False)

    exit_code, raw = _run_child(LOCAL_STAGE_ROOT)
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("isolated replay child returned invalid JSON") from exc
    if result.get("schema_id") != RESULT_SCHEMA_ID:
        raise RuntimeError("isolated replay child returned wrong result schema")

    RESULT_PATH.write_bytes(raw)
    if exit_code != 0 or result.get("status") != "ok":
        return {
            "status": "error",
            "child_exit_code": exit_code,
            "child_status": result.get("status"),
            "message": result.get("message", "isolated replay child failed"),
        }
    return {
        "status": "ok",
        "child_exit_code": exit_code,
        "bundle_id": result.get("bundle_id"),
    }


def main() -> int:
    try:
        status = _broker()
        exit_code = 0 if status["status"] == "ok" else 2
    except BaseException as exc:
        if not STATE_ROOT.exists():
            STATE_ROOT.mkdir(parents=False)
        status = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        exit_code = 2

    _write_json(STATUS_PATH, status)
    DONE_PATH.write_text("done\n", encoding="ascii")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
