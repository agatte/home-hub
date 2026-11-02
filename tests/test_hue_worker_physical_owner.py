"""#370 V1 acceptance: real source ingest/predicate/applicator/Hue, memory I/O.

Signed Python -B runner AST-loads selected production methods, avoiding the
application dependency graph. No environment, credentials or devices accessed.
The original eight RED cases remain pre-acceptance regression proofs.
"""
import ast
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import importlib.util
import logging
from pathlib import Path
import sys
from threading import Event, RLock, Thread, get_ident
from time import monotonic, sleep
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def selected(name, classes, namespace):
    path = ROOT / 'backend/services' / (name + '.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in classes:
            methods = classes[node.name]
            if methods is not None:
                node.body = [n for n in node.body if getattr(n, 'name', None) in methods]
                assert methods <= {getattr(n, 'name', None) for n in node.body}
            nodes.append(node)
    assert {n.name for n in nodes} == set(classes)
    code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[
        ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), str(path), 'exec'), namespace)
    return namespace


def fixture_modules():
    # Private process-only packages: pure Hue modules never import app config.
    for name in ('backend', 'backend.services'):
        module = ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
    base = dict(asyncio=asyncio, dataclass=dataclass, field=field,
                datetime=datetime, timedelta=timedelta, timezone=timezone,
                logger=logging.getLogger(__name__))
    # Load numeric policy values from source, rather than duplicating them.
    for filename, names in (
        ('automation_constants', {'PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS',
         'PHYSICAL_CONTEXT_PRESENCE_LOSS_SECONDS', 'SOURCE_STALE_SECONDS'}),
        ('presence_fusion', {'FUTURE_SKEW_TOLERANCE_S',
         'STRONG_PRESENCE_FRESHNESS_S', 'LATITUDE_STRONG_FACE_THRESHOLD'}),
    ):
        tree = ast.parse((ROOT / 'backend/services' / (filename + '.py')).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in node.targets
            ):
                exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), base)
        assert names <= base.keys()
    presence = ModuleType('backend.services.presence_fusion')
    presence.__dict__.update(base)
    sys.modules[presence.__name__] = presence
    selected('presence_fusion', {'PresenceReading': None, 'PresenceFusion': {
        'on_observation', 'invalidate_source', 'get_source_reading', 'physical_source_acceptance_gate',
        '_is_at_desk', '_is_strongly_present'}}, presence.__dict__)
    sys.modules[presence.__name__] = presence
    for name in ('lighting_authority', 'lighting_transition_boundary', 'circuit_breaker', 'hue_service'):
        fullname = 'backend.services.' + name
        spec = importlib.util.spec_from_file_location(fullname, ROOT / 'backend/services' / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = module
        spec.loader.exec_module(module)
    base.update(mode_apply_epoch=ContextVar('worker_mode', default=None),
                mode_physical_validator=ContextVar('worker_physical', default=None))
    selected('automation_engine', {'DeskAuthorityState': None, 'DeskAuthorityDecision': None,
        'AutomationEngine': {'_desk_activity_owner', '_capture_mode_physical_validator', '_resolve_desk_process_authority',
        '_physical_context_source_reading', '_physical_context_reading_age'}}, base)
    selected('light_applicator', {'LightApplyResult': None, 'LightApplicator': {
        '_write_many', '_apply_per_light_locked'}}, base)
    return base, presence


if __name__ == '__main__':
    NS, PRESENCE = fixture_modules()
else:
    from backend.services import presence_fusion as PRESENCE
    from backend.services.automation_engine import AutomationEngine
    from backend.services.automation_constants import PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS
    from backend.services.light_applicator import LightApplicator, mode_apply_epoch, mode_physical_validator
    NS = dict(AutomationEngine=AutomationEngine, LightApplicator=LightApplicator,
              mode_apply_epoch=mode_apply_epoch, mode_physical_validator=mode_physical_validator,
              PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS=PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS)
from backend.services.hue_service import HueService
from backend.services.lighting_transition_boundary import LightingTransitionBoundary


class WorkerPhysicalOwner(unittest.IsolatedAsyncioTestCase):
    def test_expiry_while_waiting_for_source_gate(self):
        from backend.services.lighting_authority import DeskAcceptanceGuard, LightingAuthority
        from time import monotonic
        lock, waiting = RLock(), Event()
        class ObservedGate:
            def __enter__(self):
                waiting.set()
                lock.acquire()
            def __exit__(self, *args):
                lock.release()
        gate = ObservedGate()
        presence = SimpleNamespace(_physical_source_gate=gate, _readings={})
        guard = DeskAcceptanceGuard(SimpleNamespace(), presence, monotonic() + 0.05)
        authority = LightingAuthority(SimpleNamespace())
        lease = authority.issue('static_apply', ['1'], intent_only=True)
        state = SimpleNamespace(manual_light_overrides={}, transit_light_overrides={})
        waiting.clear()
        result = []
        worker = Thread(target=lambda: result.append(guard.commit(authority, lease, '1', state, True)))
        with lock:
            worker.start()
            self.assertTrue(waiting.wait(2))
            # Cross the original deadline naturally while acquisition waits.
            sleep(max(0, guard.deadline - monotonic()) + 0.02)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [None])

    async def scenario(self, count, revoke, independent=False, post=False, split=False, failure=False, at_commit=False, cancel=False, timeout=False, future=None, future_delay=2.05, wait_expiry=False):
        loop_thread = get_ident()
        now = [datetime(2026, 10, 13, 12, tzinfo=timezone.utc)]
        fusion = object.__new__(PRESENCE.PresenceFusion)
        fusion._readings = {}
        fusion._physical_source_gate = RLock()
        fusion._clock = SimpleNamespace(utc_now=lambda: now[0])
        fusion._capture_call = lambda *args: None
        # Attendance bookkeeping is outside this slice. Source publication,
        # immutable reading identity and both Desk predicates are real methods.
        fusion.is_strongly_present_any = lambda: False
        fusion._last_at_desk_at = fusion._last_at_desk_source = None
        fusion._last_global_absence_observed_at = None
        reading = PRESENCE.PresenceReading(source='desktop', captured_at=now[0],
            face_present=True, detection_source='face', zone='desk')
        if wait_expiry:
            reading = replace(reading, captured_at=now[0] - timedelta(
                seconds=NS['PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS'] - 0.05))
        fusion.on_observation(reading)
        engine_type = type('FixtureEngine', (NS['AutomationEngine'],), {
            'effective_mode': property(lambda self: self._current_mode),
            'house_state': property(lambda self: 'home'),
        })
        e = object.__new__(engine_type)
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
        def loop_now():
            self.assertEqual(get_ident(), loop_thread)
            self.assertFalse(fusion._physical_source_gate._is_owned())
            return now[0]
        e._now = loop_now
        if revoke == 'latitude_aba':
            latitude_original = PRESENCE.PresenceReading(
                source='latitude', captured_at=now[0], face_present=True,
                detection_source='yolo', zone='desk')
            fusion.on_observation(latitude_original)
        if future:
            zone, source, detection, confidence = future
            fusion.on_observation(PRESENCE.PresenceReading(
                source=source, captured_at=now[0] + timedelta(seconds=future_delay),
                face_present=True, detection_source=detection,
                face_confidence=confidence, zone=zone))
        physical = e._capture_mode_physical_validator()
        self.assertTrue(physical())
        if independent:
            e._manual_override = True
            self.assertIsNone(e._capture_mode_physical_validator())
        hue = HueService('memory', 'memory')
        hue._connected = True
        if timeout:
            hue.breaker.call_timeout = 0.02
        calls = []
        bridge_entered = [Event() for _ in range(count)]
        bridge_release = Event()
        def bridge(lid, command):
            self.assertFalse(fusion._physical_source_gate._is_owned())
            bridge_entered[lid - 1].set()
            if post or split:
                if not bridge_release.wait(5):
                    raise AssertionError('ACK barrier timeout')
            if failure:
                raise OSError('memory bridge failure')
            calls.append((lid, command))
        hue._bridge = SimpleNamespace(set_light=bridge)
        boundary = LightingTransitionBoundary(hue)
        hue.set_transition_boundary(boundary)
        app = object.__new__(NS['LightApplicator'])
        app._transition_boundary = boundary
        app._st = SimpleNamespace(last_applied_per_light={}, manual_light_overrides={}, transit_light_overrides={})
        app._suppressed = lambda: False
        app._owner_revision_getter = lambda: e._mode_transition_revision
        app._current_mode_getter = lambda: e.effective_mode
        app._overrides = SimpleNamespace(prune_expired_transit=lambda: None)
        app.protected_light_ids = lambda: set()
        app._hue_getter = lambda: hue
        app._invalidate_screen_sync_cache = lambda ids: None
        states = {str(i): {'bri': 100} for i in range(1, count + 1)}
        def revoke_now():
            if revoke == 'expired' and not wait_expiry:
                now[0] += timedelta(seconds=NS['PHYSICAL_CONTEXT_OBSERVATION_FRESH_SECONDS'], microseconds=1)
            elif revoke == 'replacement':
                fusion.on_observation(replace(reading))
                self.assertIsNot(fusion.get_source_reading('desktop'), reading)
            elif revoke == 'invalidated':
                fusion.invalidate_source('desktop')
            elif revoke == 'owner_aba':
                e._desk_activity_owner = None
                e._desk_activity_owner = tuple([7, 'gaming', 'process:desktop'])
            elif revoke == 'lease':
                boundary.authority.invalidate(states)
            elif revoke == 'manual_light':
                app._st.manual_light_overrides['1'] = object()
            elif revoke == 'latitude_aba':
                fusion.on_observation(replace(latitude_original))
                fusion.on_observation(latitude_original)
                self.assertIs(fusion.get_source_reading('latitude'), latitude_original)
            elif revoke == 'native_deadline':
                physical.acceptance_guard.deadline = 0
        if at_commit:
            original_commit = physical.acceptance_guard.commit
            def racing_commit(*args):
                self.assertEqual(get_ident(), loop_thread)
                self.assertFalse(fusion._physical_source_gate._is_owned())
                revoke_now()
                if future or wait_expiry:
                    lock, waiting = RLock(), Event()
                    class ObservedGate:
                        def __enter__(gate_self):
                            waiting.set()
                            lock.acquire()
                        def __exit__(gate_self, *exc):
                            lock.release()
                    # Use the same source RLock, held by another thread. The
                    # loop commit blocks on it after its last policy check.
                    lock = fusion._physical_source_gate
                    physical.acceptance_guard.gate = ObservedGate()
                    ready = Event()
                    def contend():
                        with lock:
                            ready.set()
                            if not waiting.wait(2):
                                raise AssertionError('acceptance did not contend')
                            started = monotonic()
                            sleep(0.10)
                            now[0] += timedelta(seconds=monotonic() - started)
                    holder = Thread(target=contend)
                    holder.start()
                    self.assertTrue(ready.wait(2))
                    try:
                        receipt = original_commit(*args)
                    finally:
                        holder.join(2)
                    self.assertFalse(holder.is_alive())
                    conflict = bool(future) and future_delay <= 2.1 and source == 'latitude' and zone in {'couch', 'bed'} and (
                        detection in {'yolo', 'pose'} or
                        detection == 'face' and confidence >= PRESENCE.LATITUDE_STRONG_FACE_THRESHOLD)
                    self.assertEqual(physical(), not (conflict or wait_expiry))
                    return receipt
                return original_commit(*args)
            physical.acceptance_guard.commit = racing_commit
        entered = [Event() for _ in states]
        releases = [Event() for _ in states]
        original = boundary.dispatch_snapshot_valid
        index = [0]
        def paused(snapshot):
            self.assertNotEqual(get_ident(), loop_thread)
            slot = index[0]
            index[0] += 1
            entered[slot].set()
            if not releases[slot].wait(5):
                raise AssertionError('worker barrier timeout')
            return original(snapshot)
        async def apply():
            owner = NS['mode_apply_epoch'].set(None if independent else (7, 'gaming'))
            guard = NS['mode_physical_validator'].set(None if independent else physical)
            try:
                async with boundary.serialized():
                    return await app._apply_per_light_locked(states, None)
            finally:
                NS['mode_physical_validator'].reset(guard)
                NS['mode_apply_epoch'].reset(owner)
        with patch.object(boundary, 'dispatch_snapshot_valid', paused):
            task = asyncio.create_task(apply())
            try:
                async with asyncio.timeout(5):
                    while not all(event.is_set() for event in entered):
                        await asyncio.sleep(0.001)
                generations = (boundary._serialized_epoch, boundary.authority._global, boundary.authority._whole)
                if post or split:
                    for event in releases[:1 if split else count]:
                        event.set()
                    async with asyncio.timeout(5):
                        while sum(event.is_set() for event in bridge_entered) < (1 if split else count):
                            await asyncio.sleep(0.001)
                    self.assertEqual(app._st.last_applied_per_light, {})
                    self.assertEqual(hue._inflight_until, {})
                    self.assertEqual(hue._transition_settle_until, {})
                    self.assertIsNone(hue.breaker.snapshot()['last_success_at'])
                    if cancel:
                        task.cancel()
                        task.cancel()
                        await asyncio.sleep(0)
                        self.assertFalse(task.done())
                        self.assertTrue(boundary._lock.locked())
                    if timeout:
                        # The breaker is already waiting; shorten via its
                        # existing per-call budget before dispatch (below).
                        await asyncio.sleep(0.05)
                        self.assertFalse(task.done())
                        self.assertTrue(boundary._lock.locked())
                if not at_commit:
                    revoke_now()
                if revoke != 'lease':
                    self.assertEqual(generations, (boundary._serialized_epoch, boundary.authority._global, boundary.authority._whole))
                if not at_commit and revoke not in ('lease', 'manual_light', 'native_deadline'):
                    self.assertEqual(physical(), revoke == 'unchanged' and not independent)
                for event in releases:
                    event.set()
                bridge_release.set()
                if cancel:
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(app._st.last_applied_per_light, {})
                    self.assertEqual(len(calls), count)
                    self.assertIsNotNone(hue.breaker.snapshot()['last_success_at'])
                    return
                result, _ = await task
                allowed = independent or revoke == 'unchanged' or post
                if future or wait_expiry:
                    allowed = physical()
                # Collect all failures together: bridge actuation and each
                # false-success record must be absent for a revoked plan.
                actual = (len(calls), set(app._st.last_applied_per_light),
                          set(hue._inflight_until), set(hue._transition_settle_until),
                          result.successful, hue.breaker.snapshot()['last_success_at'] is not None)
                expected_ids = ({str(i + 1) for i, event in enumerate(bridge_entered) if event.is_set()}
                                if split else set(states) if allowed else set())
                if failure or timeout:
                    expected_ids = set()
                    self.assertEqual(hue.breaker.snapshot()['consecutive_failures'], count)
                self.assertEqual(actual, (count if timeout else len(expected_ids), expected_ids,
                    expected_ids, expected_ids, expected_ids, bool(expected_ids)))
            finally:
                for event in releases:
                    event.set()
                bridge_release.set()
                await asyncio.gather(task, return_exceptions=True)


