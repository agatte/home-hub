"""Read-only single-transaction cleanup preparation. No removal executor or CLI.

Cooperative observations are not an atomic snapshot or host deletion authority.
Only hashes, paths and filesystem metadata are returned, never file contents.
"""

from hashlib import sha256
import json
from pathlib import Path
import re

from manage_obsidian_vault import MANAGED, MANIFEST
from obsidian_simple_mirror import _plain
from plan_obsidian_retention import OID, PREFIX, _snapshot, plan
from run_obsidian_simple_mirror import exact_path

TOKEN = re.compile(r"[0-9a-f]{32}")


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _record(path):
    for ancestor in (path, *path.parents):
        _plain(ancestor)
    before = path.stat()
    if path.is_file() and before.st_nlink != 1:
        raise ValueError("hardlinked_file_refused")
    record = dict(path=str(path), device=before.st_dev, inode=before.st_ino,
                  mtime_ns=before.st_mtime_ns, size=before.st_size,
                  kind="directory" if path.is_dir() else "file")
    if record["kind"] == "file":
        record["sha256"] = sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    # Reads can legitimately update access time, including directory access time.
    # Compare identity/content metadata, not the read's own atime side effect.
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
              "st_mtime_ns", "st_ctime_ns", "st_file_attributes")
    if any(getattr(before, field, None) != getattr(after, field, None) for field in fields):
        raise ValueError("changed_during_observation")
    return record


def _snapshot_records(root):
    metadata = _snapshot(root)
    files = sorted([MANIFEST, *metadata["sha256"]])
    dirs = {parent for name in files for parent in (root / name).parents
            if parent != root and root in parent.parents}
    return [[_record(root / name) for name in files],
            [_record(path) for path in sorted(dirs, key=lambda p: (-len(p.parts), str(p)))]
            + [_record(root)]]


def _observe(vault, expected_commit, token):
    report = plan(vault)
    if report["current_commit"] != expected_commit:
        raise ValueError("current_commit_mismatch")
    selected = next((t for t in report["candidates"] if t["token"] == token), None)
    if selected is None:
        raise ValueError("not_a_current_candidate")
    expected = {kind: str(vault.parent / (PREFIX + kind + "-" + token + suffix))
                for kind, suffix in (("backup", ""), ("completed-stage", ""),
                                     ("complete", ".json"))}
    if selected["paths"] != expected:
        raise ValueError("exact_three_paths_mismatch")
    observations = {}
    for triple in report["retained"] + report["candidates"]:
        for kind in ("backup", "completed-stage"):
            root = Path(triple["paths"][kind])
            observations[str(root)] = _snapshot_records(root)
        receipt = Path(triple["paths"]["complete"])
        observations[str(receipt)] = _record(receipt)
    observations[str(vault / MANAGED)] = _snapshot_records(vault / MANAGED)
    # Standalone contents and personal notes/settings are deliberately not read.
    standalone = [_record(Path(p)) for p in report["protected_standalone"]]
    operations = []
    for kind in ("backup", "completed-stage"):
        files, directories = observations[expected[kind]]
        # Leave seal until the other snapshot files have been removed.
        files = sorted(files, key=lambda item: (Path(item["path"]).name == MANIFEST,
                                               item["path"]))
        operations.extend(dict(operation="unlink", evidence=item) for item in files)
        operations.extend(dict(operation="rmdir_empty", evidence=item) for item in directories)
    # Receipt is last: partial work must retain its transaction evidence.
    operations.append(dict(operation="unlink", evidence=observations[expected["complete"]]))
    return dict(schema=1, action="preparation_only", vault=str(vault), token=token,
                current_commit=expected_commit, selected_paths=expected,
                operations=operations, operation_count=len(operations),
                file_count=sum(op["operation"] == "unlink" for op in operations),
                estimated_bytes=selected["estimated_bytes"], report=report,
                observations=observations, protected_standalone=standalone)


def prepare(vault: Path, *, expected_commit: str, token: str) -> dict:
    """Verify twice; bind approval to exact paths, bytes, identities and preserved sets.

    This intentionally supplies no function that consumes operations as real writes.
    """
    exact_path(str(vault))
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("explicit_32hex_token_required")
    if not isinstance(expected_commit, str) or not OID.fullmatch(expected_commit):
        raise ValueError("explicit_current_commit_required")
    first = _observe(vault, expected_commit, token)
    second = _observe(vault, expected_commit, token)
    if first != second:
        raise ValueError("changed_during_preparation")
    return dict(first, digest=fingerprint(first))


def revalidate(selection: dict, acknowledgement: str) -> dict:
    """Read-only approval contract; even success grants no filesystem write capability."""
    digest = selection.get("digest")
    body = {k: v for k, v in selection.items() if k != "digest"}
    if digest != fingerprint(body):
        raise ValueError("selection_digest_mismatch")
    required = f"REVIEW ONE {selection['token']} {digest}"
    if acknowledgement != required:
        raise ValueError("exact_acknowledgement_required")
    current = prepare(Path(selection["vault"]), expected_commit=selection["current_commit"],
                      token=selection["token"])
    if current != selection:
        raise ValueError("reapproval_required")
    return current
