"""Offline fake GitHub API. No real network, user data, filesystem or Vault."""
from __future__ import annotations

import base64
from hashlib import sha1
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from obsidian_github_docs_source import (
    REPO_PATH, SourceUnavailable, github_master_sha, github_docs_at_exact_sha, verify_snapshot_ancestry, github_json, prepare_current_docs,
)
from obsidian_source_verifier import OID

COMMIT = "a" * 40
TREE = "b" * 40
DOC_TREE = "e" * 40
FILES = {
    "AGENTS.md": b"Guide\n", "docs/PROJECT_SPEC.md": b"Specification\n",
    "docs/PROJECT_ADMIN_HUB.md": b"Hub\n", "docs/README.md": b"Index\n",
}


def fake_payloads():
    index = []
    blobs = {}
    for path, data in FILES.items():
        sha = sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
        index.append({"path": path, "mode": "100644", "type": "blob", "sha": sha, "size": len(data)})
        blobs[REPO_PATH + "/git/blobs/" + sha] = {
            "sha": sha, "encoding": "base64", "size": len(data),
            "content": base64.b64encode(data).decode(),
        }
    return {
        REPO_PATH + "/git/ref/heads/master": {"object": {"type": "commit", "sha": COMMIT}},
        REPO_PATH + "/git/commits/" + COMMIT: {"sha": COMMIT, "tree": {"sha": TREE}},
        REPO_PATH + "/git/trees/" + TREE: {"sha": TREE, "truncated": False, "tree": [
            {"path": "AGENTS.md", "type": "blob", "mode": "100644", "sha": next(e["sha"] for e in index if e["path"] == "AGENTS.md"), "size": len(FILES["AGENTS.md"])},
            {"path": "docs", "type": "tree", "mode": "040000", "sha": DOC_TREE},
        ]},
        REPO_PATH + "/git/trees/" + DOC_TREE + "?recursive=1": {"sha": DOC_TREE, "truncated": False, "tree": [
            {**e, "path": e["path"].removeprefix("docs/")} for e in index if e["path"].startswith("docs/")
        ]},
        **blobs,
    }


