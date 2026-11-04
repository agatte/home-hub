"""#370 non-actuating real-method slice; run with signed Python -B.

AST-selected production code, no application imports or device libraries.
Executes calculator, General composer, applicator filtering/write validators,
engine lease validators and real authority/boundary. Transport is memory only.
Not end-to-end: fusion qualification is supplied, full _apply_mode, DND policy,
Gaming publication, ScreenSync frame composition and Hue worker are unexercised.
No shared numeric L2 floor or physical adequacy claim (#136); #402 unchanged.
"""
import ast
import asyncio
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = {}
ROWS = []


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 13, 12, tzinfo=timezone.utc)


def load(filename, classes=None, functions=(), constants=False, namespace=None):
    """Compile reviewed definitions only; never execute source imports/init I/O."""
    path = ROOT / 'backend/services' / (filename + '.py')
    raw = path.read_bytes()
    PROVENANCE[filename] = hashlib.sha256(raw).hexdigest()
    tree = ast.parse(raw.decode('utf-8'))
    ns = dict(namespace or {})
    ns.update(datetime=FrozenDatetime, timezone=timezone, dataclass=dataclass,
              field=field, isfinite=isfinite, asyncio=asyncio,
              asynccontextmanager=asynccontextmanager, nullcontext=nullcontext, ContextVar=ContextVar,
              logger=logging.getLogger('desk_owner_fixture'))
    nodes = []
    found = set()
    for node in tree.body:
        name = getattr(node, 'name', None)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in functions:
            nodes.append(node)
            found.add(name)
        elif isinstance(node, ast.ClassDef) and classes and name in classes:
            selected = classes[name]
            if selected is not None:
                node.body = [n for n in node.body if getattr(n, 'name', None) in selected
                             or (filename == 'screen_sync' and isinstance(n, (ast.Assign, ast.AnnAssign)))]
                actual = {getattr(n, 'name', None) for n in node.body}
                assert set(selected) <= actual, (name, set(selected) - actual)
            nodes.append(node)
            found.add(name)
        elif constants and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if all(isinstance(t, ast.Name) and t.id.isupper() for t in targets):
                # TZ is irrelevant: all candidate periods are explicit.
                if any(t.id == '_LOOPBACK_PICKER' for t in targets):
                    continue  # Service singleton is outside this method slice.
                if any(t.id == 'TZ' for t in targets):
                    ns['TZ'] = timezone.utc
                else:
                    nodes.append(node)
    assert set(functions) | set(classes or {}) == found
    module = ast.Module(body=[ast.ImportFrom(module='__future__',
        names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), ns)
    return ns


# Pure calculator has only standard-library dependencies. Retain all helpers
# so selected functions use production tables/algorithms rather than copies.
calculator_tree = ast.parse((ROOT / 'backend/services/light_state_calculator.py').read_text(encoding='utf-8'))
CALC = load('light_state_calculator',
    functions={n.name for n in calculator_tree.body if isinstance(n, ast.FunctionDef)},
    classes={n.name: None for n in calculator_tree.body if isinstance(n, ast.ClassDef)}, constants=True)
CONSTANTS = load('automation_constants', constants=True)
AUTH = load('lighting_authority', classes={'LightingLease': None, 'LightingAuthority': None})
BOUND = load('lighting_transition_boundary', classes={'LightingTransitionBoundary': None},
             functions={'settle_lighting_io'}, namespace=AUTH)
BOUND['lighting_write_validator'] = ContextVar('fixture_write_validator', default=None)
SYNC = load('screen_sync', classes={'ScreenSyncService': {'get_floor', 'get_cap', '_scale_for_ambient'}},
            constants=True, namespace=CALC)
APP = load('light_applicator', classes={'LightApplyResult': None, 'LightApplicator': {
    'protected_light_ids', 'external_owned_light_ids', '_write_many',
    '_apply_per_light_locked', '_invalidate_screen_sync_cache'}}, namespace={**CALC, **CONSTANTS})
APP['mode_apply_epoch'] = ContextVar('fixture_mode_epoch', default=None)
APP['mode_physical_validator'] = ContextVar('fixture_physical_validator', default=None)
ENGINE = load('automation_engine', classes={'AutomationEngine': {
    'validate_lighting_lease', 'validate_screen_sync_lease', '_protected_light_ids',
    '_current_zone_posture', '_fixture_comfort_zone', '_compose_general_state'}},
    namespace={**CALC, **CONSTANTS,
        '_apply_general_desk_lux_balance': CALC['apply_general_desk_lux_balance'],
        '_enforce_fixture_comfort_invariants': CALC['enforce_fixture_comfort_invariants']})


class MemoryTransport:
    """Only explicitly modeled set_light is supported; unknown calls fail."""
    def __init__(self, boundary):
        self.boundary = boundary
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def set_light(self, lid, payload):
        self.entered.set()
        await self.release.wait()
        # Real dispatch validation again after the deterministic queue barrier.
        allowed, snapshot = self.boundary.validate_dispatch(BOUND['lighting_write_validator'].get())
        if not allowed or not self.boundary.dispatch_snapshot_valid(snapshot):
            return False
        assert lid in CALC['ALL_LIGHT_IDS']
        assert not ('ct' in payload and ('hue' in payload or 'sat' in payload))
        self.calls.append((lid, dict(payload)))
        return True

    def __getattr__(self, name):
        raise AssertionError('Unhandled device call: ' + name)


def runtime(mode='watching'):
    e = ENGINE['AutomationEngine'].__new__(ENGINE['AutomationEngine'])
    e.current_mode = mode
    e._enabled = True
    for name in ('_external_off_detected', '_away_hold', '_host_return_hold', '_gaming_scene_transition_pending'):
        setattr(e, name, False)
    for name in ('_active_scene_override_key', '_gaming_scene_override', '_active_effect_name'):
        setattr(e, name, None)
    e._active_effect_lights = []
    e._effect_manager = SimpleNamespace(authority_known=True)
    e.manual_light_overrides = {}
    e._transit_light_overrides = {}
    e._screen_sync = None
    e._active_external_light_owners = lambda: []
    e.revision = 1
    b = BOUND['LightingTransitionBoundary'](None)
    e._transition_boundary = b
    transport = MemoryTransport(b)
    a = APP['LightApplicator'].__new__(APP['LightApplicator'])
    a._st = SimpleNamespace(manual_light_overrides=e.manual_light_overrides,
        transit_light_overrides=e._transit_light_overrides, last_applied_per_light={})
    a._screen_sync_getter = lambda: e._screen_sync
    a._current_mode_getter = lambda: e.current_mode
    a._external_owners_getter = e._active_external_light_owners
    a._hue_getter = lambda: transport
    a._suppressed = lambda: e._away_hold or e._external_off_detected
    a._owner_revision_getter = lambda: e.revision
    a._transition_boundary = b
    a._overrides = SimpleNamespace(prune_expired_transit=lambda: None)
    e._applicator = a
    return e, a, b, transport


def record(scenario, candidate, disposition, reason, owner):
    ROWS.append(dict(scenario=scenario, candidate=candidate,
        disposition=disposition, reason=reason, owner=owner))


class DeskOwnerDispatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # WDAC/Sandbox scheduling is variable; it must not alter scenario output.
        asyncio.get_running_loop().slow_callback_duration = 10

    def test_candidates(self):
        sync = SYNC['ScreenSyncService'].__new__(SYNC['ScreenSyncService'])
        sync._cap_overrides = {}
        candidates = {}
        for period in ('day', 'night'):
            for label, zone in (('fresh-qualified', 'desk'), ('stale', None),
                                ('unknown', None), ('bed', 'bed'), ('couch', 'couch')):
                state = CALC['resolve_activity_state']('watching', period)
                state = CALC['apply_zone_overlay'](state, 'watching', period, zone, None)
                before = {lid: dict(value) for lid, value in state.items()}
                state = CALC['enforce_fixture_comfort_invariants'](state, 'watching', period, zone)
                candidates[label, period] = state
                self.assertEqual(state['3'], state['4'])
                self.assertEqual(state['2'], before['2'])  # Comfort is cap-only L5.
                for lid in ('2', '5'):
                    self.assertLessEqual(state[lid]['bri'], before[lid]['bri'])
                    ceiling = CALC['get_fixture_comfort_brightness_ceiling'](lid, 'watching', period, zone)
                    if ceiling is not None:
                        self.assertLessEqual(state[lid]['bri'], ceiling)
                    lo = sync.get_floor('watching', lid, zone=zone, period=period)
                    hi = sync.get_cap('watching', lid, zone, None, period=period)
                    self.assertLessEqual(lo, hi)
                    record(f'{label}/{period}/L{lid}', (state[lid]['bri'], lo, hi),
                           'candidate', 'static, sync floor/cap; adequacy unknown', 'calculator')
            self.assertGreater(candidates['fresh-qualified', period]['2']['bri'],
                               candidates['unknown', period]['2']['bri'])
            for fallback in ('stale', 'bed', 'couch'):
                self.assertEqual(candidates[fallback, period], candidates['unknown', period])
        e, _, _, _ = runtime('general')
        for zone in ('desk', None, 'bed', 'couch'):
            e._presence_fusion = SimpleNamespace(latest_zone=lambda: zone,
                latest_posture=lambda: None, seconds_since_at_desk=lambda: None)
            e._read_fresh_bedroom_lux = lambda: (None, None)
            base = CALC['resolve_activity_state']('working', 'day')
            composed = e._compose_general_state(base, 'day')
            self.assertEqual(composed['3'], composed['4'])
            record('general/' + str(zone), (composed['2']['bri'], composed['5']['bri']),
                   'candidate', 'real General composer with Working/day input; no calibrated lux', 'static')
        record('calibration/#136', None, 'unknown', 'no accepted shared L2 floor', 'physical')

    async def test_static_protection(self):
        for owner in ('manual-L2', 'manual-L5', 'transit', 'screen_sync', 'external'):
            e, a, b, t = runtime()
            protected = '5' if owner == 'manual-L5' else '2'
            if owner.startswith('manual'):
                e.manual_light_overrides[protected] = object()
            elif owner == 'transit':
                e._transit_light_overrides[protected] = object()
            elif owner == 'screen_sync':
                e._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {protected})
            else:
                external = SimpleNamespace(owned_light_targets=lambda: {protected},
                    set_lighting_authority_notifier=lambda fn: None)
                a._external_owners_getter = lambda: [external]
            states = CALC['resolve_activity_state']('watching', 'day')
            async with b.serialized():
                result, _ = await a._apply_per_light_locked(states, None)
            self.assertIn(protected, result.skipped)
            self.assertIn('3', result.successful)
            self.assertNotIn(protected, dict(t.calls))
            self.assertEqual(dict(t.calls)['3'], states['3'])
            self.assertEqual(dict(t.calls)['3'], dict(t.calls)['4'])
            record(owner, states[protected], 'suppressed', 'real applicator protected skip; L3 eligible', owner)

    async def test_engine_final_owners(self):
        for owner in ('auto', 'manual_activity', 'manual_light', 'scene', 'effect', 'screen_sync', 'away', 'sleeping', 'disabled'):
            e, _, b, t = runtime()
            if owner == 'manual_activity': e.manual_override_mode = 'watching'
            if owner == 'manual_light': e.manual_light_overrides['2'] = object()
            if owner == 'scene': e._active_scene_override_key = 'fixture'
            if owner == 'effect': e._active_effect_name, e._active_effect_lights = 'fixture', ['2']
            if owner == 'screen_sync': e._screen_sync = SimpleNamespace(fresh_owned_light_ids=lambda: {'2'})
            if owner == 'away': e._away_hold = True
            if owner == 'sleeping': e.current_mode = 'sleeping'
            if owner == 'disabled': e._enabled = False
            lease = b.authority.issue('static', ['2'])
            async with b.serialized():
                result = await b.run_write(lambda: t.set_light('2', {'bri': 1}),
                    validator=lambda: e.validate_lighting_lease(lease))
            allowed = owner in ('auto', 'manual_activity')
            self.assertEqual(result, allowed)
            self.assertEqual(len(t.calls), int(allowed))
            record('final/' + owner, {'bri': 1}, 'allowed' if allowed else 'suppressed', 'real engine lease validator', owner)

    async def test_unhandled_device_calls_rejected(self):
        _, _, _, transport = runtime()
        for name in ('get_all_lights', 'set_all_lights', 'http', 'usb'):
            with self.assertRaisesRegex(AssertionError, 'Unhandled device call'):
                getattr(transport, name)

    async def test_queued_static_mode_revoked(self):
        e, a, b, t = runtime()
        t.release.clear()
        token = APP['mode_apply_epoch'].set((1, 'watching'))
        async def apply():
            async with b.serialized():
                return await a._apply_per_light_locked({'2': {'bri': 1}}, None)
        task = asyncio.create_task(apply())
        try:
            await asyncio.wait_for(t.entered.wait(), 2)
            e.revision += 1  # Effective mode owner revoked while callback queued.
            t.release.set()
            result, _ = await asyncio.wait_for(task, 2)
            self.assertEqual(result.failed, {'2'})
            self.assertEqual(t.calls, [])
            record('queued/static', {'bri': 1}, 'suppressed', 'real applicator revision check', 'stale-mode')
        finally:
            t.release.set()
            await task
            APP['mode_apply_epoch'].reset(token)

    async def test_screen_sync_lease_revocation(self):
        for change in ('unchanged', 'expiry', 'same-mode-ABA', 'manual'):
            e, _, b, t = runtime()
            lease = b.authority.issue('screen_sync', ['2'])
            t.release.clear()
            async def apply():
                async with b.serialized():
                    return await b.run_write(lambda: t.set_light('2', {'bri': 1}),
                        validator=lambda: e.validate_screen_sync_lease(lease, '2', 'watching', 'desktop'))
            task = asyncio.create_task(apply())
            try:
                await asyncio.wait_for(t.entered.wait(), 2)
                if change == 'expiry': b.authority.invalidate(['2'])
                if change == 'same-mode-ABA':
                    e.current_mode = 'working'
                    b.authority.invalidate()
                    e.current_mode = 'watching'
                    b.authority.invalidate()
                if change == 'manual': e.manual_light_overrides['2'] = object()
                t.release.set()
                self.assertEqual(await asyncio.wait_for(task, 2), change == 'unchanged')
                self.assertEqual(len(t.calls), int(change == 'unchanged'))
                record('queued/sync/' + change, {'bri': 1}, 'allowed' if change == 'unchanged' else 'suppressed',
                       'real lease validator; expiry publication modeled', 'screen_sync')
            finally:
                t.release.set()
                await task


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DeskOwnerDispatch)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for row in sorted(ROWS, key=lambda r: r['scenario']):
        print('DESK_OWNER ' + ' '.join(f'{key}={value}' for key, value in row.items()))
    for name, digest in sorted(PROVENANCE.items()):
        print(f'SOURCE {name} sha256={digest}')
    print('GAPS fusion qualification; full mode orchestration; DND; Gaming publication; '
          'ScreenSync frame/expiry publisher; Hue worker; physical calibration #136; shadow #402')
    raise SystemExit(0 if result.wasSuccessful() else 1)
