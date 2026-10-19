"""Pinned in-process scheduled mirror launcher; inert unless --run is explicit."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import ctypes
from hashlib import sha256
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat

SOURCE_COMMIT = "f91407d165fd1263319bbadc45586da3681560aa"
MODULES = (
    "create_obsidian_pilot", "manage_obsidian_vault", "obsidian_github_docs_source",
    "obsidian_raw_blob_transport", "obsidian_simple_mirror", "obsidian_source_verifier",
    "obsidian_verified_stage", "run_obsidian_simple_mirror",
)
FILES = {name + ".py" for name in MODULES} | {"launch_obsidian_mirror.py"}
HEX = re.compile(r"[0-9a-f]{64}")


class QuietArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def digest(data):
    return sha256(data).hexdigest()


def read_small(path, limit=2 * 1024 * 1024):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("oversized_bundle_file")
    return raw


def file_digest(path):
    h = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def exact(raw):
    if not isinstance(raw, str):
        raise ValueError("path")
    p = PureWindowsPath(raw)
    if (str(p) != raw or not re.fullmatch(r"[A-Z]:\\", p.anchor)
            or any(part.endswith((".", " ")) or part in {".", ".."}
                   or any(c in part for c in '<>:"|?*%~$`')
                   or any(ord(c) < 32 for c in part)
                   or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                   for part in p.parts[1:])):
        raise ValueError("path")
    return p


def validate_spec(spec):
    if set(spec) != {"source_commit", "user_root", "sid", "bundle", "python",
                     "python_sha256", "vault", "files"}:
        raise ValueError("schema")
    root, bundle, python, vault = [exact(spec[k]) for k in
                                   ("user_root", "bundle", "python", "vault")]
    if (spec["source_commit"] != SOURCE_COMMIT or len(root.parts) != 3
            or root.parts[1] != "Users" or root.name.lower() in {"public", "default", "all users"}
            or str(bundle) != str(root / "AppData" / "Local" / "HomeHub" /
                                  "ObsidianMirror" / SOURCE_COMMIT)
            or not python.is_relative_to(root) or python.name != "python.exe"
            or any(x.lower() in {"worktrees", ".git"} for x in python.parts)
            or not vault.is_relative_to(root) or vault == root
            or vault.is_relative_to(bundle) or bundle.is_relative_to(vault)
            or not re.fullmatch(r"S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}", spec["sid"])
            or not HEX.fullmatch(spec["python_sha256"])
            or set(spec["files"]) != FILES
            or any(not HEX.fullmatch(v) for v in spec["files"].values())):
        raise ValueError("binding")
    return spec


def plain(path):
    for p in (path, *path.parents):
        info = p.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
            raise ValueError("reparse")


def windows_identity():
    """Read current process token and actual profile; no environment identity trust."""
    if os.name != "nt":
        raise ValueError("windows_required")
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ValueError("token")
    try:
        def info(kind):
            size = wintypes.DWORD()
            adv.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(token, kind, buf, size, ctypes.byref(size)):
                raise ValueError("token_info")
            return buf
        user_info = info(1)  # Keep TOKEN_USER buffer alive through SID conversion.
        sid_pointer = ctypes.cast(user_info, ctypes.POINTER(ctypes.c_void_p))[0]
        sid = wintypes.LPWSTR()
        if not adv.ConvertSidToStringSidW(ctypes.c_void_p(sid_pointer), ctypes.byref(sid)):
            raise ValueError("sid")
        try:
            sid_text = sid.value
        finally:
            kernel.LocalFree(ctypes.cast(sid, ctypes.c_void_p))
        elevated = ctypes.cast(info(20), ctypes.POINTER(wintypes.DWORD))[0]
        session = ctypes.cast(info(12), ctypes.POINTER(wintypes.DWORD))[0]
        size = wintypes.DWORD(32768)
        profile = ctypes.create_unicode_buffer(size.value)
        if not userenv.GetUserProfileDirectoryW(token, profile, ctypes.byref(size)):
            raise ValueError("profile")
        return sid_text, profile.value, bool(elevated), session
    finally:
        kernel.CloseHandle(token)


class VerifiedModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Execute verified bytes, never re-open local modules after validation."""
    def __init__(self, blobs):
        self.blobs = blobs

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.blobs:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = "<verified-bundle>/" + module.__name__ + ".py"
        exec(compile(self.blobs[module.__name__], module.__file__, "exec"), module.__dict__)


