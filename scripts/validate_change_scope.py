#!/usr/bin/env python3
"""Suggest validation commands from the files changed in a Home Hub diff.

This is intentionally advisory. It ports the Claude issue-to-test checklist into a
repo-native tool that Codex, Claude, or a human can run before pushing.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: tuple[str, ...]
    checks: tuple[str, ...]
    notes: tuple[str, ...] = ()


RULES: tuple[Rule, ...] = (
    Rule(
        name="Backend Python",
        patterns=("backend/*.py", "backend/**/*.py", "run.py"),
        checks=("python -m ruff check backend/",),
    ),
    Rule(
        name="Backend routes/API",
        patterns=("backend/main.py", "backend/routes/**/*.py", "backend/api/**/*.py"),
        checks=("python -m pytest tests -q",),
        notes=(
            "Cover happy path, write gate/auth, bad input, and source attribution where relevant.",
        ),
    ),
    Rule(
        name="Automation/services",
        patterns=("backend/services/**/*.py",),
        checks=("python -m pytest tests/test_automation_engine.py -q",),
        notes=(
            "Use fake hardware tests for side effects, dedup/override state, callbacks, and event logging.",
        ),
    ),
    Rule(
        name="Lighting behavior",
        patterns=(
            "backend/services/*light*.py",
            "backend/services/*hue*.py",
            "backend/services/*scene*.py",
            "backend/services/automation_engine.py",
            "tests/test_*light*.py",
            "tests/test_automation_engine.py",
            "frontend-svelte/src/**/*Light*",
            "frontend-svelte/src/**/*light*",
        ),
        checks=(
            "python -m pytest tests/test_automation_engine.py tests/test_transit_lighting_service.py tests/test_desk_exit_kitchen_service.py tests/test_screen_sync_multi.py -q",
        ),
        notes=(
            "Review lighting changes against the lighting-curator rubric and reference photos before commit.",
        ),
    ),
    Rule(
        name="ML/fusion/source trust",
        patterns=(
            "backend/services/*ml*.py",
            "backend/services/*fusion*.py",
            "backend/services/*confidence*.py",
            "backend/services/*source*.py",
            "tests/test_*ml*.py",
            "tests/test_*fusion*.py",
            "tests/test_*source*.py",
        ),
        checks=("python -m pytest tests -q",),
        notes=(
            "Include stale-signal behavior, deterministic fixtures, persistence, and trust guardrails.",
        ),
    ),
    Rule(
        name="Scheduler/background task",
        patterns=(
            "backend/services/*scheduler*.py",
            "backend/services/*background*.py",
            "backend/services/*task*.py",
            "backend/services/*logger*.py",
        ),
        checks=("python -m pytest tests -q",),
        notes=(
            "Check registration, manual trigger, idempotency, failure logging, and health visibility.",
        ),
    ),
    Rule(
        name="Tests",
        patterns=("tests/*.py", "tests/**/*.py"),
        checks=("python -m pytest <targeted test files> -q",),
        notes=(
            "Use the smallest pytest set that covers the changed behavior; broaden when touching shared contracts.",
        ),
    ),
    Rule(
        name="Frontend",
        patterns=("frontend-svelte/**/*",),
        checks=("cd frontend-svelte && npm run check", "cd frontend-svelte && npm run test"),
    ),
    Rule(
        name="Frontend 3D/layout",
        patterns=(
            "frontend-svelte/src/**/*.svelte",
            "frontend-svelte/src/**/*three*",
            "frontend-svelte/src/**/*threlte*",
        ),
        checks=("cd frontend-svelte && npm run check",),
        notes=("Use browser/screenshot verification for layout-heavy or Three.js changes.",),
    ),
    Rule(
        name="Ops/deploy/live system",
        patterns=(
            ".gitattributes",
            ".githooks/*",
            "scripts/*.py",
            "scripts/**/*.py",
            "scripts/deploy.sh",
            "deployment/**/*",
            "docker/**/*",
            ".github/workflows/**/*",
        ),
        checks=("python -m ruff check backend/",),
        notes=(
            "Prefer dry-run/read-only verification first, then exact post-deploy endpoints or queries.",
        ),
    ),
    Rule(
        name="Docs-only",
        patterns=("*.md", "docs/**/*.md", "AGENTS.md", "CODEX_TODO.md"),
        checks=("No runtime tests required unless commands/config examples changed.",),
    ),
)


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def default_base() -> str:
    for ref in ("origin/master", "origin/main", "master", "main"):
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", ref],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            continue
        try:
            return run_git(["merge-base", "HEAD", ref])
        except subprocess.CalledProcessError:
            return ref
    return "HEAD"


def untracked_files() -> str:
    return run_git(["ls-files", "--others", "--exclude-standard"])


def changed_files(args: argparse.Namespace) -> list[str]:
    if args.files:
        return sorted({normalize_path(item) for item in args.files})

    if args.staged:
        output = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    elif args.all:
        output = "\n".join(
            part
            for part in (
                run_git(["diff", "--name-only", "--diff-filter=ACMR", "HEAD"]),
                untracked_files(),
            )
            if part
        )
    else:
        base = args.base or default_base()
        output = run_git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"])
        uncommitted = run_git(["diff", "--name-only", "--diff-filter=ACMR"])
        output = "\n".join(part for part in (output, uncommitted, untracked_files()) if part)

    return sorted({normalize_path(line) for line in output.splitlines() if line.strip()})


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern)


def rule_matches(rule: Rule, files: list[str]) -> bool:
    return any(matches(path, pattern) for path in files for pattern in rule.patterns)


def is_docs_only(files: list[str]) -> bool:
    docs_rule = next(rule for rule in RULES if rule.name == "Docs-only")
    return bool(files) and all(
        any(matches(path, pattern) for pattern in docs_rule.patterns) for path in files
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Optional explicit file paths to classify.")
    parser.add_argument(
        "--base",
        help="Base ref for committed branch diff. Defaults to merge-base with origin/master.",
    )
    parser.add_argument("--staged", action="store_true", help="Only inspect staged files.")
    parser.add_argument(
        "--all", action="store_true", help="Inspect all tracked changes against HEAD."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if changed files do not match any rule.",
    )
    args = parser.parse_args()

    files = changed_files(args)
    if not files:
        print("No changed files detected.")
        return 0

    matched = [rule for rule in RULES if rule_matches(rule, files)]

    print("Changed files:")
    for path in files:
        print(f"  - {path}")

    if is_docs_only(files):
        matched = [rule for rule in matched if rule.name == "Docs-only"]

    print("\nRecommended validation:")
    commands: list[str] = []
    notes: list[str] = []
    for rule in matched:
        print(f"\n[{rule.name}]")
        for check in rule.checks:
            if check not in commands:
                commands.append(check)
                print(f"  - {check}")
        for note in rule.notes:
            if note not in notes:
                notes.append(note)
                print(f"  note: {note}")

    unmatched = [
        path
        for path in files
        if not any(matches(path, pattern) for rule in RULES for pattern in rule.patterns)
    ]
    if unmatched:
        print("\nUnclassified files:")
        for path in unmatched:
            print(f"  - {path}")
        print("Add a rule if this path becomes common enough to deserve standard validation.")

    return 1 if args.strict and unmatched else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or str(exc)
        print(f"git command failed: {message}", file=sys.stderr)
        raise SystemExit(2)
