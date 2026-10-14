"""Non-actuating source retrieval for HomeHub #399 (prototype, NOT deployed).

One GitHub public API origin, no credentials, no redirects, bounded JSON inputs,
and exact Git blob verification. Nothing here touches Obsidian, Git, Windows or
local files. Only GitHub HTTPS transport authenticates the claimed master ref;
these Python functions cannot certify GitHub's content by themselves.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
import re
import ssl
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request

from obsidian_source_verifier import DocBlob, OID, MAX_DOC_BYTES, validate_tree, verify_blob

REPO_PATH = "/repos/agatte/home-hub"
API_ROOT = "https://api.github.com"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def _approved_api_path(path: str) -> bool:
    """Only endpoints needed for the bounded public documentation snapshot.

    In particular, a relative URL, encoded delimiter, dot segment or caller-
    supplied extra query is never forwarded to the GitHub HTTP transport.
    """
    if not isinstance(path, str) or not path.startswith(REPO_PATH + "/"):
        return False
    tail = path[len(REPO_PATH) + 1:]
    if tail == "git/ref/heads/master":
        return True
    if re.fullmatch(r"git/(?:commits|blobs|trees)/[0-9a-f]{40}", tail):
        return True
    if re.fullmatch(r"git/trees/[0-9a-f]{40}\?recursive=1", tail):
        return True
    if re.fullmatch(r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", tail):
        return True
    return False


class SourceUnavailable(ValueError):
    """Refuse automatic refresh on missing/inconsistent source evidence."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceUnavailable("github_redirect_refused")


