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


def changed_pr_paths(base: str, head: str = "HEAD") -> list[str] | None:
    """Get exact names relative to PR base; no rename can hide a moved old path."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base):
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
             base, head, "--"],
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
    parser.add_argument("--base", default="")
    args = parser.parse_args()

    paths = changed_pr_paths(args.base) if args.event == "pull_request" else None
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
