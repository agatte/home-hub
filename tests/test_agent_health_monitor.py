"""
Tests for the Latitude-side AgentHealthMonitor watchdog + the notifier's
DND-respecting emit_alert primitive.

Scenario it guards: the desktop agent supervisor stops POSTing heartbeats
(crash / desktop asleep / network drop) and the Latitude silently degrades —
the 2026-06-03 hours-long presence outage that nothing alerted on.
"""
import pytest

from backend.services.agent_health_monitor import (
    AGENT_STUCK_SECONDS,
    SUPERVISOR_SILENT_SECONDS,
    AgentHealthMonitor,
)
from backend.services.notifier_service import NotifierService


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[dict] = []

    async def emit_alert(self, *, title, body, kind="alert", force=False):
        self.alerts.append({"title": title, "body": body, "kind": kind})
        return True

    def kinds(self) -> list[str]:
        return [a["kind"] for a in self.alerts]


class FakeEngine:
    def __init__(self, mode="working", external_off=False, dnd=False) -> None:
        self.current_mode = mode
        self._external_off_detected = external_off
        self._dnd = dnd

    def is_dnd_active(self) -> bool:
        return self._dnd


def _make(mode="working", external_off=False):
    t = [1000.0]
    eng = FakeEngine(mode=mode, external_off=external_off)
    notif = FakeNotifier()
    mon = AgentHealthMonitor(
        automation_engine=eng, notifier=notif, clock=lambda: t[0],
    )
    return mon, notif, eng, t


# ── Supervisor silence ──────────────────────────────────────────────────

class TestSupervisorSilence:
    async def test_no_alert_before_any_report(self):
        # Never heard from the supervisor (fresh boot, desktop off) → no alarm.
        mon, notif, _, t = _make()
        t[0] += SUPERVISOR_SILENT_SECONDS + 100
        await mon.check()
        assert notif.alerts == []

    async def test_fresh_report_no_alert(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {}})
        t[0] += 30
        await mon.check()
        assert notif.alerts == []

    async def test_silence_alerts_once(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        assert len(notif.alerts) == 1
        assert notif.alerts[0]["kind"] == "alert"
        assert "offline" in notif.alerts[0]["title"].lower()
        # Edge-triggered — still silent next pass, but no re-fire.
        t[0] += 120
        await mon.check()
        assert len(notif.alerts) == 1

    async def test_recovery_after_silence(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        assert notif.kinds() == ["alert"]
        # Supervisor comes back.
        t[0] += 10
        await mon.record_report({"agents": {}})
        assert notif.kinds() == ["alert", "recovery"]
        # A later silence can alert again (flag was cleared).
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        assert notif.kinds() == ["alert", "recovery", "alert"]

    async def test_silence_suppressed_when_sleeping(self):
        mon, notif, _, t = _make(mode="sleeping")
        await mon.record_report({"agents": {}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        assert notif.alerts == []

    async def test_silence_suppressed_when_external_off(self):
        mon, notif, _, t = _make(external_off=True)
        await mon.record_report({"agents": {}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        assert notif.alerts == []

    async def test_suppressed_silence_does_not_spuriously_recover(self):
        # Went silent while sleeping (suppressed, no alert). When it wakes and
        # reports, there must be NO "recovered" notice (nothing was alerted).
        mon, notif, eng, t = _make(mode="sleeping")
        await mon.record_report({"agents": {}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        t[0] += 10
        await mon.record_report({"agents": {}})
        assert notif.alerts == []


# ── Per-agent stuck ─────────────────────────────────────────────────────

class TestAgentStuck:
    async def test_stuck_agent_alerts_once(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {"emotion_capture": {"status": "stopped"}}})
        t[0] += AGENT_STUCK_SECONDS + 1  # still < supervisor-silent threshold
        await mon.check()
        assert len(notif.alerts) == 1
        assert "emotion_capture" in notif.alerts[0]["title"]
        await mon.check()
        assert len(notif.alerts) == 1  # not re-fired

    async def test_stuck_agent_not_alerted_within_threshold(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {"emotion_capture": {"status": "hung"}}})
        t[0] += AGENT_STUCK_SECONDS - 10
        await mon.check()
        assert notif.alerts == []

    async def test_agent_recovers_before_threshold(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {"screen_sync": {"status": "stopped"}}})
        t[0] += 60
        await mon.record_report({"agents": {"screen_sync": {"status": "running"}}})
        t[0] += AGENT_STUCK_SECONDS + 1
        await mon.check()
        assert notif.alerts == []

    async def test_disabled_agent_is_not_stuck(self):
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {"sleep_watcher": {"status": "disabled"}}})
        t[0] += AGENT_STUCK_SECONDS + 1
        await mon.check()
        assert notif.alerts == []

    async def test_stuck_not_evaluated_while_supervisor_silent(self):
        # If the supervisor is silent, its last per-agent data is stale — don't
        # also fire per-agent alerts off it.
        mon, notif, _, t = _make()
        await mon.record_report({"agents": {"emotion_capture": {"status": "stopped"}}})
        t[0] += SUPERVISOR_SILENT_SECONDS + 1
        await mon.check()
        # Exactly one alert — the supervisor-silence one, not a per-agent one.
        assert len(notif.alerts) == 1
        assert "offline" in notif.alerts[0]["title"].lower()


# ── snapshot() ──────────────────────────────────────────────────────────

class TestSnapshot:
    async def test_online_then_stale(self):
        mon, _, _, t = _make()
        assert mon.snapshot()["ever_reported"] is False
        await mon.record_report({"agents": {}})
        snap = mon.snapshot()
        assert snap["online"] is True
        assert snap["silent_for_seconds"] == 0.0
        t[0] += SUPERVISOR_SILENT_SECONDS + 50
        snap = mon.snapshot()
        assert snap["online"] is False
        assert snap["silent_for_seconds"] == pytest.approx(SUPERVISOR_SILENT_SECONDS + 50)

    async def test_stuck_agents_listed(self):
        mon, _, _, t = _make()
        await mon.record_report({"agents": {
            "emotion_capture": {"status": "hung"},
            "activity_detector": {"status": "running"},
        }})
        assert mon.snapshot()["stuck_agents"] == ["emotion_capture"]


# ── Notifier emit_alert (DND transport behavior) ────────────────────────

class FakeWS:
    def __init__(self) -> None:
        self.broadcasts: list[tuple] = []

    async def broadcast(self, event, payload):
        self.broadcasts.append((event, payload))


class TestEmitAlert:
    def _notifier(self, dnd: bool) -> tuple[NotifierService, FakeWS]:
        ws = FakeWS()
        eng = FakeEngine(dnd=dnd)
        n = NotifierService(ws_manager=ws, automation_engine=eng, ntfy_topic=None)
        return n, ws

    async def test_suppressed_by_dnd(self):
        n, ws = self._notifier(dnd=True)
        ok = await n.emit_alert(title="x", body="y")
        assert ok is False
        assert ws.broadcasts == []

    async def test_force_bypasses_dnd(self):
        n, ws = self._notifier(dnd=True)
        ok = await n.emit_alert(title="x", body="y", force=True)
        assert ok is True
        assert len(ws.broadcasts) == 1
        event, payload = ws.broadcasts[0]
        assert event == "notification"
        assert payload["kind"] == "alert"

    async def test_dispatches_when_not_dnd(self):
        n, ws = self._notifier(dnd=False)
        ok = await n.emit_alert(title="Desktop agents offline", body="down", kind="alert")
        assert ok is True
        assert len(ws.broadcasts) == 1
        assert ws.broadcasts[0][1]["title"] == "Desktop agents offline"
