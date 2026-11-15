"""Phase A additive readiness baseline: offline, no real lifespan or service actions."""
import ast
from pathlib import Path
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.health import router, ping, readiness, health_check
from scripts.readiness_prerequisite import evaluate_response


ROOT = Path(__file__).resolve().parents[1]


class BaselineReadinessRoutes(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        # Do not start the real HomeHub hardware/service-owning lifespan.
        self.client = TestClient(self.app)

    def test_strict_bootstrap_flag_and_no_details(self):
        for flag, expected_status, expected_body in (
            (None, 503, b'{"ready":false}'),
            (False, 503, b'{"ready":false}'),
            ("true", 503, b'{"ready":false}'),
            (1, 503, b'{"ready":false}'),
            (True, 200, b'{"ready":true}'),
        ):
            with self.subTest(flag=flag):
                self.app.state.bootstrap_ready = flag
                result = self.client.get("/api/readiness")
                self.assertEqual(result.status_code, expected_status)
                self.assertEqual(result.content, expected_body)
                self.assertEqual(result.headers.get("cache-control"), "no-store")
                self.assertEqual(result.headers.get("content-type"), "application/json")
                self.assertEqual(evaluate_response(str(result.status_code),
                    result.headers.get("content-type", ""), "0", result.content),
                    flag is True)

    def test_existing_liveness_and_full_diagnostics_not_redefined(self):
        endpoints = {getattr(route, "path", ""): getattr(route, "endpoint", None)
                     for route in self.app.routes}
        self.assertIs(endpoints["/api/ping"], ping)
        self.assertIs(endpoints["/api/readiness"], readiness)
        self.assertIs(endpoints["/health"], health_check)
        result = self.client.get("/api/ping")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"ok": True})
        self.assertEqual(self.client.head("/api/readiness").status_code, 405)
        # Legacy FastAPI redirects slash aliases. The strict readiness probe
        # never follows redirects and the Phase B REST boundary denies aliases.
        self.assertEqual(self.client.get("/api/readiness/", follow_redirects=False).status_code, 307)
        # /health intentionally NOT invoked: real handler expects device state.

    def test_lifespan_flag_ast_order_and_exceptional_shutdown(self):
        src = (ROOT / "backend" / "bootstrap.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "lifespan")
        flag_assigns = []
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and len(n.targets) == 1:
                t = n.targets[0]
                if (isinstance(t, ast.Attribute) and t.attr == "bootstrap_ready"
                    and isinstance(t.value, ast.Attribute) and t.value.attr == "state"):
                    flag_assigns.append(n)
        flag_assigns.sort(key=lambda n: n.lineno)
        self.assertEqual([n.value.value for n in flag_assigns], [False, True, False])
        init_db = next(n for n in ast.walk(node)
                       if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
                       and isinstance(n.value.func, ast.Name) and n.value.func.id == "init_db")
        self.assertLess(flag_assigns[0].lineno, init_db.lineno)
        yield_node = next(n for n in ast.walk(node) if isinstance(n, ast.Expr)
                          and isinstance(n.value, ast.Yield))
        self.assertLess(flag_assigns[1].lineno, yield_node.lineno)
        enclosing = [n for n in ast.walk(node) if isinstance(n, ast.Try)
                     and any(x is yield_node for x in n.body)]
        self.assertEqual(len(enclosing), 1)
        self.assertIn(flag_assigns[2], enclosing[0].finalbody)
        self.assertLess(yield_node.lineno, flag_assigns[2].lineno)


if __name__ == "__main__":
    unittest.main()
