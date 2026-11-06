"""Conservative PR test routing: skip expensive suites only for known safe paths.

Unrecognized paths, missing PR ancestry, subprocess failures and ambiguous diffs
all run the complete checks. This script never selects individual backend tests.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


def classify_paths(paths: list[str] | None) -> tuple[bool, bool, str]:
    """Return (backend, frontend, reason). Both True means full CI."""
    if not paths:
        return True, True, "empty-or-unavailable-diff"

    frontend = False
    for path in paths:
        if not path or "\\" in path or path.startswith("/") or ".." in path.split("/"):
            return True, True, "invalid-path"
        if path.startswith("frontend-svelte/") and len(path) > len("frontend-svelte/"):
            frontend = True
        elif path.startswith("docs/") and path.endswith((".md", ".mdx")):
            continue
        elif "/" not in path and path.endswith((".md", ".mdx")):
            continue
        else:
            return True, True, "shared-or-unknown-path"

    if frontend:
        return False, True, "frontend-and-optional-docs-only"
    return False, False, "docs-only"


def changed_pr_paths(pr_head: str, merge_sha: str, checkout: str = "HEAD") -> list[str] | None:
    """Diff GitHub's verified PR merge against its *actual* target parent.

    The pull_request.base.sha event field can be stale on long-lived PRs.
    actions/checkout uses a synthetic merge with current base as first parent
    and PR head as second. Never trust those parents without verifying both
    GitHub-provided SHAs; missing or ambiguous ancestry triggers full CI.
    """
    sha = r"[0-9a-fA-F]{40}"
    if not re.fullmatch(sha, pr_head) or not re.fullmatch(sha, merge_sha):
        return None
    try:
        ancestry = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", checkout],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if ancestry.returncode != 0:
            return None
        parts = ancestry.stdout.decode("ascii", errors="strict").split()
        if (len(parts) != 3
                or any(not re.fullmatch(sha, part) for part in parts)
                or parts[0].lower() != merge_sha.lower()
                or parts[2].lower() != pr_head.lower()):
            return None

        # Compare the merged tree (including conflict resolutions) to the
        # exact base tree used by GitHub, not a potentially stale event base.
        result = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
             parts[1], parts[0], "--"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout
        if not raw.endswith(b"\0"):
            return None
        return [entry.decode("utf-8", errors="strict")
                for entry in raw[:-1].split(b"\0")]
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--pr-head", default="")
    parser.add_argument("--merge-sha", default="")
    args = parser.parse_args()

    paths = (changed_pr_paths(args.pr_head, args.merge_sha)
             if args.event == "pull_request" else None)
    backend, frontend, reason = classify_paths(paths)
    if args.event != "pull_request":
        reason = "full-validation-event"

    values = {"backend": str(backend).lower(), "frontend": str(frontend).lower()}
    print(f"CI scope: {reason}; backend={values['backend']} frontend={values['frontend']}")
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
