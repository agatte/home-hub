"""Offline real V2 PUT acceptance; signed Python -B, stdlib dependencies only."""
import ast
import asyncio
import importlib.util
import logging
from datetime import datetime, timedelta, timezone
from threading import RLock, Thread
from time import monotonic, sleep
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
if __name__ != '__main__':
    class OfflineV2Acceptance(unittest.TestCase):
        def test_signed_python_offline_v2_acceptance(self):
            # Keep pure-package shims private to a disposable child process;
            # normal pytest collection must retain its application imports.
            import subprocess
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve())],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
else:
    # Reuse the V1 real-source/engine AST loader without running its tests.
    tree = ast.parse((ROOT / 'tests/test_hue_worker_physical_owner.py').read_text(encoding='utf-8'))
    loader = {'__file__': str(ROOT / 'tests/test_hue_worker_physical_owner.py')}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,
        (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign))
        and not (isinstance(n, ast.ImportFrom) and n.module.startswith('backend'))], type_ignores=[]),
        'v1_fixture_loader', 'exec'), loader)
    NS, PRESENCE = loader['fixture_modules']()
    module = ModuleType('backend.services.light_applicator')
    module.mode_physical_validator = NS['mode_physical_validator']
    sys.modules[module.__name__] = module
    constants = ModuleType('backend.services.light_state_calculator')
    constants.ALL_LIGHT_IDS = ['1', '2']
    constants.AUTOMATIC_EFFECT_LIGHT_IDS = ['1', '2']
    constants.EFFECT_AUTO_MAP = {}
    sys.modules[constants.__name__] = constants
    spec = importlib.util.spec_from_file_location('backend.services.effect_manager',
        ROOT / 'backend/services/effect_manager.py')
    manager_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = manager_module
    spec.loader.exec_module(manager_module)
    from backend.services.lighting_transition_boundary import LightingTransitionBoundary, lighting_write_validator
    from backend.services.lighting_authority import DeskAcceptanceGuard

    class HTTPStatusError(Exception):
        def __init__(self, status):
            self.response = SimpleNamespace(status_code=status)

    V2 = loader['selected']('hue_v2_service', {'HueV2Service': {
        'set_effect', 'set_effect_all', 'stop_effect', 'stop_effect_all',
        'activate_scene', 'v1_to_v2_id', 'mapped_light_ids', 'connected'}},
        dict(asyncio=asyncio, lighting_write_validator=lighting_write_validator,
             httpx=SimpleNamespace(HTTPStatusError=HTTPStatusError),
             logger=logging.getLogger(__name__)))['HueV2Service']

    class V2Acceptance(unittest.IsolatedAsyncioTestCase):
        def fixture(self, *, lights=('1', '2'), future=None, ttl=8):
            now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
            fusion = object.__new__(PRESENCE.PresenceFusion)
            fusion._readings = {}
            fusion._physical_source_gate = RLock()
            fusion._clock = SimpleNamespace(utc_now=lambda: now)
            fusion._capture_call = lambda *args: None
            fusion.is_strongly_present_any = lambda: False
            fusion._last_at_desk_at = fusion._last_at_desk_source = None
            fusion._last_global_absence_observed_at = None
            reading = PRESENCE.PresenceReading(source='desktop',
                captured_at=now-timedelta(seconds=8-ttl), face_present=True,
                detection_source='face', zone='desk')
            fusion.on_observation(reading)
            if future:
                fusion.on_observation(PRESENCE.PresenceReading(source='latitude',
                    captured_at=now+timedelta(seconds=2.08), face_present=True,
                    detection_source='yolo', zone=future))
            fixture = type('Engine', (NS['AutomationEngine'],), {
                'effective_mode': property(lambda s: s._current_mode),
                'house_state': property(lambda s: 'home')})
            e = object.__new__(fixture)
            e._manual_override = False
            e._current_mode = 'gaming'
            e._mode_transition_revision = 7
            e._mode_source_key = 'process:desktop'
            e._desk_activity_owner = (7, 'gaming', 'process:desktop')
            e._presence_fusion = fusion
            e._enabled = True
            e._away_hold = e._host_return_hold = e._external_off_detected = False
            e._last_process_semantic_by_device = {}
            e.is_dnd_active = lambda: False
            def clock():
                self.assertFalse(fusion._physical_source_gate._is_owned())
                return now
            e._now = clock
            e._state = SimpleNamespace(manual_light_overrides={}, transit_light_overrides={})
            e._screen_sync = None
            e._external_light_owners = []
            e._suspended_external_owner_ids = set()
            # Real production eligibility and protected-light getter, fake owners.
            extra = loader['selected']('automation_engine', {'AutomationEngine': {
                '_active_external_light_owners', '_protected_light_ids'}}, {})['AutomationEngine']
            e._active_external_light_owners = extra._active_external_light_owners.__get__(e)
            e._protected_light_ids = extra._protected_light_ids.__get__(e)
            protected = loader['selected']('light_applicator', {'LightApplicator': {
                'protected_light_ids'}}, dict(datetime=datetime, timezone=timezone,
                    SCREEN_SYNC_MODES={'gaming', 'watching'}, SCREEN_SYNC_FRESH_SECONDS=8))['LightApplicator']
            applicator = object.__new__(protected)
            applicator._st = e._state
            applicator._screen_sync_getter = lambda: e._screen_sync
            applicator._current_mode_getter = lambda: e._current_mode
            applicator._external_owners_getter = e._active_external_light_owners
            e._applicator = applicator
            v2 = object.__new__(V2)
            v2._connected = True
            v2._v1_to_v2 = {lid: 'uuid'+lid for lid in lights}
            calls = []
            async def put(path, **kwargs):
                self.assertFalse(fusion._physical_source_gate._is_owned())
                calls.append((path, kwargs))
                return SimpleNamespace(raise_for_status=lambda: None)
            v2._client = SimpleNamespace(put=put)
            manager = manager_module.EffectManager(v2)
            manager.STOP_START_GUARD_SECONDS = 0
            e._transition_boundary = manager.transition_boundary
            physical = e._capture_mode_physical_validator()
            self.assertTrue(physical())
            return e, fusion, v2, manager, physical, calls

        async def run_manager(self, physical, method, *args):
            token = NS['mode_physical_validator'].set(physical)
            try:
                return await method(*args)
            finally:
                NS['mode_physical_validator'].reset(token)

        def revoke(self, cause, e, fusion, manager):
            if cause == 'source':
                fusion.invalidate_source('desktop')
            elif cause == 'replacement':
                reading = fusion.get_source_reading('desktop')
                fusion.on_observation(PRESENCE.PresenceReading(source='desktop',
                    captured_at=reading.captured_at, face_present=True,
                    detection_source='face', zone='desk'))
            elif cause == 'source_aba':
                reading = fusion.get_source_reading('desktop')
                fusion.invalidate_source('desktop')
                fusion.on_observation(reading)
            elif cause == 'owner':
                e._mode_transition_revision += 2
            elif cause == 'desk_aba':
                original = e._desk_activity_owner
                e._desk_activity_owner = None
                e._desk_activity_owner = original
            elif cause in ('screensync', 'effect', 'scene', 'external'):
                manager.transition_boundary.authority.invalidate(['1'])
            elif cause in ('couch', 'bed'):
                reading = fusion.get_source_reading('desktop')
                fusion.on_observation(PRESENCE.PresenceReading(source='latitude',
                    captured_at=reading.captured_at, face_present=True,
                    detection_source='yolo', zone=cause))
            elif cause == 'manual':
                e._state.manual_light_overrides['1'] = 1
            elif cause == 'transit':
                e._state.transit_light_overrides['1'] = 1

        async def test_raw_commit_rejects_after_policy_without_http(self):
            for cause in ('source', 'replacement', 'source_aba', 'owner', 'desk_aba', 'couch', 'bed',
                          'screensync', 'effect', 'scene', 'external', 'manual', 'transit'):
                with self.subTest(cause=cause):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    original = DeskAcceptanceGuard.commit
                    def commit(guard, *args):
                        # Deterministic rendezvous after on-loop policy; publication
                        # itself uses the real source/authority synchronization.
                        self.assertFalse(fusion._physical_source_gate._is_owned())
                        self.revoke(cause, e, fusion, manager)
                        return original(guard, *args)
                    with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                        self.assertFalse(await self.run_manager(physical,
                            manager.reconcile_light, '1', 'candle', self.safety))
                    self.assertEqual(calls, [])
                    self.assertFalse(manager.authority_known)

        async def test_original_monotonic_deadlines(self):
            for kind in ('ttl', 'couch', 'bed'):
                with self.subTest(kind=kind):
                    e, fusion, v2, manager, physical, calls = self.fixture(
                        lights=('1',), ttl=.08 if kind == 'ttl' else 8,
                        future=None if kind == 'ttl' else kind)
                    original = DeskAcceptanceGuard.commit
                    def commit(guard, *args):
                        deadline = guard.deadline if kind == 'ttl' else guard.conflict_not_after
                        sleep(max(0, deadline-monotonic())+.01)
                        # Wall-clock fixture remains unchanged: the raw gate must
                        # enforce the original monotonic deadline independently.
                        self.assertTrue(physical())
                        return original(guard, *args)
                    with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                        self.assertFalse(await self.run_manager(physical,
                            manager.reconcile_light, '1', 'candle', self.safety))
                    self.assertEqual(calls, [])

        async def test_split_fanout_and_accepted_transport_after_revocation(self):
            for operation in ('set_effect_all', 'stop_effect_all'):
                for cause in ('source', 'owner'):
                    with self.subTest(operation=operation, cause=cause):
                        e, fusion, v2, manager, physical, calls = self.fixture()
                        receipts = []
                        original = DeskAcceptanceGuard.commit
                        def commit(guard, *args):
                            receipt = original(guard, *args)
                            receipts.append(receipt)
                            return receipt
                        entered, release = asyncio.Event(), asyncio.Event()
                        acked = []
                        async def put(path, **kwargs):
                            self.assertFalse(fusion._physical_source_gate._is_owned())
                            calls.append(path)
                            entered.set()
                            # Thread publication must finish during the HTTP await.
                            thread = Thread(target=lambda: self.revoke(cause, e, fusion, manager))
                            thread.start(); thread.join(2)
                            self.assertFalse(thread.is_alive())
                            await release.wait()
                            acked.append(path)
                            return SimpleNamespace(raise_for_status=lambda: None)
                        v2._client.put = put
                        checkpoint = manager._publish_transition_checkpoint('test', physical=physical)
                        async def write():
                            async with manager.transition_boundary.serialized():
                                def current():
                                    return manager._transition_current(checkpoint, physical)
                                manager._attach_effect_acceptance(current, checkpoint, physical)
                                method = getattr(v2, operation)
                                return await manager._mutate(lambda: method('candle')
                                    if operation == 'set_effect_all' else method(), current)
                        with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                            task = asyncio.create_task(write())
                            await asyncio.wait_for(entered.wait(), 2)
                            release.set()
                            self.assertFalse(await asyncio.wait_for(task, 2))
                        self.assertEqual(calls, ['/light/uuid1'])
                        self.assertEqual(acked, calls)
                        self.assertIsNotNone(receipts[0])
                        self.assertEqual(len(receipts), 1)

        async def test_each_put_has_distinct_receipt_in_release_and_start(self):
            e, fusion, v2, manager, physical, calls = self.fixture()
            receipts = []
            original = DeskAcceptanceGuard.commit
            def commit(guard, *args):
                receipt = original(guard, *args)
                receipts.append(receipt)
                return receipt
            with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                self.assertTrue(await self.run_manager(physical, manager.reconcile,
                    {'effect': 'candle', 'lights': ['1', '2']}, self.safety))
            self.assertEqual(len(calls), 4)
            self.assertEqual(len({id(r.command) for r in receipts}), 4)
            self.assertTrue(manager.authority_known)
            self.assertEqual(manager.active_name, 'candle')

        async def test_release_preserves_holds_start_rejects_stronger_owners(self):
            for hold in ('manual', 'transit', 'sync', 'unbound_sync', 'external', 'legacy_external'):
                with self.subTest(hold=hold):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    if hold in ('manual', 'transit'):
                        getattr(e._state, hold+'_light_overrides')['1'] = 1
                    elif 'sync' in hold:
                        e._screen_sync = SimpleNamespace(
                            _transition_boundary=manager.transition_boundary if hold=='sync' else None,
                            fresh_owned_light_ids=lambda: {'1'})
                    else:
                        owner = SimpleNamespace(owned_light_targets=lambda: {'1': {'bri': 40}})
                        if hold == 'external':
                            owner.set_lighting_authority_notifier = lambda _: None
                        e._external_light_owners.append(owner)
                    self.assertTrue(await self.run_manager(physical, manager.reconcile_light,
                        '1', None, self.safety))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][1]['json']['effects']['effect'], 'no_effect')
                    self.assertFalse(await self.run_manager(physical, manager.reconcile_light,
                        '1', 'candle', self.safety))
                    self.assertEqual(len(calls), 1)

        def hold(self, kind, e, manager):
            if kind in ('manual', 'transit'):
                getattr(e._state, kind+'_light_overrides')['1'] = 1
            elif kind in ('sync', 'unbound_sync'):
                e._screen_sync = SimpleNamespace(
                    _transition_boundary=manager.transition_boundary if kind == 'sync' else None,
                    fresh_owned_light_ids=lambda: {'1'})
            else:
                owner = SimpleNamespace(owned_light_targets=lambda: {'1': {'bri': 40}})
                if kind == 'external':
                    owner.set_lighting_authority_notifier = lambda _: None
                e._external_light_owners.append(owner)

        async def test_direct_stop_refuses_preexisting_holds(self):
            for kind in ('manual', 'transit', 'sync', 'unbound_sync', 'external', 'legacy_external'):
                with self.subTest(kind=kind):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    manager._active_name = 'old'
                    manager._tracker_known = False
                    self.hold(kind, e, manager)
                    self.assertFalse(await self.run_manager(physical, manager.stop_all))
                    self.assertEqual(calls, [])
                    self.assertFalse(manager.authority_known)
                    self.assertEqual(manager.active_name, 'old')

        async def test_direct_stop_protection_between_policy_and_receipt(self):
            for kind in ('manual', 'transit', 'sync', 'external'):
                with self.subTest(kind=kind):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    manager._active_name = 'old'
                    manager._tracker_known = True
                    original = DeskAcceptanceGuard.commit
                    def commit(guard, *args):
                        self.assertFalse(fusion._physical_source_gate._is_owned())
                        self.hold(kind, e, manager)
                        if kind in ('sync', 'external'):
                            manager.transition_boundary.authority.invalidate(['1'])
                        return original(guard, *args)
                    with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                        self.assertFalse(await self.run_manager(physical, manager.stop_all))
                    self.assertEqual(calls, [])
                    self.assertFalse(manager.authority_known)
                    self.assertEqual(manager.active_name, 'old')

        async def test_gaming_marker_safe_cleanup_retains_marker_blocks_start(self):
            for kind in ('manual', 'transit', 'sync', 'external'):
                with self.subTest(kind=kind):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    marker = ('composed', 'removed-mapping')
                    e._gaming_scene_override = marker
                    self.hold(kind, e, manager)
                    manager._active_name = 'old'
                    established = []
                    applied_holds = set()
                    original_put = v2._client.put
                    async def put(path, **kwargs):
                        self.assertEqual(applied_holds, {'1'})
                        return await original_put(path, **kwargs)
                    v2._client.put = put
                    async def safety(required):
                        established.append(set(required))
                        # Disposable held-target reapplication completes before
                        # the actual production release reaches fake transport.
                        applied_holds.update(required)
                        return SimpleNamespace(covers=lambda scope: scope <= {'1'})
                    self.assertTrue(await self.run_manager(physical, manager.reconcile, None, safety))
                    self.assertEqual(established, [{'1'}])
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0][1]['json']['effects']['effect'], 'no_effect')
                    self.assertIs(e._gaming_scene_override, marker)
                    self.assertTrue(manager.authority_known)
                    self.assertIsNone(manager.active_name)
                    self.assertFalse(await self.run_manager(physical, manager.reconcile_light,
                        '1', 'candle', safety))
                    self.assertEqual(len(calls), 1)

        async def test_gaming_cleanup_requires_complete_safety(self):
            for result in (False, SimpleNamespace(covers=lambda scope: False)):
                e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                marker = {'requested_game': 'removed'}
                e._gaming_scene_override = marker
                self.hold('manual', e, manager)
                manager._active_name = 'old'
                async def safety(required):
                    return result
                self.assertFalse(await self.run_manager(physical, manager.reconcile, None, safety))
                self.assertEqual(calls, [])
                self.assertFalse(manager.authority_known)
                self.assertEqual(manager.active_name, 'old')
                self.assertIs(e._gaming_scene_override, marker)

        async def test_direct_stop_unknown_owners_fail_closed(self):
            for kind in ('unbound_sync', 'missing_sync_getter', 'legacy_external', 'missing_external_getter'):
                e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                manager._active_name = 'old'
                if 'sync' in kind:
                    e._screen_sync = SimpleNamespace(
                        _transition_boundary=None if kind == 'unbound_sync' else manager.transition_boundary)
                    if kind == 'unbound_sync':
                        e._screen_sync.fresh_owned_light_ids = lambda: set()
                else:
                    owner = SimpleNamespace()
                    if kind == 'legacy_external':
                        owner.owned_light_targets = lambda: {}
                    else:
                        owner.set_lighting_authority_notifier = lambda _: None
                    e._external_light_owners.append(owner)
                self.assertFalse(await self.run_manager(physical, manager.stop_all))
                self.assertEqual(calls, [])
                self.assertFalse(manager.authority_known)

        async def test_scene_marker_start_blocked_even_without_target_holds(self):
            for field in ('_gaming_scene_override', '_active_scene_override_key'):
                e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                setattr(e, field, 'stronger')
                self.assertFalse(await self.run_manager(physical, manager.reconcile_light,
                    '1', 'candle', self.safety))
                self.assertEqual(calls, [])
                manager._active_name = 'old'
                calls.clear()
                self.assertFalse(await self.run_manager(physical, manager.stop_all))
                self.assertEqual(calls, [])

        async def test_direct_stop_unheld_and_manual_path(self):
            for autonomous in (True, False):
                e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                manager._active_name = 'old'
                if not autonomous:
                    self.hold('manual', e, manager)
                self.assertTrue(await self.run_manager(physical if autonomous else None,
                    manager.stop_all))
                self.assertEqual(len(calls), 1)
                self.assertTrue(manager.authority_known)
                self.assertIsNone(manager.active_name)

        async def test_stop_effect_uses_release_receipt(self):
            e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
            checkpoint = manager._publish_transition_checkpoint('stop_one', physical=physical)
            async with manager.transition_boundary.serialized():
                def current():
                    return manager._transition_current(checkpoint, physical)
                manager._attach_effect_acceptance(current, checkpoint, physical)
                self.assertTrue(await manager._mutate(lambda: v2.stop_effect('1'), current))
            self.assertEqual(len(calls), 1)

        async def test_fresh_screensync_publication_at_commit_revokes_original_checkpoint(self):
            e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
            # Real ScreenSync publication plus freshness getters; no frame/network.
            sync_type = loader['selected']('screen_sync', {'ScreenSyncService': {
                '_record_source_write', 'fresh_owned_light_ids', 'held_owned_light_ids'}},
                dict(datetime=datetime, timezone=timezone, SCREEN_SYNC_FRESH_SECONDS=8))['ScreenSyncService']
            sync = object.__new__(sync_type)
            sync._transition_boundary = manager.transition_boundary
            sync._frame_guard = loader['ContextVar']('offline_frame', default=None)
            sync._last_color_at = None
            sync._last_color_at_by_light = {}
            sync._last_color_at_by_source = {}
            sync._last_frame_kind_by_light = {}
            sync._desk_page_source_by_light = {}
            sync._hold_refreshed_at = {}
            e._screen_sync = sync
            original = DeskAcceptanceGuard.commit
            def commit(guard, *args):
                self.assertTrue(sync._record_source_write('desktop', '1'))
                self.assertEqual(sync.fresh_owned_light_ids(), {'1'})
                return original(guard, *args)
            with loader['patch'].object(DeskAcceptanceGuard, 'commit', commit):
                self.assertFalse(await self.run_manager(physical,
                    manager.reconcile_light, '1', 'candle', self.safety))
            self.assertEqual(calls, [])

        async def test_new_intent_during_safety_cannot_recapture_checkpoint(self):
            for kind in ('screensync', 'effect', 'scene', 'external'):
                with self.subTest(kind=kind):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    async def safety(required):
                        self.revoke(kind, e, fusion, manager)
                        return True
                    self.assertFalse(await self.run_manager(physical, manager.reconcile,
                        'candle', safety))
                    self.assertEqual(calls, [])

        async def test_preexisting_global_stronger_policy_rejects_both_operations(self):
            for policy in ('dnd', 'away', 'external_off', 'disabled', 'scene', 'manual', 'sleeping'):
                for desired in (None, 'candle'):
                    with self.subTest(policy=policy, desired=desired):
                        e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                        if policy == 'dnd':
                            e.is_dnd_active = lambda: True
                        elif policy == 'away':
                            e._away_hold = True
                        elif policy == 'external_off':
                            e._external_off_detected = True
                        elif policy == 'disabled':
                            e._enabled = False
                        elif policy == 'scene':
                            e._active_scene_override_key = 'stronger'
                        elif policy == 'manual':
                            e._manual_override = True
                        else:
                            e._current_mode = 'sleeping'
                        self.assertFalse(await self.run_manager(physical,
                            manager.reconcile_light, '1', desired, self.safety))
                        self.assertEqual(calls, [])

        async def test_http_failure_ack_and_post_ack_currency(self):
            for failure in ('http', '429', 'transport', 'stale_ack', 'ack'):
                with self.subTest(failure=failure):
                    e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
                    manager._active_name = 'old'
                    manager._tracker_known = True
                    async def put(path, **kwargs):
                        self.assertFalse(fusion._physical_source_gate._is_owned())
                        calls.append(path)
                        if failure == 'transport':
                            raise OSError('offline failure')
                        if failure == 'stale_ack':
                            fusion.invalidate_source('desktop')
                        def ack():
                            if failure in ('http', '429'):
                                raise HTTPStatusError(429 if failure=='429' else 500)
                        return SimpleNamespace(raise_for_status=ack)
                    v2._client.put = put
                    self.assertEqual(await self.run_manager(physical, manager.stop_all), failure=='ack')
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(manager.authority_known, failure=='ack')
                    self.assertEqual(manager.active_name, None if failure=='ack' else 'old')

        async def test_cancellation_settles_accepted_http_and_tracker_unknown(self):
            e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
            manager._active_name = 'old'
            manager._tracker_known = True
            entered, release = asyncio.Event(), asyncio.Event()
            async def put(path, **kwargs):
                self.assertFalse(fusion._physical_source_gate._is_owned())
                entered.set()
                await release.wait()
                calls.append(path)
                return SimpleNamespace(raise_for_status=lambda: None)
            v2._client.put = put
            task = asyncio.create_task(self.run_manager(physical, manager.stop_all))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            fusion.invalidate_source('desktop')
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertTrue(manager.transition_boundary._lock.locked())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(calls, ['/light/uuid1'])
            self.assertFalse(manager.transition_boundary._lock.locked())
            self.assertFalse(manager.authority_known)

        async def test_scene_desk_fails_closed_manual_and_direct_effect_unchanged(self):
            e, fusion, v2, manager, physical, calls = self.fixture(lights=('1',))
            self.assertFalse(await self.run_manager(physical, manager.replace_with_action,
                lambda: v2.activate_scene('native'), self.safety))
            self.assertEqual([c[0] for c in calls], ['/light/uuid1'])
            self.assertFalse(manager.authority_known)
            calls.clear()
            e._manual_override = True
            self.assertIsNone(e._capture_mode_physical_validator())
            self.assertTrue(await manager.replace_with_action(
                lambda: v2.activate_scene('manual'), self.safety))
            self.assertEqual([c[0] for c in calls], ['/light/uuid1', '/scene/manual'])
            fusion.invalidate_source('desktop')
            self.assertTrue(await v2.set_effect('1', 'candle'))
            self.assertEqual(calls[-1][0], '/light/uuid1')
            # Explicit effect has no Desk dependency, even with held fixtures.
            e._state.manual_light_overrides['1'] = 1
            self.assertTrue(await manager.reconcile('candle', self.safety))
            self.assertTrue(manager.authority_known)

        async def test_missing_receipt_rejects_desk_before_put(self):
            v2 = object.__new__(V2)
            v2._connected = True
            v2._v1_to_v2 = {'1': 'one'}
            calls = []
            async def put(*args, **kwargs):
                calls.append(args)
                return SimpleNamespace(raise_for_status=lambda: None)
            v2._client = SimpleNamespace(put=put)
            manager = manager_module.EffectManager(v2)
            # A Desk predicate without the original raw acceptance receipt is unsafe.
            token = NS['mode_physical_validator'].set(lambda: True)
            try:
                self.assertFalse(await manager.reconcile_light('1', 'candle',
                    self.safety))
            finally:
                NS['mode_physical_validator'].reset(token)
            self.assertEqual(calls, [])

        async def safety(self, required):
            return True

    unittest.main()
