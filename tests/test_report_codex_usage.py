"""Synthetic fixtures for the read-only, aggregation-only Codex usage report."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import report_codex_usage as report


NOW = datetime(2026, 11, 11, 22, 44, tzinfo=timezone.utc)


def make_task(registry, index, created=NOW, mode="Write", model="", status="completed",
              usage=None, extra_events=()):
    folder = registry / f"{index:032x}"
    folder.mkdir()
    (folder / "task.json").write_text(json.dumps({
        "created_utc": created.isoformat(), "mode": mode, "model": model,
        "user_prompt": "SECRET-NOT-FOR-REPORT",
        "workdir": r"C:\secret\worktree",
    }), encoding="utf-8")
    (folder / "state.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    (folder / "user-prompt.txt").write_text("PRIVATE-PROMPT-CONTENT", encoding="utf-8")
    (folder / "last-message.txt").write_text("PRIVATE-ANSWER-CONTENT", encoding="utf-8")
    if usage is not None:
        attempt = folder / "attempt-001"
        attempt.mkdir()
        events = [{"type": "turn.started"}] + list(extra_events) + [
            {"type": "turn.completed", "usage": usage},
        ]
        (attempt / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )
    return folder


def test_usage_is_aggregated_without_prompts_or_task_identifiers(tmp_path):
    make_task(tmp_path, 1, usage={
        "input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 70,
        "reasoning_output_tokens": 15,
    }, extra_events=[{"type": "item.completed", "payload": "SENSITIVE"}])
    make_task(tmp_path, 2, mode="Read", model="gpt-6-sol", usage={
        "input_tokens": 200, "cached_input_tokens": 50, "output_tokens": 30,
    })
    result = report.summarize(tmp_path, NOW)
    assert result["tasks"] == 2
    assert result["modes"] == {"Read": 1, "Write": 1}
    assert result["turns_with_usage"] == 2
    assert result["tokens"]["input_tokens"] == 1200
    assert result["tokens"]["cached_input_tokens"] == 950
    assert result["tokens"]["uncached_input_tokens"] == 250
    assert result["tokens"]["output_tokens"] == 100
    assert result["requested_model_overrides"] == {
        "gpt-6-sol": 1, "launcher default (unresolved)": 1
    }
    rendered = json.dumps(result)
    for secret in ("SENSITIVE", "PRIVATE", "SECRET", "worktree", "000000000000"):
        assert secret not in rendered


def test_window_and_zero_token_reporting(tmp_path):
    make_task(tmp_path, 1, created=NOW - timedelta(days=8), usage={
        "input_tokens": 25, "cached_input_tokens": 20, "output_tokens": 5,
    })
    make_task(tmp_path, 2, created=NOW + timedelta(seconds=1), usage={
        "input_tokens": 25, "cached_input_tokens": 20, "output_tokens": 5,
    })
    make_task(tmp_path, 3, created=NOW - timedelta(days=2), mode="Read", usage=None)
    result = report.summarize(tmp_path, NOW, days=7)
    assert result["tasks"] == 1
    assert result["tasks_without_usage"] == 1
    assert result["tokens"]["input_tokens"] == 0
    assert result["tokens"]["cached_input_fraction"] is None


def test_malformed_and_invalid_usage_is_skipped_without_crash(tmp_path):
    valid = make_task(tmp_path, 1, usage={
        "input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 20,
    })
    with (valid / "attempt-001" / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write(json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 10, "cached_input_tokens": 20, "output_tokens": 3,
        }}) + "\n")
        handle.write(json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": True, "cached_input_tokens": 0, "output_tokens": 1,
        }}) + "\n")
    bad = tmp_path / f"{2:032x}"
    bad.mkdir()
    (bad / "task.json").write_text("{invalid", encoding="utf-8")
    result = report.summarize(tmp_path, NOW)
    assert result["tasks"] == 1
    assert result["skipped_invalid_task_records"] == 1
    assert result["turns_with_usage"] == 1
    assert result["tokens"]["input_tokens"] == 100


def test_multiple_attempts_sum_consumed_tokens(tmp_path):
    folder = make_task(tmp_path, 1, usage={
        "input_tokens": 80, "cached_input_tokens": 75, "output_tokens": 5,
    })
    retry = folder / "attempt-002"
    retry.mkdir()
    (retry / "events.jsonl").write_text(json.dumps({
        "type": "turn.completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 90, "output_tokens": 10,
        },
    }), encoding="utf-8")
    totals = report.summarize(tmp_path, NOW)["tokens"]
    assert totals["input_tokens"] == 180
    assert totals["cached_input_tokens"] == 165
    assert totals["output_tokens"] == 15


@pytest.mark.parametrize("days", [0, -1, 91])
def test_invalid_windows_rejected(tmp_path, days):
    with pytest.raises(ValueError, match="days"):
        report.summarize(tmp_path, NOW, days=days)


def test_missing_registry_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="registry"):
        report.summarize(tmp_path / "absent", NOW)


def test_metadata_limits_and_unrecognized_model_are_not_leaked(tmp_path):
    make_task(tmp_path, 1, model="secret model string with spaces", usage={
        "input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 1,
    })
    folder = make_task(tmp_path, 2, usage=None)
    (folder / "task.json").write_text("X" * (report.MAX_METADATA_BYTES + 1), encoding="utf-8")
    result = report.summarize(tmp_path, NOW)
    assert result["tasks"] == 1
    assert result["skipped_invalid_task_records"] == 1
    assert result["requested_model_overrides"] == {"launcher default (unresolved)": 1}


def test_cli_outputs_json_only(tmp_path, capsys):
    make_task(tmp_path, 1, created=datetime.now(timezone.utc), usage={
        "input_tokens": 50, "cached_input_tokens": 40, "output_tokens": 9,
    })
    assert report.main(["--registry", str(tmp_path), "--days", "7"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"] == 1
    assert payload["tokens"]["uncached_input_tokens"] == 10
