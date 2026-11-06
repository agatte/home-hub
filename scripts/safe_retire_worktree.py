"""Proposed #504 Sandbox guard. No network or removal without explicit options.

This is not the currently approved worktree-removal procedure. See LOCAL_WORKSPACE.
Never logs Git stderr, file contents, task prompts, or credentials.
"""

import argparse
import contextlib
import ctypes
import getpass
import hashlib
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess

ROOT = Path(r"C:\Work\home-hub-project")
MAIN = ROOT / "main"
RUNS = Path(r"C:\Work\PC-Performance-Audit\.rdc-sandbox-state\codex-runs")
GIT = r"C:\Tools\Git\cmd\git.exe"
SHA = re.compile(r"[0-9a-f]{40}")


class Refused(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise Refused(reason)


def key(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def target_path(raw):
    p = PureWindowsPath(raw)
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", p.name)), "Invalid name")
    require(key(p.parent) == key(ROOT / "worktrees"), "Not a direct Sandbox worktree")
    require(str(p) == raw and ".." not in p.parts, "Noncanonical path")
    return Path(raw)


def no_links(path, tree=False):
    # lstat, never resolve through a reparse point (including junctions/cloud placeholders).
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for item in [*reversed(path.parents), path]:
        s = item.lstat()
        require(not (s.st_file_attributes & reparse), "Reparse path")
        require(not stat.S_ISLNK(s.st_mode), "Symlink path")
    if tree:
        with os.scandir(path) as entries:
            for entry in entries:
                child = Path(entry.path)
                s = child.lstat()
                require(not (s.st_file_attributes & reparse),
                        "Reparse tree entry")
                require(not stat.S_ISLNK(s.st_mode), "Symlink tree entry")
                if stat.S_ISDIR(s.st_mode):
                    no_links(child, tree=True)
                else:
                    require(stat.S_ISREG(s.st_mode), "Special tree entry")


def git(*args, cwd=MAIN):
    require(key(cwd) == key(MAIN)
            or key(PureWindowsPath(str(cwd)).parent) == key(ROOT / "worktrees"),
            "Unexpected Git working directory")
    env = os.environ.copy()
    # Disallow inherited repository/config redirection and external diff programs.
    env = {k: v for k, v in env.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    # Windows mapped repos are owned by the host account, not WDAGUtilityAccount.
    # Scope safe.directory per subprocess, never edit global or repo Git config.
    safe = Path(cwd).as_posix()
    result = subprocess.run(
        [GIT, "-c", "safe.directory=" + safe,
         "-c", "core.fsmonitor=false", "-c", "core.hooksPath=NUL", *args],
        cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        check=False,
    )
    require(result.returncode == 0,
            "Git refused operation; stop, retain evidence; never clean/force/retry removal")
    return result.stdout


def registrations():
    records = git("worktree", "list", "--porcelain", "-z").split(b"\0\0")
    result = {}
    for record in records:
        if not record:
            continue
        fields = record.rstrip(b"\0").split(b"\0")
        require(fields[0].startswith(b"worktree "), "Malformed registration")
        name = key(os.fsdecode(fields[0][9:]))
        require(name not in result, "Duplicate registration")
        result[name] = tuple(fields[1:])
    return result


def registry_clear(target):
    no_links(RUNS)
    require(RUNS.is_dir(), "Task registry unavailable")
    for folder in RUNS.iterdir():
        if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
            require(folder.name == "_startup-failures", "Unknown registry entry")
            continue
        no_links(folder)
        values = []
        for name in ("task.json", "state.json"):
            p = folder / name
            no_links(p)
            values.append(json.loads(p.read_text(encoding="utf-8-sig")))
        task, state = values
        require(isinstance(task, dict) and isinstance(state, dict), "Unparseable registry object")
        require(isinstance(task.get("workdir"), str) and bool(task["workdir"]),
                "Unparseable task workdir")
        require(isinstance(state.get("status"), str), "Unparseable task state")
        # A Write worker may run inside the checkout (e.g. <target>\backend);
        # its launcher lease would hash that subdirectory, not the target root.
        workdir = key(task["workdir"])
        target_key = key(target)
        if workdir == target_key or workdir.startswith(target_key + "\\"):
            require(state["status"] in {"completed", "superseded"}, "Unresolved Codex task")


@contextlib.contextmanager
def lease(target):
    # CodexSandboxTask.ps1 uses OpenOrCreate/FileShare.None on this exact key.
    # Read-mode worktrees may have no lock yet. Create only the lock file, not
    # an arbitrary directory, using OPEN_ALWAYS and OPEN_REPARSE_POINT.
    digest = hashlib.sha256(str(target).lower().encode("utf-8")).hexdigest()
    lock_root = RUNS.parent / "codex-run-locks"
    no_links(lock_root)
    require(lock_root.is_dir(), "Codex lease directory unavailable")
    lock = lock_root / (digest + ".lock")
    if lock.exists() or lock.is_symlink():
        no_links(lock)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(lock), 0xC0000000, 0, None, 4, 0x00200080, None)
    require(handle != ctypes.c_void_p(-1).value, "Codex lease unavailable")
    try:
        no_links(lock)
        yield
    finally:
        kernel.CloseHandle(handle)


def cache_allowed(name):
    parts = name.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        return False
    # Exact generated layouts only; arbitrary files under cache-named dirs are refused.
    if len(parts) >= 2 and parts[-2] == "__pycache__":
        return bool(re.fullmatch(r"[A-Za-z0-9_]+\.cpython-313(?:\.opt-[12])?\.pyc", parts[-1]))
    if name in {".pytest_cache/.gitignore", ".pytest_cache/CACHEDIR.TAG",
                ".pytest_cache/README.md", ".ruff_cache/.gitignore", ".ruff_cache/CACHEDIR.TAG"}:
        return True
    if len(parts) == 4 and parts[:3] == [".pytest_cache", "v", "cache"]:
        return parts[3] in {"nodeids", "lastfailed", "stepwise"}
    return (len(parts) == 3 and parts[0] == ".ruff_cache"
            and bool(re.fullmatch(r"\d+\.\d+\.\d+", parts[1]))
            and bool(re.fullmatch(r"\d+", parts[2])))


def validate(target, head, branch, master):
    before = registrations()
    require(key(MAIN) in before, "Canonical main registration missing")
    record = before.get(key(target), ())
    require(record == (b"HEAD " + head.encode(), b"branch refs/heads/" + branch.encode()),
            "Wrong, locked, prunable, detached or missing target registration")
    no_links(MAIN / ".git")
    require((MAIN / ".git").is_dir(), "Canonical main .git directory required")
    no_links(target, tree=True)
    dotgit = target / ".git"
    require(dotgit.is_file(), "Linked .git file required")
    pointer = dotgit.read_text(encoding="utf-8").strip()
    require(pointer.startswith("gitdir: "), "Malformed .git file")
    admin = PureWindowsPath(pointer[8:])
    require(admin.is_absolute() and key(admin.parent) == key(MAIN / ".git" / "worktrees"),
            "Unexpected linked-worktree administration path")
    no_links(Path(str(admin)), tree=True)
    require(key((Path(str(admin)) / "gitdir").read_text(encoding="utf-8").strip())
            == key(dotgit),
            "Broken worktree backlink")
    common = Path(os.fsdecode(git("rev-parse", "--path-format=absolute", "--git-common-dir",
                                 cwd=target)).strip())
    require(key(common) == key(MAIN / ".git"), "Wrong common Git directory")
    require(key(os.fsdecode(git("rev-parse", "--show-toplevel", cwd=target)).strip())
            == key(target), "Wrong worktree root")
    require(git("rev-parse", "HEAD", cwd=target).strip().decode() == head, "Wrong HEAD")
    require(git("symbolic-ref", "HEAD", cwd=target).strip().decode()
            == "refs/heads/" + branch, "Wrong branch")
    require(not git("status", "--porcelain=v1", "-z", "--untracked-files=all",
                    "--ignore-submodules=none", cwd=target), "Dirty or untracked target")
    # Git status hides working-tree edits for assume-unchanged and skip-worktree
    # index entries. Refuse both (and any unfamiliar ls-files -v tag) rather
    # than trusting a "clean" status for a sparsely populated checkout.
    tracked = git("ls-files", "-v", "-z", cwd=target)
    require(tracked.endswith(b"\0"), "Malformed tracked-file inventory")
    require(all(entry.startswith(b"H ") for entry in tracked[:-1].split(b"\0")),
            "Hidden, sparse or unfamiliar tracked-file index flags")
    ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", "-z", cwd=target)
    require(all(cache_allowed(os.fsdecode(p)) for p in ignored.split(b"\0") if p),
            "Unknown ignored content")
    require(git("rev-parse", "refs/remotes/origin/master").strip().decode() == master,
            "Local origin/master differs from expected master; no automatic fetch")
    git("merge-base", "--is-ancestor", head, master)
    return before, main_snapshot()


def main_snapshot():
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    metadata = []
    for name in sorted(set(names.split(b"\0")) - {b""}):
        path = MAIN / os.fsdecode(name)
        # Do not read file contents (including secrets), nor follow symlinks.
        try:
            s = path.lstat()
            metadata.append((name, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ino))
        except FileNotFoundError:
            metadata.append((name, None))
    return status, hashlib.sha256(repr(metadata).encode()).hexdigest()


def sandbox_guest():
    return os.name == "nt" and getpass.getuser().lower() == "wdagutilityaccount"


def execute(args, emit=print):
    require(sandbox_guest(), "Protected Windows Sandbox guest required")
    target = target_path(args.worktree)
    no_links(MAIN / ".git")
    no_links(target)
    require(SHA.fullmatch(args.expected_head or "") and SHA.fullmatch(args.expected_master or ""),
            "Exact lowercase 40hex HEAD and master required")
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", args.expected_branch or "")),
            "Expected branch required")
    git("check-ref-format", "refs/heads/" + args.expected_branch)
    if args.apply:
        require(args.verify_remote, "Apply requires separately authorized remote read")
    with lease(target) if args.apply else contextlib.nullcontext():
        registry_clear(target)
        before, main_status = validate(target, args.expected_head, args.expected_branch,
                                       args.expected_master)
        if args.verify_remote:
            # Read-only network query; never fetch or change origin refs.
            remote = git("ls-remote", "--exit-code", "origin", "refs/heads/master")
            require(remote == (args.expected_master + "\trefs/heads/master\n").encode(),
                    "Remote master mismatch; local ancestry is stale/unverified")
        emit(json.dumps({"phase": "validated", "head": args.expected_head,
                         "target": str(target), "branch": args.expected_branch,
                         "master": args.expected_master, "registrations": len(before),
                         "remote_verified": args.verify_remote, "apply": args.apply,
                         "registration_digest": hashlib.sha256(repr(before).encode()).hexdigest(),
                         "main_status_digest": hashlib.sha256(repr(main_status).encode()).hexdigest()}))
        if not args.apply:
            emit("DRY-RUN: no removal. Offline ancestry is not remote freshness evidence.")
            return
        registry_clear(target)
        require(validate(target, args.expected_head, args.expected_branch, args.expected_master)
                == (before, main_status), "Preflight changed; stop")
        git("worktree", "remove", str(target))  # Sole destructive operation; NEVER --force.
        after = registrations()
        require(after == {k: v for k, v in before.items() if k != key(target)},
                "Postflight registration mismatch; stop, no rollback/cleanup")
        require(not target.exists(), "Target still exists after removal")
        require(git("rev-parse", "refs/heads/" + args.expected_branch).strip().decode()
                == args.expected_head, "Branch changed; stop")
        require(main_snapshot() == main_status,
                "Main status changed; stop")
        emit("REMOVED: native Git only; branch preserved; registration/main-status checks passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--expected-master", required=True)
    parser.add_argument("--verify-remote", action="store_true",
                        help="Separately authorized read-only ls-remote; never fetch")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        execute(args)
    except Refused as error:
        print("REFUSED: " + str(error))  # Only fixed guard-authored messages.
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        # Exception text can include filenames, remote URLs or registry content. Do not emit it.
        print("REFUSED: validation/Git/I/O failed. No cleanup or automatic retry. "
              "Retain phase evidence; review locally with secrets protected.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
