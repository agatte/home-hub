#!/usr/bin/env python3
"""Build an isolated, source-preserving Obsidian preview of tracked HomeHub Markdown.

No network, installs, credentials, source writes, sync, or deletion. Only Git HEAD's
regular Markdown blobs from docs/ and AGENTS.md are exported.
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024

LANDING = """# HomeHub Knowledge — preview

> **Read-only relative to the repository.** This is an isolated, dated export of
> Git-tracked Markdown from one commit. It is **not** the authoritative HomeHub
> repository, live deployment state, or a second task tracker. Edits here do
> not update GitHub or the source files. Do not enable Sync, Publish, or
> community plugins for this pilot.

## Start here

- [Project Admin Hub](docs/PROJECT_ADMIN_HUB.md) — find the current authority
- [Documentation index](docs/README.md) — architecture and subsystem links
- [Product specification](docs/PROJECT_SPEC.md) — accepted product contract
- [Execution map](docs/EXECUTION_MAP.md) — sequencing and dependencies
- [Future development](docs/Future_Development.md) — speculative ideas
- [Agent rules](AGENTS.md) — safety and workflow boundaries

## Project management (live, outside the snapshot)

- [HomeHub GitHub Projects board](https://github.com/users/agatte/projects/1)
- [Open GitHub issues](https://github.com/agatte/home-hub/issues?q=is%3Aissue%20is%3Aopen)
- [Open pull requests](https://github.com/agatte/home-hub/pulls)

## What this preview intentionally does not do

- No `.env`, credentials, database, media, raw logs, or arbitrary repo files
- No bidirectional sync or repo mutations; no automated Git commands from Obsidian
- No promise that today's CI, issues, or production match the exported commit
- Non-Markdown attachments referenced in docs will not be copied

Open this folder in Obsidian using **Open folder as vault**. Obsidian may create
its own `.obsidian` settings directory in the preview only, never in the repo.
To refresh, generate a **new uniquely named** preview folder rather than
rewriting an existing one.
"""


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=40,
    )
    return result.stdout


def tracked_markdown(repo: Path) -> tuple[str, list[tuple[PurePosixPath, bytes]]]:
    head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    records = git(repo, "ls-tree", "-rz", "--full-tree", head, "--", "AGENTS.md", "docs")
    result: list[tuple[PurePosixPath, bytes]] = []
    total = 0
    for record in records.split(b"\0"):
        if not record:
            continue
        try:
            meta, encoded_name = record.split(b"\t", 1)
            mode, kind, _oid = meta.split(b" ", 2)
            name = encoded_name.decode("utf-8", "strict")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid Git tree entry") from exc
        rel = PurePosixPath(name)
        if not (name == "AGENTS.md" or name.startswith("docs/")):
            continue
        if rel.is_absolute() or ".." in rel.parts or "\\" in name:
            raise ValueError("Unsafe path in tracked tree")
        if rel.suffix.lower() != ".md" or kind != b"blob" or mode not in (b"100644", b"100755"):
            continue
        data = git(repo, "show", f"{head}:{name}")
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Preview exceeds bounded Markdown size")
        result.append((rel, data))
    if not {"docs/PROJECT_ADMIN_HUB.md", "docs/README.md", "docs/PROJECT_SPEC.md"}.issubset(
        {str(p) for p, _ in result}
    ):
        raise ValueError("Not a compatible HomeHub Markdown tree")
    return head, result


def outside_repo(repo: Path, output: Path) -> None:
    repo = repo.resolve(strict=True)
    output = output.resolve(strict=False)
    if repo == output or repo in output.parents or output in repo.parents:
        raise ValueError("Preview destination must be separate from the repository")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Preview destination already exists; refusing to overwrite")
    if not output.parent.is_dir():
        raise ValueError("Preview parent directory must already exist")
    # A sibling worktree isn't a descendant of the chosen source checkout.
    # Never permit an export to place untracked files in *any* Git worktree.
    probe = subprocess.run(
        ["git", "-C", str(output.parent), "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if probe.returncode == 0:
        raise ValueError("Preview destination must be outside every Git worktree")


def create(repo: Path, output: Path) -> tuple[str, int]:
    outside_repo(repo, output)
    head, files = tracked_markdown(repo)
    # Everything is prevalidated before the first write. A failed partial export
    # is intentionally preserved for inspection, not recursively cleaned up.
    output.mkdir(mode=0o700)
    for relative, data in files:
        target = output.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    (output / "00-START-HERE.md").write_text(LANDING, encoding="utf-8")
    (output / "SNAPSHOT.md").write_text(
        f"# Preview provenance\n\nSource Git commit: `{head}`.\n\n"
        f"Exported Git-tracked Markdown files: **{len(files)}**.\n\n"
        "This is an isolated copy, not a live-status verification.\n",
        encoding="utf-8",
    )
    return head, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="HomeHub repo root")
    parser.add_argument(
        "--output", type=Path, required=True, help="New nonexisting preview folder OUTSIDE repo"
    )
    args = parser.parse_args(argv)
    try:
        head, count = create(args.repo, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Obsidian preview created: {args.output} ({count} tracked Markdown files; Git {head})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
