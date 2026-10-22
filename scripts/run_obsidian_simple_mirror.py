"""Off-by-default one-shot evaluation; no host approval or scheduling implied."""

from __future__ import annotations

import sys

# Direct CLI execution must not create import caches, including in check mode.
sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path

from obsidian_github_docs_source import SourceUnavailable, github_json, prepare_current_docs
from obsidian_raw_blob_transport import github_raw_blob
from obsidian_simple_mirror import _guard, _refuse_active_evidence, _sealed, run_once


def exact_path(raw: str) -> Path:
    """Reject spelling normalization, relative paths and Windows device aliases."""
    path = Path(raw)
    if (not path.is_absolute() or str(path) != raw or path.anchor.startswith("\\\\")
            or ".." in path.parts or path == path.parent):
        raise ValueError("invalid_exact_path")
    devices = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    devices.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³")
    if any("~" in part or part.split(".", 1)[0].upper() in devices
           for part in path.parts[1:]):
        raise ValueError("ambiguous_path")
    return path


def main(argv=None, *, fetch=None, blob_source=None, output=None) -> int:
    """Emit bounded JSON; transports are injectable for offline fixture tests.

    Exit 0: no change/updated, 1: update available, 2: refused,
    3: source unavailable, 4: operation failed (retain evidence for review).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--expected-vault", required=True)
    parser.add_argument("--approve-local-evaluation", action="store_true")
    args = parser.parse_args(argv)
    # Only the production default selects raw content. Injected API fixtures
    # retain their in-memory REST blobs unless they also inject a blob source.
    if fetch is None:
        fetch = github_json
        if blob_source is None:
            blob_source = github_raw_blob
    report = {}
    try:
        vault, expected = exact_path(args.vault), exact_path(args.expected_vault)
        if args.apply and not args.approve_local_evaluation:
            raise ValueError("approval_missing")
        if args.check and args.approve_local_evaluation:
            raise ValueError("check_does_not_accept_write_approval")
        # Validate before either network acquisition or the single writer call.
        managed = _guard(vault, expected)
        _refuse_active_evidence(vault)
        old = _sealed(managed)["source_commit"]
        if args.check:
            prepared = prepare_current_docs(old, fetch=fetch, blob_source=blob_source)
            state = "no_change" if prepared.intended_commit == old else "update_available"
            report = {"status": state, "previous_commit": old,
                      "commit": prepared.intended_commit}
        else:
            result = run_once(vault=vault, expected_vault=expected,
                              local_evaluation_approved=True, fetch=fetch,
                              blob_source=blob_source)
            state = result.state
            report = {"status": state, "previous_commit": result.previous_commit,
                      "commit": result.commit}
        code = 1 if state == "update_available" else 0
    except SourceUnavailable:
        report, code = {"status": "source_unavailable"}, 3
    except (ValueError, OSError):
        report, code = {"status": "refused_or_failed_review_evidence"}, 2
    except Exception:
        # Never echo exception messages, transport payloads, paths or file content.
        report, code = {"status": "operation_failed_review_evidence"}, 4
    print(json.dumps(report, sort_keys=True), file=output or sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
