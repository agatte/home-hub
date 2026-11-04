"""Offline #370 source-publication acceptance contracts (test-first packet).

Tests use actual PresenceFusion.on_observation/invalidate_source AST methods in a
controlled in-memory fixture. They do not import HomeHub, access hardware, or
write to the repository. Run via signed stdlib Python as a script, or pytest.

These tests intentionally FAIL on draft PR #387 as of 82bc3baf: that revision
has no shared publication gate / per-source ABA generation. Historical V1/V2
acceptance worktree is the comparison baseline, not an approved transplant.
"""

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from threading import Event, RLock, Thread
import unittest

ROOT = Path(os.environ.get("HOMEHUB_TEST_REPO_ROOT", Path(__file__).resolve().parents[1]))
SOURCE = ROOT / "backend" / "services" / "presence_fusion.py"


def load_source_slice():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    source_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PresenceFusion"
    )
    methods = {
        "on_observation", "invalidate_source", "physical_source_generation",
        "physical_source_acceptance_gate",
    }
    source_class.body = [
        node for node in source_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods
    ]
    ns = {
        "__name__": "synthetic_source_publication_fixture",
        "datetime": datetime,
        "timezone": timezone,
        "logger": logging.getLogger("test_desk_atomic_source_publication_contract"),
        "FUTURE_SKEW_TOLERANCE_S": 2.0,
        "STRONG_PRESENCE_FRESHNESS_S": 8.0,
    }

    @dataclass(frozen=True)
    class PresenceReading:
        source: str
        captured_at: datetime
        face_present: bool | None = None
        zone: str | None = None
        detection_source: str | None = None

    ns["PresenceReading"] = PresenceReading
    module = ast.Module(body=[source_class], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), ns)
    return ns["PresenceFusion"], PresenceReading


class SourcePublicationAcceptance(unittest.TestCase):
    """A freshness check and an accepted Hue receipt must share source order."""

    def setUp(self):
        self.Fusion, self.Reading = load_source_slice()
        self.now = datetime(2026, 11, 1, 19, tzinfo=timezone.utc)
        self.fusion = object.__new__(self.Fusion)
        self.gate = RLock()
        self.fusion._physical_source_gate = self.gate
        self.fusion._physical_source_generations = {}
        self.fusion._readings = {}
        self.fusion._clock = type("Clock", (), {"utc_now": lambda _self: self.now})()
        self.fusion._sample_utc_now = lambda: self.now
        self.fusion._capture_call = lambda *args: None
        self.fusion._is_at_desk = lambda reading: False
        self.fusion._is_strongly_present = lambda reading: False
        self.fusion.is_strongly_present_any = lambda: False
        self.fusion._last_at_desk_at = None
        self.fusion._last_at_desk_source = None
        self.fusion._last_global_absence_observed_at = None
        self.fusion._last_strong_reacquisition_at = None
        self.fusion._last_strong_reacquisition_source = None

    def _run_while_acceptance_holds_source_gate(self, operation, before, after):
        started, done = Event(), Event()
        errors = []

        def worker():
            started.set()
            try:
                operation()
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        thread = Thread(target=worker, daemon=True)
        with self.gate:
            thread.start()
            self.assertTrue(started.wait(2), "worker did not start")
            self.assertFalse(done.wait(0.15), "publication bypassed the receipt gate")
            before()
        self.assertTrue(done.wait(2), "publication failed to release the gate")
        thread.join(2)
        self.assertFalse(errors, repr(errors))
        after()

    def test_new_opposing_observation_waits_for_acceptance_gate(self):
        """An accepted Desk write cannot race an uncommitted Couch/Bed publication."""
        reading = self.Reading("latitude", self.now, True, "couch", "face")
        self._run_while_acceptance_holds_source_gate(
            lambda: self.fusion.on_observation(reading),
            before=lambda: self.assertNotIn("latitude", self.fusion._readings),
            after=lambda: self.assertIs(self.fusion._readings.get("latitude"), reading),
        )

    def test_invalidation_waits_for_same_acceptance_gate(self):
        """Source replacement/removal must not bypass the same lock."""
        reading = self.Reading("desktop", self.now, True, "desk", "face")
        self.fusion._readings["desktop"] = reading
        self._run_while_acceptance_holds_source_gate(
            lambda: self.fusion.invalidate_source("desktop"),
            before=lambda: self.assertIs(self.fusion._readings.get("desktop"), reading),
            after=lambda: self.assertNotIn("desktop", self.fusion._readings),
        )

    def test_equal_timestamp_source_aba_increments_revision(self):
        """Reading identity and timestamps alone cannot fence removal/reinsert ABA."""
        self.assertTrue(
            hasattr(self.fusion, "physical_source_generation"),
            "missing per-source revision interface",
        )
        reading = self.Reading("desktop", self.now, True, "desk", "face")
        initial = self.fusion.physical_source_generation("desktop")
        self.fusion.on_observation(reading)
        after_first = self.fusion.physical_source_generation("desktop")
        self.fusion.invalidate_source("desktop")
        after_remove = self.fusion.physical_source_generation("desktop")
        self.fusion.on_observation(reading)
        after_reinsert = self.fusion.physical_source_generation("desktop")
        self.assertEqual(
            [after_first, after_remove, after_reinsert],
            [initial + 1, initial + 2, initial + 3],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
