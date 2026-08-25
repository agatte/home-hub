"""Focused Hue v2 ID-discovery tests with no bridge access."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.hue_v2_service import HueV2Service


@pytest.mark.asyncio
async def test_build_id_map_discovers_plant_wash_from_bridge_light_resources():
    service = HueV2Service("192.0.2.10", "test-key")
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {"id": f"v2-uuid-{light_id}", "id_v1": f"/lights/{light_id}"}
            for light_id in range(1, 7)
        ]
    }
    service._client = MagicMock()
    service._client.get = AsyncMock(return_value=response)

    await service._build_id_map()

    service._client.get.assert_awaited_once_with("/light")
    response.raise_for_status.assert_called_once_with()
    assert service.v1_to_v2_id("6") == "v2-uuid-6"
    assert service.v2_to_v1_id("v2-uuid-6") == "6"
    assert service.mapped_light_ids == ["1", "2", "3", "4", "5", "6"]


@pytest.mark.asyncio
async def test_build_id_map_refresh_discovers_and_then_removes_plant_wash():
    def inventory(*light_ids: int) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"id": f"v2-uuid-{light_id}", "id_v1": f"/lights/{light_id}"}
                for light_id in light_ids
            ]
        }
        return response

    service = HueV2Service("192.0.2.10", "test-key")
    service._client = MagicMock()
    service._client.get = AsyncMock(side_effect=[
        inventory(1, 2, 3, 4, 5),
        inventory(1, 2, 3, 4, 5, 6),
        inventory(1, 2, 3, 4, 5),
    ])

    await service._build_id_map()
    assert service.v1_to_v2_id("6") is None

    await service._build_id_map()
    assert service.v1_to_v2_id("6") == "v2-uuid-6"
    assert service.v2_to_v1_id("v2-uuid-6") == "6"

    await service._build_id_map()
    assert service.v1_to_v2_id("6") is None
    assert service.v2_to_v1_id("v2-uuid-6") is None
