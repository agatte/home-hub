"""Tests for automation route helper behavior."""

import asyncio
from types import SimpleNamespace

from backend.api.routes.automation import (
    _agent_health_origin,
    _merge_agent_health_reports,
    get_agent_health,
    report_agent_health,
)


def test_agent_health_origin_defaults_to_desktop():
    assert _agent_health_origin({"agents": {}}) == "desktop"


def test_agent_health_origin_normalizes_explicit_origin():
    assert _agent_health_origin({"origin": " Latitude "}) == "latitude"


def test_merge_agent_health_reports_preserves_origins_and_merges_agents():
    merged = _merge_agent_health_reports(_fresh_reports(
        desktop={
            "agents": {"activity_detector": {"status": "running"}},
            "supervisor_uptime": 100,
        },
        latitude={
            "origin": "latitude",
            "agents": {"latitude_streaming_detector": {"status": "running"}},
            "service_uptime": 10,
        },
    ), now=1000.0)

    assert merged["supervisor_uptime"] == 100
    assert merged["agents"]["activity_detector"]["status"] == "running"
    assert merged["agents"]["latitude_streaming_detector"]["status"] == "running"
    assert set(merged["origins"]) == {"desktop", "latitude"}

def test_merge_agent_health_reports_prefixes_duplicate_agent_names():
    merged = _merge_agent_health_reports(_fresh_reports(
        desktop={"agents": {"streaming": {"status": "running"}}},
        latitude={"agents": {"streaming": {"status": "running"}}},
    ), now=1000.0)

    assert "streaming" in merged["agents"]
    assert "latitude:streaming" in merged["agents"]

def _fresh_reports(*, desktop=None, latitude=None):
    reports = {}
    if desktop is not None:
        reports["desktop"] = {"report": desktop, "received_at": 1000.0}
    if latitude is not None:
        reports["latitude"] = {"report": latitude, "received_at": 1000.0}
    return reports


def _desktop(heartbeat_age=0):
    return {
        "agents": {"activity_detector": {"status": "running", "heartbeat_age": heartbeat_age}},
        "supervisor_pid": 1234,
        "supervisor_instance": "1234:identity",
    }


def test_stale_desktop_is_historical_not_current():
    from backend.services.agent_health_monitor import SUPERVISOR_SILENT_SECONDS

    merged = _merge_agent_health_reports(
        _fresh_reports(desktop=_desktop()), now=1000.0 + SUPERVISOR_SILENT_SECONDS + 1,
    )
    assert merged["agents"] == {}
    assert "supervisor_pid" not in merged
    assert merged["origins"]["desktop"]["fresh"] is False
    assert merged["origins"]["desktop"]["agents"]["activity_detector"]["status"] == "running"


def test_fresh_latitude_stays_current_while_desktop_is_stale():
    from backend.services.agent_health_monitor import SUPERVISOR_SILENT_SECONDS

    reports = _fresh_reports(
        desktop=_desktop(),
        latitude={"agents": {"latitude_streaming": {"status": "running"}}},
    )
    reports["latitude"]["received_at"] += SUPERVISOR_SILENT_SECONDS + 1
    merged = _merge_agent_health_reports(reports, now=1000.0 + SUPERVISOR_SILENT_SECONDS + 2)
    assert set(merged["agents"]) == {"latitude_streaming"}
    assert set(merged["origins"]) == {"desktop", "latitude"}


def test_desktop_recovery_and_heartbeat_age_are_current_only():
    from backend.services.agent_health_monitor import SUPERVISOR_SILENT_SECONDS

    reports = _fresh_reports(desktop=_desktop(0))
    recovered_at = 1000.0 + SUPERVISOR_SILENT_SECONDS + 1
    assert _merge_agent_health_reports(reports, now=recovered_at)["agents"] == {}
    reports["desktop"]["received_at"] = recovered_at
    merged = _merge_agent_health_reports(reports, now=recovered_at + 42)
    agent = merged["agents"]["activity_detector"]
    assert merged["supervisor_pid"] == 1234
    assert merged["supervisor_instance"] == "1234:identity"
    assert merged["origins"]["desktop"]["origin_age_seconds"] == 42.0
    assert agent["heartbeat_age_at_report"] == 0
    assert agent["heartbeat_age"] == 42.0


def test_null_heartbeat_never_becomes_a_number_and_empty_reports_are_never_current():
    merged = _merge_agent_health_reports(_fresh_reports(desktop=_desktop(None)), now=1042.0)
    agent = merged["agents"]["activity_detector"]
    assert agent["heartbeat_age_at_report"] is None
    assert agent["heartbeat_age"] is None
    assert _merge_agent_health_reports({}, now=2000.0) == {"status": "no_report", "agents": {}, "origins": {}}


def test_freshness_boundary_matches_watchdog_threshold():
    from backend.services.agent_health_monitor import SUPERVISOR_SILENT_SECONDS

    reports = _fresh_reports(desktop=_desktop())
    assert _merge_agent_health_reports(reports, now=1000.0 + SUPERVISOR_SILENT_SECONDS)["origins"]["desktop"]["fresh"] is True
    assert _merge_agent_health_reports(reports, now=1000.0 + SUPERVISOR_SILENT_SECONDS + 0.1)["origins"]["desktop"]["fresh"] is False

class _RouteRequest:
    def __init__(self, app, body=None):
        self.app = app
        self._body = body

    async def json(self):
        return self._body


def test_post_uses_server_receipt_time_and_get_recalculates_age():
    clock = [1000.0]
    app = SimpleNamespace(state=SimpleNamespace(agent_health_clock=lambda: clock[0]))
    asyncio.run(report_agent_health(_RouteRequest(app, _desktop(0))))

    clock[0] += 20
    health = asyncio.run(get_agent_health(_RouteRequest(app)))
    assert app.state.agent_health_reports["desktop"]["received_at"] == 1000.0
    assert health["origins"]["desktop"]["server_received_at"] == 1000.0
    assert health["agents"]["activity_detector"]["heartbeat_age"] == 20.0

def test_desktop_origin_and_watchdog_share_post_receipt_boundary():
    from backend.services.agent_health_monitor import (
        SUPERVISOR_SILENT_SECONDS,
        AgentHealthMonitor,
    )

    route_clock = [1000.0]
    monitor_clock = [1000.5]
    monitor = AgentHealthMonitor(
        automation_engine=SimpleNamespace(current_mode="working", _external_off_detected=False),
        notifier=SimpleNamespace(),
        clock=lambda: monitor_clock[0],
    )
    app = SimpleNamespace(state=SimpleNamespace(
        agent_health_clock=lambda: route_clock[0],
        agent_health_monitor=monitor,
    ))

    asyncio.run(report_agent_health(_RouteRequest(app, _desktop())))

    for age, expected_fresh in (
        (SUPERVISOR_SILENT_SECONDS - 0.1, True),
        (SUPERVISOR_SILENT_SECONDS, True),
        (SUPERVISOR_SILENT_SECONDS + 0.1, False),
    ):
        route_clock[0] = 1000.0 + age
        # GET supplies its route clock to the watchdog; this deliberately remains distinct.
        health = asyncio.run(get_agent_health(_RouteRequest(app)))
        assert health["origins"]["desktop"]["fresh"] is expected_fresh
        assert health["watchdog"]["online"] is expected_fresh