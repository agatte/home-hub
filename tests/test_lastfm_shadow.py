"""Synthetic-only shadow lifecycle, privacy and integration contract tests."""
import ast
import asyncio
import json
from pathlib import Path
import threading
import hmac
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services.apple_music_lastfm_recent_source import (
    LastFmRecentUnavailable, read_lastfm_observed_page, _read_https,
)
from backend.services.lastfm_shadow import LastFmShadowService, MAX_REMEMBERED

USER = "fictional_user"
KEY = "0" * 32
PRIVATE = "FICTIONAL_PRIVATE_MARKER"
NOW = 1795000000


def row(title=PRIVATE, artist=PRIVATE, second=NOW - 10, live=False):
    return {"name": title, "artist": {"#text": artist},
            "date": {"uts": str(second)},
            "@attr": {"nowplaying": "true" if live else "false"}}


def page(rows, key=b"x" * 32):
    raw = json.dumps({"recenttracks": {"@attr": {"user": USER}, "track": rows}}).encode()
    return read_lastfm_observed_page(
        USER, KEY, fingerprint_key=key, now_seconds=NOW,
        fetch_bytes=lambda request: raw)


class SourceTests(unittest.TestCase):
    def test_identity_and_current_exclusion(self):
        result = page([row(), row(), row(artist="other"), row(title="other"), row(live=True)])
        self.assertEqual(len(result.fingerprints), 3)
        self.assertNotIn(PRIVATE, repr(result))
        self.assertNotEqual(result.fingerprints, page([row()], b"y" * 32).fingerprints)

    def test_missing_labels_dates_and_future_abstain(self):
        missing = row()
        del missing["date"]
        self.assertFalse(page([row(title=""), row(artist=None), missing,
                               row(second=NOW + 1)]).fingerprints)

    def test_malformed_raw_fails_closed_redacted(self):
        for raw in (PRIVATE.encode(), json.dumps({"error": PRIVATE}).encode()):
            with self.assertRaises(LastFmRecentUnavailable) as caught:
                read_lastfm_observed_page(USER, KEY, fingerprint_key=b"x" * 32,
                                         fetch_bytes=lambda request: raw)
            self.assertNotIn(PRIVATE, str(caught.exception))

    def test_transport_deadline_and_timeout_without_network(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read1.return_value = b"chunk"
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch("backend.services.apple_music_lastfm_recent_source.build_opener", return_value=opener), \
                patch("backend.services.apple_music_lastfm_recent_source.time.monotonic",
                      side_effect=[0, 0, 13]):
            with self.assertRaises(LastFmRecentUnavailable):
                _read_https(object())
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 12)
        response.read1.assert_called_once()


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def service(self, **kwargs):
        return LastFmShadowService(enabled=True, username=USER, api_key=KEY, **kwargs)

    async def test_disabled_and_invalid_create_no_task_or_request(self):
        def forbidden(*args, **kwargs):
            self.fail("network attempted")
        services = [LastFmShadowService(source=forbidden),
                    LastFmShadowService(enabled=True, source=forbidden)]
        for minutes in (4, 1441, True, "15"):
            services.append(self.service(poll_minutes=minutes, source=forbidden))
        for s in services:
            self.assertIsNone(s.start())
            await s._poll_once()
            self.assertIn(s.status()["state"], ("disabled", "unconfigured"))
        for username, key in (("bad user", KEY), (USER, "")):
            self.assertFalse(LastFmShadowService(enabled=True, username=username, api_key=key).ready)
        for minutes in (5, 15, 1440):
            self.assertTrue(self.service(poll_minutes=minutes).ready)

    async def test_baseline_overlap_failure_and_staleness(self):
        now = [0]
        rows = [row()]
        fail = [False]
        def source(*args, **kwargs):
            if fail[0]:
                raise ValueError(PRIVATE)
            return page(rows, kwargs["fingerprint_key"])
        s = self.service(source=source, clock=lambda: now[0])
        with patch("logging.Logger._log") as logs:
            await s._poll_once()
            self.assertEqual(s.status()["unseen_observations_since_baseline"], 0)
            rows.append(row(artist="different"))
            await s._poll_once()
            await s._poll_once()
            self.assertEqual(s.status()["unseen_observations_since_baseline"], 1)
            fail[0] = True
            await s._poll_once()
            self.assertEqual(s.status()["state"], "degraded")
            now[0] = 1801
            self.assertEqual(s.status()["freshness"], "stale")
            fail[0] = False
            await s._poll_once()
            self.assertEqual(s.status()["state"], "fresh")
            logs.assert_not_called()
        text = json.dumps(s.status())
        for private in (PRIVATE, USER, KEY, str(NOW)):
            self.assertNotIn(private, text)

    async def test_bounded_memory_and_expiry(self):
        now = [0]
        counter = [0]
        def source(*args, **kwargs):
            counter[0] += 1
            return page([row(title=str(counter[0]))], kwargs["fingerprint_key"])
        s = self.service(source=source, clock=lambda: now[0])
        # Exercise actual eviction without thousands of worker round trips.
        s._seen.update((str(i).encode(), 0) for i in range(MAX_REMEMBERED))
        await s._poll_once()
        self.assertEqual(len(s._seen), MAX_REMEMBERED)
        now[0] = 7 * 86400 + 1
        self.assertEqual(s.status()["remembered_observations"], 0)

    async def test_opt_in_and_cancel_during_thread(self):
        entered = threading.Event()
        release = threading.Event()
        def source(*args, **kwargs):
            entered.set()
            release.wait(2)
            return page([])
        s = self.service(source=source)
        task = s.start()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            self.assertIsNone(s.start())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, .2)
            self.assertFalse(s.status()["baseline_seeded"])
        finally:
            release.set()


