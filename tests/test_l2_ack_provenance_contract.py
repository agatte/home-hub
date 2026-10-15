"""#370 scoped offline method contracts, not physical acceptance tests.

Compile selected actual production AST definitions only: no backend imports,
initializers, configuration, DB, phue or hardware. Selected inner method bodies
are explicitly undecorated; synthetic boundaries do NOT test production frame
decorators, native processes, complete leases or Desk acceptance contract B.
Existing lighting_authority and screen_sync_multi tests cover fuller lease/frame
paths. This slice adds independent bridge readback versus acknowledgement/cache/
freshness evidence. All numbers are synthetic, never a calibration or baseline.
Fake bridge False replies characterize this adapter's nonthrow path only; they
do not assert that real phue returns False. No new runtime adapter is installed.
"""
import ast
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVOKED = object()


class CircuitBreakerOpen(Exception):
    pass


def selected_class(filename, name, methods, *, complete=False):
    """Fail closed on missing definitions; execute no module imports/init code."""
    path = ROOT / 'backend' / 'services' / filename
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    if not complete:
        chosen = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name in methods]
        if {n.name for n in chosen} != set(methods):
            raise AssertionError('Selected production methods missing')
        cls.body = chosen
    # Deliberate inner-body scope, never evidence for the decorators' contracts.
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
    ns = dict(Any=Any, asyncio=asyncio, time=time, datetime=datetime,
              timezone=timezone, dataclass=dataclass, field=field,
              logger=logging.getLogger('offline_ack_contract'),
              CircuitBreakerOpen=CircuitBreakerOpen, _WRITE_REVOKED=REVOKED,
              DEFAULT_TRANSITION_SECONDS=0.4, INFLIGHT_BUFFER_SECONDS=0.5)
    if complete:
        ns['dataclass'] = dataclass
    module = ast.Module(body=[ast.ImportFrom(module='__future__',
        names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), ns)
    return ns[name]


Hue = selected_class('hue_service.py', 'HueService', {'set_light', 'get_all_lights'})
Result = selected_class('light_applicator.py', 'LightApplyResult', (), complete=True)
Applicator = selected_class('light_applicator.py', 'LightApplicator', {'_apply_per_light_locked'})
# Inject the actual result class into the selected method's globals.
Applicator._apply_per_light_locked.__globals__['LightApplyResult'] = Result
Sync = selected_class('screen_sync.py', 'ScreenSyncService',
                      {'_set_light_serialized', '_record_source_write', '_drop_physical_claim'})


class Bridge:
    """Requests never alter readback; response and readback are independent."""
    def __init__(self, reply=True):
        self.reply = reply
        self.calls = []

    def set_light(self, lid, state):
        self.calls.append((lid, state.copy()))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def get_api(self):
        return {'lights': {'2': {'name': 'synthetic L2',
                                'state': {'on': True, 'bri': 24, 'reachable': True}}}}


def hue_fixture(reply=True):
    h = Hue()
    h._connected = True
    h._bridge = Bridge(reply)
    h._transition_boundary = None
    h._inflight_until = {}
    h._transition_settle_until = {}
    h.known_light_ids = set()
    async def safe_call(fn, *args, **kwargs):
        return fn(*args)
    h._safe_call = safe_call
    return h


class Authority:
    def __init__(self):
        self.calls = []

    def invalidate(self, ids, **kwargs):
        self.calls.append((list(ids), kwargs))


def app_fixture(hue, protected=(), cache=None, suppressed=False, replies=None):
    app = Applicator()
    app._suppressed = lambda: suppressed
    app._overrides = SimpleNamespace(prune_expired_transit=lambda: None)
    app.protected_light_ids = lambda: set(protected)
    app._hue_getter = lambda: hue
    app._st = SimpleNamespace(last_applied_per_light=dict(cache or {}))
    app._transition_boundary = SimpleNamespace(authority=Authority())
    app.invalidated = []
    app._invalidate_screen_sync_cache = lambda ids: app.invalidated.extend(ids)
    async def write_many(tasks, ids):
        if replies is not None:
            return replies
        return await asyncio.gather(*(task() for task in tasks), return_exceptions=True)
    app._write_many = write_many
    return app


def sync_fixture(hue):
    sync = Sync()
    sync.valid = True
    sync.accepted = 0
    def accept():
        sync.accepted += 1
    sync._frame_guard = ContextVar('offline_frame', default=(lambda: sync.valid, accept, 'synthetic', False))
    async def run_write(fn, *, validator, light_ids):
        return await fn() if validator() else False
    sync._transition_boundary = SimpleNamespace(held_by_current_task=True,
        authority=Authority(), run_write=run_write)
    sync._hue = hue
    sync._last_color_at = None
    sync._last_source = None
    for name in ('_last_color_at_by_source', '_last_color_at_by_light',
                 '_last_frame_kind_by_light', '_desk_page_source_by_light',
                 '_last_sent_state', '_last_daylight_state', '_hold_refreshed_at'):
        setattr(sync, name, {})
    return sync


class ProvenanceContract(unittest.IsolatedAsyncioTestCase):
    async def assert_readback(self, hue):
        self.assertEqual((await hue.get_all_lights())[0]['bri'], 24)

    async def test_hue_ack_is_not_bridge_brightness(self):
        h = hue_fixture()
        target = {'bri': 70}
        self.assertIs(await h.set_light('2', target), True)
        self.assertEqual(h._bridge.calls, [(2, target)])
        self.assertIn('2', h._inflight_until)
        await self.assert_readback(h)

    async def test_hue_nonthrow_false_reply_still_acknowledges(self):
        h = hue_fixture(False)
        self.assertIs(await h.set_light('2', {'bri': 70}), True)
        self.assertIn('2', h._transition_settle_until)
        await self.assert_readback(h)

    async def test_hue_exception_has_no_receipt(self):
        h = hue_fixture(RuntimeError('synthetic bridge failure'))
        with self.assertLogs('offline_ack_contract', level='ERROR'):
            self.assertIs(await h.set_light('2', {'bri': 70}), False)
        self.assertEqual(h._inflight_until, {})
        self.assertEqual(h._transition_settle_until, {})
        await self.assert_readback(h)

    async def test_hue_disconnected_has_no_command_or_receipt(self):
        h = hue_fixture()
        h._connected = False
        self.assertIs(await h.set_light('2', {'bri': 70}), False)
        self.assertEqual(h._bridge.calls, [])
        self.assertEqual(h._inflight_until, {})
        self.assertEqual(await h.get_all_lights(), [])

    async def test_hue_empty_or_revoked_has_no_receipt(self):
        for state, reply in (({'unknown': 70}, True), ({'bri': 70}, REVOKED)):
            with self.subTest(state=state):
                h = hue_fixture(reply)
                self.assertIs(await h.set_light('2', state), False)
                self.assertEqual(h._inflight_until, {})
                self.assertEqual(h._transition_settle_until, {})
                self.assertEqual(len(h._bridge.calls), int(reply is REVOKED))

    async def test_hue_ct_preserves_sat_before_ct_and_input(self):
        h = hue_fixture()
        target = {'ct': 350, 'hue': 123, 'sat': 80, 'bri': 70}
        before = target.copy()
        self.assertTrue(await h.set_light('2', target))
        command = h._bridge.calls[0][1]
        self.assertEqual(list(command), ['bri', 'sat', 'ct'])
        self.assertEqual(command, {'bri': 70, 'sat': 0, 'ct': 350})
        self.assertEqual(target, before)
        await self.assert_readback(h)

    async def test_app_partial_failure_is_per_light_not_readback(self):
        h = hue_fixture()
        original = h.set_light
        async def write(lid, state):
            return await original(lid, state) if lid == '2' else False
        h.set_light = write
        app = app_fixture(h, cache={'5': {'bri': 24}})
        target = {'2': {'bri': 70}, '5': {'bri': 50}}
        result, logs = await app._apply_per_light_locked(target, 4)
        self.assertEqual(result.successful, {'2'})
        self.assertEqual(result.failed, {'5'})
        self.assertFalse(result.covers({'2', '5'}))
        self.assertTrue(result.covers({'2'}))
        self.assertEqual(app._st.last_applied_per_light, {'2': {'bri': 70}, '5': {'bri': 24}})
        self.assertEqual(app.invalidated, ['2'])
        self.assertEqual(app._transition_boundary.authority.calls, [(['2'], {'intent': False})])
        self.assertEqual(logs, [('2', {}, {'bri': 70})])
        self.assertEqual(h._bridge.calls, [(2, {'bri': 70, 'transitiontime': 4})])
        self.assertEqual(target, {'2': {'bri': 70}, '5': {'bri': 50}})
        await self.assert_readback(h)

    async def test_app_false_or_exception_acquires_nothing(self):
        for reply in (False, RuntimeError('synthetic'), 1):
            with self.subTest(reply=reply):
                app = app_fixture(hue_fixture(), replies=[reply])
                result, logs = await app._apply_per_light_locked({'2': {'bri': 70}}, None)
                self.assertEqual(result.failed, {'2'})
                self.assertEqual(result.successful, set())
                self.assertEqual(app._st.last_applied_per_light, {})
                self.assertEqual(app.invalidated, [])
                self.assertEqual(app._transition_boundary.authority.calls, [])
                self.assertEqual(logs, [])

    async def test_app_protected_l2_does_not_acquire_receipt(self):
        h = hue_fixture()
        app = app_fixture(h, protected={'2'})
        result, logs = await app._apply_per_light_locked({'2': {'bri': 70}}, None)
        self.assertEqual(result.skipped, {'2'})
        self.assertFalse(result.covers({'2'}))
        self.assertEqual((h._bridge.calls, app.invalidated, logs), ([], [], []))
        self.assertEqual(app._transition_boundary.authority.calls, [])

    async def test_app_suppressed_has_no_receipt(self):
        h = hue_fixture()
        app = app_fixture(h, suppressed=True)
        result, logs = await app._apply_per_light_locked({'2': {'bri': 70}}, None)
        self.assertEqual(result.skipped, {'2'})
        self.assertEqual(result.successful, set())
        self.assertEqual((h._bridge.calls, app.invalidated, logs), ([], [], []))
        self.assertEqual(app._transition_boundary.authority.calls, [])

    async def test_app_deduplicated_virtual_cache_is_not_brightness(self):
        h = hue_fixture()
        app = app_fixture(h, cache={'2': {'bri': 70}})
        result, logs = await app._apply_per_light_locked({'2': {'bri': 70}}, None)
        self.assertEqual(result.deduplicated, {'2'})
        self.assertFalse(result.covers({'2'}))
        self.assertEqual((h._bridge.calls, app.invalidated, logs), ([], [], []))
        self.assertEqual(app._transition_boundary.authority.calls, [])
        await self.assert_readback(h)

    async def test_app_protection_survives_other_light_failure(self):
        h = hue_fixture()
        app = app_fixture(h, protected={'2'}, cache={'2': {'bri': 24}}, replies=[False])
        target = {'2': {'bri': 70}, '5': {'bri': 50}}
        result, logs = await app._apply_per_light_locked(target, None)
        self.assertEqual(result.skipped, {'2'})
        self.assertEqual(result.failed, {'5'})
        self.assertEqual(result.successful, set())
        self.assertEqual(app._st.last_applied_per_light, {'2': {'bri': 24}})
        self.assertEqual(app._transition_boundary.authority.calls, [])
        self.assertEqual((app.invalidated, logs), ([], []))
        self.assertEqual(target, {'2': {'bri': 70}, '5': {'bri': 50}})

    async def test_sync_accepted_command_and_stamp_are_not_readback(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        self.assertTrue(await sync._set_light_serialized('2', {'bri': 70}))
        self.assertEqual(sync.accepted, 1)
        self.assertEqual(sync._last_color_at_by_light, {})
        self.assertTrue(sync._record_source_write('desktop', '2'))
        self.assertIn('2', sync._last_color_at_by_light)
        self.assertEqual(sync._transition_boundary.authority.calls,
                         [(['2'], {'intent': False}), (['2'], {})])
        await self.assert_readback(h)

    async def test_sync_failed_command_does_not_stamp(self):
        h = hue_fixture(REVOKED)
        sync = sync_fixture(h)
        self.assertFalse(await sync._set_light_serialized('2', {'bri': 70}))
        self.assertEqual(sync.accepted, 0)
        self.assertEqual(sync._last_color_at_by_source, {})
        self.assertEqual(sync._transition_boundary.authority.calls, [])
        await self.assert_readback(h)

    async def test_sync_revoked_before_dispatch_never_writes(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        sync.valid = False
        self.assertFalse(await sync._set_light_serialized('2', {'bri': 70}))
        self.assertEqual(h._bridge.calls, [])
        self.assertEqual(sync.accepted, 0)
        self.assertEqual(sync._transition_boundary.authority.calls, [])
        self.assertEqual(sync._last_color_at_by_light, {})

    async def test_sync_stale_mid_io_success_drops_claim_not_source_refresh(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        self.assertTrue(sync._record_source_write('desktop', '2'))
        stamp = sync._last_color_at_by_source['desktop']
        sync._last_sent_state['2'] = {'bri': 70}
        sync._last_daylight_state['2'] = {'bri': 70}
        sync._desk_page_source_by_light['2'] = 'desktop'
        sync._hold_refreshed_at[('desktop', '2')] = stamp
        original = h.set_light
        async def write(lid, state):
            success = await original(lid, state)
            sync.valid = False
            return success
        h.set_light = write
        self.assertFalse(await sync._set_light_serialized('2', {'bri': 70}))
        self.assertEqual(len(h._bridge.calls), 1)
        self.assertIn('2', h._inflight_until)
        self.assertEqual(sync.accepted, 0)
        self.assertFalse(sync._record_source_write('desktop', '2'))
        self.assertEqual(sync._last_color_at_by_source['desktop'], stamp)
        for name in ('_last_sent_state', '_last_daylight_state',
                     '_desk_page_source_by_light', '_last_color_at_by_light', '_last_frame_kind_by_light'):
            self.assertNotIn('2', getattr(sync, name))
        self.assertEqual(sync._hold_refreshed_at, {})
        self.assertEqual(sync._transition_boundary.authority.calls[-1], (['2'], {'intent': False}))
        await self.assert_readback(h)

    async def test_sync_deduplicated_stamp_without_write_is_not_brightness(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        # Model only the freshness publication step of a deduplicated frame;
        # actual frame composition/deadband/dedup selection is outside scope.
        sync._last_sent_state['2'] = {'bri': 70}
        self.assertTrue(sync._record_source_write('desktop', '2'))
        self.assertIn('desktop', sync._last_color_at_by_source)
        self.assertEqual(sync._last_sent_state['2'], {'bri': 70})
        self.assertEqual(h._bridge.calls, [])
        self.assertEqual(h._inflight_until, {})
        await self.assert_readback(h)

    async def test_sync_invalid_frame_cannot_stamp_source(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        sync.valid = False
        self.assertFalse(sync._record_source_write('desktop', '2'))
        self.assertIsNone(sync._last_source)
        self.assertIsNone(sync._last_color_at)
        self.assertEqual(sync._last_color_at_by_source, {})
        self.assertEqual(sync._last_color_at_by_light, {})
        self.assertEqual(sync._transition_boundary.authority.calls, [])

    async def test_sync_requires_synthetic_held_boundary(self):
        h = hue_fixture()
        sync = sync_fixture(h)
        sync._transition_boundary.held_by_current_task = False
        with self.assertRaisesRegex(RuntimeError, 'leased frame boundary'):
            await sync._set_light_serialized('2', {'bri': 70})
        self.assertEqual(h._bridge.calls, [])
        self.assertEqual(sync._last_color_at_by_source, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
