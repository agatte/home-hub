"""Offline safety contracts: all filesystem, registry, network/removal calls mocked."""

import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location(
    "retire", Path(__file__).parents[1] / "scripts" / "safe_retire_worktree.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
NATIVE_GIT = guard.git
TARGET = r"C:\Work\home-hub-project\worktrees\test-504"
HEAD = "a" * 40
MASTER = "b" * 40
BRANCH = "work/test-504"


def args(**changes):
    values = dict(worktree=TARGET, expected_head=HEAD, expected_master=MASTER,
                  expected_branch=BRANCH, apply=False, verify_remote=False)
    values.update(changes)
    return argparse.Namespace(**values)


class PathTests(unittest.TestCase):
    def test_only_direct_fixed_root(self):
        self.assertEqual(str(guard.target_path(TARGET)), TARGET)
        for path in [r"C:\Work\home-hub-project", r"C:\Work\home-hub-project\main",
                     r"C:\Users\Anthony\Documents\home-hub-project\worktrees\x",
                     r"D:\Work\home-hub-project\worktrees\x", TARGET + r"\child",
                     TARGET + r"\..\other", r"worktrees\x", TARGET + ".",
                     TARGET + ":stream", r"\\?\C:\Work\home-hub-project\worktrees\x"]:
            with self.subTest(path=path), self.assertRaises(guard.Refused):
                guard.target_path(path)

    def test_links_refused_in_ancestors_and_tree(self):
        normal = MagicMock(st_file_attributes=0, st_mode=stat.S_IFDIR)
        reparse = MagicMock(st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
                            st_mode=stat.S_IFDIR)
        with patch.object(Path, "lstat", return_value=reparse):
            with self.assertRaises(guard.Refused):
                guard.no_links(Path(TARGET))
        entry = MagicMock(path=TARGET + r"\linked")
        def lstat_for_link(path):
            return reparse if str(path).endswith(r"\linked") else normal

        with patch.object(Path, "lstat", autospec=True, side_effect=lstat_for_link), \
                patch.object(guard.os, "scandir") as scan:
            scan.return_value.__enter__.return_value = [entry]
            with self.assertRaises(guard.Refused):
                guard.no_links(Path(TARGET), tree=True)
        symlink = MagicMock(st_file_attributes=0, st_mode=stat.S_IFLNK)
        with patch.object(Path, "lstat", return_value=symlink):
            with self.assertRaises(guard.Refused):
                guard.no_links(Path(TARGET))

    def test_cache_layout_strict(self):
        for name in ["scripts/__pycache__/a.cpython-313.pyc", ".pytest_cache/v/cache/nodeids",
                     ".ruff_cache/0.14.1/12345", ".pytest_cache/README.md"]:
            self.assertTrue(guard.cache_allowed(name), name)
        for name in [".env", ".pytest_cache/password.txt", ".ruff_cache/other",
                     "x/__pycache__/notes.txt", "x/__pycache__/a.cpython-312.pyc",
                     "../__pycache__/a.cpython-313.pyc", ".pytest_cache/v/cache/secret"]:
            self.assertFalse(guard.cache_allowed(name), name)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(guard, "no_links"))
        self.stack.enter_context(patch.object(Path, "is_file", return_value=True))
        self.stack.enter_context(patch.object(Path, "is_dir", return_value=True))
        # Mock bound methods explicitly to provide .git pointer/backlink metadata only.
        self.stack.enter_context(patch.object(Path, "read_text", autospec=True,
            side_effect=lambda p, **kw: ("gitdir: " + str(guard.MAIN / ".git" / "worktrees" / "test")
                                        if p.name == ".git" else TARGET + r"\.git")))
        self.reg = {guard.key(guard.MAIN): (b"main",),
                    guard.key(TARGET): (b"HEAD " + HEAD.encode(),
                                       b"branch refs/heads/" + BRANCH.encode())}
        self.stack.enter_context(patch.object(guard, "registrations", return_value=self.reg))
        self.stack.enter_context(patch.object(guard, "main_snapshot", return_value=(b"", "meta")))
        self.overrides = {}
        self.git = self.stack.enter_context(patch.object(guard, "git", side_effect=self.command))

    def command(self, *cmd, **kw):
        if cmd in self.overrides:
            value = self.overrides[cmd]
            if isinstance(value, Exception):
                raise value
            return value
        defaults = {
            ("rev-parse", "--path-format=absolute", "--git-common-dir"):
                str(guard.MAIN / ".git").encode(),
            ("rev-parse", "--show-toplevel"): TARGET.encode(),
            ("rev-parse", "HEAD"): HEAD.encode(),
            ("symbolic-ref", "HEAD"): ("refs/heads/" + BRANCH).encode(),
            ("rev-parse", "refs/remotes/origin/master"): MASTER.encode(),
            ("ls-files", "-v", "-z"): b"H tracked.py\0",
        }
        return defaults.get(cmd, b"")

    def validate(self):
        return guard.validate(Path(TARGET), HEAD, BRANCH, MASTER)

    def test_valid(self):
        self.assertEqual(self.validate(), (self.reg, (b"", "meta")))

    def test_status_and_ignored_failures(self):
        for command, value in [
            (("status", "--porcelain=v1", "-z", "--untracked-files=all",
              "--ignore-submodules=none"), b" M tracked\0"),
            (("status", "--porcelain=v1", "-z", "--untracked-files=all",
              "--ignore-submodules=none"), b"?? untracked\0"),
            (("ls-files", "--others", "--ignored", "--exclude-standard", "-z"), b".env\0"),
            (("rev-parse", "HEAD"), b"c" * 40),
            (("symbolic-ref", "HEAD"), b"refs/heads/wrong"),
            (("rev-parse", "refs/remotes/origin/master"), b"c" * 40),
            (("merge-base", "--is-ancestor", HEAD, MASTER), guard.Refused("unmerged")),
            (("rev-parse", "--path-format=absolute", "--git-common-dir"), b"C:/other/.git"),
        ]:
            with self.subTest(command=command, value=value):
                self.overrides = {command: value}
                with self.assertRaises(guard.Refused):
                    self.validate()

    def test_hidden_assume_unchanged_and_skip_worktree_flags_fail_closed(self):
        # Git status can return clean even for changed contents under either
        # index flag. The tool must refuse BEFORE any native remove.
        for contents in (b"h secretly_edited.py\0", b"S missing_file.py\0",
                         b"H clean.py\0h changed.py\0",
                         b"H clean.py\0S changed.py\0", b"H missing_terminator"):
            with self.subTest(contents=contents):
                self.overrides = {("ls-files", "-v", "-z"): contents}
                with self.assertRaises(guard.Refused):
                    self.validate()

    def test_registration_and_dotgit_anomalies(self):
        for record in [(), (b"HEAD wrong",), self.reg[guard.key(TARGET)] + (b"locked",)]:
            with patch.object(guard, "registrations", return_value={guard.key(TARGET): record}):
                with self.assertRaises(guard.Refused):
                    self.validate()
        with patch.object(Path, "is_file", return_value=False):
            with self.assertRaises(guard.Refused):
                self.validate()
        for pointer in ["gitdir: C:/Users/Anthony/host", "gitdir: ../outside", "invalid"]:
            with patch.object(Path, "read_text", return_value=pointer):
                with self.assertRaises(guard.Refused):
                    self.validate()
        with patch.object(Path, "read_text", side_effect=[
                "gitdir: " + str(guard.MAIN / ".git" / "worktrees" / "test"), "C:/wrong/.git"]):
            with self.assertRaises(guard.Refused):
                self.validate()

    def test_missing_main_registration(self):
        del self.reg[guard.key(guard.MAIN)]
        with self.assertRaises(guard.Refused):
            self.validate()