class IntegrationContractTests(unittest.TestCase):
    def test_config_defaults_without_loading_environment(self):
        tree = ast.parse(Path("backend/config.py").read_text(encoding="utf-8"))
        settings = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings")
        values = {n.target.id: ast.literal_eval(n.value) for n in settings.body
                  if isinstance(n, ast.AnnAssign) and n.target.id.startswith("LASTFM_SHADOW_")}
        self.assertEqual(values, {"LASTFM_SHADOW_ENABLED": False,
                                 "LASTFM_SHADOW_USERNAME": "", "LASTFM_SHADOW_POLL_MINUTES": 15})

    def test_route_dependencies_and_cached_read(self):
        tree = ast.parse(Path("backend/api/routes/music.py").read_text(encoding="utf-8"))
        route = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == "lastfm_shadow_status")
        decorator = ast.unparse(route.decorator_list[0])
        self.assertIn("router.get", decorator)
        self.assertIn("Depends(require_api_key_strict)", decorator)
        self.assertIn("Depends(require_localhost)", decorator)
        self.assertNotIn("await", ast.unparse(route))
        self.assertIn("service.status()", ast.unparse(route))

    def test_isolated_service_imports_and_lifespan_registration(self):
        text = Path("backend/services/lastfm_shadow.py").read_text()
        for forbidden in ("music_taste", "music_bandit", "sonos", "presence", "lighting", "database"):
            self.assertNotIn(forbidden, text.lower())
        bootstrap = Path("backend/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("app.state.lastfm_shadow = lastfm_shadow", bootstrap)
        self.assertIn("tasks.append(lastfm_shadow_task)", bootstrap)


class RouteBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dependency_bodies_and_cached_route_without_fastapi(self):
        # Execute the actual function bodies with synthetic framework objects.
        # No config import: that would load environment-specific credentials.
        class Denied(Exception):
            def __init__(self, status_code, detail):
                self.status_code = status_code
        ns = {"HTTPException": Denied, "hmac": hmac,
              "settings": SimpleNamespace(HOME_HUB_API_KEY="fictional-key",
                                           HOME_HUB_SKILL_TOKEN="fictional-skill"),
              "TRUSTED_LOCAL": {"127.0.0.1", "::1"},
              "TUNNEL_ORIGIN_HEADER": "X-Tunnel-Origin",
              "TUNNEL_ORIGIN_VALUE": "cloudflare"}
        tree = ast.parse(Path("backend/api/auth.py").read_text(encoding="utf-8"))
        names = {"require_api_key_strict", "is_direct_localhost", "require_localhost"}
        funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in names]
        route_tree = ast.parse(Path("backend/api/routes/music.py").read_text(encoding="utf-8"))
        funcs.append(next(n for n in route_tree.body if isinstance(n, ast.AsyncFunctionDef)
                          and n.name == "lastfm_shadow_status"))
        for func in funcs:
            func.decorator_list = []
            func.returns = None
            func.args.defaults = [ast.Constant(None) for _ in func.args.defaults]
            for arg in func.args.args:
                arg.annotation = None
        module = ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[]))
        exec(compile(module, "<actual route/auth bodies>", "exec"), ns)
        service = LastFmShadowService(source=lambda *a, **k: self.fail("read made network request"))
        request = SimpleNamespace(client=SimpleNamespace(host="192.168.1.12"), headers={},
                                  app=SimpleNamespace(state=SimpleNamespace(lastfm_shadow=service)))
        with self.assertRaises(Denied) as denied:
            await ns["require_api_key_strict"](request)
        self.assertEqual(denied.exception.status_code, 401)
        await ns["require_api_key_strict"](request, "fictional-key")
        with self.assertRaises(Denied):
            await ns["require_localhost"](request)
        request.client.host = "127.0.0.1"
        request.headers = {"X-Tunnel-Origin": "cloudflare"}
        with self.assertRaises(Denied):
            await ns["require_localhost"](request)
        request.headers = {}
        await ns["require_api_key_strict"](request)
        await ns["require_localhost"](request)
        for _ in range(2):
            self.assertEqual((await ns["lastfm_shadow_status"](request))["state"], "disabled")


if __name__ == "__main__":
    unittest.main()
