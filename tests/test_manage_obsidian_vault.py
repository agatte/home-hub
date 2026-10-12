"""Synthetic Git acceptance tests for the persistent HomeHub Obsidian vault."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manage_obsidian_vault import (  # noqa: E402
    MANAGED,
    initialize,
    refresh,
    verify_sealed,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=10,
    )
    return result.stdout.decode().strip()


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "docs").mkdir()
    for rel, body in {
        "AGENTS.md": "Guidelines\n",
        "docs/PROJECT_ADMIN_HUB.md": "Project Admin\n",
        "docs/README.md": "# HomeHub Docs\n",
        "docs/PROJECT_SPEC.md": "Version A\n",
    }.items():
        (repo / rel).write_text(body, encoding="utf-8")
    git(repo, "add", "AGENTS.md", "docs")
    git(repo, "commit", "-qm", "Initial notes")
    return repo, git(repo, "rev-parse", "HEAD")


def next_head(repo: Path) -> str:
    (repo / "docs" / "PROJECT_SPEC.md").write_text("Version B\n", encoding="utf-8")
    git(repo, "add", "docs/PROJECT_SPEC.md")
    git(repo, "commit", "-qm", "New docs")
    return git(repo, "rev-parse", "HEAD")


def test_initialize_creates_sealed_source_and_no_repo_changes(source, tmp_path):
    repo, sha = source
    vault = tmp_path / "Permanent HomeHub Knowledge Vault"
    message = initialize(repo, vault, sha)
    assert sha in message
    assert verify_sealed(vault / MANAGED)["source_commit"] == sha
    assert (vault / MANAGED / "00-START-HERE.md").exists()
    assert (vault / MANAGED / "docs/PROJECT_SPEC.md").read_text() == "Version A\n"
    assert git(repo, "status", "--porcelain") == ""


def test_refresh_keeps_user_notes_settings_and_archives_old_snapshot(source, tmp_path):
    repo, first = source
    vault = tmp_path / "Permanent Vault"
    initialize(repo, vault, first)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text('{"showInlineTitle": true}')
    (vault / "My Notes.md").write_text("Personal work should survive\n")
    second = next_head(repo)
    message = refresh(repo, vault, second)
    assert "Refreshed" in message
    assert verify_sealed(vault / MANAGED)["source_commit"] == second
    assert (vault / MANAGED / "docs/PROJECT_SPEC.md").read_text() == "Version B\n"
    assert (vault / "My Notes.md").read_text() == "Personal work should survive\n"
    assert (vault / ".obsidian/app.json").read_text() == '{"showInlineTitle": true}'
    backups = list(tmp_path.glob(".Permanent Vault-homehub-backup-*"))
    assert len(backups) == 1
    assert verify_sealed(backups[0])["source_commit"] == first
    assert (backups[0] / "docs/PROJECT_SPEC.md").read_text() == "Version A\n"
    assert git(repo, "status", "--porcelain") == ""


def test_rejects_manual_managed_file_edit_without_moving_anything(source, tmp_path):
    repo, first = source
    vault = tmp_path / "Vault"
    initialize(repo, vault, first)
    second = next_head(repo)
    file = vault / MANAGED / "docs/PROJECT_SPEC.md"
    file.chmod(0o666)
    file.write_text("USER CHANGE\n")
    with pytest.raises(ValueError, match="Managed file changed"):
        refresh(repo, vault, second)
    assert file.read_text() == "USER CHANGE\n"
    assert not list(tmp_path.glob(".Vault-homehub-backup-*"))
    assert not list(tmp_path.glob(".Vault-homehub-stage-*"))


def test_rejects_new_note_inside_managed_subtree(source, tmp_path):
    repo, first = source
    vault = tmp_path / "Vault"
    initialize(repo, vault, first)
    (vault / MANAGED / "important-note.md").write_text("private")
    second = next_head(repo)
    with pytest.raises(ValueError, match="Untracked"):
        refresh(repo, vault, second)
    assert (vault / MANAGED / "important-note.md").read_text() == "private"


def test_rejects_wrong_expected_head_without_creating_vault(source, tmp_path):
    repo, first = source
    second = next_head(repo)
    vault = tmp_path / "Vault"
    with pytest.raises(ValueError, match="Source HEAD mismatch"):
        initialize(repo, vault, first)
    assert not vault.exists()
    initialize(repo, vault, second)
    assert "no changes" in refresh(repo, vault, second)
    assert not list(tmp_path.glob(".Vault-homehub-*"))


def test_rejects_existing_vault_and_other_git_worktree(source, tmp_path):
    repo, sha = source
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.md").write_text("KEEP")
    with pytest.raises(FileExistsError):
        initialize(repo, occupied, sha)
    assert (occupied / "keep.md").read_text() == "KEEP"
    sibling = tmp_path / "other-checkout"
    sibling.mkdir()
    git(sibling, "init", "-q")
    with pytest.raises(ValueError, match="outside every Git worktree"):
        initialize(repo, sibling / "new-vault", sha)


def test_refuses_location_under_homehub_project_worktrees(tmp_path):
    project = tmp_path / "home-hub-project"
    repo = project / "main"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "docs").mkdir()
    for rel in ("AGENTS.md", "docs/PROJECT_ADMIN_HUB.md", "docs/README.md", "docs/PROJECT_SPEC.md"):
        (repo / rel).write_text("# Data\n")
    git(repo, "add", "AGENTS.md", "docs")
    git(repo, "commit", "-qm", "Setup")
    worktrees = project / "worktrees"
    worktrees.mkdir()
    destination = worktrees / "Wrong Vault"
    with pytest.raises(ValueError, match="outside the HomeHub project workspace"):
        initialize(repo, destination, git(repo, "rev-parse", "HEAD"))
    assert not destination.exists()


def test_failed_swap_restores_old_managed_tree(source, tmp_path, monkeypatch):
    import manage_obsidian_vault as manager

    repo, first = source
    vault = tmp_path / "Vault"
    initialize(repo, vault, first)
    (vault / "My Notes.md").write_text("KEEP")
    second = next_head(repo)
    real_rename = manager.os.rename

    def fail_new_snapshot_move(src, dest):
        if "homehub-stage" in Path(src).name and Path(dest) == vault / MANAGED:
            raise OSError("Simulated second rename failure")
        return real_rename(src, dest)

    monkeypatch.setattr(manager.os, "rename", fail_new_snapshot_move)
    with pytest.raises(OSError, match="Simulated second rename"):
        refresh(repo, vault, second)
    assert verify_sealed(vault / MANAGED)["source_commit"] == first
    assert (vault / "My Notes.md").read_text() == "KEEP"
    assert len(list(tmp_path.glob(".Vault-homehub-stage-*"))) == 1


def test_rejects_relative_vault_path(source):
    repo, sha = source
    with pytest.raises(ValueError, match="absolute"):
        initialize(repo, Path("relative-vault"), sha)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_windows_vault_and_refreshed_source_inherit_user_acl(source, tmp_path):
    repo, head = source
    vault = tmp_path / "Private Vault"
    account = subprocess.check_output(["whoami"], text=True).strip().casefold()
    # Mirror a Documents folder with an explicit normal-user ACE.
    subprocess.run(
        ["icacls.exe", str(tmp_path), "/grant", f"{account}:(OI)(CI)(F)"],
        check=True,
        capture_output=True,
        text=True,
    )
    initialize(repo, vault, head)

    def assert_user_can_traverse(path):
        acl = subprocess.check_output(
            ["icacls.exe", str(path)], text=True, encoding="utf-8", errors="replace"
        ).casefold()
        assert f"{account}:" in acl
        assert "(i)" in acl

    assert_user_can_traverse(vault)
    assert_user_can_traverse(vault / MANAGED)
    second = next_head(repo)
    refresh(repo, vault, second)
    assert_user_can_traverse(vault / MANAGED)


def test_rejects_symlinked_managed_file(source, tmp_path):
    repo, sha = source
    vault = tmp_path / "Vault"
    initialize(repo, vault, sha)
    file = vault / MANAGED / "docs/PROJECT_SPEC.md"
    target = tmp_path / "outside-secret.md"
    target.write_text("Never touch")
    try:
        file.unlink()
        file.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Fixture symlink unsupported on this platform")
    with pytest.raises(ValueError, match="Refusing linked path"):
        refresh(repo, vault, next_head(repo))
    assert target.read_text() == "Never touch"


def test_generated_pages_stay_sealed_after_lf_normalization(source, tmp_path):
    """Opening an editor that normalizes CRLF to LF must not break the seal."""
    repo, sha = source
    vault = tmp_path / "Stable Newline Vault"
    initialize(repo, vault, sha)
    managed = vault / MANAGED
    before = (managed / ".homehub-snapshot-manifest.json").read_bytes()
    for filename in ("00-START-HERE.md", "SNAPSHOT.md"):
        path = managed / filename
        data = path.read_bytes()
        assert b"\r\n" not in data
        path.write_bytes(data.replace(b"\r\n", b"\n"))
    assert verify_sealed(managed)["source_commit"] == sha
    assert (managed / ".homehub-snapshot-manifest.json").read_bytes() == before
