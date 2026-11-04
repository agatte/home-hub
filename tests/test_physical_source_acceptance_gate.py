"""Stage 1 offline real-method checks; signed Python -B, no app/device imports."""
import ast
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from threading import Event, Thread, current_thread
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'backend/services/presence_fusion.py'
TREE = ast.parse(PATH.read_text(encoding='utf-8'))
# Load real classes and numeric policy; never import the application graph.
NODES = [n for n in TREE.body if isinstance(n, (ast.ClassDef, ast.Assign))]
NS = dict(dataclass=dataclass, datetime=datetime, timezone=timezone,
          logging=logging,
          SystemDecisionClock=lambda **kwargs: SimpleNamespace(utc_now=kwargs['utc_now_fn']))
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[
    ast.alias(name='annotations')], level=0), *NODES], type_ignores=[])), str(PATH), 'exec'), NS)
Fusion, Reading = NS['PresenceFusion'], NS['PresenceReading']
# Exercise the actual injectable production clock without application imports.
clock_tree = ast.parse((ROOT / 'backend/services/decision_clock.py').read_text(encoding='utf-8'))
clock_class = next(n for n in clock_tree.body if isinstance(n, ast.ClassDef)
                   and n.name == 'SystemDecisionClock')
clock_scope = dict(datetime=datetime, timezone=timezone,
                   time=SimpleNamespace(monotonic_ns=lambda: 0))
exec(compile(ast.fix_missing_locations(ast.Module(body=[
    ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
    clock_class], type_ignores=[])), 'decision_clock.py', 'exec'), clock_scope)
SystemClock = clock_scope['SystemDecisionClock']



