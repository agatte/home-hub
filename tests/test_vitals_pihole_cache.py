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


@pytest.mark.asyncio
async def test_concurrent_cache_misses_share_one_successful_pihole_fetch() -> None:
    """A waiting vitals request reuses the first request's freshly cached data."""
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

    assert pihole.calls == 1
    assert first_result["metrics"]["pihole"]["status"] == "ok"
    assert second_result["metrics"]["pihole"]["status"] == "ok"


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
