from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bash_executable() -> str:
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.exists():
            return str(git_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the deploy self-update harness")
    return bash


def _bash_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if os.name == "nt" and len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_deploy_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def test_deploy_reexecs_new_body_after_pull(tmp_path: Path):
    origin = tmp_path / "origin.git"
    author = tmp_path / "author"
    prod = tmp_path / "prod"
    home = tmp_path / "home"
    author.mkdir()
    home.mkdir()

    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    _git(author, "init")
    _git(author, "config", "user.email", "deploy-test@example.invalid")
    _git(author, "config", "user.name", "Deploy Test")

    deploy_source = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")
    deploy_path = author / "scripts/deploy.sh"
    _write_deploy_script(deploy_path, deploy_source)
    _git(author, "add", "scripts/deploy.sh")
    _git(author, "update-index", "--chmod=+x", "scripts/deploy.sh")
    _git(author, "commit", "-m", "initial deploy script")
    _git(author, "branch", "-M", "main")
    _git(author, "remote", "add", "origin", str(origin))
    _git(author, "push", "-u", "origin", "main")
    first_sha = _git(author, "rev-parse", "HEAD")

    subprocess.run(
        ["git", "clone", "--branch", "main", str(origin), str(prod)],
        check=True,
        capture_output=True,
        text=True,
    )
    (prod / ".last-deployed-sha").write_text(f"{first_sha}\n", encoding="utf-8")

    marker_line = "printf 'new-body\\n' >> \"$HOME/reexec.log\"\n"
    updated_source = deploy_source.replace(
        "set -euo pipefail\n",
        f"set -euo pipefail\n{marker_line}",
        1,
    )
    assert updated_source != deploy_source

    _write_deploy_script(deploy_path, updated_source)
    _git(author, "add", "scripts/deploy.sh")
    _git(author, "update-index", "--chmod=+x", "scripts/deploy.sh")
    _git(author, "commit", "-m", "update deploy script body")
    _git(author, "push")
    second_sha = _git(author, "rev-parse", "HEAD")

    shell_command = (
        f'export HOME="{_bash_path(home)}"; '
        f'cd "{_bash_path(prod)}"; '
        "bash ./scripts/deploy.sh"
    )
    completed = subprocess.run(
        [_bash_executable(), "-c", shell_command],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    reexec_log = home / "reexec.log"
    assert reexec_log.exists(), completed.stdout
    assert reexec_log.read_text(encoding="utf-8").splitlines() == ["new-body"]
    assert completed.stdout.count("deploy.sh changed during pull") == 1
    assert completed.stdout.count("Deploying ") == 1
    assert completed.stdout.count("Changed files:") == 1
    assert (prod / ".last-deployed-sha").read_text(encoding="utf-8").strip() == second_sha
