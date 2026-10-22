"""Bounded, isolated tests for the HomeHub Obsidian read-only snapshot pilot."""

import os
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


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_windows_preview_directory_inherits_user_acl(repo, tmp_path):
    preview = tmp_path / "preview-acl"
    account = subprocess.check_output(["whoami"], text=True).strip().casefold()
    # pytest's Windows basetemp may itself use restrictive 0o700 ACLs.
    # Emulate the ordinary user-accessible Documents parent directory.
    subprocess.run(
        ["icacls.exe", str(tmp_path), "/grant", f"{account}:(OI)(CI)(F)"],
        check=True,
        capture_output=True,
        text=True,
    )
    create(repo, preview)
    acl = subprocess.check_output(
        ["icacls.exe", str(preview)], text=True, encoding="utf-8", errors="replace"
    ).casefold()
    assert f"{account}:" in acl
    assert "(i)" in acl


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


def test_generated_pages_are_exact_utf8_lf_bytes_on_all_platforms(repo, tmp_path):
    """Generated pages must be byte-stable across Windows and POSIX."""
    from create_obsidian_pilot import LANDING

    dest = tmp_path / "stable-generated-pages"
    sha, count = create(repo, dest)
    assert (dest / "00-START-HERE.md").read_bytes() == LANDING.encode("utf-8")
    expected_provenance = (
        f"# Preview provenance\n\nSource Git commit: `{sha}`.\n\n"
        f"Exported Git-tracked Markdown files: **{count}**.\n\n"
        "This is an isolated copy, not a live-status verification.\n"
    ).encode("utf-8")
    assert (dest / "SNAPSHOT.md").read_bytes() == expected_provenance
    assert b"\r" not in expected_provenance
