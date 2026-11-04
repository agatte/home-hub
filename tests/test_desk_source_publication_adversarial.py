"""Scratch-only adversarial source-publication probes; no HomeHub imports/I/O.
Loads the exact published #370 source-publication test harness for controlled AST.
"""
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

original = Path(__file__).with_name("test_desk_atomic_source_publication_contract.py")
spec = importlib.util.spec_from_file_location("published_source_contract", original)
published = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = published
spec.loader.exec_module(published)


class AdversarialSourcePublication(unittest.TestCase):
    def setUp(self):
        ref = published.SourcePublicationAcceptance(
            "test_equal_timestamp_source_aba_increments_revision"
        )
        ref.setUp()
        self.fusion = ref.fusion
        self.Reading = ref.Reading
        self.now = ref.now

    def test_gate_accessor_is_exact_reentrant_publication_gate(self):
        gate = self.fusion.physical_source_acceptance_gate()
        self.assertIs(gate, self.fusion._physical_source_gate)
        with gate:
            self.assertEqual(self.fusion.physical_source_generation("desktop"), 0)
            self.fusion.invalidate_source("desktop")
            self.assertEqual(self.fusion.physical_source_generation("desktop"), 1)

    def test_out_of_order_source_does_not_mutate_or_advance_generation(self):
        current = self.Reading("desktop", self.now, True, "desk", "face")
        older = self.Reading("desktop", self.now - timedelta(seconds=10), False, "bed", "pose")
        self.fusion.on_observation(current)
        revision = self.fusion.physical_source_generation("desktop")
        self.fusion.on_observation(older)
        self.assertIs(self.fusion._readings["desktop"], current)
        self.assertEqual(self.fusion.physical_source_generation("desktop"), revision)

    def test_future_dated_prior_is_replaced_and_advances_generation(self):
        future = self.Reading("desktop", self.now + timedelta(seconds=60), True, "desk", "face")
        honest = self.Reading("desktop", self.now, False, "bed", "pose")
        self.fusion.on_observation(future)
        first = self.fusion.physical_source_generation("desktop")
        self.fusion.on_observation(honest)
        self.assertIs(self.fusion._readings["desktop"], honest)
        self.assertEqual(self.fusion.physical_source_generation("desktop"), first + 1)

    def test_equal_stamp_rebroadcast_invalidates_prior_generation(self):
        reading = self.Reading("desktop", self.now, True, "desk", "face")
        self.fusion.on_observation(reading)
        first = self.fusion.physical_source_generation("desktop")
        self.fusion.on_observation(reading)
        self.assertEqual(self.fusion.physical_source_generation("desktop"), first + 1)

    def test_absent_invalidation_advances_only_its_source_revision(self):
        before_other = self.fusion.physical_source_generation("latitude")
        self.fusion.invalidate_source("desktop")
        self.fusion.invalidate_source("desktop")
        self.assertEqual(self.fusion.physical_source_generation("desktop"), 2)
        self.assertEqual(self.fusion.physical_source_generation("latitude"), before_other)

    def test_nonphysical_legacy_stream_does_not_publish_source(self):
        bad = self.Reading("latitude_streaming", self.now, True, "desk", "face")
        self.fusion.on_observation(bad)
        self.assertNotIn("latitude_streaming", self.fusion._readings)
        self.assertEqual(self.fusion.physical_source_generation("latitude_streaming"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
