"""Synthetic policy checks for scripts/create-chatgpt-snapshot.ps1."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create-chatgpt-snapshot.ps1"


def _powershell():
    return shutil.which("pwsh") or shutil.which("powershell")


def _ps_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def _write_fake_git(fakebin, tracked, untracked):
    """Provide only the read-only Git answers the snapshot script may use."""
    fakebin.mkdir()
    helper = fakebin / "fake_git.py"
    helper.write_text(
        "import sys\n"
        f"TRACKED = {tracked!r}\n"
        f"UNTRACKED = {untracked!r}\n"
        "args = sys.argv[1:]\n"
        "if len(args) >= 2 and args[0] == '-C':\n"
        "    args = args[2:]\n"
        "command = tuple(args)\n"
        "if command == ('rev-parse', '--is-inside-work-tree'):\n"
        "    print('true')\n"
        "elif command == ('branch', '--show-current'):\n"
        "    print('synthetic')\n"
        "elif command == ('rev-parse', '--short=12', 'HEAD'):\n"
        "    print('deadbeefcafe')\n"
        "elif command == ('ls-files', '--cached'):\n"
        "    print('\\n'.join(TRACKED))\n"
        "elif command == ('ls-files', '--others', '--exclude-standard'):\n"
        "    print(\"warning: could not open directory '.pytest_cache/': Permission denied\", file=sys.stderr)\n"
        "    print('\\n'.join(UNTRACKED))\n"
        "else:\n"
        "    print('unexpected git invocation', file=sys.stderr)\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    git_cmd = fakebin / "git.cmd"
    git_cmd.write_text(
        f'@echo off\r\n"{sys.executable}" "%~dp0fake_git.py" %*\r\n',
        encoding="utf-8",
    )

    # PowerShell on POSIX resolves native commands by executable filename;
    # a Windows-only git.cmd shim is invisible there and would fall through
    # to the runner's real Git. Provide the same synthetic Git contract under
    # an extensionless executable name so this policy test stays platform-neutral.
    if os.name != "nt":
        git_exe = fakebin / "git"
        git_exe.write_text(
            f"#!{sys.executable}\n"
            "import runpy\n"
            "from pathlib import Path\n"
            "runpy.run_path(str(Path(__file__).with_name('fake_git.py')), "
            "run_name='__main__')\n",
            encoding="utf-8",
        )
        git_exe.chmod(0o755)


@unittest.skipIf(_powershell() is None, "PowerShell is unavailable")
class SnapshotExportPolicyTests(unittest.TestCase):
    def test_snapshot_policy_uses_synthetic_repository(self):
        with tempfile.TemporaryDirectory(prefix="homehub-snapshot-test-") as temp:
            tmp_path = Path(temp)
            repo = tmp_path / "repo"
            repo.mkdir()

            files = {
                "backend/app.py": "SAFE_BACKEND_MARKER",
                "backend/config.py": "SAFE_CONFIG_SOURCE_MARKER",
                "docs/guide.md": "SAFE_DOC_MARKER",
                ".env.example": "SAFE_ENV_EXAMPLE_MARKER",
                "pyproject.toml": "SAFE_PYPROJECT_MARKER",
                "pyrightconfig.json": "SAFE_ROOT_CONFIG_MARKER",
                "requirements.txt": "SAFE_REQUIREMENTS_MARKER",
                "frontend-svelte/package.json": "SAFE_FRONTEND_CONFIG_MARKER",
                ".mcp.json": "EXCLUDED_MCP_MARKER",
                "docs/.MCP.JSON": "EXCLUDED_CASE_MCP_MARKER",
                "tests/nested/.mcp.json": "EXCLUDED_NESTED_MCP_MARKER",
                "backend/nested/.env.production": "EXCLUDED_ENV_MARKER",
                "backend/nested/credentials.json": "EXCLUDED_CREDENTIAL_MARKER",
                "backend/settings.local.json": "EXCLUDED_LOCAL_SETTINGS_MARKER",
                "docs/.vscode/settings.json": "EXCLUDED_EDITOR_SETTINGS_MARKER",
                "misc/private.py": "EXCLUDED_UNALLOWLISTED_MARKER",
            }
            for name, contents in files.items():
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")

            # Copy only the policy script into this disposable repository. No
            # secret-bearing file from the real HomeHub checkout is opened.
            (repo / "scripts").mkdir()
            shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)

            outside = tmp_path / "outside.txt"
            outside.write_text("EXCLUDED_SYMLINK_MARKER", encoding="utf-8")
            link = repo / "backend" / "escape.py"
            link_created = False
            try:
                link.symlink_to(outside)
                link_created = True
            except (OSError, NotImplementedError):
                pass

            # This untracked sensitive file must pass through the same policy
            # as tracked candidates.
            (repo / "backend" / ".mcp.json").write_text(
                "EXCLUDED_UNTRACKED_MCP_MARKER", encoding="utf-8"
            )

            tracked = [
                "backend/app.py",
                "backend/config.py",
                "docs/guide.md",
                ".env.example",
                "pyproject.toml",
                "pyrightconfig.json",
                "requirements.txt",
                "frontend-svelte/package.json",
                "scripts/create-chatgpt-snapshot.ps1",
                ".mcp.json",
                "docs/.MCP.JSON",
                "tests/nested/.mcp.json",
                "backend/nested/.env.production",
                "backend/nested/credentials.json",
                "backend/settings.local.json",
                "docs/.vscode/settings.json",
            ]
            untracked = ["backend/.mcp.json", "misc/private.py", "../outside.txt"]
            if link_created:
                untracked.append("backend/escape.py")

            fakebin = tmp_path / "fakebin"
            _write_fake_git(fakebin, tracked, untracked)
            env = os.environ.copy()
            env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                [
                    _powershell(),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(repo / "scripts" / SCRIPT.name),
                ],
                cwd=repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout)

            archives = list((tmp_path / "snapshots").glob("home-hub-chatgpt-*.zip"))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as archive:
                names = set(archive.namelist())
                manifest = archive.read("SNAPSHOT_MANIFEST.txt").decode("utf-8-sig")
                contents = "\n".join(
                    archive.read(name).decode("utf-8", errors="replace")
                    for name in names
                    if not name.endswith("/")
                )

            for expected in (
                "backend/app.py",
                "backend/config.py",
                "docs/guide.md",
                ".env.example",
                "pyproject.toml",
                "pyrightconfig.json",
                "requirements.txt",
                "frontend-svelte/package.json",
                "scripts/create-chatgpt-snapshot.ps1",
            ):
                self.assertIn(expected, names)

            self.assertFalse(any(name.lower().endswith(".mcp.json") for name in names))
            self.assertNotIn("backend/nested/.env.production", names)
            self.assertNotIn("backend/nested/credentials.json", names)
            self.assertNotIn("backend/settings.local.json", names)
            self.assertNotIn("docs/.vscode/settings.json", names)
            self.assertNotIn("misc/private.py", names)
            if link_created:
                self.assertNotIn("backend/escape.py", names)

            for marker in (
                "SAFE_BACKEND_MARKER",
                "SAFE_CONFIG_SOURCE_MARKER",
                "SAFE_DOC_MARKER",
                "SAFE_ENV_EXAMPLE_MARKER",
                "SAFE_PYPROJECT_MARKER",
                "SAFE_ROOT_CONFIG_MARKER",
                "SAFE_REQUIREMENTS_MARKER",
                "SAFE_FRONTEND_CONFIG_MARKER",
            ):
                self.assertIn(marker, contents)

            for marker in (
                "EXCLUDED_MCP_MARKER",
                "EXCLUDED_CASE_MCP_MARKER",
                "EXCLUDED_NESTED_MCP_MARKER",
                "EXCLUDED_ENV_MARKER",
                "EXCLUDED_CREDENTIAL_MARKER",
                "EXCLUDED_LOCAL_SETTINGS_MARKER",
                "EXCLUDED_EDITOR_SETTINGS_MARKER",
                "EXCLUDED_UNTRACKED_MCP_MARKER",
                "EXCLUDED_UNALLOWLISTED_MARKER",
                "EXCLUDED_SYMLINK_MARKER",
            ):
                self.assertNotIn(marker, contents)

            self.assertNotIn("Origin:", manifest)
            self.assertNotIn("Repository:", manifest)
            self.assertNotIn("https://", manifest)
            self.assertNotIn(".git/config", manifest)

    def test_final_archive_validator_rejects_disallowed_member(self):
        with tempfile.TemporaryDirectory(prefix="homehub-snapshot-validator-") as temp:
            archive_path = Path(temp) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "SNAPSHOT_MANIFEST.txt",
                    "Home Hub - ChatGPT Snapshot Manifest\n"
                    "====================================\n"
                    "HEAD: deadbeefcafe\n",
                )
                archive.writestr(".mcp.json", "SYNTHETIC_SECRET_MARKER")

            command = (
                f". {_ps_quote(SCRIPT)}; "
                f"Assert-SnapshotArchiveSafe -ArchivePath {_ps_quote(archive_path)}"
            )
            result = subprocess.run(
                [
                    _powershell(),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Archive validation failed", result.stdout)
            self.assertNotIn("SYNTHETIC_SECRET_MARKER", result.stdout)


if __name__ == "__main__":
    unittest.main()
