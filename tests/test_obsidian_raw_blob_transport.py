"""SHA-pinned public raw-content transport regression tests. No live network."""

import base64
from hashlib import sha1
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from obsidian_github_docs_source import REPO_PATH, prepare_current_docs
from obsidian_raw_blob_transport import (
    _NoRedirect, RawBlobUnavailable, github_raw_blob, raw_blob_url,
)
from obsidian_source_verifier import DocBlob
from test_obsidian_github_docs_source import COMMIT, FILES, fake_payloads

BYTES = FILES["AGENTS.md"]
OID = sha1(b"blob " + str(len(BYTES)).encode("ascii") + bytes([0]) + BYTES).hexdigest()
BLOB = DocBlob("AGENTS.md", OID, "100644", len(BYTES))


class FakeResponse:
    def __init__(self, url, body=BYTES, status=200):
        self.url, self.body, self.status = url, body, status
        self.read_limit = None
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self, n):
        self.read_limit = n
        return self.body[:n]


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls = []
    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout, request.get_method()))
        if self.error is not None:
            raise self.error
        return self.response


class RawBlobTransportTests(unittest.TestCase):
    def test_exact_pinned_url_and_hash(self):
        url = raw_blob_url(COMMIT, BLOB)
        self.assertEqual(
            url, "https://raw.githubusercontent.com/agatte/home-hub/" + COMMIT + "/AGENTS.md"
        )
        response = FakeResponse(url)
        opener = FakeOpener(response)
        self.assertEqual(github_raw_blob(COMMIT, BLOB, opener=opener), BYTES)
        self.assertEqual(opener.calls, [(url, 12, "GET")])
        self.assertEqual(response.read_limit, len(BYTES) + 1)

    def test_path_allowlist_and_oid_refusal_before_network(self):
        for path in ("../secret.md", ".env", "docs/../../secret.md",
                     "https://evil.invalid/docs/a.md", "docs/a.txt",
                     "docs/NUL.md", "docs/name?.md", "docs/a\\b.md"):
            with self.subTest(path=path):
                with self.assertRaises(RawBlobUnavailable):
                    raw_blob_url(COMMIT, DocBlob(path, OID, "100644", len(BYTES)))
        for sha in ("", "../bad", "A" * 40, "e" * 39):
            with self.subTest(commit=sha):
                with self.assertRaisesRegex(RawBlobUnavailable, "raw_commit_unpinned"):
                    raw_blob_url(sha, BLOB)

    def test_bad_size_and_nonregular_mode_refused(self):
        for blob in (DocBlob("AGENTS.md", OID, "120000", len(BYTES)),
                     DocBlob("AGENTS.md", OID, "100644", -1),
                     DocBlob("AGENTS.md", OID, "100644", 4_000_000)):
            with self.subTest(blob=blob):
                with self.assertRaises(RawBlobUnavailable):
                    raw_blob_url(COMMIT, blob)

    def test_redirect_always_refused(self):
        guard = _NoRedirect()
        with self.assertRaisesRegex(RawBlobUnavailable, "raw_redirect_refused"):
            guard.redirect_request(None, None, 302, "found", {}, "https://evil.invalid")

    def test_unsafe_effective_origin_refused(self):
        expected = raw_blob_url(COMMIT, BLOB)
        with self.assertRaisesRegex(RawBlobUnavailable, "raw_origin_or_status"):
            github_raw_blob(COMMIT, BLOB, opener=FakeOpener(
                FakeResponse("https://evil.invalid", BYTES)
            ))
        with self.assertRaisesRegex(RawBlobUnavailable, "raw_origin_or_status"):
            github_raw_blob(COMMIT, BLOB, opener=FakeOpener(
                FakeResponse(expected, BYTES, status=206)
            ))

    def test_short_extra_wrong_hash_and_size_rejected(self):
        url = raw_blob_url(COMMIT, BLOB)
        for body in (BYTES[:-1], BYTES + b"X", b"0" * len(BYTES)):
            with self.subTest(body=body):
                with self.assertRaisesRegex(RawBlobUnavailable, "raw_git_blob_identity"):
                    github_raw_blob(COMMIT, BLOB, opener=FakeOpener(
                        FakeResponse(url, body)
                    ))

    def test_offline_and_http_error_refuse(self):
        for exc in (OSError("offline"), HTTPError("https://raw.githubusercontent.com",
                                                 429, "rate-limited", {}, None)):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaisesRegex(RawBlobUnavailable, "raw_blob_unavailable"):
                    github_raw_blob(COMMIT, BLOB, opener=FakeOpener(error=exc))

    def test_forward_fetch_uses_six_rest_metadata_calls_not_one_per_file(self):
        api = fake_payloads()
        old = "d" * 40
        api[REPO_PATH + "/compare/" + old + "..." + COMMIT] = {
            "status": "ahead", "base_commit": {"sha": old},
            "merge_base_commit": {"sha": old},
        }
        requests = []
        def fetch(path):
            requests.append(path)
            if "/git/blobs/" in path:
                self.fail("REST blob API calls must be absent")
            return api[path]
        raw_commits = []
        def get_raw(commit, blob):
            raw_commits.append(commit)
            data = base64.b64decode(api[REPO_PATH + "/git/blobs/" + blob.oid]["content"])
            return data
        result = prepare_current_docs(old, fetch=fetch, blob_source=get_raw)
        self.assertEqual(result.ancestry, "forward")
        self.assertEqual(result.docs.contents, FILES)
        self.assertEqual(len(requests), 6)
        self.assertEqual(len(raw_commits), len(FILES))
        self.assertEqual(set(raw_commits), {COMMIT})
        self.assertFalse(result.refresh_authorized)

    def test_tampered_raw_content_refused_even_if_metadata_correct(self):
        api = fake_payloads()
        with self.assertRaisesRegex(ValueError, "git_blob_oid_mismatch"):
            prepare_current_docs(
                COMMIT, fetch=api.__getitem__,
                blob_source=lambda commit, blob: b"x" * blob.size
            )


if __name__ == "__main__":
    unittest.main()
