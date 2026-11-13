"""Offline, boundary-level regression tests for the WebSocket Hue writer.

No real network, bridge, host or app lifespan is used. The fixture loads the
actual engine lease validator method from source to exercise its real owner
precedence without starting the complete automation runtime.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from backend.services.lighting_transition_boundary import (
    LightingTransitionBoundary, lighting_write_validator,
)
from backend.services.ws_manual_light_guard import dispatch_manual_light


def real_validator():
    path = Path(__file__).resolve().parents[1] / "backend/services/automation_engine.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AutomationEngine")
    method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "validate_lighting_lease")
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            method,
        ],
        type_ignores=[],
    )
    namespace = {"ALL_LIGHT_IDS": tuple(str(i) for i in range(1, 7))}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["validate_lighting_lease"]


class Engine:
    validate_lighting_lease = real_validator()

    def __init__(self):
        self._transition_boundary = LightingTransitionBoundary(None)
        self.house_state = "home"
        self.current_mode = "relaxing"
        self._enabled = True
        self._external_off_detected = False
        self._away_hold = False
        self._host_return_hold = False
        self._gaming_scene_transition_pending = False
        self._active_scene_override_key = None
        self._gaming_scene_override = None
        self._effect_manager = SimpleNamespace(authority_known=True)
        self._transit_light_overrides = set()
        self.manual_light_overrides = set()
        self._screen_sync = None
        self._active_effect_name = None
        self._active_effect_lights = set()
        self._external = set()
        self._custom_protected = set()
        self._legacy_owners = []
        self._applicator = SimpleNamespace(external_owned_light_ids=lambda: set(self._external))
        self.stamps = []
        self.persists = 0
        self.persist_error = False
        self.persist_wait = None
        self.persist_hook = None

    @property
    def lighting_transition_boundary(self):
        return self._transition_boundary

    def _active_external_light_owners(self):
        return self._legacy_owners

    def _protected_light_ids(self):
        return (
            self._custom_protected
            | self.manual_light_overrides
            | self._transit_light_overrides
            | self._external
            | (self._screen_sync.fresh_owned_light_ids() if self._screen_sync is not None else set())
        )

    def mark_light_manual(self, lid, state):
        assert self._transition_boundary.held_by_current_task
        self.stamps.append((lid, dict(state)))
        self.manual_light_overrides.add(lid)
        self._transition_boundary.authority.invalidate([lid])

    async def persist_manual_light_ownership(self, *, raise_on_error):
        assert raise_on_error is True
        assert self._transition_boundary.held_by_current_task
        self.persists += 1
        if self.persist_wait is not None:
            await self.persist_wait.wait()
        if self.persist_hook is not None:
            await self.persist_hook()
        if self.persist_error:
            raise RuntimeError("fake persistence unavailable")


class Hue:
    """Fake final Hue path: delegated context, commit-time policy and lease fence."""

    def __init__(self, engine):
        self._transition_boundary = engine.lighting_transition_boundary
        self.connected = True
        self.fixture = {"light_id": "2", "reachable": True, "name": "Bedroom left", "bri": 80}
        self.get_hook = None
        self.send_hook = None
        self.after_write_hook = None
        self.ack = True
        self.calls = []
        self.read_count = 0

    async def get_light(self, lid):
        self.read_count += 1
        if self.get_hook:
            await self.get_hook()
        return self.fixture

    async def set_light(self, lid, state):
        if self.send_hook:
            await self.send_hook()
        boundary = self._transition_boundary
        validator = lighting_write_validator.get()
        allowed, snapshot = boundary.validate_dispatch(validator)
        if not allowed or not boundary.dispatch_snapshot_valid(snapshot):
            return False
        self.calls.append((lid, dict(state)))
        if self.after_write_hook is not None:
            await self.after_write_hook()
        return self.ack


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = Engine()
        self.hue = Hue(self.engine)

    async def send(self, lid="2", state=None):
        return await dispatch_manual_light(
            self.engine, self.hue, lid, {"bri": 100} if state is None else state
        )

    async def test_acknowledged_manual_and_repeat_are_single_fixture_and_durable(self):
        result = await self.send()
        self.assertEqual(result.status, "acknowledged")
        self.assertIs(result.before, self.hue.fixture)
        self.assertEqual(self.hue.calls, [("2", {"bri": 100})])
        self.assertEqual(self.engine.stamps, [("2", {"bri": 100})])
        self.assertEqual(self.engine.persists, 1)
        again = await self.send(state={"on": False})
        self.assertEqual(again.status, "acknowledged")
        self.assertEqual(self.hue.calls, [
            ("2", {"bri": 100}), ("2", {"on": False}),
        ])
        self.assertEqual(self.engine.persists, 2)

    async def test_rejects_unknown_target_or_mixed_color_temperature(self):
        for lid, state in [
            ("unknown", {"on": True}), ("999", {"bri": 100}),
            ("2", {}), ("2", {"transitiontime": 1}),
            ("2", {"ct": 400, "hue": 100}), ("2", {"sat": 0, "ct": 350}),
            ("2", {"invented": True}),
        ]:
            with self.subTest(lid=lid, state=state):
                self.assertEqual((await self.send(lid, state)).status, "denied")
        self.assertEqual(self.hue.calls, [])
        self.assertEqual(self.engine.stamps, [])

    async def test_denies_all_stronger_owner_and_lifecycle_cases_without_write(self):
        cases = [
            ("_enabled", False), ("_external_off_detected", True),
            ("_away_hold", True), ("_host_return_hold", True),
            ("house_state", "away"), ("house_state", "sleeping"),
            ("house_state", "unknown"), ("current_mode", "sleeping"),
            ("_gaming_scene_transition_pending", True),
            ("_active_scene_override_key", "active-scene"),
            ("_gaming_scene_override", {"name": "game"}),
            ("_active_effect_name", "effect"),
            ("_transit_light_overrides", {"2"}),
            ("_custom_protected", {"2"}),
            ("_external", {"2"}),
            ("_screen_sync", SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})),
            ("_legacy_owners", [object()]),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                self.setUp()
                setattr(self.engine, key, value)
                result = await self.send()
                self.assertEqual(result.status, "denied", key)
                self.assertEqual(self.hue.calls, [], key)
                self.assertEqual(self.engine.stamps, [], key)
                self.assertEqual(self.engine.persists, 0, key)

    async def test_unknown_identity_reachability_and_boundary_deny(self):
        for fixture in (None, {"light_id": "5", "reachable": True},
                        {"light_id": "2", "reachable": False}, {"light_id": "2"}):
            with self.subTest(fixture=fixture):
                self.setUp()
                self.hue.fixture = fixture
                self.assertEqual((await self.send()).status, "unavailable")
                self.assertEqual(self.hue.calls, [])
        self.setUp()
        self.hue._transition_boundary = LightingTransitionBoundary(None)
        self.assertEqual((await self.send()).status, "unavailable")
        self.assertEqual(self.hue.calls, [])

    async def test_new_owner_while_queued_invalidates_old_lease(self):
        boundary = self.engine.lighting_transition_boundary
        async with boundary.serialized():
            task = asyncio.create_task(self.send())
            await asyncio.sleep(0)
            self.engine._active_scene_override_key = "new_scene"
            boundary.authority.invalidate(["2"])
        result = await task
        self.assertEqual(result.status, "denied")
        self.assertEqual(self.hue.calls, [])
        self.assertEqual(self.engine.stamps, [])

    async def test_new_owner_during_bridge_read_is_rechecked(self):
        async def takeover():
            self.engine._transit_light_overrides.add("2")
            self.engine.lighting_transition_boundary.authority.invalidate(["2"])
        self.hue.get_hook = takeover
        self.assertEqual((await self.send()).status, "denied")
        self.assertEqual(self.hue.calls, [])
        self.assertEqual(self.engine.stamps, [])

    async def test_new_owner_at_final_hue_dispatch_is_fenced(self):
        async def takeover():
            self.engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})
            self.engine.lighting_transition_boundary.authority.invalidate(["2"])
        self.hue.send_hook = takeover
        self.assertEqual((await self.send()).status, "uncertain")
        self.assertEqual(self.hue.calls, [])
        self.assertEqual(self.engine.stamps, [])
        self.assertEqual(self.engine.persists, 0)

    async def test_bridge_failure_and_persistence_failure_never_retries(self):
        self.hue.ack = False
        self.assertEqual((await self.send()).status, "uncertain")
        self.assertEqual(len(self.hue.calls), 1)
        self.assertEqual(self.engine.stamps, [])
        self.assertEqual(self.engine.persists, 0)

        self.setUp()
        self.engine.persist_error = True
        self.assertEqual((await self.send()).status, "uncertain")
        self.assertEqual(len(self.hue.calls), 1)
        self.assertEqual(self.engine.stamps, [("2", {"bri": 100})])
        self.assertEqual(self.engine.persists, 1)

    async def test_caller_cancellation_drains_hue_ack_and_manual_stamp(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_bridge():
            entered.set()
            await release.wait()

        self.hue.send_hook = blocked_bridge
        task = asyncio.create_task(self.send())
        await entered.wait()
        task.cancel()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.assertEqual(self.hue.calls, [("2", {"bri": 100})])
        self.assertEqual(self.engine.stamps, [("2", {"bri": 100})])
        self.assertEqual(self.engine.persists, 1)


    async def test_existing_websocket_handler_wires_through_the_guard(self):
        # Call only the handler with synthetic app state, never TestClient lifespan.
        from backend.main import _handle_light_command
        from backend.schemas.ws import LightCommandData

        app = SimpleNamespace(state=SimpleNamespace(
            hue=self.hue, automation=self.engine, event_logger=None,
        ))
        await _handle_light_command(
            app, LightCommandData(light_id="2", bri=101), None,
        )
        self.assertEqual(self.hue.calls, [("2", {"bri": 101})])
        self.assertEqual(self.engine.persists, 1)
        self.assertEqual(len(self.engine.stamps), 1)

        self.setUp()
        self.engine._active_scene_override_key = "scene"
        app.state.hue, app.state.automation = self.hue, self.engine
        await _handle_light_command(
            app, LightCommandData(light_id="2", on=False), None,
        )
        self.assertEqual(self.hue.calls, [])
        self.assertEqual(self.engine.stamps, [])

    async def test_real_hue_dispatch_rendezvous_accepts_only_fenced_ack(self):
        # Real HueService thread/circuit-breaker/lease machinery, fake bridge IO.
        # No Hue discovery, network connection, or physical device calls.
        from unittest.mock import AsyncMock
        from backend.services.hue_service import HueService

        class FakeBridge:
            def __init__(self):
                self.calls = []
                self.valid_ack = True

            def set_light(self, lid, command):
                self.calls.append((lid, dict(command)))
                if not self.valid_ack:
                    return [[{"error": {"type": 901}}]]
                return [[{"success": {f"/lights/{lid}/state/{k}": v}}
                         for k, v in command.items()]]

        service = HueService("synthetic.invalid", "fake-no-network")
        service.set_transition_boundary(self.engine.lighting_transition_boundary)
        service._bridge = FakeBridge()
        service._connected = True
        service.get_light = AsyncMock(return_value=self.hue.fixture)

        ack = await dispatch_manual_light(self.engine, service, "2", {"bri": 120})
        self.assertEqual(ack.status, "acknowledged")
        self.assertEqual(service._bridge.calls, [(2, {"bri": 120})])
        self.assertEqual(self.engine.stamps, [("2", {"bri": 120})])

        # Already-owned ScreenSync must reject BEFORE a second bridge call.
        self.engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})
        self.engine.lighting_transition_boundary.authority.invalidate(["2"])
        denied = await dispatch_manual_light(self.engine, service, "2", {"on": False})
        self.assertEqual(denied.status, "denied")
        self.assertEqual(service._bridge.calls, [(2, {"bri": 120})])

        # An ambiguous bridge reply is not physical confirmation or permission
        # to stamp a fresh manual override.
        self.setUp()
        service.set_transition_boundary(self.engine.lighting_transition_boundary)
        service._bridge.calls.clear()
        service._bridge.valid_ack = False
        service.get_light = AsyncMock(return_value=self.hue.fixture)
        uncertain = await dispatch_manual_light(self.engine, service, "2", {"on": False})
        self.assertEqual(uncertain.status, "uncertain")
        self.assertEqual(service._bridge.calls, [(2, {"on": False})])
        self.assertEqual(self.engine.stamps, [])

    async def test_stronger_owner_arriving_after_bridge_dispatch_prevents_manual_stamp(self):
        async def takeover_after_outbound_call():
            self.engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})
            self.engine.lighting_transition_boundary.authority.invalidate(["2"])

        self.hue.after_write_hook = takeover_after_outbound_call
        result = await self.send()
        # The command reached the bridge; no claim of zero physical mutation.
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(self.hue.calls, [("2", {"bri": 100})])
        self.assertEqual(self.engine.stamps, [])
        self.assertEqual(self.engine.persists, 0)

    async def test_owner_change_during_persistence_downgrades_acknowledgement(self):
        async def takeover_during_persistence():
            self.engine._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {"2"})
            self.engine.lighting_transition_boundary.authority.invalidate(["2"])

        self.engine.persist_hook = takeover_during_persistence
        result = await self.send()
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(self.hue.calls, [("2", {"bri": 100})])
        # The earlier acknowledgement did stamp, but is not current authority
        # after a newer stronger owner publication during persistence.
        self.assertEqual(len(self.engine.stamps), 1)
        self.assertEqual(self.engine.persists, 1)

if __name__ == "__main__":
    unittest.main()
