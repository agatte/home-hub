"""Read-only recovery of the boot effect tracker, using a fake Hue bridge."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.effect_manager import EffectManager
from backend.services.hue_v2_service import HueV2Service
from backend.services.lighting_transition_boundary import LightingTransitionBoundary


IDS = {"1", "2", "3", "4", "5", "6"}


def fixture(light_id):
    return {
        "type": "light", "id": f"rid-{light_id}", "id_v1": f"/lights/{light_id}",
        "mode": "normal", "dynamics": {"status": "none"},
        "effects": {"status": "no_effect"},
    }


def bridge(rows=None, errors=None):
    hue = HueV2Service("example.invalid", "fake-key")
    hue._connected = True
    hue._v1_to_v2 = {lid: f"rid-{lid}" for lid in IDS}
    hue._client = MagicMock()
    response = MagicMock()
    response.json.return_value = {
        "errors": [] if errors is None else errors,
        "data": [fixture(lid) for lid in sorted(IDS)] if rows is None else rows,
    }
    hue._client.get = AsyncMock(return_value=response)
    hue._client.put = AsyncMock()
    return hue


@pytest.mark.asyncio
async def test_boot_recovers_when_safety_would_fail_but_bridge_already_static():
    hue = bridge()
    manager = EffectManager(hue, transition_boundary=LightingTransitionBoundary(None))
    safety = AsyncMock(return_value=False)

    assert not manager.authority_known
    assert await manager.reconcile(None, establish_safety=safety)
    assert manager.authority_known
    assert manager.active_name is None
    assert not manager.needs_reconcile(None)
    hue._client.get.assert_awaited_once_with("/light", timeout=5.0)
    hue._client.put.assert_not_called()
    safety.assert_not_called()
    assert await manager.reconcile(None, establish_safety=safety)
    assert hue._client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "missing", "duplicate", "wrong_id", "unmapped", "active", "unknown",
    "dynamic", "streaming", "conflict", "errors", "malformed",
])
async def test_partial_or_nonstatic_observation_never_releases_ownership(case):
    rows = [fixture(lid) for lid in sorted(IDS)]
    errors = None
    if case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows.append(rows[0].copy())
    elif case == "wrong_id":
        rows[0]["id"] = "wrong"
    elif case == "unmapped":
        rows.append(fixture("7"))
    elif case == "active":
        rows[0]["effects"]["status"] = "candle"
    elif case == "unknown":
        del rows[0]["effects"]
    elif case == "dynamic":
        rows[0]["dynamics"]["status"] = "dynamic_palette"
    elif case == "streaming":
        rows[0]["mode"] = "streaming"
    elif case == "conflict":
        rows[0]["effects_v2"] = {"status": {"effect": "fire"}}
    elif case == "errors":
        errors = [{"description": "fake error"}]
    elif case == "malformed":
        rows[0]["effects_v2"] = None
    hue = bridge(rows, errors)
    manager = EffectManager(hue, transition_boundary=LightingTransitionBoundary(None))
    safety = AsyncMock(return_value=False)
    assert not await manager.reconcile(None, establish_safety=safety)
    assert not manager.authority_known
    safety.assert_awaited_once_with(IDS)
    hue._client.put.assert_not_called()


@pytest.mark.asyncio
async def test_current_effect_v2_format_and_legacy_agree():
    rows = [fixture(lid) for lid in sorted(IDS)]
    rows[0].pop("effects")
    rows[0]["effects_v2"] = {"status": {"effect": "no_effect"}}
    rows[1]["effects_v2"] = {"status": {"effect": "no_effect"}}
    hue = bridge(rows)
    assert await hue.observe_no_effects(IDS)
    hue._client.put.assert_not_called()


@pytest.mark.asyncio
async def test_newer_owner_during_read_cannot_establish_boot_authority():
    hue = bridge()
    boundary = LightingTransitionBoundary(None)
    manager = EffectManager(hue, transition_boundary=boundary)
    entered, release = asyncio.Event(), asyncio.Event()

    async def observed(_required):
        entered.set()
        await release.wait()
        return True

    hue.observe_no_effects = observed
    safety = AsyncMock(return_value=False)
    task = asyncio.create_task(manager.reconcile(None, establish_safety=safety))
    await asyncio.wait_for(entered.wait(), timeout=2)
    boundary.authority.invalidate(["3"])
    release.set()
    assert not await task
    assert not manager.authority_known
    hue._client.put.assert_not_called()


@pytest.mark.asyncio
async def test_uncertain_mutation_does_not_enable_boot_shortcut():
    hue = bridge()
    manager = EffectManager(hue, transition_boundary=LightingTransitionBoundary(None))
    async with manager.transition_boundary.serialized():
        assert await manager._mutate(AsyncMock(return_value=False)) is False
    assert not await manager.reconcile(None, establish_safety=AsyncMock(return_value=False))
    assert not manager.authority_known
    hue._client.get.assert_not_called()


@pytest.mark.asyncio
async def test_partial_mapping_cannot_certify_unmapped_owner_fixtures():
    hue = bridge([fixture(lid) for lid in sorted(IDS - {"6"})])
    hue._v1_to_v2.pop("6")
    manager = EffectManager(hue, transition_boundary=LightingTransitionBoundary(None))
    safety = AsyncMock(return_value=False)
    assert not await manager.reconcile(None, establish_safety=safety)
    assert not manager.authority_known
    hue._client.get.assert_not_called()
    hue._client.put.assert_not_called()
