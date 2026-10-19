"""Public raw.githubusercontent.com transport for exact SHA-pinned docs (#399).

Read-only, no credentials, redirects, local writes, fallback origins or dynamic
hosts. The caller must first authenticate the source commit/tree through GitHub
TLS and MUST verify the returned content against the Git tree blob SHA.
"""

from __future__ import annotations

import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, Request

from obsidian_github_docs_source import SourceUnavailable
from obsidian_source_verifier import (
    DocBlob, MAX_FILE_BYTES, OID, _safe_markdown_path, verify_blob,
)

ORIGIN = "https://raw.githubusercontent.com"
PREFIX = "/agatte/home-hub"
MAX_RESPONSE_BUFFER = MAX_FILE_BYTES + 1


class RawBlobUnavailable(SourceUnavailable):
    """Fail closed for invalid identity or inaccessible source content."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RawBlobUnavailable("raw_redirect_refused")


def raw_blob_url(commit: str, blob: DocBlob) -> str:
    """Only fixed repository origin, exact commit and validated Markdown path."""
    if not isinstance(commit, str) or not OID.fullmatch(commit):
        raise RawBlobUnavailable("raw_commit_unpinned")
    if (
        not isinstance(blob, DocBlob)
        or not _safe_markdown_path(blob.path)
        or not isinstance(blob.oid, str) or not OID.fullmatch(blob.oid)
        or type(blob.size) is not int or not 0 <= blob.size <= MAX_FILE_BYTES
        or blob.mode not in ("100644", "100755")
    ):
        raise RawBlobUnavailable("raw_blob_not_allowlisted")
    # Encode individual segments, never interpret input as an absolute URL or
    # let slash/percent escapes insert new authorities or traversal segments.
    relative = "/".join(quote(segment, safe="") for segment in blob.path.split("/"))
    return f"{ORIGIN}{PREFIX}/{commit}/{relative}"


def github_raw_blob(commit: str, blob: DocBlob, *, opener=None) -> bytes:
    """Download one bounded raw GitHub file and verify its exact Git blob ID.

    Never return partially received/extra data. Never follow redirects. Does
    not treat a correct hash as proof of signed GitHub commit history.
    """
    url = raw_blob_url(commit, blob)
    if opener is None:
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        url, headers={"User-Agent": "HomeHub-Obsidian-SHA-ReadOnly"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=12) as response:
            if response.status != 200 or response.url != url:
                raise RawBlobUnavailable("raw_origin_or_status_mismatch")
            # Max file length already validated; refuse extra bytes or size drift.
            content = response.read(blob.size + 1)
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise RawBlobUnavailable("raw_blob_unavailable") from error
    try:
        verify_blob(blob, content)
    except ValueError as error:
        raise RawBlobUnavailable("raw_git_blob_identity_mismatch") from error
    return content