def github_json(path: str, *, opener=None) -> dict[str, Any]:
    """Bounded, anonymous, HTTPS-only GitHub API client; no arbitrary URLs."""
    if not _approved_api_path(path):
        raise SourceUnavailable("disallowed_api_path")
    if opener is None:
        opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        API_ROOT + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "HomeHub-Obsidian-Docs-ReadOnly"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=12) as response:
            if response.status != 200:
                raise SourceUnavailable("github_non_success_response")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SourceUnavailable("github_network_or_rate_limit_unavailable") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SourceUnavailable("github_response_too_large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise SourceUnavailable("invalid_github_json") from error
    if not isinstance(payload, dict):
        raise SourceUnavailable("invalid_github_payload")
    return payload


def github_master_sha(fetch: Callable[[str], dict[str, Any]] = github_json) -> str:
    """Read current master SHA; commit evidence is TLS-origin dependent."""
    data = fetch(REPO_PATH + "/git/ref/heads/master")
    value = data.get("object")
    if not isinstance(value, dict) or value.get("type") != "commit":
        raise SourceUnavailable("unverified_master_commit_ref")
    sha = value.get("sha")
    if not isinstance(sha, str) or not OID.fullmatch(sha):
        raise SourceUnavailable("invalid_master_sha")
    return sha


def verify_snapshot_ancestry(previous_commit: str, intended_commit: str,
                             fetch: Callable[[str], dict[str, Any]] = github_json) -> str:
    """Refuse non-forward documentation updates, using pinned GitHub compare API.

    A GitHub response over authenticated HTTPS is the source of ancestry trust.
    Status ``identical`` is a no-op; only ``ahead`` is a forward update.
    """
    if (not isinstance(previous_commit, str) or not OID.fullmatch(previous_commit)
            or not isinstance(intended_commit, str) or not OID.fullmatch(intended_commit)):
        raise SourceUnavailable("invalid_comparison_sha")
    if previous_commit == intended_commit:
        return "identical"
    report = fetch(REPO_PATH + f"/compare/{previous_commit}...{intended_commit}")
    status = report.get("status")
    if status != "ahead":
        raise SourceUnavailable("non_forward_or_unverified_history")
    base = report.get("base_commit")
    head = report.get("merge_base_commit")
    if (not isinstance(base, dict) or base.get("sha") != previous_commit
            or not isinstance(head, dict) or head.get("sha") != previous_commit):
        raise SourceUnavailable("comparison_base_mismatch")
    return "forward"


@dataclass(frozen=True)
class PreparedDocs:
    """Acquisition evidence only, never a host-write authorization token."""

    previously_sealed_commit: str
    intended_commit: str
    ancestry: str
    docs: "VerifiedDocs"
    source_ref_stable: bool
    refresh_authorized: bool = False


@dataclass(frozen=True)
class VerifiedDocs:
    commit: str
    tree: str
    files: tuple[DocBlob, ...]
    contents: dict[str, bytes]


def github_docs_at_exact_sha(
    commit: str, fetch: Callable[[str], dict[str, Any]] = github_json,
    *, blob_source: Callable[[str, DocBlob], bytes] | None = None,
) -> VerifiedDocs:
    """Retrieve only allowlisted immutable blobs from one SHA, fail closed.

    Requires a caller-pinned SHA previously read from GitHub master over its
    authenticated HTTPS transport. Never uses the mutable branch name for blobs.
    """
    if not isinstance(commit, str) or not OID.fullmatch(commit):
        raise SourceUnavailable("invalid_pinned_commit")
    metadata = fetch(REPO_PATH + f"/git/commits/{commit}")
    if metadata.get("sha") != commit:
        raise SourceUnavailable("commit_response_mismatch")
    tree = metadata.get("tree")
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(tree_sha, str) or not OID.fullmatch(tree_sha):
        raise SourceUnavailable("invalid_commit_tree")
    # Fetch only the root tree and the docs subtree: HomeHub has unrelated code,
    # dependencies and media which must never enter an Obsidian source request.
    root = fetch(REPO_PATH + f"/git/trees/{tree_sha}")
    if root.get("sha") != tree_sha or root.get("truncated") is not False:
        raise SourceUnavailable("unverified_or_truncated_root_tree")
    root_entries = root.get("tree")
    if not isinstance(root_entries, list) or len(root_entries) > 5000:
        raise SourceUnavailable("unsafe_root_tree_size")
    docs = [e for e in root_entries if isinstance(e, dict) and e.get("path") == "docs"]
    agents = [e for e in root_entries if isinstance(e, dict) and e.get("path") == "AGENTS.md"]
    if len(docs) != 1 or len(agents) != 1:
        raise SourceUnavailable("missing_or_duplicate_root_entries")
    docs_entry, agents_entry = docs[0], agents[0]
    docs_sha = docs_entry.get("sha")
    if docs_entry.get("type") != "tree" or docs_entry.get("mode") not in ("040000", "40000"):
        raise SourceUnavailable("invalid_docs_tree_entry")
    if not isinstance(docs_sha, str) or not OID.fullmatch(docs_sha):
        raise SourceUnavailable("invalid_docs_tree_sha")
    doc_tree = fetch(REPO_PATH + f"/git/trees/{docs_sha}?recursive=1")
    if doc_tree.get("sha") != docs_sha or doc_tree.get("truncated") is not False:
        raise SourceUnavailable("unverified_or_truncated_docs_tree")
    docs_entries = doc_tree.get("tree")
    if not isinstance(docs_entries, list) or len(docs_entries) > 10000:
        raise SourceUnavailable("unsafe_docs_tree_size")
    if any(not isinstance(e, dict) for e in docs_entries):
        raise SourceUnavailable("invalid_docs_tree_entries")
    # Reject a docs/ prefix buried inside a subtree and absolute/nested escape.
    entries = [agents_entry]
    for entry in docs_entries:
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise SourceUnavailable("invalid_docs_tree_relative_path")
        entries.append({**entry, "path": "docs/" + relative})
    files = validate_tree(entries)
    content_by_path: dict[str, bytes] = {}
    accumulated = 0
    for blob in files:
        if blob_source is not None:
            # The explicitly injected raw transport must yield exact bytes;
            # retain end-to-end Git blob verification after the download.
            data = blob_source(commit, blob)
            verify_blob(blob, data)
            accumulated += len(data)
            if accumulated > MAX_DOC_BYTES:
                raise SourceUnavailable("github_total_blob_limit")
            content_by_path[blob.path] = data
            continue
        result = fetch(REPO_PATH + f"/git/blobs/{blob.oid}")
        if result.get("sha") != blob.oid or result.get("encoding") != "base64":
            raise SourceUnavailable("github_blob_metadata_mismatch")
        if result.get("size") != blob.size:
            raise SourceUnavailable("github_blob_size_mismatch")
        encoded = result.get("content")
        if not isinstance(encoded, str) or len(encoded) > 2 * (blob.size + 16):
            raise SourceUnavailable("github_blob_encoded_limit")
        try:
            data = base64.b64decode(encoded.replace("\n", "").replace("\r", ""), validate=True)
        except (binascii.Error, ValueError) as error:
            raise SourceUnavailable("github_blob_decode_error") from error
        verify_blob(blob, data)
        accumulated += len(data)
        if accumulated > MAX_DOC_BYTES:
            raise SourceUnavailable("github_total_blob_limit")
        content_by_path[blob.path] = data
    return VerifiedDocs(commit, tree_sha, files, content_by_path)


def prepare_current_docs(
    previous_commit: str, fetch: Callable[[str], dict[str, Any]] = github_json,
    *, blob_source: Callable[[str, DocBlob], bytes] | None = None,
) -> PreparedDocs:
    """Fetch/pin/docs/ancestry/recheck current ref as one non-actuating action.

    The old SHA is only a label unless a separate trusted caller has fully
    verified the existing Vault manifest. The newly returned data must be
    independently assessed and host-revalidated before any filesystem change.
    """
    if not isinstance(previous_commit, str) or not OID.fullmatch(previous_commit):
        raise SourceUnavailable("invalid_previous_snapshot_commit")
    intended = github_master_sha(fetch)
    ancestry = verify_snapshot_ancestry(previous_commit, intended, fetch)
    docs = github_docs_at_exact_sha(intended, fetch, blob_source=blob_source)
    if github_master_sha(fetch) != intended:
        raise SourceUnavailable("github_master_changed_during_acquisition")
    return PreparedDocs(previous_commit, intended, ancestry, docs, True)
