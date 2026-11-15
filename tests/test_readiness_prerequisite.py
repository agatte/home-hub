"""Offline fixtures: no HTTP, shell, Git mutation, services or app imports.

Linux/Bash: python3 -B -m unittest discover -s tests -p test_readiness_prerequisite.py -v
"""
import ast
import asyncio
import hashlib
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import readiness_prerequisite as readiness


class ProbeTests(unittest.TestCase):
    def test_current_route_wire_bytes_without_app_or_lifespan_import(self):
        # Execute only the reviewed pure handler AST. No config/dotenv/bootstrap.
        from starlette.responses import JSONResponse

        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "backend/api/routes/health.py").read_text(encoding="utf-8"))
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                       and n.name == "readiness")
        handler.decorator_list = []
        handler.args.args[0].annotation = None
        namespace = {"JSONResponse": JSONResponse}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "<readiness-only>", "exec"), namespace)
        for marker in (True, False, None, 1, "true"):
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(bootstrap_ready=marker)))
            response = asyncio.run(namespace["readiness"](request))
            self.assertEqual(readiness.evaluate_response(str(response.status_code),
                response.headers["content-type"], "0", response.body), marker is True)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_strict_response_matrix(self):
        cases = [
            ("200", "application/json", "0", b'{"ready":true}', True),
            ("503", "application/json", "0", b'{"ready":false}', False),
            *[(code, "application/json", "0", b'{"ready":true}', False)
              for code in ("401", "403", "404", "204", "301", "302", "307", "308")],
            ("200", "application/json", "1", b'{"ready":true}', False),
            *[("200", media, "0", b'{"ready":true}', False)
              for media in ("text/html", "text/plain", "", "application/json; charset=utf-8")],
            *[("200", "application/json", "0", body, False) for body in (
                b'{"ok":true}', b'{"status":"healthy"}', b'{"ready":true,"extra":1}',
                b'{"ready":true,"ready":false}', b'{"ready":1}', b'{"ready":"true"}',
                b'{"ready":false}', b'', b'null', b'not json', b'{"ready":true}\n',
            )],
        ]
        for status, media, redirects, body, expected in cases:
            with self.subTest(status=status, media=media, redirects=redirects, body=body):
                self.assertEqual(readiness.evaluate_response(status, media, redirects, body), expected)

    def test_stub_curl_transport_and_no_fallback(self):
        for code, payload in (
            (0, b'{"ready":true}\n200\napplication/json\n0'),
            (0, b'{"ready":true}\n403\napplication/json\n0'),
            (0, b'{"ready":true}\n404\napplication/json\n0'),
            (0, b'{"ready":false}\n503\napplication/json\n0'),
            (0, b'{"ready":true}\n302\napplication/json\n0'),
            (0, b''), (0, b'\xff\n200\n\xff\n0'), (0, b'x' * 1201),
            (28, b'{"ready":true}\n200\napplication/json\n0'),
        ):
            run = Mock(return_value=SimpleNamespace(returncode=code, stdout=payload))
            self.assertEqual(readiness.probe(run=run), code == 0 and payload ==
                             b'{"ready":true}\n200\napplication/json\n0')
            run.assert_called_once_with(readiness.CURL, capture_output=True, timeout=3, check=False)
        for error in (OSError(), subprocess.TimeoutExpired("curl", 3)):
            run = Mock(side_effect=error)
            self.assertFalse(readiness.probe(run=run))
            run.assert_called_once()

    def test_fixed_transport_scope(self):
        args = readiness.CURL
        self.assertEqual(args[:2], ("curl", "--disable"))
        for flag, value in (("--proxy", ""), ("--noproxy", "*"),
                            ("--resolve", "localhost:8000:127.0.0.1"),
                            ("--connect-timeout", "1"), ("--max-time", "2"),
                            ("--max-redirs", "0"), ("--proto", "=http")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertEqual(args[-1], "http://localhost:8000/api/readiness")
        self.assertIn("Host: localhost:8000", args)
        for forbidden in ("--location", "-L", "--user", "--cookie", "--netrc", "X-Source"):
            self.assertNotIn(forbidden, args)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.old, self.new = "a" * 40, "b" * 40
        self.blobs = {(sha, path): (sha + path).encode()
                      for sha in (self.old, self.new) for path in readiness.ARTIFACTS}
        self.reviewed = {
            sha: readiness.ReviewedTarget(sha, readiness.CONTRACT, {
                path: hashlib.sha256(self.blobs[sha, path]).hexdigest()
                for path in readiness.ARTIFACTS}) for sha in (self.old, self.new)
        }
        self.read = Mock(side_effect=lambda sha, path: self.blobs[sha, path])

    def admit(self, last=None, forward=None, rollback=None):
        return readiness.admit_targets(self.old if last is None else last,
            self.new if forward is None else forward, self.old if rollback is None else rollback,
            self.reviewed, self.read)

    def test_forward_and_rollback_and_same_head_baseline(self):
        self.assertTrue(self.admit())
        self.assertTrue(self.admit(forward=self.old))
        self.assertTrue(self.admit(last=self.new, forward=self.old, rollback=self.new))

    def test_old_route_absent_or_unreviewed_refuses(self):
        del self.blobs[self.old, "backend/api/routes/health.py"]
        self.assertFalse(self.admit())
        del self.reviewed[self.old]
        self.assertFalse(self.admit())

    def test_unknown_missing_or_ambiguous_marker_before_blob_reads(self):
        for marker in ("", "master", "a" * 7, "c" * 40, self.old + "\n", "A" * 40):
            self.read.reset_mock()
            self.assertFalse(self.admit(last=marker))
            self.read.assert_not_called()

    def test_retained_new_controller_checks_old_helper_and_rejects_drift(self):
        # The running controller remains new after a hypothetical checkout rollback.
        # It must validate BOTH committed copies before any side effects.
        self.blobs[self.old, "scripts/readiness_prerequisite.py"] = b"old incompatible helper"
        self.assertFalse(self.admit())

    def test_bad_contract_incomplete_evidence_and_blob_failure(self):
        original = self.reviewed[self.old]
        for record in (readiness.ReviewedTarget(self.old, "legacy-health", original.digests),
                       readiness.ReviewedTarget(self.new, readiness.CONTRACT, original.digests),
                       readiness.ReviewedTarget(self.old, readiness.CONTRACT, {})):
            self.reviewed[self.old] = record
            self.assertFalse(self.admit())
        self.reviewed[self.old] = original
        self.read.side_effect = OSError("missing committed object")
        self.assertFalse(self.admit())

    def test_no_operational_activation(self):
        # Review tripwire: the prerequisite must remain unwired until phase A.
        root = Path(__file__).resolve().parents[1]
        for script in ("deploy.sh", "backup-db.sh", "homehub-hostctl.sh"):
            text = (root / "scripts" / script).read_text(encoding="utf-8")
            self.assertNotIn("readiness_prerequisite", text)
        source = (root / "scripts/readiness_prerequisite.py").read_text(encoding="utf-8")
        for command in ("systemctl", "git reset", "migrations", "__main__"):
            self.assertNotIn(command, source)


if __name__ == "__main__":
    unittest.main()