class FakeClientTests(unittest.TestCase):
    def test_happy_exact_sha(self):
        api = fake_payloads()
        getter = api.__getitem__
        self.assertTrue(OID.fullmatch(github_master_sha(getter)))
        result = github_docs_at_exact_sha(COMMIT, getter)
        self.assertEqual(result.contents, FILES)
        self.assertEqual(result.commit, COMMIT)
        self.assertEqual(result.tree, TREE)

    def test_no_mutable_blob_lookup(self):
        api = fake_payloads()
        touched = []
        def getter(path):
            touched.append(path)
            return api[path]
        github_docs_at_exact_sha(COMMIT, getter)
        self.assertTrue(all("heads/master" not in p for p in touched))
        self.assertNotIn(REPO_PATH + "/git/trees/" + TREE + "?recursive=1", touched)
        self.assertEqual(len(touched), 3 + len(FILES))

    def test_untrusted_ref_abstains(self):
        api = fake_payloads()
        api[REPO_PATH + "/git/ref/heads/master"]["object"]["type"] = "tag"
        with self.assertRaisesRegex(SourceUnavailable, "unverified_master"):
            github_master_sha(api.__getitem__)

    def test_mismatched_commit(self):
        api = fake_payloads()
        api[REPO_PATH + "/git/commits/" + COMMIT]["sha"] = "c" * 40
        with self.assertRaisesRegex(SourceUnavailable, "commit_response_mismatch"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_truncated_tree_abstains(self):
        api = fake_payloads()
        api[REPO_PATH + "/git/trees/" + DOC_TREE + "?recursive=1"]["truncated"] = True
        with self.assertRaisesRegex(SourceUnavailable, "unverified_or_truncated"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_tree_mismatch_abstains(self):
        api = fake_payloads()
        api[REPO_PATH + "/git/trees/" + DOC_TREE + "?recursive=1"]["sha"] = "0" * 40
        with self.assertRaisesRegex(SourceUnavailable, "unverified_or_truncated"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_tampered_blob_abstains(self):
        api = fake_payloads()
        blob_key = next(p for p in api if "/git/blobs/" in p)
        api[blob_key]["content"] = base64.b64encode(b"corrupt").decode()
        with self.assertRaises(ValueError):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_mismatch_blob_size_abstains(self):
        api = fake_payloads()
        blob_key = next(p for p in api if "/git/blobs/" in p)
        api[blob_key]["size"] = 999
        with self.assertRaisesRegex(SourceUnavailable, "github_blob_size_mismatch"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_identical_history_no_network(self):
        def no_fetch(_):
            self.fail("Unexpected fetch")
        self.assertEqual(verify_snapshot_ancestry(COMMIT, COMMIT, no_fetch), "identical")

    def test_forward_ancestry(self):
        past = "d" * 40
        expected = REPO_PATH + "/compare/" + past + "..." + COMMIT
        def fetch(path):
            self.assertEqual(path, expected)
            return {"status": "ahead", "base_commit": {"sha": past}, "merge_base_commit": {"sha": past}}
        self.assertEqual(verify_snapshot_ancestry(past, COMMIT, fetch), "forward")

    def test_divergent_refused(self):
        past = "d" * 40
        with self.assertRaisesRegex(SourceUnavailable, "non_forward"):
            verify_snapshot_ancestry(past, COMMIT, lambda _: {"status": "diverged"})

    def test_claimed_ahead_but_wrong_base_refused(self):
        past = "d" * 40
        with self.assertRaisesRegex(SourceUnavailable, "comparison_base_mismatch"):
            verify_snapshot_ancestry(past, COMMIT, lambda _: {
                "status": "ahead", "base_commit": {"sha": past}, "merge_base_commit": {"sha": COMMIT}
            })

    def test_untrusted_extra_root_docs_entry_refused(self):
        api = fake_payloads()
        root = api[REPO_PATH + "/git/trees/" + TREE]
        root["tree"].append(root["tree"][1].copy())
        with self.assertRaisesRegex(SourceUnavailable, "duplicate_root_entries"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_bad_docs_relative_path_refused(self):
        api = fake_payloads()
        api[REPO_PATH + "/git/trees/" + DOC_TREE + "?recursive=1"]["tree"][0]["path"] = "../out.md"
        with self.assertRaisesRegex(ValueError, "unsafe_markdown_path"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_base64_junk_refused(self):
        api = fake_payloads()
        blob_key = next(p for p in api if "/git/blobs/" in p)
        api[blob_key]["content"] = "##" + api[blob_key]["content"]
        with self.assertRaisesRegex(SourceUnavailable, "github_blob_decode_error"):
            github_docs_at_exact_sha(COMMIT, api.__getitem__)

    def test_arbitrary_url_refused_before_request(self):
        class FailOpen:
            def open(self, *_a, **_kw):
                raise AssertionError("must not access network")
        with self.assertRaisesRegex(SourceUnavailable, "disallowed_api_path"):
            github_json("https://example.invalid/private", opener=FailOpen())

    def test_overlarge_response_refused(self):
        class FakeResponse:
            status = 200
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, n):
                return b" " * n
        class FakeOpener:
            def open(self, *_a, **_kw):
                return FakeResponse()
        with self.assertRaisesRegex(SourceUnavailable, "github_response_too_large"):
            github_json(REPO_PATH + "/git/ref/heads/master", opener=FakeOpener())

    def test_invalid_commit_abstains_pre_fetch(self):
        def no_fetch(_):
            self.fail("Unexpected fetch")
        with self.assertRaisesRegex(SourceUnavailable, "invalid_pinned_commit"):
            github_docs_at_exact_sha("../bad", no_fetch)

    def test_source_preparation_rechecks_ref_and_never_authorizes_write(self):
        api = fake_payloads()
        prepared = prepare_current_docs(COMMIT, api.__getitem__)
        self.assertEqual(prepared.ancestry, "identical")
        self.assertEqual(prepared.docs.contents, FILES)
        self.assertTrue(prepared.source_ref_stable)
        self.assertFalse(prepared.refresh_authorized)

    def test_source_preparation_detects_master_change_mid_read(self):
        api = fake_payloads()
        seen = 0
        def getter(path):
            nonlocal seen
            if path.endswith("/git/ref/heads/master"):
                seen += 1
                if seen == 2:
                    return {"object":{"type":"commit","sha":"f"*40}}
            return api[path]
        with self.assertRaisesRegex(SourceUnavailable, "github_master_changed_during_acquisition"):
            prepare_current_docs(COMMIT, getter)

    def test_source_preparation_rejects_bad_old_sha_before_fetch(self):
        def no_fetch(_):
            self.fail("No fetch allowed")
        with self.assertRaisesRegex(SourceUnavailable, "invalid_previous_snapshot_commit"):
            prepare_current_docs("a", no_fetch)

    def test_transport_rejects_path_traversal_and_other_repo_endpoints(self):
        class FailOpen:
            def open(self, *_a, **_kw):
                raise AssertionError("No request expected")
        for path in (
            REPO_PATH + "/../../users/login",
            REPO_PATH + "/git/blobs/" + COMMIT + "?redirect=1",
            REPO_PATH + "/contents/.env",
            REPO_PATH + "/git/ref/heads/other",
            REPO_PATH + "/git/trees/" + COMMIT + "?recursive=2",
            REPO_PATH + "/git/blobs/" + COMMIT + "%2Fbad",
            REPO_PATH + "/git/commits/" + COMMIT + "/../another",
        ):
            with self.subTest(path=path), self.assertRaisesRegex(SourceUnavailable, "disallowed_api_path"):
                github_json(path, opener=FailOpen())

    def test_transport_does_not_allow_relative_external_origin(self):
        class FailOpen:
            def open(self, *_a, **_kw):
                raise AssertionError("No request expected")
        for path in ("//evil.invalid", "https://evil.invalid/", "", "/repos/not-ours/contents"):
            with self.subTest(path=path), self.assertRaisesRegex(SourceUnavailable, "disallowed_api_path"):
                github_json(path, opener=FailOpen())

    def test_https_transport_handles_http_error_without_leaking_response(self):
        from urllib.error import HTTPError

        class FakeOpener:
            def open(self, *_args, **_kwargs):
                raise HTTPError("https://api.github.com", 429, "rate limit", {}, None)

        with self.assertRaisesRegex(SourceUnavailable, "github_network_or_rate_limit_unavailable"):
            github_json(REPO_PATH + "/git/ref/heads/master", opener=FakeOpener())

    def test_https_transport_refuses_invalid_json(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _size):
                return b"not-json"

        class FakeOpener:
            def open(self, *_args, **_kwargs):
                return FakeResponse()

        with self.assertRaisesRegex(SourceUnavailable, "invalid_github_json"):
            github_json(REPO_PATH + "/git/ref/heads/master", opener=FakeOpener())

    def test_https_transport_refuses_json_array(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _size):
                return b"[]"

        class FakeOpener:
            def open(self, *_args, **_kwargs):
                return FakeResponse()

        with self.assertRaisesRegex(SourceUnavailable, "invalid_github_payload"):
            github_json(REPO_PATH + "/git/ref/heads/master", opener=FakeOpener())

    def test_https_redirect_handler_refuses_redirect(self):
        from obsidian_github_docs_source import NoRedirect

        with self.assertRaisesRegex(SourceUnavailable, "github_redirect_refused"):
            NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://example.invalid/")


if __name__ == "__main__":
    unittest.main()
