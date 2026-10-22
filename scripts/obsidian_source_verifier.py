"""Offline, non-actuating GitHub documentation source verifier for HomeHub #399.

This library performs *no network, filesystem writes, Git operations or refreshes*.
It verifies regular Markdown tree entries and their blob Git SHA-1 identifiers.
Neither tree data nor a matching SHA authenticates the remote source: the caller
must independently establish commit provenance through a reviewed channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import PurePosixPath
import re
from typing import Iterable, Mapping

OID = re.compile(r"[0-9a-f]{40}\Z")
MAX_DOC_FILES = 490  # Leave room for generated landing/provenance pages.
MAX_DOC_BYTES = 30 * 1024 * 1024
MAX_FILE_BYTES = 3 * 1024 * 1024
WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
REQUIRED = frozenset({"AGENTS.md", "docs/PROJECT_SPEC.md", "docs/PROJECT_ADMIN_HUB.md", "docs/README.md"})


@dataclass(frozen=True)
class DocBlob:
    path: str
    oid: str
    mode: str
    size: int


def _safe_markdown_path(path: str) -> bool:
    if not isinstance(path, str) or "\\" in path or not path or len(path) > 300:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return False
    p = PurePosixPath(path)
    if p.as_posix() != path or p.is_absolute() or any(part in (".", "..") for part in path.split("/")):
        return False
    if any(
        part.endswith((".", " "))
        or any(ch in part for ch in '<>:"|?*')
        or part.split(".", 1)[0].upper() in WINDOWS_RESERVED
        for part in p.parts
    ):
        return False
    if path != "AGENTS.md" and not path.startswith("docs/"):
        return False
    return p.suffix.lower() == ".md"


def validate_tree(entries: Iterable[Mapping[str, object]], *, truncated: bool = False) -> tuple[DocBlob, ...]:
    """Validate a *complete* immutable Git tree listing, returning an allowlist.

    A caller must supply a complete, independently pinned GitHub commit/tree.
    This function does not authenticate that claim or authorize installation.
    """
    if truncated:
        raise ValueError("truncated_git_tree")
    result: list[DocBlob] = []
    names: set[str] = set()
    folded: set[str] = set()
    # Windows resolves paths without case sensitivity and cannot have a file
    # and directory at the same path, even when their Git names differ in case.
    # Reject aliases in *every* component, not only identical full file names.
    namespace: dict[str, tuple[str, str]] = {}
    total_size = 0
    for e in entries:
        path = e.get("path")
        if not isinstance(path, str):
            raise ValueError("invalid_tree_path")
        if path == "AGENTS.md" or path.startswith("docs/"):
            # Git tree directories are metadata, not exported files.
            if e.get("type") == "tree" and e.get("mode") in ("040000", "40000"):
                continue
            # Unsafe Markdown *candidates* must not be silently omitted.
            if path.lower().endswith(".md") and not _safe_markdown_path(path):
                raise ValueError("unsafe_markdown_path")
            if not _safe_markdown_path(path):
                continue
            if e.get("type") != "blob" or e.get("mode") not in ("100644", "100755"):
                raise ValueError("non_regular_markdown_blob")
            oid, size = e.get("sha"), e.get("size")
            if not isinstance(oid, str) or not OID.fullmatch(oid):
                raise ValueError("invalid_blob_oid")
            if type(size) is not int or size < 0 or size > MAX_FILE_BYTES:
                raise ValueError("invalid_blob_size")
            if path in names or path.casefold() in folded:
                raise ValueError("duplicate_windows_markdown_path")
            parts = path.split("/")
            for index in range(len(parts)):
                prefix = "/".join(parts[: index + 1])
                kind = "file" if index == len(parts) - 1 else "directory"
                existing = namespace.get(prefix.casefold())
                if existing is not None and existing != (prefix, kind):
                    raise ValueError("windows_path_namespace_collision")
                namespace[prefix.casefold()] = (prefix, kind)
            names.add(path)
            folded.add(path.casefold())
            total_size += size
            if len(result) >= MAX_DOC_FILES or total_size > MAX_DOC_BYTES:
                raise ValueError("documentation_limits_exceeded")
            result.append(DocBlob(path, oid, str(e["mode"]), size))
    if not REQUIRED.issubset(names):
        raise ValueError("required_homehub_docs_missing")
    return tuple(sorted(result, key=lambda x: x.path))


def verify_blob(blob: DocBlob, data: bytes) -> None:
    """Check exact Git blob identity and size before consumer writes a stage file."""
    if not isinstance(data, bytes) or len(data) != blob.size:
        raise ValueError("git_blob_size_mismatch")
    git_content = b"blob " + str(len(data)).encode("ascii") + b"\x00" + data
    if sha1(git_content).hexdigest() != blob.oid:
        raise ValueError("git_blob_oid_mismatch")


def verify_all(blobs: tuple[DocBlob, ...], raw_data: Mapping[str, bytes]) -> None:
    if set(raw_data) != {b.path for b in blobs}:
        raise ValueError("incomplete_or_unexpected_source_bundle")
    for blob in blobs:
        verify_blob(blob, raw_data[blob.path])