class RegistryTests(unittest.TestCase):
    def test_unparseable_json_and_nonobjects(self):
        folder = MagicMock()
        folder.name = "a" * 32
        for text in ["invalid", "[]", "null"]:
            file = MagicMock()
            file.read_text.return_value = text
            folder.__truediv__.return_value = file
            with patch.object(guard, "no_links"), \
                    patch.object(Path, "is_dir", return_value=True), \
                    patch.object(Path, "iterdir", return_value=[folder]):
                with self.assertRaises((guard.Refused, ValueError)):
                    guard.registry_clear(Path(TARGET))

    def test_terminal_and_unresolved_and_malformed(self):
        folder = MagicMock(name="folder")
        folder.name = "a" * 32
        for task, state, allowed in [
            ({"workdir": TARGET}, {"status": "completed"}, True),
            ({"workdir": TARGET}, {"status": "superseded"}, True),
            ({"workdir": TARGET + r"\backend"}, {"status": "completed"}, True),
            ({"workdir": TARGET + r"\backend"}, {"status": "running"}, False),
            ({"workdir": TARGET + r"\backend"}, {"status": "failed"}, False),
            ({"workdir": TARGET + r"\backend\service"}, {"status": "queued"}, False),
            ({"workdir": TARGET + r"-similar"}, {"status": "running"}, False),
            ({"workdir": TARGET + r"-similar"}, {"status": "failed"}, True),
            *[({"workdir": TARGET}, {"status": s}, False)
              for s in ["running", "queued", "failed", "interrupted-or-unverified", "unknown"]],
            *[({"workdir": alias}, {"status": status}, False)
              for alias in [r"C:\Work\home-hub-project\main\junction\backend",
                            r"C:\Work\HOME-H~1\alias", "C:\\Work\\unicode-\u00e4",
                            r"C:\Work\osrs-flip-assistant-project"]
              for status in ["queued", "running", "unverified"]],
            ({"workdir": r"C:\Work\home-hub-project\main\junction\backend"},
             {"status": "failed"}, True),
            ({}, {"status": "completed"}, False),
            ({"workdir": TARGET}, {}, False),
        ]:
            with self.subTest(state=state), patch.object(guard, "no_links"), \
                    patch.object(Path, "is_dir", return_value=True), \
                    patch.object(Path, "iterdir", return_value=[folder]):
                files = [MagicMock(), MagicMock()]
                files[0].read_text.return_value = json.dumps(task)
                files[1].read_text.return_value = json.dumps(state)
                folder.__truediv__.side_effect = files
                if allowed:
                    guard.registry_clear(Path(TARGET))
                else:
                    with self.assertRaises(guard.Refused):
                        guard.registry_clear(Path(TARGET))

    def test_missing_registry(self):
        with patch.object(guard, "no_links"), patch.object(Path, "is_dir", return_value=False):
            with self.assertRaises(guard.Refused):
                guard.registry_clear(Path(TARGET))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(guard, "no_links"))
        self.stack.enter_context(patch.object(guard, "sandbox_guest", return_value=True))
        self.lease = self.stack.enter_context(patch.object(guard, "lease",
            side_effect=lambda t: contextlib.nullcontext()))
        self.registry = self.stack.enter_context(patch.object(guard, "registry_clear"))
        self.before = {guard.key(TARGET): (b"target",), "other": (b"preserved",)}
        self.validate = self.stack.enter_context(patch.object(guard, "validate",
            return_value=(self.before, (b"dirty main unchanged", "metadata"))))
        self.reg = self.stack.enter_context(patch.object(guard, "registrations",
            return_value={"other": (b"preserved",)}))
        self.stack.enter_context(patch.object(Path, "exists", return_value=False))
        self.snapshot = self.stack.enter_context(patch.object(guard, "main_snapshot",
            return_value=(b"dirty main unchanged", "metadata")))
        self.git = self.stack.enter_context(patch.object(guard, "git", side_effect=self.command))

    def command(self, *cmd, **kw):
        if cmd[0] == "ls-remote":
            return (MASTER + "\trefs/heads/master\n").encode()
        if cmd[0] == "rev-parse":
            return HEAD.encode()
        return b""

    def run_apply(self):
        guard.execute(args(apply=True, verify_remote=True), emit=lambda x: None)

    def test_dry_run_never_removes_or_networks(self):
        guard.execute(args(), emit=lambda x: None)
        self.assertEqual(self.git.call_count, 1)  # branch format only
        self.lease.assert_not_called()

    def test_apply_only_native_remove_preserves_branch(self):
        self.run_apply()
        self.git.assert_any_call("worktree", "remove", TARGET)
        self.assertEqual(sum(c.args[:2] == ("worktree", "remove") for c in self.git.call_args_list), 1)
        self.assertFalse(any("--force" in c.args for c in self.git.call_args_list))
        self.assertEqual(self.registry.call_count, 2)
        self.assertEqual(self.validate.call_count, 2)

    def test_apply_through_native_wrapper_with_subprocess_mocked(self):
        self.git.side_effect = NATIVE_GIT
        def native(argv, **kw):
            output = b""
            if "ls-remote" in argv:
                output = (MASTER + "\trefs/heads/master\n").encode()
            if "rev-parse" in argv:
                output = HEAD.encode()
            return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")
        with patch.object(subprocess, "run", side_effect=native) as run:
            self.run_apply()
            removals = [call.args[0] for call in run.call_args_list if "worktree" in call.args[0]]
            self.assertEqual(len(removals), 1)
            self.assertEqual(removals[0][0], guard.GIT)
            self.assertEqual(removals[0][-3:], ["worktree", "remove", TARGET])
            self.assertNotIn("--force", removals[0])

    def test_explicit_options_identity_and_bad_sha(self):
        for options in [args(apply=True), args(expected_head="abc"), args(expected_master="abc"),
                        args(expected_branch=""), args(expected_branch="--bad")]:
            with self.subTest(options=options), self.assertRaises(guard.Refused):
                guard.execute(options)
        with patch.object(guard, "sandbox_guest", return_value=False):
            with self.assertRaises(guard.Refused):
                guard.execute(args())

    def test_remote_mismatch_blocks_removal(self):
        self.git.side_effect = lambda *a, **kw: b"stale" if a[0] == "ls-remote" else b""
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.assertFalse(any(c.args[0] == "worktree" for c in self.git.call_args_list))

    def test_registry_and_preflight_races_block_removal(self):
        self.registry.side_effect = [None, guard.Refused("new task")]
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.registry.side_effect = None
        self.validate.side_effect = [(self.before, (b"x", "meta")), ({}, (b"x", "meta"))]
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.assertFalse(any(c.args[0] == "worktree" for c in self.git.call_args_list))

    def test_native_refusal_never_retries(self):
        def refuse(*a, **kw):
            if a[0] == "worktree":
                raise guard.Refused("ignored caches blocked native Git")
            return self.command(*a, **kw)
        self.git.side_effect = refuse
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.assertEqual(sum(c.args[0] == "worktree" for c in self.git.call_args_list), 1)
        self.reg.assert_not_called()

    def test_postflight_detects_other_registration_and_main_changes(self):
        self.reg.return_value = {"unexpected": ()}
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.reg.return_value = {"other": (b"preserved",)}
        self.snapshot.return_value = (b"changed", "metadata")
        with self.assertRaises(guard.Refused):
            self.run_apply()
        self.snapshot.return_value = (b"dirty main unchanged", "metadata")
        with patch.object(Path, "exists", return_value=True):
            with self.assertRaises(guard.Refused):
                self.run_apply()

    def test_postflight_branch_change(self):
        def changed(*cmd, **kw):
            return b"c" * 40 if cmd[0] == "rev-parse" else self.command(*cmd, **kw)
        self.git.side_effect = changed
        with self.assertRaises(guard.Refused):
            self.run_apply()