class PhysicalSourceAcceptanceGate(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        self.fusion = Fusion(clock=SimpleNamespace(utc_now=lambda: self.now))
        self.original = Reading('desktop', self.now, True, 0.95, 'face', 'desk')
        self.fusion.on_observation(self.original)
        self.generation = self.fusion.physical_source_generation('desktop')

    def accepts_original(self):
        # A synchronous source-only acceptance commit, with real source methods.
        # Stage 2 must add owner generations and per-light leases to this scope.
        with self.fusion.physical_source_acceptance_gate():
            current = self.fusion.get_source_reading('desktop')
            return (current is self.original
                    and self.fusion.physical_source_generation('desktop') == self.generation
                    and -NS['FUTURE_SKEW_TOLERANCE_S'] <= (
                        self.now - self.original.captured_at).total_seconds()
                    <= NS['STRONG_PRESENCE_FRESHNESS_S']
                    and self.fusion._is_strongly_present(current)
                    and current.face_present and current.zone == 'desk'
                    and not any(
                        (r := self.fusion.get_source_reading(source)) is not None
                        and self.fusion._fresh(r, NS['STRONG_PRESENCE_FRESHNESS_S'], now=self.now)
                        and self.fusion._is_strongly_present(r)
                        and r.zone in ('couch', 'bed')
                        for source in ('latitude',)))

    def publish(self, action):
        attempted, done = Event(), Event()
        errors = []
        def worker():
            attempted.set()
            try:
                action()
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        thread = Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(attempted.wait(1))
        return thread, done, errors

    def assert_publication_waits(self, action):
        commits = []
        with self.fusion.physical_source_acceptance_gate():
            thread, done, errors = self.publish(action)
            self.assertFalse(done.wait(0.05), 'publication crossed acceptance gate')
            commits.append(self.accepts_original())
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(done.is_set())
        self.assertEqual(commits, [True])
        self.assertFalse(self.accepts_original())

    def test_replacement_waits_for_acceptance_commit(self):
        replacement = replace(self.original, face_present=False, zone=None)
        self.assert_publication_waits(lambda: self.fusion.on_observation(replacement))
        self.assertIs(self.fusion.get_source_reading('desktop'), replacement)

    def test_invalidation_waits_for_acceptance_commit(self):
        self.assert_publication_waits(lambda: self.fusion.invalidate_source('desktop'))
        self.assertIsNone(self.fusion.get_source_reading('desktop'))

    def test_conflicting_source_publication_waits_for_commit(self):
        conflict = Reading('latitude', self.now, True, detection_source='yolo', zone='couch')
        self.assert_publication_waits(lambda: self.fusion.on_observation(conflict))
        self.assertEqual(self.fusion.physical_source_generation('desktop'), self.generation)

    def test_published_before_acceptance_rejects_retained_original(self):
        for invalidate in (False, True):
            with self.subTest(invalidate=invalidate):
                self.setUp()
                action = (lambda: self.fusion.invalidate_source('desktop')) if invalidate else (
                    lambda: self.fusion.on_observation(replace(self.original, zone='bed', detection_source='pose')))
                thread, done, errors = self.publish(action)
                self.assertTrue(done.wait(1))
                thread.join(1)
                self.assertEqual(errors, [])
                self.assertFalse(self.accepts_original())

    def test_repeated_removal_reinsert_same_object_aba(self):
        for i in range(4):
            self.fusion.invalidate_source('desktop')
            self.fusion.invalidate_source('desktop')  # absent removal advances too
            self.fusion.on_observation(self.original)
            self.assertIs(self.fusion.get_source_reading('desktop'), self.original)
            self.assertEqual(self.fusion.physical_source_generation('desktop'), self.generation + 3 * (i + 1))
            self.assertFalse(self.accepts_original())

    def test_equal_timestamp_replacement_advances_source_only(self):
        self.fusion.on_observation(replace(self.original))
        self.assertEqual(self.fusion.physical_source_generation('desktop'), self.generation + 1)
        self.assertEqual(self.fusion.physical_source_generation('latitude'), 0)
        self.assertFalse(self.accepts_original())

    def test_older_rejected_reading_does_not_revoke(self):
        self.fusion.on_observation(replace(self.original, captured_at=self.now - timedelta(seconds=1), face_present=False))
        self.assertEqual(self.fusion.physical_source_generation('desktop'), self.generation)
        self.assertTrue(self.accepts_original())

    def test_future_clock_healing_and_high_water(self):
        self.fusion.on_observation(replace(self.original, captured_at=self.now + timedelta(seconds=10)))
        self.fusion.on_observation(replace(self.original, face_present=False, zone=None))
        self.assertEqual(self.fusion.physical_source_generation('desktop'), self.generation + 2)
        self.assertEqual(self.fusion.seconds_since_at_desk(), 0)

    def test_captured_at_expiry_is_not_extended_by_publication(self):
        self.now += timedelta(seconds=9)
        self.assertFalse(self.accepts_original())
        self.fusion.on_observation(self.original)
        self.assertFalse(self.fusion.is_strongly_present_any())
        self.assertEqual(self.fusion.get_source_reading('desktop').captured_at, self.original.captured_at)

    def test_strong_reacquisition_and_attendance(self):
        self.fusion.on_observation(replace(self.original, face_present=False, zone=None))
        self.assertFalse(self.fusion.is_strongly_present_any())
        self.now += timedelta(seconds=1)
        positive = replace(self.original, captured_at=self.now)
        self.fusion.on_observation(positive)
        self.assertTrue(self.fusion.is_strong_presence_reacquisition(positive))
        self.assertTrue(self.fusion.is_at_desk_fresh())
        self.assertEqual(self.fusion.get_at_desk_attribution(), 'desktop')

    def test_face_zone_and_physical_bed_veto(self):
        unknown = replace(self.original, zone=None)
        self.fusion.on_observation(unknown)
        self.assertTrue(self.fusion.is_strongly_present_any())
        self.assertFalse(self.fusion.is_at_desk_fresh())
        self.fusion.on_observation(self.original)
        bed = Reading('latitude', self.now, True, detection_source='yolo', zone='bed')
        self.fusion.on_observation(bed)
        self.assertFalse(self.fusion.is_at_desk_fresh())
        self.assertIsNone(self.fusion.get_at_desk_attribution())

    def test_instance_owned_and_reentrant(self):
        other = Fusion(clock=self.fusion._clock)
        self.assertIsNot(self.fusion.physical_source_acceptance_gate(), other.physical_source_acceptance_gate())
        with self.fusion.physical_source_acceptance_gate():
            with self.fusion.physical_source_acceptance_gate():
                self.assertEqual(self.fusion._get_status_at(now=self.now)['zone'], 'desk')
                self.assertTrue(self.accepts_original())

    def test_capture_callbacks_can_publish_from_another_thread(self):
        events = []
        fusion = self.fusion
        class Capture:
            def record_fusion_ingest(capture, reading):
                fusion.set_navigation_incident_capture(None)
                thread, done, errors = self.publish(lambda: fusion.invalidate_source('latitude'))
                if not done.wait(1):
                    raise AssertionError('capture ran under publication lock')
                thread.join(1)
                self.assertEqual(errors, [])
                events.append(('ingest', reading))
            def record_fusion_invalidation(capture, source):
                fusion.set_navigation_incident_capture(None)
                thread, done, errors = self.publish(lambda: fusion.on_observation(self.original))
                if not done.wait(1):
                    raise AssertionError('invalidation capture ran under publication lock')
                thread.join(1)
                self.assertEqual(errors, [])
                events.append(('invalidate', source))
        fusion.set_navigation_incident_capture(Capture())
        replacement = replace(self.original)
        fusion.on_observation(replacement)
        self.assertIs(fusion.get_source_reading('desktop'), replacement)
        fusion.set_navigation_incident_capture(Capture())
        fusion.invalidate_source('desktop')
        self.assertIsNone(fusion.get_source_reading('desktop'))
        self.assertEqual(events, [('ingest', replacement), ('invalidate', 'desktop')])

    def test_future_warning_handler_runs_outside_gate(self):
        self.fusion.on_observation(replace(self.original, captured_at=self.now + timedelta(seconds=10)))
        results = []
        fusion = self.fusion
        class Handler(logging.Handler):
            def emit(handler, record):
                thread, done, errors = self.publish(lambda: fusion.invalidate_source('latitude'))
                results.append(done.wait(1))
                thread.join(1)
                results.append(not errors)
        logger = NS['logger']
        handler = Handler()
        logger.addHandler(handler)
        try:
            fusion.on_observation(self.original)
        finally:
            logger.removeHandler(handler)
        self.assertEqual(results, [True, True])

    def test_injected_clock_waits_for_other_thread_without_gate(self):
        # The callback deadline releases the old implementation's lock too,
        # so failure cleans up every worker rather than leaving a deadlock.
        methods = [
            lambda: self.fusion.on_observation(replace(self.original)),
            lambda: self.fusion.is_strongly_present_any(),
            lambda: self.fusion._physical_says_bed(8),
            lambda: self.fusion.is_at_desk_fresh(),
            lambda: self.fusion.freshest_strong_presence(),
            lambda: self.fusion.is_strong_presence_reacquisition(self.original),
            lambda: self.fusion.is_present_within_seconds(8),
            lambda: self.fusion.seconds_since_at_desk(),
            lambda: self.fusion.get_at_desk_attribution(),
            lambda: self.fusion.latest_zone(),
            lambda: self.fusion.latest_strong_zone(),
            lambda: self.fusion.latest_posture(),
            lambda: self.fusion.get_sources(),
            lambda: self.fusion.get_status(),
            lambda: self.fusion.as_fusion_factor(),
            lambda: self.fusion._desktop_at_desk_fresh(8),
            lambda: self.fusion._fresh(self.original, 8),
        ]
        for index, method in enumerate(methods):
            for publish in (False, True):
                with self.subTest(method=index, publish=publish):
                    self.fusion._last_strong_reacquisition_source = 'desktop'
                    self.fusion._last_strong_reacquisition_at = self.original.captured_at
                    workers, outcomes, errors = [], [], []
                    caller = current_thread()
                    def clock():
                        if current_thread() is not caller:
                            return self.now
                        attempted, done = Event(), Event()
                        def worker():
                            attempted.set()
                            try:
                                if publish:
                                    self.fusion.on_observation(Reading('latitude', self.now, False))
                                else:
                                    self.fusion.get_source_reading('desktop')
                            except BaseException as exc:
                                errors.append(exc)
                            finally:
                                done.set()
                        thread = Thread(target=worker)
                        workers.append(thread)
                        thread.start()
                        ready = attempted.wait(1)
                        outcomes.append(ready and done.wait(0.2))
                        return self.now
                    self.fusion._clock = SystemClock(utc_now_fn=clock)
                    try:
                        method()
                    finally:
                        self.fusion._clock = SimpleNamespace(utc_now=lambda: self.now)
                        for thread in workers:
                            thread.join(1)
                    self.assertTrue(workers, 'operation did not exercise clock')
                    self.assertFalse(any(t.is_alive() for t in workers))
                    self.assertEqual(errors, [])
                    self.assertTrue(all(outcomes), 'clock callback waited while gate was held')
                    self.assertEqual(len(outcomes), 1, 'nested query resampled wall clock')

    def test_status_uses_one_snapshot_at_freshness_deadline(self):
        boundary = self.original.captured_at + timedelta(seconds=300)
        calls = []
        def crossing_clock():
            value = boundary + timedelta(microseconds=len(calls))
            calls.append(value)
            return value
        self.fusion._clock = SystemClock(utc_now_fn=crossing_clock)
        status = self.fusion.get_status()
        self.assertEqual(calls, [boundary])
        self.assertTrue(status['at_desk_fresh'])
        self.assertEqual(status['at_desk_source'], 'desktop')
        self.assertEqual(status['zone'], 'desk')
        self.assertTrue(status['sources']['desktop']['fresh'])
        status = self.fusion.get_status()
        self.assertFalse(status['at_desk_fresh'])
        self.assertIsNone(status['at_desk_source'])
        self.assertIsNone(status['zone'])
        self.assertFalse(status['sources']['desktop']['fresh'])

    def test_ingest_uses_one_snapshot_at_strong_deadline(self):
        self.fusion.invalidate_source('desktop')
        boundary = self.now
        negative = replace(self.original, captured_at=boundary - timedelta(seconds=8),
                           face_present=False, zone=None)
        calls = []
        def crossing_clock():
            value = boundary + timedelta(microseconds=len(calls))
            calls.append(value)
            return value
        self.fusion._clock = SystemClock(utc_now_fn=crossing_clock)
        self.fusion.on_observation(negative)
        self.assertEqual(calls, [boundary])
        self.assertEqual(self.fusion._last_global_absence_observed_at, negative.captured_at)
        self.fusion._clock = SystemClock(utc_now_fn=lambda: boundary)
        self.fusion.on_observation(self.original)
        self.assertTrue(self.fusion.is_strong_presence_reacquisition(self.original))
        self.now = boundary + timedelta(seconds=8)
        self.fusion._clock = SystemClock(utc_now_fn=lambda: self.now)
        self.assertTrue(self.fusion.is_strongly_present_any())
        self.assertTrue(self.fusion.is_strong_presence_reacquisition(self.original))
        self.now += timedelta(microseconds=1)
        self.assertFalse(self.fusion.is_strongly_present_any())
        self.assertFalse(self.fusion.is_strong_presence_reacquisition(self.original))

    def test_future_healing_exact_two_second_boundary(self):
        for skew, heals in ((2, False), (2.000001, True)):
            with self.subTest(skew=skew):
                self.setUp()
                future = replace(self.original, captured_at=self.now + timedelta(seconds=skew))
                self.fusion.on_observation(future)
                generation = self.fusion.physical_source_generation('desktop')
                negative = replace(self.original, face_present=False, zone=None)
                self.fusion.on_observation(negative)
                self.assertIs(self.fusion.get_source_reading('desktop'), negative if heals else future)
                self.assertEqual(self.fusion.physical_source_generation('desktop'), generation + int(heals))
                self.assertEqual(self.fusion.seconds_since_at_desk(), 0 if heals else -2)

    def test_negative_freshness_future_skew_and_reacquisition_boundaries(self):
        # Negative freshness is two-sided; historical positive getter freshness
        # remains one-sided in Stage 1. No wider Contract B claim is made here.
        for age, fresh in ((-2.000001, False), (-2, True), (2, True),
                           (8, True), (8.000001, False)):
            with self.subTest(age=age):
                fusion = Fusion(clock=SystemClock(utc_now_fn=lambda: self.now))
                captured = self.now - timedelta(seconds=age)
                negative = replace(self.original, captured_at=captured, face_present=False, zone=None)
                fusion.on_observation(negative)
                self.assertEqual(fusion._last_global_absence_observed_at,
                                 captured if fresh else None)
                positive = replace(negative, face_present=True, zone='desk')
                fusion.on_observation(positive)
                self.assertEqual(fusion.is_strong_presence_reacquisition(positive), fresh)
                self.assertEqual(fusion.is_strongly_present_any(), age <= 8)

    def test_outer_gate_rejects_clock_sampling_without_callback(self):
        calls = []
        self.fusion._clock = SystemClock(utc_now_fn=lambda: calls.append(True) or self.now)
        with self.fusion.physical_source_acceptance_gate():
            with self.assertRaisesRegex(RuntimeError, 'capture wall clock before'):
                self.fusion.get_status()
            with self.assertRaisesRegex(RuntimeError, 'capture wall clock before'):
                self.fusion._fresh(self.original, 8)
            self.assertTrue(self.fusion._fresh(self.original, 8, now=self.now))
            self.assertEqual(self.fusion._get_status_at(now=self.now)['zone'], 'desk')
        self.assertEqual(calls, [])

    def test_locked_bodies_never_sample_clock(self):
        tree = ast.parse(PATH.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PresenceFusion')
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for scope in ast.walk(method):
                if not isinstance(scope, ast.With):
                    continue
                for call in (n for n in ast.walk(scope) if isinstance(n, ast.Call)):
                    name = getattr(call.func, 'attr', '')
                    self.assertNotIn(name, ('utc_now', '_sample_utc_now'), method.name)
                    if name == '_fresh':
                        self.assertIn('now', [kw.arg for kw in call.keywords], method.name)

    def test_constructor_bypass_ast_fixture_compatibility(self):
        # Existing tests extract only these methods, so no added helper dependency.
        names = {'on_observation', 'invalidate_source', 'get_source_reading', '_is_at_desk', '_is_strongly_present'}
        tree = ast.parse(PATH.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PresenceFusion')
        cls.body = [n for n in cls.body if getattr(n, 'name', '') in names]
        scope = dict(NS)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])), str(PATH), 'exec'), scope)
        fusion = object.__new__(scope['PresenceFusion'])
        fusion._clock = self.fusion._clock
        fusion._readings = {}
        fusion._capture_call = lambda *args: None
        fusion.is_strongly_present_any = lambda: False
        fusion._last_at_desk_at = fusion._last_at_desk_source = None
        fusion._last_global_absence_observed_at = None
        fusion.on_observation(self.original)
        self.assertIs(fusion.get_source_reading('desktop'), self.original)
        fusion.invalidate_source('desktop')
        self.assertIsNone(fusion.get_source_reading('desktop'))


if __name__ == '__main__':
    unittest.main(verbosity=2)