"""Bounded, isolated tests for the HomeHub Obsidian read-only snapshot pilot."""

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from create_obsidian_pilot import create  # noqa: E402


def cmd(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=5)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    cmd(root, "init", "-q")
    cmd(root, "config", "user.name", "Test")
    cmd(root, "config", "user.email", "test@example.invalid")
    (root / "docs").mkdir()
    for name, content in (
        ("AGENTS.md", "# Guide\n"),
        ("docs/README.md", "# Docs\n[spec](PROJECT_SPEC.md)\n"),
        ("docs/PROJECT_SPEC.md", "# Spec\n"),
        ("docs/PROJECT_ADMIN_HUB.md", "# Hub\n"),
        ("docs/UNTRACKED.md", "NOT A SOURCE\n"),
    ):
        (root / name).write_text(content)
    (root / ".env").write_text("SECRET=nevercopy\n")
    (root / "docs" / "secret.txt").write_text("PRIVATE\n")
    cmd(
        root,
        "add",
        "AGENTS.md",
        "docs/README.md",
        "docs/PROJECT_SPEC.md",
        "docs/PROJECT_ADMIN_HUB.md",
    )
    cmd(root, "commit", "-qm", "Seed")
    (root / "docs" / "README.md").write_text("LOCAL SECRET DO NOT COPY\n")
    return root


def test_export_isolated_head_only(repo, tmp_path):
    dest = tmp_path / "preview"
    sha, count = create(repo, dest)
    assert len(sha) == 40
    assert count == 4
    assert (dest / "docs/README.md").read_text() == "# Docs\n[spec](PROJECT_SPEC.md)\n"
    assert not (dest / ".env").exists()
    assert not (dest / "docs/secret.txt").exists()
    assert not (dest / "docs/UNTRACKED.md").exists()
    assert (dest / "00-START-HERE.md").exists()
    assert (repo / "docs/README.md").read_text() == "LOCAL SECRET DO NOT COPY\n"


def test_refuses_overwrite_or_repo_descendant(repo, tmp_path):
    dest = tmp_path / "preview"
    create(repo, dest)
    with pytest.raises(FileExistsError):
        create(repo, dest)
    with pytest.raises(ValueError):
        create(repo, repo / "preview")
    with pytest.raises(ValueError):
        create(repo, tmp_path)


def test_refuses_export_inside_sibling_worktree(repo, tmp_path):
    sibling = tmp_path / "other-worktree"
    sibling.mkdir()
    cmd(sibling, "init", "-q")
    with pytest.raises(ValueError, match="outside every Git worktree"):
        create(repo, sibling / "preview")
    assert not (sibling / "preview").exists()


def test_preview_file_is_read_only(repo, tmp_path):
    dest = tmp_path / "preview"
    create(repo, dest)
    mode = (dest / "docs/README.md").stat().st_mode
    assert mode & 0o222 == 0


def test_symlink_is_not_copied(repo, tmp_path):
    link = repo / "docs/LINKED_SECRET.md"
    try:
        link.symlink_to(repo / ".env")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation unavailable in this environment: {type(exc).__name__}")
    cmd(repo, "add", "docs/LINKED_SECRET.md")
    cmd(repo, "commit", "-qm", "Add tracked symlink")
    dest = tmp_path / "preview-symlink"
    _sha, count = create(repo, dest)
    assert count == 4
    assert not (dest / "docs/LINKED_SECRET.md").exists()
    assert not (dest / ".env").exists()
