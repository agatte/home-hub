"""Fictional identifiers only; no files, artist data, network or storage at runtime."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import unittest
from unittest.mock import patch

from backend.services import apple_music_offline_handoff_gate as module
from backend.services.apple_music_offline_handoff_gate import (
    OfflineHandoffGate, OfflineRefused,
)


class OfflineGateTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.binding = dict(session='fiction-session', principal='fiction-person',
                            audience='fiction-recipient', boot_epoch='fiction-boot')
        self.gate = self.make_gate()

    def make_gate(self, **changes):
        return OfflineHandoffGate(**(self.binding | changes),
                                  clock=lambda: self.now,
                                  token_factory=lambda: 'fiction-token-0123456789')

    def attempt(self, gate=None, challenge=None, **changes):
        gate = gate or self.gate
        challenge = challenge or self.challenge
        args = self.binding | dict(token=challenge.token,
                                   snapshot_revision=challenge.revision,
                                   confirmed=True)
        return gate.redeem(**(args | changes))

    def assert_burned(self):
        with self.assertRaises(OfflineRefused):
            self.attempt()
        with self.assertRaises(OfflineRefused):
            self.gate.issue()

    def test_success_once(self):
        self.challenge = self.gate.issue()
        self.assertTrue(self.attempt())
        self.assert_burned()

    def test_invalid_attempts_burn_even_correct_followup(self):
        for change in ({'confirmed': False}, {'confirmed': 1}, {'rejected': True},
                       {'principal': 'fiction-other'}, {'audience': 'fiction-other'},
                       {'boot_epoch': 'fiction-other'}, {'session': 'fiction-other'},
                       {'token': 'fiction-wrong'}, {'token': object()},
                       {'snapshot_revision': 1}, {'snapshot_revision': False}):
            with self.subTest(fields=tuple(change)):
                self.gate = self.make_gate()
                self.challenge = self.gate.issue()
                with self.assertRaises(OfflineRefused):
                    self.attempt(**change)
                self.assert_burned()

    def test_changed_then_restored_every_event(self):
        for kind in ('selection', 'action', 'source_reload'):
            with self.subTest(kind=kind):
                self.gate = self.make_gate()
                self.challenge = self.gate.issue()
                self.assertEqual(self.gate.event(kind), 1)
                self.assertEqual(self.gate.event(kind), 2)
                self.assert_burned()

    def test_original_revision_required(self):
        self.assertEqual(self.gate.event('selection'), 1)
        self.assertEqual(self.gate.event('action'), 2)
        self.challenge = self.gate.issue()
        self.assertEqual(self.challenge.revision, 2)
        with self.assertRaises(OfflineRefused):
            self.attempt(snapshot_revision=0)
        self.assert_burned()

    def test_current_snapshot_succeeds(self):
        self.gate.event('source_reload')
        self.challenge = self.gate.issue()
        self.assertTrue(self.attempt())

    def test_deadline_boundary(self):
        for elapsed, accepted in ((59.999, True), (60.0, False), (60.001, False)):
            with self.subTest(elapsed=elapsed):
                self.now = 100.0
                self.gate = self.make_gate()
                self.challenge = self.gate.issue()
                self.now += elapsed
                if accepted:
                    self.assertTrue(self.attempt())
                else:
                    with self.assertRaises(OfflineRefused):
                        self.attempt()
                self.assert_burned()

    def test_sweep_releases_expired_challenge(self):
        self.challenge = self.gate.issue()
        self.assertFalse(self.gate.sweep())
        self.now += 60
        self.assertTrue(self.gate.sweep())
        self.assertIsNone(self.gate._challenge)
        self.assertIsNone(self.gate._deadline)
        self.assertFalse(self.gate.sweep())
        self.assert_burned()

    def test_cancel_close_and_discard(self):
        for close in (lambda: self.gate.close(), lambda: self.gate.event('discard')):
            self.gate = self.make_gate()
            self.challenge = self.gate.issue()
            close()
            self.gate.close()
            self.assertIsNone(self.gate._binding)
            self.assert_burned()

    def test_restart_has_no_rehydration(self):
        self.challenge = self.gate.issue()
        self.gate.close()
        restarted = self.make_gate(boot_epoch='fiction-boot-two')
        with self.assertRaises(OfflineRefused):
            self.attempt(gate=restarted)
        with self.assertRaises(OfflineRefused):
            restarted.issue()

    def test_second_issue_revokes_first(self):
        self.challenge = self.gate.issue()
        with self.assertRaises(OfflineRefused):
            self.gate.issue()
        self.assert_burned()

    def test_attempt_before_issue_terminal(self):
        with self.assertRaises(OfflineRefused):
            self.gate.redeem(**self.binding, token='fiction-token-0123456789',
                             snapshot_revision=0, confirmed=True)
        with self.assertRaises(OfflineRefused):
            self.gate.issue()

    def test_clock_faults_fail_closed(self):
        for bad in (99.0, float('nan'), float('inf'), 'fiction-time'):
            self.now = 100.0
            self.gate = self.make_gate()
            self.challenge = self.gate.issue()
            self.now = bad
            with self.assertRaises(OfflineRefused):
                self.attempt()
            self.now = 100.0
            self.assert_burned()

    def test_invalid_event_burns(self):
        self.challenge = self.gate.issue()
        with self.assertRaises(OfflineRefused):
            self.gate.event('fiction-unknown-event')
        self.assert_burned()

    def test_concurrent_redemption_exactly_one(self):
        from threading import Barrier
        barrier = Barrier(12)
        self.challenge = self.gate.issue()

        def run(_):
            barrier.wait()
            try:
                return self.attempt()
            except OfflineRefused:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(run, range(12))), 1)
        self.assert_burned()

    def test_redaction(self):
        self.challenge = self.gate.issue()
        with self.assertRaises(OfflineRefused) as result:
            self.attempt(principal='fiction-sensitive-marker')
        rendered = repr(self.gate) + repr(self.challenge) + repr(result.exception)
        for value in (*self.binding.values(), self.challenge.token,
                      'fiction-sensitive-marker'):
            self.assertNotIn(value, rendered)
        self.assertEqual(str(result.exception), 'Offline attempt refused')

    def test_import_and_lifecycle_no_io_or_random_on_import(self):
        def blocked(*args, **kwargs):
            raise AssertionError('Forbidden I/O')

        with patch('builtins.open', blocked), patch('socket.socket', blocked), \
                patch('sqlite3.connect', blocked), \
                patch.object(module.secrets, 'token_urlsafe', blocked):
            importlib.reload(module)
            gate = module.OfflineHandoffGate(**self.binding, clock=lambda: 1,
                                            token_factory=lambda: 'fiction-token-0123456789')
            challenge = gate.issue()
            self.assertTrue(gate.redeem(**self.binding, token=challenge.token,
                                       snapshot_revision=0, confirmed=True))
            gate.sweep()
            gate.close()
        # Reload preserves old exception references only in this test module.
        globals()['OfflineRefused'] = module.OfflineRefused
        globals()['OfflineHandoffGate'] = module.OfflineHandoffGate

    def test_secure_default_lazy(self):
        with patch.object(module.secrets, 'token_urlsafe',
                          return_value='fiction-secure-token-0123456789') as random:
            gate = OfflineHandoffGate(**self.binding, clock=lambda: 1)
            random.assert_not_called()
            gate.issue()
            random.assert_called_once_with(32)

    def test_extreme_integer_ttl_fails_closed(self):
        for ttl in (10 ** 1000, -(10 ** 1000)):
            with self.subTest(positive=ttl > 0):
                with self.assertRaises(OfflineRefused):
                    OfflineHandoffGate(**self.binding, ttl=ttl)

    def test_invalid_configuration_and_generator(self):
        for ttl in (0, -1, 61, True, float('nan')):
            with self.assertRaises(OfflineRefused):
                OfflineHandoffGate(**self.binding, ttl=ttl)
        gate = OfflineHandoffGate(**self.binding, clock=lambda: 0,
                                 token_factory=lambda: 'short')
        with self.assertRaises(OfflineRefused):
            gate.issue()
        with self.assertRaises(OfflineRefused):
            gate.issue()


class FreshImportIsolationTests(unittest.TestCase):
    def test_first_import_has_no_io_or_random_requests(self):
        """A separate interpreter tests import, not reload of a cached module."""
        import subprocess
        import sys
        from pathlib import Path

        guard = """
import builtins
import importlib
import os
import pathlib
import secrets
import socket
import sqlite3

def blocked(*args, **kwargs):
    raise AssertionError("Unexpected IO or token on fresh import")

builtins.open = blocked
os.open = blocked
pathlib.Path.open = blocked
socket.socket = blocked
sqlite3.connect = blocked
secrets.token_urlsafe = blocked

target = importlib.import_module(
    "backend.services.apple_music_offline_handoff_gate"
)
assert target.OfflineHandoffGate.__name__ == "OfflineHandoffGate"
print("FRESH_IMPORT_NO_IO_OK")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", guard],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        self.assertEqual(result.stdout.strip(), "FRESH_IMPORT_NO_IO_OK")

if __name__ == '__main__':
    unittest.main()
