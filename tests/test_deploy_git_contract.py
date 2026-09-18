from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bash_executable() -> str:
    if os.name == "nt":
        git_bash = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Git/bin/bash.exe"
        )
        if git_bash.exists():
            return str(git_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the deploy Git-contract harness")
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


def _seed_production(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    author = tmp_path / "author"
    prod = tmp_path / "prod"
    home = tmp_path / "home"
    author.mkdir()
    home.mkdir()

    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True,
        capture_output=True,
    )
    _git(author, "init")
    _git(author, "config", "user.email", "deploy-test@example.invalid")
    _git(author, "config", "user.name", "Deploy Test")

    scripts = author / "scripts"
    scripts.mkdir()
    shutil.copy2(PROJECT_ROOT / "scripts/deploy.sh", scripts / "deploy.sh")
    (author / "README.md").write_text("v1\n", encoding="utf-8")
    _git(author, "add", "scripts/deploy.sh", "README.md")
    _git(author, "update-index", "--chmod=+x", "scripts/deploy.sh")
    _git(author, "commit", "-m", "seed")
    _git(author, "branch", "-M", "master")
    _git(author, "remote", "add", "origin", str(origin))
    _git(author, "push", "-u", "origin", "master")

    subprocess.run(
        ["git", "clone", "--branch", "master", str(origin), str(prod)],
        check=True,
        capture_output=True,
        text=True,
    )
    head = _git(prod, "rev-parse", "HEAD")
    (prod / ".last-deployed-sha").write_text(f"{head}\n", encoding="utf-8")
    return author, prod, home


def _run_deploy(prod: Path, home: Path) -> subprocess.CompletedProcess[str]:
    command = (
        f'export HOME="{_bash_path(home)}"; '
        f'cd "{_bash_path(prod)}"; '
        "bash ./scripts/deploy.sh"
    )
    return subprocess.run(
        [_bash_executable(), "-c", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_deploy_fast_forwards_behind_production_checkout(tmp_path: Path) -> None:
    author, prod, home = _seed_production(tmp_path)
    (author / "README.md").write_text("v2\n", encoding="utf-8")
    _git(author, "add", "README.md")
    _git(author, "commit", "-m", "remote advance")
    _git(author, "push")
    expected = _git(author, "rev-parse", "HEAD")

    completed = _run_deploy(prod, home)

    assert completed.returncode == 0, completed.stderr
    assert _git(prod, "rev-parse", "HEAD") == expected
    assert (prod / ".last-deployed-sha").read_text(encoding="utf-8").strip() == expected
    assert "Fast-forward" in completed.stdout


@pytest.mark.parametrize(
    ("mutate", "expected_message"),
    [
        ("wrong_branch", "Production checkout must be on master"),
        ("dirty_tracked", "Production checkout has tracked local changes"),
        ("missing_origin", "Production checkout is missing the permanent origin remote"),
        ("missing_upstream", "Production master must track origin/master"),
        (
            "local_only_commit",
            "Production HEAD is not an ancestor of origin/master",
        ),
    ],
)
def test_deploy_rejects_invalid_production_git_contract(
    tmp_path: Path,
    mutate: str,
    expected_message: str,
) -> None:
    _, prod, home = _seed_production(tmp_path)

    if mutate == "wrong_branch":
        _git(prod, "checkout", "-b", "wrong-branch")
    elif mutate == "dirty_tracked":
        (prod / "README.md").write_text("dirty\n", encoding="utf-8")
    elif mutate == "missing_origin":
        _git(prod, "remote", "remove", "origin")
    elif mutate == "missing_upstream":
        _git(prod, "branch", "--unset-upstream")
    elif mutate == "local_only_commit":
        _git(prod, "config", "user.email", "deploy-test@example.invalid")
        _git(prod, "config", "user.name", "Deploy Test")
        (prod / "README.md").write_text("local\n", encoding="utf-8")
        _git(prod, "add", "README.md")
        _git(prod, "commit", "-m", "local-only commit")
    else:
        raise AssertionError(f"unknown mutation {mutate}")

    completed = _run_deploy(prod, home)

    assert completed.returncode == 4
    assert expected_message in completed.stderr
