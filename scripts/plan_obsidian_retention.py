"""Read-only #399 proposal. No cleanup capability or source acquisition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from obsidian_simple_mirror import _guard, _plain, _sealed
from manage_obsidian_vault import MANIFEST

PREFIX = ".HomeHub Knowledge Vault-homehub-"
MEMBER = re.compile(re.escape(PREFIX) + r"(backup|completed-stage|complete)-([0-9a-f]{32})(\.json)?")
OID = re.compile(r"[0-9a-f]{40}")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _json(path, limit):
    _plain(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("invalid_or_oversized_metadata")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("oversized_metadata")
    return json.loads(raw, object_pairs_hook=_unique)


def _snapshot(path):
    _plain(path)
    metadata = _json(path / MANIFEST, 128 * 1024)
    if (not isinstance(metadata, dict)
            or set(metadata) != {"schema", "source_commit", "sha256"}
            or type(metadata["schema"]) is not int):
        raise ValueError("untrusted_manifest_schema")
    verified = _sealed(path)
    if metadata != verified:
        raise ValueError("snapshot_changed_during_verification")
    return verified


def _size(path, metadata):
    return sum((path / name).stat().st_size for name in [MANIFEST, *metadata["sha256"]])


def plan(vault: Path) -> dict:
    """Return a proposal only after every complete set passes; failures preserve all."""
    if vault.name != "HomeHub Knowledge Vault" or vault.parent.name != "Documents":
        raise ValueError("unexpected_vault_identity")
    managed = _guard(vault, vault)
    current = _snapshot(managed)
    groups = {}
    for path in vault.parent.iterdir():
        if not path.name.casefold().startswith(PREFIX.casefold()):
            continue
        match = MEMBER.fullmatch(path.name)
        if not match:
            raise ValueError("unexpected_or_active_sibling_namespace: " + str(path))
        kind, token, extension = match.groups()
        _plain(path)
        if (extension != (".json" if kind == "complete" else None)
                or (path.is_file() if kind == "complete" else path.is_dir()) is not True):
            raise ValueError("unexpected_component_type")
        groups.setdefault(token, {})[kind] = path
    triples, protected = [], []
    for token, parts in sorted(groups.items()):
        if set(parts) == {"backup"}:
            # Protect legacy snapshots without traversing their contents.
            protected.append(str(parts["backup"]))
            continue
        if set(parts) != {"backup", "completed-stage", "complete"}:
            raise ValueError("incomplete_set_preserved: " + token)
        receipt = _json(parts["complete"], 4096)
        if (not isinstance(receipt, dict)
                or set(receipt) != {"token", "from", "to", "backup"}
                or any(not isinstance(value, str) for value in receipt.values())
                or receipt["token"] != token
                or receipt["backup"] != parts["backup"].name
                or not OID.fullmatch(receipt["from"])
                or not OID.fullmatch(receipt["to"])
                or receipt["from"] == receipt["to"]):
            raise ValueError("untrusted_receipt")
        backup = _snapshot(parts["backup"])
        stage = _snapshot(parts["completed-stage"])
        if (backup["source_commit"] != receipt["from"]
                or stage["source_commit"] != receipt["to"]):
            raise ValueError("receipt_snapshot_mismatch")
        triples.append(dict(token=token, completion_mtime_ns=parts["complete"].stat().st_mtime_ns,
                            source_commit=stage["source_commit"],
                            paths={kind: str(path) for kind, path in parts.items()},
                            estimated_bytes=_size(parts["backup"], backup)
                            + _size(parts["completed-stage"], stage)
                            + parts["complete"].stat().st_size))
    triples.sort(key=lambda item: (item["completion_mtime_ns"], item["token"]), reverse=True)
    if not triples or triples[0]["source_commit"] != current["source_commit"]:
        raise ValueError("newest_completed_stage_does_not_match_current")
    candidates = triples[5:]
    return dict(action="plan_only", vault=str(vault), current_commit=current["source_commit"],
                retained=triples[:5], candidates=candidates, protected_standalone=protected,
                verified_triple_count=len(triples), candidate_triple_count=len(candidates),
                candidate_path_count=3 * len(candidates),
                candidate_estimated_bytes=sum(t["estimated_bytes"] for t in candidates))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan"])
    parser.add_argument("--vault", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = plan(args.vault)
    except (ValueError, OSError, TypeError, KeyError) as error:
        print("STOP; all evidence protected: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
