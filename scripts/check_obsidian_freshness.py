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
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Existing HomeHub Git checkout")
    parser.add_argument("--vault", type=Path, required=True, help="Existing Obsidian Vault root")
    parser.add_argument(
        "--github-head",
        help="Independently verified GitHub master SHA (not fetched by this command)",
    )
    args = parser.parse_args(argv)
    try:
        result = compare(args.repo, args.vault, args.github_head)
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
    return 0 if result["state"] == "aligned_to_supplied_sha" else 1


if __name__ == "__main__":
    sys.exit(main())