class NativeTests(unittest.TestCase):
    def test_exclusive_lock_creates_or_opens_only_lock_file(self):
        kernel = MagicMock()
        kernel.CreateFileW.return_value = 123
        with patch.object(guard, "no_links"), \
                patch.object(Path, "is_dir", return_value=True), \
                patch.object(Path, "exists", return_value=False), \
                patch.object(Path, "is_symlink", return_value=False), \
                patch.object(guard.ctypes, "WinDLL", return_value=kernel, create=True):
            with guard.lease(Path(TARGET)):
                kernel.CloseHandle.assert_not_called()
            call = kernel.CreateFileW.call_args.args
            self.assertEqual(call[2], 0)  # FileShare.None
            self.assertEqual(call[1], 0xC0000000)  # ReadWrite, exclusive retirement
            digest = guard.hashlib.sha256(guard.key(TARGET).encode("utf-8")).hexdigest()
            self.assertEqual(Path(call[0]).name, "lifecycle-" + digest + ".lock")
            self.assertEqual(call[4], 4)  # OPEN_ALWAYS; Read tasks may lack lock
            self.assertTrue(call[5] & 0x00200000)  # OPEN_REPARSE_POINT
            kernel.CloseHandle.assert_called_once_with(123)
            kernel.CreateFileW.return_value = guard.ctypes.c_void_p(-1).value
            with self.assertRaises(guard.Refused), guard.lease(Path(TARGET)):
                self.fail("Unavailable lease must block")
        with patch.object(guard, "no_links"), \
                patch.object(Path, "is_dir", return_value=False), \
                patch.object(guard.ctypes, "WinDLL", return_value=kernel, create=True):
            with self.assertRaises(guard.Refused):
                with guard.lease(Path(TARGET)):
                    self.fail("Missing lock directory must block")

    def test_git_failure_and_timeout_and_sanitized_environment(self):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1)) as run:
            with self.assertRaises(guard.Refused):
                guard.git("worktree", "remove", TARGET)
            self.assertEqual(run.call_args.args[0][-3:], ["worktree", "remove", TARGET])
        with patch.dict(guard.os.environ, {"GIT_DIR": "redirect"}), \
                patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=b"")) as run:
            guard.git("status")
            self.assertNotIn("GIT_DIR", run.call_args.kwargs["env"])
            self.assertTrue(any(arg.startswith("safe.directory=")
                                for arg in run.call_args.args[0]))
        with self.assertRaises(guard.Refused):
            guard.git("status", cwd=Path(r"C:\Users\Anthony\host"))
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 120)):
            with self.assertRaises(subprocess.TimeoutExpired):
                guard.git("status")

    def test_registration_parser_preserves_prunable_others(self):
        raw = (b"worktree C:/Work/home-hub-project/main\0HEAD abc\0branch refs/heads/master\0\0"
               b"worktree C:/host/old\0HEAD def\0detached\0prunable old\0\0")
        with patch.object(guard, "git", return_value=raw):
            self.assertEqual(len(guard.registrations()), 2)
        with patch.object(guard, "git", return_value=b"malformed\0\0"):
            with self.assertRaises(guard.Refused):
                guard.registrations()


if __name__ == "__main__":
    unittest.main()
