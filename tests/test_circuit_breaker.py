"""
Unit tests for CircuitBreaker — state transitions and timeout handling.
No FastAPI wiring; integration coverage for /health lives elsewhere.
"""

import asyncio

import pytest

from backend.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


@pytest.fixture
def breaker() -> CircuitBreaker:
    # Tight thresholds make the test cases compact.
    return CircuitBreaker(
        name="test", failure_threshold=3, cooldown_seconds=0.05, call_timeout=0.5
    )


async def _ok() -> str:
    return "ok"


async def _boom() -> None:
    raise RuntimeError("nope")


async def _slow() -> None:
    await asyncio.sleep(10)


class TestInit:
    def test_starts_closed(self, breaker):
        assert breaker.state == CircuitBreaker.CLOSED
        snap = breaker.snapshot()
        assert snap["state"] == "closed"
        assert snap["consecutive_failures"] == 0
        assert snap["opened_at"] is None

    def test_rejects_invalid_args(self):
        with pytest.raises(ValueError):
            CircuitBreaker("x", failure_threshold=0)
        with pytest.raises(ValueError):
            CircuitBreaker("x", cooldown_seconds=0)
        with pytest.raises(ValueError):
            CircuitBreaker("x", call_timeout=0)


class TestClosedStateTransitions:
    @pytest.mark.asyncio
    async def test_success_keeps_closed(self, breaker):
        result = await breaker.call(_ok)
        assert result == "ok"
        assert breaker.state == CircuitBreaker.CLOSED

    @pytest.mark.asyncio
    async def test_failure_increments_counter(self, breaker):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
        assert breaker.snapshot()["consecutive_failures"] == 1
        assert breaker.state == CircuitBreaker.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_counter(self, breaker):
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
        assert breaker.snapshot()["consecutive_failures"] == 2
        await breaker.call(_ok)
        assert breaker.snapshot()["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_threshold_opens_breaker(self, breaker):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(_boom)
        # State property may already see "half_open" if cooldown is tiny;
        # check the underlying state directly to confirm the transition.
        assert breaker._state == CircuitBreaker.OPEN
        assert breaker.snapshot()["consecutive_failures"] == 3
        assert breaker.snapshot()["opened_at"] is not None


class TestOpenState:
    @pytest.mark.asyncio
    async def test_open_raises_without_calling_fn(self, breaker):
        # Force open with a non-trivial cooldown so the test can assert
        # the fail-fast path before promotion fires.
        breaker = CircuitBreaker(
            "test", failure_threshold=1, cooldown_seconds=10, call_timeout=0.5
        )
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
        assert breaker.state == CircuitBreaker.OPEN

        called = False

        async def _spy() -> str:
            nonlocal called
            called = True
            return "ok"

        with pytest.raises(CircuitBreakerOpen):
            await breaker.call(_spy)
        assert called is False


class TestCooldownAndHalfOpen:
    @pytest.mark.asyncio
    async def test_cooldown_promotes_to_half_open(self, breaker):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(_boom)
        await asyncio.sleep(0.06)  # > cooldown_seconds
        # Snapshot should show half_open after cooldown elapses.
        assert breaker.snapshot()["state"] == "half_open"

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self, breaker):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(_boom)
        await asyncio.sleep(0.06)
        result = await breaker.call(_ok)
        assert result == "ok"
        assert breaker.state == CircuitBreaker.CLOSED
        assert breaker.snapshot()["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self, breaker):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(_boom)
        first_opened_at = breaker.snapshot()["opened_at"]
        await asyncio.sleep(0.06)
        # Probe call fails — should re-open, with a NEW opened_at.
        with pytest.raises(RuntimeError):
            await breaker.call(_boom)
        assert breaker._state == CircuitBreaker.OPEN
        second_opened_at = breaker.snapshot()["opened_at"]
        assert second_opened_at is not None
        assert second_opened_at > first_opened_at


class TestTimeout:
    @pytest.mark.asyncio
    async def test_slow_call_counts_as_failure(self, breaker):
        with pytest.raises(asyncio.TimeoutError):
            await breaker.call(_slow)
        assert breaker.snapshot()["consecutive_failures"] == 1

    @pytest.mark.asyncio
    async def test_repeated_slow_calls_open_breaker(self, breaker):
        for _ in range(3):
            with pytest.raises(asyncio.TimeoutError):
                await breaker.call(_slow)
        assert breaker._state == CircuitBreaker.OPEN


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_records_last_success(self, breaker):
        await breaker.call(_ok)
        snap = breaker.snapshot()
        assert snap["last_success_at"] is not None

    def test_snapshot_shape(self, breaker):
        snap = breaker.snapshot()
        for key in (
            "state",
            "consecutive_failures",
            "opened_at",
            "last_success_at",
            "failure_threshold",
            "cooldown_seconds",
        ):
            assert key in snap
