#!/usr/bin/env python3
"""Read-only comparison of HomeHub's Git HEAD and sealed Obsidian snapshot (#365).

The GitHub master SHA is an explicit, externally verified input: this script
does NOT connect to GitHub or authenticate the supplied reference. It neither
updates the checkout nor refreshes the Vault, schedules tasks, or removes backups.
Do not interpret a matching SHA as production deployment or reboot acceptance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

from create_obsidian_pilot import git
from manage_obsidian_vault import MANAGED, SHA40, safe_vault_path, verify_sealed


def compare(repo: Path, vault: Path, github_head: str | None) -> dict[str, object]:
    """Inspect only the designated checkout and sealed managed subtree."""
    if github_head is not None and not SHA40.fullmatch(github_head):
        raise ValueError("GitHub head must be exactly 40 lowercase hex characters")
    safe_vault_path(repo, vault)
    if not vault.is_dir():
        raise ValueError("Expected existing Vault directory")
    checkout = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    if not SHA40.fullmatch(checkout):
        raise ValueError("Invalid checkout HEAD")
    manifest = verify_sealed(vault / MANAGED)
    snapshot = manifest["source_commit"]

    equality = {
        "snapshot_vs_checkout": "same" if snapshot == checkout else "different",
        "snapshot_vs_github": (
            "unknown" if github_head is None else "same" if snapshot == github_head else "different"
        ),
        "checkout_vs_github": (
            "unknown" if github_head is None else "same" if checkout == github_head else "different"
        ),
    }
    if equality["snapshot_vs_checkout"] == "different":
        state = "different"
    elif github_head is None:
        state = "unknown"
    elif all(result == "same" for result in equality.values()):
        state = "aligned_to_supplied_sha"
    else:
        state = "different"
    return {
        "schema": 1,
        "read_only": True,
        "state": state,
        "github_master": {
            "sha": github_head,
            "source": "operator_supplied_not_verified" if github_head else "unknown",
        },
        "checkout_head": checkout,
        "vault_snapshot": snapshot,
        "managed_integrity": "hash_consistent",
        "comparisons": equality,
        "ancestry": "not_evaluated",
        "refresh_authorized": False,
        "note": (
            "SHA equality is not proof of remote authenticity, clean checkout, "
            "runtime deployment, Obsidian app closure, or reboot durability."
        ),
    }


def _tracked_docs(repo: Path, sha: str) -> dict[str, str]:
    """Read only Git tree metadata for the snapshot's regular Markdown allowlist."""
    entries = git(repo, "ls-tree", "-rz", "--full-tree", sha, "--", "AGENTS.md", "docs")
    result: dict[str, str] = {}
    for record in entries.split(b"\0"):
        if not record:
            continue
        try:
            meta, raw_name = record.split(b"\t", 1)
            mode, kind, oid = meta.split(b" ", 2)
            name = raw_name.decode("utf-8", "strict")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Malformed tracked Git tree entry") from exc
        if name != "AGENTS.md" and not name.startswith("docs/"):
            continue
        pure = PurePosixPath(name)
        if pure.suffix.lower() != ".md":
            continue
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or pure.as_posix() != name
            or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
        ):
            raise ValueError("Unsafe tracked Markdown path")
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Tracked Markdown is not a regular Git blob")
        if name in result:
            raise ValueError("Duplicate tracked Markdown path")
        result[name] = oid.decode("ascii", "strict")
    if len(result) > 500:
        raise ValueError("Tracked Markdown list exceeds limit")
    return result


def _checkout_has_changes(repo: Path) -> bool:
    """Treat Git status warnings as inconclusive, not as a clean checkout."""
    scan = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo}",
            "-C",
            str(repo),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=40,
    )
    if scan.stderr:
        raise ValueError("Git reported checkout scan warnings; cleanliness unverified")
    return bool(scan.stdout)


def plan_refresh(repo: Path, vault: Path, github_head: str | None) -> dict[str, object]:
    """Advisory-only preview. Never infer approval to run the existing writer."""
    report = compare(repo, vault, github_head)
    preview: dict[str, object] = {
        "state": "blocked",
        "reason": "no_authenticated_remote_sha",
        "paths": None,
        "counts": None,
    }
    report["refresh_plan"] = preview
    if github_head is None:
        return report
    checkout = report["checkout_head"]
    snapshot = report["vault_snapshot"]
    if checkout != github_head:
        preview["reason"] = "checkout_differs_from_supplied_github_sha"
        return report
    # Even a doc-only preview must not invite a refresh from dirty/untracked work.
    if _checkout_has_changes(repo):
        preview["reason"] = "checkout_has_local_changes"
        return report
    if snapshot == checkout:
        preview.update(state="already_current", reason="no_refresh_needed", paths={}, counts={})
        return report
    try:
        git(repo, "merge-base", "--is-ancestor", snapshot, checkout)
    except subprocess.CalledProcessError:
        preview["reason"] = "snapshot_commit_not_verified_ancestor"
        return report
    old = _tracked_docs(repo, snapshot)
    new = _tracked_docs(repo, checkout)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    modified = sorted(path for path in set(old) & set(new) if old[path] != new[path])
    preview.update(
        state="reviewable",
        reason="manual_operator_review_required",
        paths={"added": added, "modified": modified, "removed": removed},
        counts={"added": len(added), "modified": len(modified), "removed": len(removed)},
    )
    # A concurrent Git checkout change invalidates the proposed file list.
    if git(repo, "rev-parse", "HEAD").decode("ascii").strip() != checkout:
        preview.update(
            state="blocked", reason="checkout_moved_during_preview", paths=None, counts=None
        )
    elif _checkout_has_changes(repo):
        preview.update(
            state="blocked", reason="checkout_changed_during_preview", paths=None, counts=None
        )
    # A plan is never an authorization or a write; no command execution is offered.
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Existing HomeHub Git checkout")
    parser.add_argument("--vault", type=Path, required=True, help="Existing Obsidian Vault root")
    parser.add_argument(
        "--github-head",
        help="Independently verified GitHub master SHA (not fetched by this command)",
    )
    parser.add_argument(
        "--plan-refresh", action="store_true", help="Advisory-only changed-doc path preview"
    )
    args = parser.parse_args(argv)
    try:
        result = (
            plan_refresh(args.repo, args.vault, args.github_head)
            if args.plan_refresh
            else compare(args.repo, args.vault, args.github_head)
        )
    except (
        OSError,
        ValueError,
        UnicodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    print(json.dumps(result, sort_keys=True))
    if args.plan_refresh:
        return 0 if result["refresh_plan"]["state"] in {"reviewable", "already_current"} else 1
    return 0 if result["state"] == "aligned_to_supplied_sha" else 1


if __name__ == "__main__":
    sys.exit(main())