def case(count, revoke, independent=False, **kwargs):
    async def test(self):
        await self.scenario(count, revoke, independent, **kwargs)
    return test


for _count in (1, 2):
    for _revoke in ('expired', 'replacement', 'invalidated', 'owner_aba', 'unchanged'):
        setattr(WorkerPhysicalOwner, f'test_{_count}_{_revoke}', case(_count, _revoke))
    setattr(WorkerPhysicalOwner, f'test_{_count}_independent_manual_source', case(_count, 'replacement', True))
    for _revoke in ('expired', 'replacement', 'invalidated', 'owner_aba'):
        setattr(WorkerPhysicalOwner, f'test_{_count}_accepted_then_{_revoke}', case(_count, _revoke, post=True))
    setattr(WorkerPhysicalOwner, f'test_{_count}_accepted_bridge_failure', case(_count, 'unchanged', failure=True))

for _zone in ('couch', 'bed'):
    setattr(WorkerPhysicalOwner, 'test_future_conflict_' + _zone,
            case(1, 'future_conflict', at_commit=True,
                 future=(_zone, 'latitude', 'yolo', 0.0)))

for _name, _future in (
    ('unknown_source', ('couch', 'other', 'yolo', 0.0)),
    ('latitude_desk', ('desk', 'latitude', 'yolo', 0.0)),
    ('weak_face', ('bed', 'latitude', 'face', 0.0)),
    ('unknown_detection', ('couch', 'latitude', None, 1.0)),
    ('strong_face', ('bed', 'latitude', 'face', PRESENCE.LATITUDE_STRONG_FACE_THRESHOLD)),
    ('pose', ('couch', 'latitude', 'pose', 0.0)),
):
    setattr(WorkerPhysicalOwner, 'test_future_' + _name,
            case(1, 'future_conflict', at_commit=True, future=_future))
