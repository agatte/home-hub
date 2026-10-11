"""Offline, synthetic-Git checks for the read-only Obsidian freshness report."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_obsidian_freshness import compare, main, plan_refresh  # noqa: E402
from manage_obsidian_vault import MANAGED, initialize  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return (
        subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=True,
            timeout=10,
        )
        .stdout.decode()
        .strip()
    )


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Synthetic Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "docs").mkdir()
    for name, content in {
        "AGENTS.md": "Accepted directions\n",
        "docs/PROJECT_SPEC.md": "# Specification\nVersion A\n",
        "docs/README.md": "Navigation\n",
        "docs/PROJECT_ADMIN_HUB.md": "Project Admin\n",
    }.items():
        (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "--", "AGENTS.md", "docs")
    git(repo, "commit", "-qm", "Synthetic first snapshot")
    first = git(repo, "rev-parse", "HEAD")
    vault = tmp_path / "Permanent Vault"
    initialize(repo, vault, first)
    # A real user's notes and Obsidian config are outside the managed tree.
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text('{"readable": true}', encoding="utf-8")
    (vault / "Personal Note.md").write_text("Never inspect or edit\n", encoding="utf-8")
    return repo, vault, first


def next_head(repo: Path) -> str:
    (repo / "docs" / "PROJECT_SPEC.md").write_text("# Specification\nVersion B\n", encoding="utf-8")
    git(repo, "add", "docs/PROJECT_SPEC.md")
    git(repo, "commit", "-qm", "New source")
    return git(repo, "rev-parse", "HEAD")


def test_aligned_report_reads_verified_snapshot_without_changes(source):
    repo, vault, first = source
    before_repo = git(repo, "status", "--porcelain")
    before_files = {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }
    report = compare(repo, vault, first)
    assert report["state"] == "aligned_to_supplied_sha"
    assert report["checkout_head"] == report["vault_snapshot"] == first
    assert report["github_master"]["sha"] == first
    assert report["github_master"]["source"] == "operator_supplied_not_verified"
    assert report["managed_integrity"] == "hash_consistent"
    assert report["comparisons"] == {
        "snapshot_vs_checkout": "same",
        "snapshot_vs_github": "same",
        "checkout_vs_github": "same",
    }
    assert report["refresh_authorized"] is False
    assert git(repo, "status", "--porcelain") == before_repo
    assert before_files == {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }


def test_snapshot_different_from_checkout_and_remote_is_not_called_behind(source):
    repo, vault, first = source
    newer = next_head(repo)
    report = compare(repo, vault, newer)
    assert report["state"] == "different"
    assert report["vault_snapshot"] == first
    assert report["checkout_head"] == newer
    assert report["comparisons"]["snapshot_vs_checkout"] == "different"
    assert report["comparisons"]["checkout_vs_github"] == "same"
    assert report["ancestry"] == "not_evaluated"
    assert "behind" not in report["state"]


def test_checkout_and_snapshot_same_but_supplied_github_differs(source):
    repo, vault, first = source
    second = next_head(repo)
    git(repo, "checkout", "-q", "--detach", first)
    report = compare(repo, vault, second)
    assert report["state"] == "different"
    assert report["comparisons"]["snapshot_vs_checkout"] == "same"
    assert report["comparisons"]["snapshot_vs_github"] == "different"
    assert report["comparisons"]["checkout_vs_github"] == "different"


def test_missing_github_sha_is_explicitly_unknown(source):
    repo, vault, first = source
    report = compare(repo, vault, None)
    assert report["state"] == "unknown"
    assert report["vault_snapshot"] == first
    assert report["github_master"] == {"sha": None, "source": "unknown"}
    assert report["comparisons"]["snapshot_vs_github"] == "unknown"
    assert report["refresh_authorized"] is False


def test_known_local_mismatch_remains_visible_without_remote_sha(source):
    repo, vault, first = source
    newer = next_head(repo)
    report = compare(repo, vault, None)
    assert report["state"] == "different"
    assert report["vault_snapshot"] == first
    assert report["checkout_head"] == newer
    assert report["comparisons"]["snapshot_vs_checkout"] == "different"
    assert report["comparisons"]["snapshot_vs_github"] == "unknown"


def test_rejects_malformed_source_sha_before_any_traversal(source, tmp_path):
    repo, vault, _ = source
    for malformed in ("1234", "f" * 39, "G" * 40, "A" * 40, "f" * 41):
        with pytest.raises(ValueError, match="GitHub head"):
            compare(tmp_path / "missing", vault, malformed)
    assert compare(repo, vault, None)["state"] == "unknown"


def test_rejects_tampered_managed_snapshot_and_does_not_repair_it(source):
    repo, vault, first = source
    managed_doc = vault / MANAGED / "docs" / "PROJECT_SPEC.md"
    # The generator deliberately makes managed docs read-only on Windows.
    managed_doc.chmod(0o666)
    managed_doc.write_text("Changed after sealing", encoding="utf-8")
    with pytest.raises(ValueError, match="Managed file changed"):
        compare(repo, vault, first)
    assert managed_doc.read_text(encoding="utf-8") == "Changed after sealing"


def test_rejects_unexpected_extra_managed_file_without_removing_it(source):
    repo, vault, first = source
    added = vault / MANAGED / "untracked.md"
    added.write_text("Someone changed managed source\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Untracked, missing, or unexpected"):
        compare(repo, vault, first)
    assert added.exists()


def test_rejects_missing_vault_and_vault_inside_checkout(source):
    repo, vault, first = source
    with pytest.raises(ValueError, match="Expected existing Vault"):
        compare(repo, vault.with_name("Missing Vault"), first)
    with pytest.raises(ValueError, match="Vault must not overlap"):
        compare(repo, repo / "inside", first)


def test_rejects_symlinked_managed_root_when_os_permits(source):
    repo, vault, first = source
    managed = vault / MANAGED
    moved = vault / "Copy of Managed"
    managed.rename(moved)
    try:
        managed.symlink_to(moved, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        moved.rename(managed)
        pytest.skip(f"Link creation not available on this runner: {exc}")
    with pytest.raises(ValueError, match="Refusing linked path"):
        compare(repo, vault, first)


def test_cli_prints_bounded_json_and_uses_distinct_outcomes(source, capsys):
    repo, vault, first = source
    args = ["--repo", str(repo), "--vault", str(vault)]
    assert main([*args, "--github-head", first]) == 0
    good = json.loads(capsys.readouterr().out)
    assert good["state"] == "aligned_to_supplied_sha"
    assert "Personal Note" not in json.dumps(good)
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["state"] == "unknown"
    assert main([*args, "--github-head", "bad"]) == 2
    assert "REFUSED: GitHub head" in capsys.readouterr().err


def test_no_external_network_or_mutating_git_calls(source, monkeypatch):
    repo, vault, first = source
    import check_obsidian_freshness as checker

    calls = []
    real_git = checker.git

    def recorded_git(target: Path, *args: str):
        calls.append(args)
        return real_git(target, *args)

    monkeypatch.setattr(checker, "git", recorded_git)
    assert checker.compare(repo, vault, first)["state"] == "aligned_to_supplied_sha"
    assert calls == [("rev-parse", "HEAD")]


def test_reviewable_plan_lists_only_changed_tracked_markdown(source):
    repo, vault, first = source
    before_note = (vault / "Personal Note.md").read_bytes()
    before_manifest = (vault / MANAGED / ".homehub-snapshot-manifest.json").read_bytes()
    newer = next_head(repo)
    (repo / "docs" / "NEW.md").write_text("New tracked docs", encoding="utf-8")
    (repo / "docs" / "README.md").unlink()
    (repo / "not-exported.log").write_text("not for documentation", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "More docs changed")
    newest = git(repo, "rev-parse", "HEAD")
    assert newest != newer
    result = plan_refresh(repo, vault, newest)
    assert result["refresh_authorized"] is False
    assert result["refresh_plan"] == {
        "state": "reviewable",
        "reason": "manual_operator_review_required",
        "paths": {
            "added": ["docs/NEW.md"],
            "modified": ["docs/PROJECT_SPEC.md"],
            "removed": ["docs/README.md"],
        },
        "counts": {"added": 1, "modified": 1, "removed": 1},
    }
    assert (vault / "Personal Note.md").read_bytes() == before_note
    assert (vault / MANAGED / ".homehub-snapshot-manifest.json").read_bytes() == before_manifest
    assert (vault / MANAGED / "docs" / "README.md").exists()
    assert git(repo, "status", "--porcelain") == ""
    assert first != newest


def test_plan_noop_when_already_at_current_git_sha(source):
    repo, vault, first = source
    result = plan_refresh(repo, vault, first)
    assert result["refresh_plan"] == {
        "state": "already_current",
        "reason": "no_refresh_needed",
        "paths": {},
        "counts": {},
    }
    assert result["refresh_authorized"] is False


def test_plan_blocks_missing_or_divergent_github_sha(source):
    repo, vault, first = source
    second = next_head(repo)
    assert (
        plan_refresh(repo, vault, None)["refresh_plan"]["reason"] == "no_authenticated_remote_sha"
    )
    assert (
        plan_refresh(repo, vault, first)["refresh_plan"]["reason"]
        == "checkout_differs_from_supplied_github_sha"
    )
    assert second != first


def test_plan_blocks_uncommitted_and_untracked_files(source):
    repo, vault, first = source
    head = next_head(repo)
    personal_file = repo / "never-index-me.txt"
    personal_file.write_text("secret-like local work", encoding="utf-8")
    report = plan_refresh(repo, vault, head)
    assert report["refresh_plan"]["reason"] == "checkout_has_local_changes"
    assert report["refresh_plan"]["paths"] is None
    assert "never-index-me" not in json.dumps(report)
    personal_file.unlink()
    (repo / "docs" / "PROJECT_SPEC.md").write_text("Local edit", encoding="utf-8")
    assert plan_refresh(repo, vault, head)["refresh_plan"]["reason"] == "checkout_has_local_changes"


def test_plan_blocks_nonancestor_snapshot_without_writing(source):
    repo, vault, first = source
    newer = next_head(repo)
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    git(repo, "rm", "-qr", "--cached", ".")
    git(repo, "add", "AGENTS.md", "docs")
    git(repo, "commit", "-qm", "Unrelated root")
    orphan = git(repo, "rev-parse", "HEAD")
    assert orphan not in (first, newer)
    report = plan_refresh(repo, vault, orphan)
    assert report["refresh_plan"]["reason"] == "snapshot_commit_not_verified_ancestor"
    assert report["refresh_authorized"] is False


def test_plan_refuses_modified_sealed_markdown(source):
    repo, vault, first = source
    second = next_head(repo)
    doc = vault / MANAGED / "docs" / "PROJECT_SPEC.md"
    doc.chmod(0o666)
    doc.write_text("not sealed", encoding="utf-8")
    with pytest.raises(ValueError, match="Managed file changed"):
        plan_refresh(repo, vault, second)


def test_plan_cli_report_is_bounded_and_never_calls_refresh(source, capsys):
    repo, vault, first = source
    second = next_head(repo)
    args = ["--repo", str(repo), "--vault", str(vault), "--github-head", second]
    assert main([*args, "--plan-refresh"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["refresh_plan"]["state"] == "reviewable"
    assert report["refresh_plan"]["paths"]["modified"] == ["docs/PROJECT_SPEC.md"]
    assert report["refresh_authorized"] is False
    assert "Personal Note" not in json.dumps(report)
    assert main(["--repo", str(repo), "--vault", str(vault), "--plan-refresh"]) == 1
    assert json.loads(capsys.readouterr().out)["refresh_plan"]["state"] == "blocked"


def test_plan_refuses_git_status_warnings_even_when_stdout_is_empty(source, monkeypatch):
    repo, vault, first = source
    second = next_head(repo)
    import check_obsidian_freshness as checker

    real_run = checker.subprocess.run

    def warning_status(argv, **kwargs):
        if "status" in argv and "--porcelain=v1" in argv:
            return subprocess.CompletedProcess(argv, 0, b"", b"permission warning")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(checker.subprocess, "run", warning_status)
    with pytest.raises(ValueError, match="cleanliness unverified"):
        plan_refresh(repo, vault, second)
    assert first != second


def test_plan_blocks_checkout_moved_during_preview(source, monkeypatch):
    repo, vault, first = source
    head = next_head(repo)
    import check_obsidian_freshness as checker

    original = checker._tracked_docs

    def tracked_then_move(target, sha):
        value = original(target, sha)
        if sha == head:
            git(repo, "checkout", "-q", "--detach", first)
        return value

    monkeypatch.setattr(checker, "_tracked_docs", tracked_then_move)
    result = plan_refresh(repo, vault, head)
    assert result["refresh_plan"]["reason"] == "checkout_moved_during_preview"
    assert result["refresh_plan"]["paths"] is None
    assert result["refresh_authorized"] is False
