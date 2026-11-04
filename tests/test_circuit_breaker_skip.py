"""Guarded Hue skips are neutral to CircuitBreaker health.

A revoked command never reaches the bridge and must not count as a
successful dependency call or an unsuccessful one.
"""
import unittest
from datetime import datetime, timedelta, timezone

from backend.services.circuit_breaker import CircuitBreaker, CircuitBreakerSkipped


class SkippedBridgeDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_closed_skip_does_not_clear_prior_failures(self):
        breaker = CircuitBreaker(
            "hue", failure_threshold=3, cooldown_seconds=60, call_timeout=1,
        )

        async def fails():
            raise ConnectionError("mock transport failure")

        async def skipped():
            raise CircuitBreakerSkipped()

        with self.assertRaises(ConnectionError):
            await breaker.call(fails)
        before = breaker.snapshot()
        self.assertEqual(before["consecutive_failures"], 1)

        with self.assertRaises(CircuitBreakerSkipped):
            await breaker.call(skipped)
        self.assertEqual(breaker.snapshot()["state"], "closed")
        self.assertEqual(breaker.snapshot()["consecutive_failures"], 1)

    async def test_neutral_skip_does_not_close_half_open_probe(self):
        breaker = CircuitBreaker(
            "hue", failure_threshold=1, cooldown_seconds=60, call_timeout=1,
        )

        async def fails():
            raise ConnectionError("mock transport failure")

        async def skipped():
            raise CircuitBreakerSkipped()

        async def succeeds():
            return "ok"

        with self.assertRaises(ConnectionError):
            await breaker.call(fails)
        self.assertEqual(breaker.snapshot()["state"], "open")

        # Force only the wall-time cooldown to expire. This is a test-only
        # clock setup; no production breaker is changed.
        breaker._opened_at = datetime.now(timezone.utc) - timedelta(seconds=61)
        with self.assertRaises(CircuitBreakerSkipped):
            await breaker.call(skipped)
        self.assertEqual(breaker.snapshot()["state"], "half_open")
        self.assertEqual(breaker.snapshot()["consecutive_failures"], 1)

        self.assertEqual(await breaker.call(succeeds), "ok")
        self.assertEqual(breaker.snapshot()["state"], "closed")
        self.assertEqual(breaker.snapshot()["consecutive_failures"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
