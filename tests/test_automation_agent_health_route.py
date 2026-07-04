"""Tests for automation route helper behavior."""

from backend.api.routes.automation import (
    _agent_health_origin,
    _merge_agent_health_reports,
)


def test_agent_health_origin_defaults_to_desktop():
    assert _agent_health_origin({"agents": {}}) == "desktop"


def test_agent_health_origin_normalizes_explicit_origin():
    assert _agent_health_origin({"origin": " Latitude "}) == "latitude"


def test_merge_agent_health_reports_preserves_origins_and_merges_agents():
    merged = _merge_agent_health_reports({
        "desktop": {
            "agents": {"activity_detector": {"status": "running"}},
            "supervisor_uptime": 100,
        },
        "latitude": {
            "origin": "latitude",
            "agents": {"latitude_streaming_detector": {"status": "running"}},
            "service_uptime": 10,
        },
    })

    assert merged["supervisor_uptime"] == 100
    assert merged["agents"]["activity_detector"]["status"] == "running"
    assert merged["agents"]["latitude_streaming_detector"]["status"] == "running"
    assert set(merged["origins"]) == {"desktop", "latitude"}


def test_merge_agent_health_reports_prefixes_duplicate_agent_names():
    merged = _merge_agent_health_reports({
        "desktop": {"agents": {"streaming": {"status": "running"}}},
        "latitude": {"agents": {"streaming": {"status": "running"}}},
    })

    assert "streaming" in merged["agents"]
    assert "latitude:streaming" in merged["agents"]