def verified_bundle(bundle, anchor):
    if not HEX.fullmatch(anchor):
        raise ValueError("anchor")
    plain(bundle)
    manifest = bundle / "manifest.json"
    plain(manifest)
    raw = read_small(manifest, 16384)
    if len(raw) > 16384 or digest(raw) != anchor:
        raise ValueError("manifest_pin")
    spec = validate_spec(json.loads(raw))
    if str(bundle) != spec["bundle"] or str(Path(__file__)) != str(bundle / "launch_obsidian_mirror.py"):
        raise ValueError("stable_path")
    sid, profile, elevated, session = windows_identity()
    if (sid != spec["sid"] or profile != spec["user_root"] or elevated or not session):
        raise ValueError("identity")
    if str(Path(sys.executable)) != spec["python"]:
        raise ValueError("interpreter_path")
    python = Path(spec["python"])
    plain(python)
    if file_digest(python) != spec["python_sha256"]:
        raise ValueError("interpreter_pin")
    if {p.name for p in bundle.iterdir()} != FILES | {"manifest.json"}:
        raise ValueError("membership")
    blobs = {}
    for name, expected in spec["files"].items():
        p = bundle / name
        plain(p)
        data = read_small(p)
        if digest(data) != expected:
            raise ValueError("module_pin")
        if name != "launch_obsidian_mirror.py":
            blobs[name[:-3]] = data
    return spec, blobs


class StatusOnly:
    """Discard incidental output; runner's explicit report uses a separate sink."""
    def write(self, value):
        return len(value)

    def flush(self):
        pass


class BoundedReport:
    def __init__(self):
        self.value = ""

    def write(self, value):
        if len(self.value) + len(value) > 512:
            raise ValueError("output_bound")
        self.value += value
        return len(value)


def invoke_once(spec, blobs):
    from contextlib import redirect_stdout, redirect_stderr
    if any(name in sys.modules for name in MODULES):
        raise ValueError("preloaded_module")
    loader = VerifiedModules(blobs)
    sys.meta_path.insert(0, loader)
    try:
        with redirect_stdout(StatusOnly()), redirect_stderr(StatusOnly()):
            import run_obsidian_simple_mirror as runner
            report = BoundedReport()
            code = runner.main(["--apply", "--approve-local-evaluation", "--vault",
                                spec["vault"], "--expected-vault", spec["vault"]], output=report)
        parsed = json.loads(report.value)
        allowed = {0: {"no_change", "updated"}, 2: {"refused_or_failed_review_evidence"},
                   3: {"source_unavailable"}, 4: {"operation_failed_review_evidence"}}
        if code not in allowed or parsed.get("status") not in allowed[code]:
            raise ValueError("output_status")
        keys = {"status", "commit", "previous_commit"} if code == 0 else {"status"}
        if set(parsed) != keys or (code == 0 and any(
                not re.fullmatch(r"[0-9a-f]{40}", parsed[k]) for k in keys - {"status"})):
            raise ValueError("output_fields")
        return code, parsed
    finally:
        sys.meta_path.remove(loader)
        for name in MODULES:
            sys.modules.pop(name, None)


def main(argv=None, *, output=None):
    parser = QuietArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--anchor")
    try:
        args = parser.parse_args(argv)
    except ValueError:
        print('{"status":"launcher_refused_review_evidence"}', file=output or sys.stdout)
        return 2
    result, code = {"status": "off"}, 0
    if args.run or args.anchor:
        try:
            if not args.run or not args.anchor or not sys.flags.isolated or not sys.dont_write_bytecode:
                raise ValueError("explicit_isolated_run_required")
            spec, blobs = verified_bundle(Path(__file__).parent, args.anchor)
            code, result = invoke_once(spec, blobs)
        except Exception:
            code, result = 2, {"status": "launcher_refused_review_evidence"}
    print(json.dumps(result, sort_keys=True), file=output or sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
