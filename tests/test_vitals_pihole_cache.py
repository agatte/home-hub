"""Concurrency coverage for the short Pi-hole cache in the vitals route."""
import asyncio
from types import SimpleNamespace

import pytest

import backend.api.routes.vitals as vitals


def _reset_pihole_cache() -> None:
    vitals._pihole_cache["data"] = None
    vitals._pihole_cache["ts"] = 0.0


def _request_for(pihole_service):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pihole_service=pihole_service))
    )


async def _run_contended_cache_miss() -> tuple:
    """Run one deliberately contended cache miss on the current event loop."""
    _reset_pihole_cache()
    fetch_started = asyncio.Event()
    allow_fetch_to_finish = asyncio.Event()

    class Pihole:
        calls = 0

        async def get_summary(self):
            self.calls += 1
            fetch_started.set()
            await allow_fetch_to_finish.wait()
            return {"blocked": 12, "percent_blocked": 3.5, "active_clients": 4}

    pihole = Pihole()
    request = _request_for(pihole)
    first = asyncio.create_task(vitals.get_vitals(request))
    await fetch_started.wait()
    second = asyncio.create_task(vitals.get_vitals(request))
    await asyncio.sleep(0)
    allow_fetch_to_finish.set()
    first_result, second_result = await asyncio.gather(first, second)
    return pihole.calls, first_result, second_result


@pytest.mark.asyncio
async def test_concurrent_cache_misses_share_one_successful_pihole_fetch() -> None:
    """A waiting vitals request reuses the first request's freshly cached data."""
    calls, first_result, second_result = await _run_contended_cache_miss()

    assert calls == 1
    assert first_result["metrics"]["pihole"]["status"] == "ok"
    assert second_result["metrics"]["pihole"]["status"] == "ok"


def test_contended_cache_misses_work_across_event_loop_lifecycles() -> None:
    """A lock bound by one completed loop cannot poison a later loop."""
    assert asyncio.run(_run_contended_cache_miss())[0] == 1
    assert asyncio.run(_run_contended_cache_miss())[0] == 1


@pytest.mark.asyncio
async def test_failed_pihole_fetch_releases_lock_for_a_later_retry() -> None:
    """A failed fetch must not leave the cache lock held indefinitely."""
    _reset_pihole_cache()

    class Pihole:
        calls = 0

        async def get_summary(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Pi-hole unavailable")
            return {"blocked": 1, "percent_blocked": 0.5, "active_clients": 2}

    pihole = Pihole()
    request = _request_for(pihole)

    failed_result = await vitals.get_vitals(request)
    retry_result = await vitals.get_vitals(request)

    assert pihole.calls == 2
    assert failed_result["metrics"]["pihole"] == {"status": "error"}
    assert retry_result["metrics"]["pihole"]["status"] == "ok"
