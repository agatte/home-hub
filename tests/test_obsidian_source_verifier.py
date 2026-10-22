"""Data-only checks: no network, filesystem, Git, Vault or Windows access."""
import hashlib
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from obsidian_source_verifier import validate_tree, verify_all, verify_blob


def rec(path, data=b"ok\n", *, mode="100644", kind="blob"):
    sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
    return {"path": path, "sha": sha, "size": len(data), "mode": mode, "type": kind}


BASE = [rec(p) for p in ("AGENTS.md", "docs/PROJECT_SPEC.md", "docs/PROJECT_ADMIN_HUB.md", "docs/README.md")]


class SourceVerifierTests(unittest.TestCase):
    def assert_refuses(self, entries, reason, **kw):
        with self.assertRaisesRegex(ValueError, reason):
            validate_tree(entries, **kw)

    def test_normal_allowlist_and_non_docs_excluded(self):
        files = validate_tree([*BASE, rec("docs/EXTRA.md", b"hello"), rec("backend/app.py")])
        self.assertEqual(len(files), 5)
        self.assertEqual(files[-1].path, "docs/README.md")

    def test_full_bundle_with_sha1_validation(self):
        files = validate_tree(BASE)
        verify_all(files, {x.path: b"ok\n" for x in files})

    def test_tampered_content_rejected(self):
        files = validate_tree(BASE)
        with self.assertRaisesRegex(ValueError, "oid_mismatch"):
            verify_blob(files[0], b"NO\n")

    def test_missing_or_extra_blob_rejected(self):
        files = validate_tree(BASE)
        for data in ({files[0].path: b"ok\n"}, {**{x.path: b"ok\n" for x in files}, "private.md": b"SECRET"}):
            with self.assertRaisesRegex(ValueError, "incomplete_or_unexpected"):
                verify_all(files, data)

    def test_size_mismatch(self):
        files = validate_tree(BASE)
        with self.assertRaisesRegex(ValueError, "size_mismatch"):
            verify_blob(files[0], b"BAD!")

    def test_rejects_symlink_candidate(self):
        self.assert_refuses([*BASE, rec("docs/out.md", mode="120000")], "non_regular")

    def test_rejects_unsafe_path_traversal(self):
        self.assert_refuses([*BASE, rec("docs/../evil.md")], "unsafe_markdown")

    def test_rejects_windows_alternate_data_stream(self):
        self.assert_refuses([*BASE, rec("docs/foo:bar.md")], "unsafe_markdown")

    def test_rejects_control_chars(self):
        self.assert_refuses([*BASE, rec("docs/odd\nname.md")], "unsafe_markdown")

    def test_rejects_case_collision(self):
        self.assert_refuses([*BASE, rec("docs/foo.md"), rec("docs/FOO.md")], "duplicate_windows")

    def test_rejects_case_variant_directory_aliases(self):
        self.assert_refuses(
            [*BASE, rec("docs/Foo/first.md"), rec("docs/foo/second.md")],
            "windows_path_namespace_collision",
        )

    def test_rejects_file_directory_case_alias(self):
        self.assert_refuses(
            [*BASE, rec("docs/note.md"), rec("docs/NOTE.MD/child.md")],
            "windows_path_namespace_collision",
        )

    def test_accepts_distinct_nested_document_paths(self):
        files = validate_tree(
            [*BASE, rec("docs/Foo/first.md"), rec("docs/Foo/second.md")]
        )
        self.assertEqual(len(files), 6)

    def test_refuses_incomplete_tree(self):
        self.assert_refuses(BASE, "truncated", truncated=True)

    def test_missing_required_docs(self):
        self.assert_refuses(BASE[:-1], "required_homehub")

    def test_rejects_invalid_blob_id(self):
        broken = rec("docs/New.md")
        broken["sha"] = "0" * 39
        self.assert_refuses([*BASE, broken], "invalid_blob_oid")

    def test_rejects_oversized_blob(self):
        broken = rec("docs/New.md")
        broken["size"] = 3 * 1024 * 1024 + 1
        self.assert_refuses([*BASE, broken], "invalid_blob_size")

    def test_does_not_accept_true_for_length(self):
        broken = rec("docs/New.md")
        broken["size"] = True
        self.assert_refuses([*BASE, broken], "invalid_blob_size")

    def test_rejects_windows_reserved_name(self):
        self.assert_refuses([*BASE, rec("docs/CON.md")], "unsafe_markdown")

    def test_rejects_windows_invalid_character(self):
        self.assert_refuses([*BASE, rec("docs/strange?.md")], "unsafe_markdown")

    def test_rejects_duplicate_exact_path(self):
        self.assert_refuses([*BASE, rec("AGENTS.md")], "duplicate_windows")


if __name__ == "__main__":
    unittest.main()
