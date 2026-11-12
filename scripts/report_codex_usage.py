"""Read-only, aggregate Codex task usage from the HomeHub Sandbox registry.

Only reads task.json, state.json, and turn.completed usage in attempt event logs.
Never reads prompt files, model responses, commands, credentials or a Codex config.
Token counts are CLI telemetry, NOT account billing or rate-limit balances.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

DEFAULT_REGISTRY = Path(r"C:\Work\PC-Performance-Audit\.rdc-sandbox-state\codex-runs")
TASK_ID = re.compile(r"[0-9a-f]{32}\Z")
MODEL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z")
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")
MAX_METADATA_BYTES = 128 * 1024
MAX_EVENT_LINE = 2 * 1024 * 1024


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing UTC timestamp")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("timezone required")
    return date.astimezone(timezone.utc)


def _metadata(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("invalid metadata file")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("metadata must be an object")
    return result


def _usage_logs(task_folder: Path) -> tuple[dict[str, int], int]:
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    turns = 0
    for attempt in task_folder.glob("attempt-*"):
        if attempt.is_symlink() or not attempt.is_dir():
            continue
        events = attempt / "events.jsonl"
        if events.is_symlink() or not events.is_file():
            continue
        with events.open(encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                if len(line) > MAX_EVENT_LINE:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "turn.completed":
                    continue
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    continue
                fields = [usage.get(name) for name in TOKEN_FIELDS]
                if any(type(value) is not int or value < 0 for value in fields):
                    continue
                if fields[1] > fields[0]:
                    continue
                turns += 1
                for name, value in zip(TOKEN_FIELDS, fields):
                    totals[name] += value
    return totals, turns


def summarize(registry: Path, now: datetime, days: int = 7) -> dict:
    """Aggregate metadata only. No individual task IDs, prompts or paths in output."""
    if days < 1 or days > 90:
        raise ValueError("days must be from 1 to 90")
    if registry.is_symlink() or not registry.is_dir():
        raise ValueError("registry directory is missing or unsafe")
    now = now.astimezone(timezone.utc)
    since = now - timedelta(days=days)
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    modes: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    explicit_models: Counter[str] = Counter()
    tasks = 0
    tasks_without_usage = 0
    skipped_invalid = 0
    turns = 0

    for folder in registry.iterdir():
        if not TASK_ID.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        try:
            task = _metadata(folder / "task.json")
            created = _timestamp(task.get("created_utc"))
            if not since <= created <= now:
                continue
            mode = task.get("mode")
            if mode not in ("Read", "Write"):
                raise ValueError("unknown task mode")
            state = _metadata(folder / "state.json")
            status = state.get("status")
            if not isinstance(status, str) or status not in (
                "completed", "failed", "superseded", "queued", "running",
                "interrupted-or-unverified", "queued-stale",
            ):
                status = "unknown"
            used, nturns = _usage_logs(folder)
        except (OSError, ValueError, TypeError, UnicodeError):
            skipped_invalid += 1
            continue
        tasks += 1
        modes[mode] += 1
        statuses[status] += 1
        dates[created.date().isoformat()] += 1
        turns += nturns
        if nturns == 0:
            tasks_without_usage += 1
        model = task.get("model")
        if isinstance(model, str) and MODEL_NAME.fullmatch(model):
            explicit_models[model] += 1
        else:
            explicit_models["launcher default (unresolved)"] += 1
        for name in TOKEN_FIELDS:
            totals[name] += used[name]

    input_total = totals["input_tokens"]
    cached = totals["cached_input_tokens"]
    return {
        "window_utc": {"from": since.isoformat(), "to": now.isoformat()},
        "tasks": tasks,
        "modes": dict(sorted(modes.items())),
        "statuses": dict(sorted(statuses.items())),
        "tasks_without_usage": tasks_without_usage,
        "skipped_invalid_task_records": skipped_invalid,
        "tasks_by_utc_day": dict(sorted(dates.items())),
        "requested_model_overrides": dict(sorted(explicit_models.items())),
        "turns_with_usage": turns,
        "tokens": {
            **totals,
            "uncached_input_tokens": input_total - cached,
            "cached_input_fraction": round(cached / input_total, 4) if input_total else None,
        },
        "interpretation": (
            "CLI usage, not billing, remaining quota or verified resolved model. "
            "Cached input is included in input_tokens; do not add them together."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        result = summarize(args.registry, datetime.now(timezone.utc), args.days)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
