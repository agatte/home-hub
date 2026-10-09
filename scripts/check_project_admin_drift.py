#!/usr/bin/env python3
"""Read-only HomeHub project-status drift report (Project Admin #339).

This checker is advisory by default. It compares living GitHub issue state
against a few *current* routes in the docs, never historical audit snapshots,
and never infers deployment, production health, or physical acceptance.
No GitHub mutations, working-tree writes, or project-board changes occur.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO = "agatte/home-hub"
ISSUE_LINK = re.compile(r"https://github\.com/agatte/home-hub/issues/([0-9]+)")
CLOSED_PACKET = re.compile(r"^### #([0-9]+).*\(closed implementation\)", re.MULTILINE)
LAST_RECONCILED = re.compile(
    r"^> \*\*Last reconciled:\*\* ([0-9]{4}-[0-9]{2}-[0-9]{2})", re.MULTILINE
)
PHYSICAL_GATE_TITLE = re.compile(r"^Post-deploy physical acceptance:", re.IGNORECASE)
CURRENT_HEADING = "## Current gate-aware routing"


def current_section(markdown: str) -> str:
    start = markdown.find(CURRENT_HEADING)
    if start < 0:
        raise ValueError("Current gate-aware routing heading is missing")
    subsequent = markdown.find("\n## ", start + len(CURRENT_HEADING))
    return markdown[start : subsequent if subsequent >= 0 else None]


def actionable_issues(markdown: str) -> set[int]:
    """Only first-column issue links in the current routing table are actionable."""
    ids: set[int] = set()
    for line in current_section(markdown).splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        first_cell = line.split("|", 2)[1]
        ids.update(int(n) for n in ISSUE_LINK.findall(first_cell))
    if not ids:
        raise ValueError("Current routing table has no linked issue owners")
    return ids


def normalize_issues(raw: object) -> dict[int, dict]:
    if isinstance(raw, dict):
        raw = raw.get("issues")
    if not isinstance(raw, list):
        raise ValueError("Snapshot must be a list of issues or {'issues': [...]} ")
    found: dict[int, dict] = {}
    for issue in raw:
        if not isinstance(issue, dict):
            raise ValueError("Invalid issue in snapshot")
        if "pull_request" in issue:
            continue
        number = issue.get("number", issue.get("issue_number"))
        state = issue.get("state")
        if type(number) is not int or state not in ("open", "closed"):
            raise ValueError("Issue number/state missing or invalid in snapshot")
        if number in found:
            raise ValueError(f"Duplicate issue #{number} in snapshot")
        found[number] = issue
    if not found:
        raise ValueError("No issues in snapshot")
    return found


def fetch_issues(repository: str = REPO) -> dict[int, dict]:
    """GET issue metadata only, bounded pagination, no token/body in output."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    issues: list[dict] = []
    for page in range(1, 21):
        url = f"https://api.github.com/repos/{repository}/issues?state=all&per_page=100&page={page}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "HomeHub-Project-Admin-Drift",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=15
            ) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"GitHub issue read failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError(f"GitHub issue read unavailable ({type(exc).__name__})") from None
        if not isinstance(payload, list):
            raise ValueError("GitHub did not return an issue list")
        issues.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return normalize_issues(issues)
    raise ValueError("Issue pagination limit exceeded; refusing partial results")


def audit(
    hub: str, execution_map: str, issues: dict[int, dict], today: date, max_age_days: int = 30
) -> tuple[list[str], list[str]]:
    drift: list[str] = []
    notices: list[str] = []
    current_ids = actionable_issues(execution_map)

    for number in sorted(current_ids):
        issue = issues.get(number)
        if issue is None:
            drift.append(f"Current route #{number}: no issue result")
        elif issue["state"] != "open":
            drift.append(f"Current route #{number}: issue is {issue['state']}, not open")

    for match in CLOSED_PACKET.finditer(execution_map):
        number = int(match.group(1))
        issue = issues.get(number)
        if issue is None:
            drift.append(f"Closed implementation packet #{number}: no issue result")
        elif issue["state"] != "closed":
            drift.append(f"Closed implementation packet #{number}: issue is {issue['state']}")

    # A gate created after the implementation issue was closed must be navigable
    # from current documentation. This deliberately does not attempt to guess
    # a physical test's pass/fail or whether the release actually happened.
    current_refs = set(map(int, ISSUE_LINK.findall(hub + "\n" + current_section(execution_map))))
    for number, issue in sorted(issues.items()):
        if issue["state"] != "open" or not PHYSICAL_GATE_TITLE.match(str(issue.get("title", ""))):
            continue
        if number not in current_refs:
            drift.append(f"Open physical gate #{number}: missing current navigation link")

    match = LAST_RECONCILED.search(execution_map)
    if not match:
        drift.append("EXECUTION_MAP: missing Last reconciled YYYY-MM-DD header")
    else:
        checkpoint = date.fromisoformat(match.group(1))
        days_old = (today - checkpoint).days
        if days_old < 0:
            drift.append(f"EXECUTION_MAP: checkpoint {checkpoint} is in the future")
        elif days_old > max_age_days:
            notices.append(f"EXECUTION_MAP: checkpoint is {days_old} days old; review when useful")

    if "GitHub Projects board existence/configuration has **not** been verified" in hub:
        notices.append("GitHub Projects board inventory remains an explicitly unverified gate")

    return drift, notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path, help="Offline JSON issue metadata fixture")
    source.add_argument("--live", action="store_true", help="Read GitHub issues (no writes)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--strict", action="store_true", help="Exit 1 when drift is detected")
    args = parser.parse_args(argv)

    if args.max_age_days < 0:
        parser.error("--max-age-days cannot be negative")
    try:
        hub = (args.root / "docs" / "PROJECT_ADMIN_HUB.md").read_text(encoding="utf-8")
        execution_map = (args.root / "docs" / "EXECUTION_MAP.md").read_text(encoding="utf-8")
        raw = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else None
        issues = normalize_issues(raw) if args.snapshot else fetch_issues()
        drift, notices = audit(hub, execution_map, issues, args.as_of, args.max_age_days)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for msg in drift:
        print(f"DRIFT: {msg}")
    for msg in notices:
        print(f"NOTICE: {msg}")
    print(f"Project Admin read-only check: {len(drift)} drift finding(s), {len(notices)} notice(s)")
    return 1 if drift and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
