"""Stage 2.5 signed-Python publication tests; no app imports or device I/O."""
import ast
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authority_module = load('stage25_authority', 'backend/services/lighting_authority.py')
source = load('stage25_source', 'tests/test_physical_source_acceptance_gate.py')
LightingAuthority = authority_module.LightingAuthority
Field = authority_module.LightingSemanticField
TREE = ast.parse((ROOT / 'backend/services/automation_engine.py').read_text(encoding='utf-8'))
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'AutomationEngine')
# Real engine descriptors and Desk setter; do not construct the application graph.
selected = [n for n in CLASS.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name) and n.value.func.id == 'LightingSemanticField'
            or getattr(n, 'name', None) == '_desk_activity_owner']
mini = ast.ClassDef(name='Engine', bases=[], keywords=[], body=selected, decorator_list=[])
scope = dict(LightingSemanticField=Field)
exec(compile(ast.fix_missing_locations(ast.Module(body=[mini], type_ignores=[])), 'engine-publication', 'exec'), scope)
Engine = scope['Engine']


class PublicationGate(unittest.TestCase):
    def setUp(self):
        self.fusion = source.Fusion(clock=SimpleNamespace(utc_now=self.clock))
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        self.reading = source.Reading('desktop', self.now, True, detection_source='face', zone='desk')
        self.fusion.on_observation(self.reading)
        test = self
        class Boundary:
            @property
            def held_by_current_task(self):
                test.assertFalse(test.fusion._physical_source_gate._is_owned())
                return True
            delegated_worker_validator_active = False
        self.boundary = Boundary()
        self.authority = self.boundary.authority = LightingAuthority(self.boundary)
        self.e = Engine()
        self.e._presence_fusion = self.fusion
        self.e._transition_boundary = self.boundary
        self.e._current_mode = 'watching'  # Lazy binding also covers bypass fixtures.
        self.e._manual_override = False

    def clock(self):
        if hasattr(self, 'fusion'):
            self.assertFalse(self.fusion._physical_source_gate._is_owned())
        return self.now

    def blocked(self, action, inside=None):
        reached, contended, done = Event(), Event(), Event()
        errors, results = [], []
        original = self.fusion._physical_source_gate

        class ObservedLock:
            # A failed nonblocking acquisition proves actual contention, even
            # if the worker is descheduled before its blocking acquisition.
            def __enter__(self):
                if not original.acquire(blocking=False):
                    contended.set()
                    reached.set()
                    original.acquire()
                return self

            def __exit__(self, *exc):
                original.release()

            def _is_owned(self):
                return original._is_owned()

        def worker():
            try:
                results.append(action())
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()
                reached.set()  # Ungated completion must also wake the test.

        self.fusion._physical_source_gate = ObservedLock()
        thread = Thread(target=worker, daemon=True)
        try:
            with self.fusion.physical_source_acceptance_gate():
                thread.start()
                self.assertTrue(reached.wait(1), 'worker never reached gate or completed')
                self.assertTrue(contended.is_set(), 'action completed without contending for source gate')
                self.assertFalse(done.is_set(), 'publication crossed held gate')
                if inside:
                    inside()
        finally:
            # Release the outer gate even on assertion failure, then collect
            # every worker exception before restoring the original lock.
            thread.join(1)
            self.fusion._physical_source_gate = original
            self.assertFalse(thread.is_alive(), 'publication deadlocked')
            self.assertEqual(errors, [])
        self.assertTrue(done.is_set())
        self.assertEqual(len(results), 1)
        return results[0]

    def test_barrier_rejects_ungated_invalidation(self):
        # Controlled mutation: the actual invalidate method with only its
        # publication gate removed. The same regression below must go RED.
        with patch.object(self.authority, 'publication_gate', nullcontext):
            with self.assertRaisesRegex(AssertionError, 'without contending'):
                self.test_invalidate_waits_for_acceptance()

    def test_semantic_storage_revision_and_lease_wait_for_acceptance(self):
        lease = self.authority.issue('mode', ['2'])
        revision = self.e._mode_transition_revision
        def unchanged():
            self.assertEqual(self.e._current_mode, 'watching')
            self.assertEqual(self.e._mode_transition_revision, revision)
            self.assertEqual(self.authority._global, lease.global_generation)
            self.assertIs(self.fusion.get_source_reading('desktop'), self.reading)
        self.blocked(lambda: setattr(self.e, '_current_mode', 'working'), unchanged)
        self.assertEqual(self.e._current_mode, 'working')
        self.assertEqual(self.e._mode_transition_revision, revision + 1)
        self.assertFalse(self.authority.valid(lease))

    def test_source_mutation_waits_for_owner_publication_turn(self):
        generation = self.fusion.physical_source_generation('desktop')
        self.blocked(lambda: self.fusion.invalidate_source('desktop'),
                     lambda: self.assertEqual(self.fusion.physical_source_generation('desktop'), generation))
        self.assertGreater(self.fusion.physical_source_generation('desktop'), generation)

    def test_direct_revision_bump_waits_and_revokes_same_mode(self):
        revision = self.e._mode_transition_revision
        lease = self.authority.issue('mode', ['2'], intent_only=True)
        self.blocked(lambda: Field.advance_owner_revision(self.e),
                     lambda: self.assertEqual(self.e._mode_transition_revision, revision))
        self.assertEqual(self.e._current_mode, 'watching')
        self.assertEqual(self.e._mode_transition_revision, revision + 1)
        self.assertFalse(self.authority.valid(lease))

    def test_same_mode_aba_cannot_restore_revision_or_lease(self):
        lease = self.authority.issue('mode', ['2'])
        revision = self.e._mode_transition_revision
        self.e._current_mode = 'working'
        self.e._current_mode = 'watching'
        self.assertEqual(self.e._mode_transition_revision, revision + 2)
        self.assertFalse(self.authority.valid(lease))
        self.e._current_mode = 'watching'
        self.assertEqual(self.e._mode_transition_revision, revision + 2)

    def test_all_five_explicit_bumps_use_shared_helper(self):
        calls = [n for n in ast.walk(CLASS) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'advance_owner_revision']
        self.assertEqual(len(calls), 5)
        stores = [n for n in ast.walk(CLASS) if isinstance(n, ast.Attribute)
                  and isinstance(n.ctx, ast.Store) and n.attr == '_mode_transition_revision']
        self.assertEqual(stores, [])

    def test_invalidate_waits_for_acceptance(self):
        lease = self.authority.issue('scene', ['2'], intent_only=True)
        self.blocked(lambda: self.authority.invalidate(['2']),
                     lambda: self.assertEqual(self.authority._intent_lights.get('2', 0), 0))
        self.assertFalse(self.authority.valid(lease))

    def test_issue_waits_then_observes_complete_invalidation(self):
        lease = self.blocked(lambda: self.authority.issue('scene', ['2']),
                             lambda: self.authority.invalidate(['2']))
        self.assertEqual(lease.light_generations, (('2', 1),))
        self.assertTrue(self.authority.valid(lease))

    def test_valid_waits_then_observes_revocation(self):
        lease = self.authority.issue('scene', ['2'])
        result = self.blocked(lambda: self.authority.valid(lease),
                              lambda: self.authority.invalidate(['2']))
        self.assertFalse(result)

    def test_close_waits_and_revokes_intent_only(self):
        lease = self.authority.issue('scene', ['2'], intent_only=True)
        self.blocked(self.authority.close, lambda: self.assertFalse(self.authority._closed))
        self.assertFalse(self.authority.valid(lease))
        self.assertFalse(self.authority.valid(self.authority.issue('late', ['2'])))

    def test_targeted_global_and_acknowledgement_semantics(self):
        normal = self.authority.issue('screen', ['2'])
        intent = self.authority.issue('setup', ['2'], intent_only=True)
        disjoint = self.authority.issue('manual', ['3'])
        whole = self.authority.issue('scene', None)
        self.authority.invalidate(['2'], intent=False)
        self.assertFalse(self.authority.valid(normal))
        self.assertTrue(self.authority.valid(intent))
        self.assertTrue(self.authority.valid(disjoint))
        self.assertFalse(self.authority.valid(whole))
        self.authority.invalidate([])
        self.assertTrue(self.authority.valid(intent))
        self.authority.invalidate(['2'])
        self.assertFalse(self.authority.valid(intent))
        self.assertTrue(self.authority.valid(disjoint))
        self.authority.invalidate()
        self.assertFalse(self.authority.valid(disjoint))

    def test_manual_underlying_updates_preserve_owner_but_revoke_hue(self):
        self.e._manual_override = True
        revision = self.e._mode_transition_revision
        lease = self.authority.issue('manual', ['2'])
        self.e._current_mode = 'working'
        self.e._mode_source_key = 'process:desktop'
        self.e._mode_source = 'process'
        self.assertEqual(self.e._mode_transition_revision, revision)
        self.assertFalse(self.authority.valid(lease))
        self.e._override_mode = 'gaming'
        self.assertGreater(self.e._mode_transition_revision, revision)

    def test_all_semantic_fields_share_gate_without_changing_owner_rules(self):
        for name, descriptor in Engine.__dict__.items():
            if isinstance(descriptor, Field):
                with self.subTest(field=name):
                    self.blocked(lambda: setattr(self.e, name, 'changed'))

    def test_iterable_conversion_and_equality_callbacks_run_outside_gate(self):
        test = self
        class LightId:
            def __str__(self):
                test.assertFalse(test.fusion._physical_source_gate._is_owned())
                return '2'
        def ids():
            self.assertFalse(self.fusion._physical_source_gate._is_owned())
            yield LightId()
        self.authority.issue(LightId(), ids())
        self.authority.invalidate(ids())
        class Semantic:
            def __ne__(self, other):
                test.assertFalse(test.fusion._physical_source_gate._is_owned())
                # A callback may rendezvous with a source publisher safely.
                done = Event()
                thread = Thread(target=lambda: (test.fusion.invalidate_source('desktop'), done.set()), daemon=True)
                thread.start()
                test.assertTrue(done.wait(1), 'equality callback holds source gate')
                thread.join(1)
                return True
        self.e.__dict__['_current_mode'] = Semantic()
        self.e._current_mode = 'working'

    def test_owner_publication_first_revokes_acceptance_inputs(self):
        lease = self.authority.issue('mode', ['2'])
        self.e._away_hold = True
        with self.fusion.physical_source_acceptance_gate():
            self.assertTrue(self.e._away_hold)
            self.assertNotEqual(self.authority._global, lease.global_generation)

    def test_fixture_without_fusion_and_instance_isolation(self):
        plain = Engine()
        plain._current_mode = 'idle'
        Field.advance_owner_revision(plain)
        self.assertEqual(plain._mode_transition_revision, 2)
        other = LightingAuthority(self.boundary)
        self.assertIsNone(other._source_gate)
        other.invalidate()
        self.assertEqual(other._global, 1)
        self.assertEqual(self.authority._global, 2)
        self.authority.bind_source_gate(self.fusion.physical_source_acceptance_gate)
        another = source.Fusion(clock=SimpleNamespace(utc_now=self.clock))
        with self.assertRaisesRegex(RuntimeError, 'another source gate'):
            self.authority.bind_source_gate(another.physical_source_acceptance_gate)

    def test_constructor_binds_before_semantic_initialization(self):
        init = next(n for n in CLASS.body if getattr(n, 'name', None) == '__init__')
        presence_line = next(n.lineno for n in ast.walk(init) if isinstance(n, ast.Attribute)
                             and isinstance(n.ctx, ast.Store) and n.attr == '_presence_fusion')
        bind_line = next(n.lineno for n in ast.walk(init) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and n.func.attr == 'bind_source_gate')
        first_field = min(n.lineno for n in ast.walk(init) if isinstance(n, ast.Attribute)
                          and isinstance(n.ctx, ast.Store) and isinstance(Engine.__dict__.get(n.attr), Field))
        self.assertLess(presence_line, bind_line)
        self.assertLess(bind_line, first_field)
        # Execute the actual boundary assignment and guarded binding block.
        start = next(i for i,n in enumerate(init.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Attribute) and t.attr == '_transition_boundary' for t in n.targets))
        statements = init.body[start:start+3]
        self.e._effect_manager = SimpleNamespace(transition_boundary=self.boundary)
        exec(compile(ast.Module(body=statements, type_ignores=[]), 'init-binding', 'exec'),
             dict(self=self.e, presence_fusion=self.fusion))
        self.assertEqual(self.authority._source_gate, self.fusion.physical_source_acceptance_gate)

    def test_comparison_race_retries_before_publication(self):
        compared, resume = Event(), Event()
        test = self
        class Semantic:
            def __ne__(self, other):
                test.assertFalse(test.fusion._physical_source_gate._is_owned())
                compared.set()
                test.assertTrue(resume.wait(1))
                return True
        self.e.__dict__['_current_mode'] = Semantic()
        errors = []
        def publish():
            try:
                self.e._current_mode = 'watching'
            except BaseException as error:
                errors.append(error)
        revision = self.e._mode_transition_revision
        thread = Thread(target=publish, daemon=True)
        thread.start()
        self.assertTrue(compared.wait(1))
        # Supersede the snapshot with the eventual target while comparison waits.
        # A retry must see equal storage and avoid publishing a spurious epoch.
        with self.fusion.physical_source_acceptance_gate():
            self.e.__dict__['_current_mode'] = 'watching'
        resume.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.e._mode_transition_revision, revision)

    def test_concurrent_explicit_bumps_do_not_lose_epochs(self):
        revision = self.e._mode_transition_revision
        start = Event()
        threads = [Thread(target=lambda: (start.wait(1), Field.advance_owner_revision(self.e)), daemon=True)
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(self.e._mode_transition_revision, revision + 8)

    def test_boolean_comparison_result_runs_outside_gate(self):
        test = self
        class Result:
            def __bool__(self):
                test.assertFalse(test.fusion._physical_source_gate._is_owned())
                return True
        class Semantic:
            def __ne__(self, other):
                return Result()
        self.e.__dict__['_current_mode'] = Semantic()
        self.e._current_mode = 'working'


class ActualBoundaryOrder(unittest.IsolatedAsyncioTestCase):
    async def test_async_boundary_then_source_gate_and_ownership_checks(self):
        tree = ast.parse((ROOT / 'backend/services/lighting_transition_boundary.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
        ns = dict(asyncio=asyncio, asynccontextmanager=asynccontextmanager,
                  ContextVar=ContextVar, LightingAuthority=LightingAuthority,
                  lighting_write_validator=ContextVar('stage25_validator', default=None))
        module = ast.Module(body=[ast.ImportFrom(module='__future__',
            names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), 'real-boundary', 'exec'), ns)
        boundary = ns['LightingTransitionBoundary'](None)
        fusion = source.Fusion(clock=SimpleNamespace(utc_now=lambda: datetime.now(timezone.utc)))
        boundary.authority.bind_source_gate(fusion.physical_source_acceptance_gate)
        engine = Engine()
        engine._presence_fusion = fusion
        engine._transition_boundary = boundary
        engine._current_mode = 'watching'
        lease = boundary.authority.issue('mode', ['2'])
        with self.assertRaisesRegex(RuntimeError, 'final boundary'):
            boundary.authority.valid(lease)
        published = Event()
        errors = []
        def mutate_source():
            try:
                fusion.invalidate_source('desktop')
                published.set()
            except BaseException as error:
                errors.append(error)
        async with boundary.serialized():
            # Semantic publication must not attempt async boundary acquisition.
            engine._current_mode = 'working'
            self.assertFalse(fusion._physical_source_gate._is_owned())
            self.assertFalse(boundary.authority.valid(lease))
            self.assertFalse(fusion._physical_source_gate._is_owned())
            thread = Thread(target=mutate_source, daemon=True)
            thread.start()
            self.assertTrue(published.wait(1), 'source publisher waits for async boundary')
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