setattr(WorkerPhysicalOwner, 'test_equal_timestamp_latitude_same_object_aba',
        case(1, 'latitude_aba', at_commit=True))
setattr(WorkerPhysicalOwner, 'test_future_conflict_before_eligibility',
        case(1, 'future_conflict', at_commit=True,
             future=('bed', 'latitude', 'yolo', 0.0), future_delay=10.0))
setattr(WorkerPhysicalOwner, 'test_natural_desk_expiry_at_hue_acceptance',
        case(1, 'expired', at_commit=True, wait_expiry=True))

setattr(WorkerPhysicalOwner, 'test_two_light_split_acceptance' , case(2, 'invalidated', split=True))
for _revoke in ('replacement', 'invalidated', 'owner_aba', 'lease', 'manual_light', 'native_deadline'):
    setattr(WorkerPhysicalOwner, 'test_raw_commit_rejects_' + _revoke, case(1, _revoke, at_commit=True))
setattr(WorkerPhysicalOwner, 'test_accepted_then_lease_revoke', case(1, 'lease', post=True))
setattr(WorkerPhysicalOwner, 'test_accepted_cancellation_settles', case(1, 'invalidated', post=True, cancel=True))
setattr(WorkerPhysicalOwner, 'test_accepted_timeout_settles', case(1, 'invalidated', post=True, timeout=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
