"""
Integration tests for the source-trust consumers:

* ConfidenceFusion hard-drops an untrusted lane (no DB).
* MLDecisionLogger stamps ``quarantined`` from the SourceTrust verdict.
* RemediationService guardrails: propose-only, unknown action, rate ceiling.

The DB-backed tests patch each module's ``async_session`` to an in-memory
SQLite engine with the real schema (same approach as test_event_logger.py).
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models import Base, MLDecision, RemediationLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeTrust:
    """Minimal SourceTrust stand-in: name → trusted bool."""

    def __init__(self, untrusted: set[str]):
        self._untrusted = untrusted

    def verdict(self, name: str) -> dict:
        return {"trusted": name not in self._untrusted, "reason": "test_untrusted"}


class _FakeWS:
    async def broadcast(self, *_a, **_k):
        return None


class _FakeNotifier:
    def __init__(self):
        self.calls = []

    async def emit_synthetic(self, **kwargs):
        self.calls.append(kwargs)
        return {}


async def _memory_sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


# ---------------------------------------------------------------------------
# ConfidenceFusion: untrusted lane drop
# ---------------------------------------------------------------------------

class TestFusionUntrustedDrop:
    def test_untrusted_camera_lane_is_dropped(self):
        from backend.services.ml.confidence_fusion import ConfidenceFusion

        fusion = ConfidenceFusion()
        fusion.set_source_trust_registry(_FakeTrust({"camera"}))

        # Camera votes idle strongly; process votes working strongly. With the
        # camera lane dropped as untrusted, the fused mode must be working and
        # the camera detail must be flagged untrusted + excluded.
        fusion.report_signal("process", "working", 0.9)
        fusion.report_signal("camera", "idle", 0.95)

        result = fusion.compute_fusion()
        assert result is not None
        assert result["fused_mode"] == "working"
        cam = result["signals"]["camera"]
        assert cam["untrusted"] is True
        assert cam["stale"] is True
        assert cam["agrees"] is False

    def test_trusted_camera_lane_counts(self):
        from backend.services.ml.confidence_fusion import ConfidenceFusion

        fusion = ConfidenceFusion()
        fusion.set_source_trust_registry(_FakeTrust(set()))  # nothing untrusted
        fusion.report_signal("camera", "idle", 0.95)
        result = fusion.compute_fusion()
        assert result is not None
        assert result["signals"]["camera"]["untrusted"] is False

    def test_no_registry_fails_open(self):
        from backend.services.ml.confidence_fusion import ConfidenceFusion

        fusion = ConfidenceFusion()  # no source_trust wired
        fusion.report_signal("camera", "idle", 0.9)
        result = fusion.compute_fusion()
        assert result is not None
        assert result["signals"]["camera"]["untrusted"] is False


# ---------------------------------------------------------------------------
# MLDecisionLogger: quarantine stamping
# ---------------------------------------------------------------------------

class TestQuarantineGate:
    async def test_untrusted_source_quarantines_row(self, monkeypatch):
        from backend.services.ml import ml_logger as ml_logger_module

        maker, engine = await _memory_sessionmaker()
        monkeypatch.setattr(ml_logger_module, "async_session", maker)

        logger = ml_logger_module.MLDecisionLogger(ws_manager=_FakeWS())
        logger.set_source_trust_registry(_FakeTrust({"camera"}))

        await logger.log_decision(
            predicted_mode="idle", confidence=0.5,
            decision_source="camera", factors={"detection": "present"},
        )

        async with maker() as s:
            row = (await s.execute(select(MLDecision))).scalar_one()
        assert row.quarantined is True
        assert row.factors["quarantine_reason"] == "test_untrusted"
        await engine.dispose()

    async def test_trusted_source_not_quarantined(self, monkeypatch):
        from backend.services.ml import ml_logger as ml_logger_module

        maker, engine = await _memory_sessionmaker()
        monkeypatch.setattr(ml_logger_module, "async_session", maker)

        logger = ml_logger_module.MLDecisionLogger(ws_manager=_FakeWS())
        logger.set_source_trust_registry(_FakeTrust(set()))

        await logger.log_decision(
            predicted_mode="working", confidence=0.8, decision_source="process",
        )
        async with maker() as s:
            row = (await s.execute(select(MLDecision))).scalar_one()
        assert row.quarantined is False
        await engine.dispose()

    async def test_no_registry_fails_open(self, monkeypatch):
        from backend.services.ml import ml_logger as ml_logger_module

        maker, engine = await _memory_sessionmaker()
        monkeypatch.setattr(ml_logger_module, "async_session", maker)

        logger = ml_logger_module.MLDecisionLogger(ws_manager=_FakeWS())
        # No source_trust set → every row trusted.
        await logger.log_decision(
            predicted_mode="idle", confidence=0.5, decision_source="camera",
        )
        async with maker() as s:
            row = (await s.execute(select(MLDecision))).scalar_one()
        assert row.quarantined is False
        await engine.dispose()


# ---------------------------------------------------------------------------
# RemediationService: guardrails
# ---------------------------------------------------------------------------

class _RecordingTrust:
    """Captures the register() call so we can assert the buffer config."""

    def __init__(self):
        self.register_kwargs = None

    def register(self, name, **kwargs):
        self.register_kwargs = (name, kwargs)


class TestCameraRegistration:
    """Guards against the 2026-06-02 drift: the post-sleep resume site had
    silently fallen back to the 300s/300-sample defaults, which defeated the
    90-min lux_variance_collapse check every morning. Both sites now route
    through CameraService._register_camera_sanity, so this one test covers
    enable + resume."""

    def test_register_camera_sanity_uses_long_horizon_buffer(self):
        from backend.services.camera_service import CameraService
        from backend.services.source_trust import (
            CAMERA_MAX_SAMPLES,
            CAMERA_WINDOW_SECONDS,
        )

        cam = CameraService(ws_manager=None, automation_engine=None)
        trust = _RecordingTrust()
        cam.set_source_trust_registry(trust)
        cam._register_camera_sanity()

        assert trust.register_kwargs is not None, "register() was never called"
        name, kwargs = trust.register_kwargs
        assert name == "camera"
        assert kwargs["window_seconds"] == CAMERA_WINDOW_SECONDS
        assert kwargs["max_samples"] == CAMERA_MAX_SAMPLES
        assert kwargs["predicate"] is not None

    def test_register_camera_sanity_noop_without_registry(self):
        from backend.services.camera_service import CameraService

        cam = CameraService(ws_manager=None, automation_engine=None)
        # No registry wired — must be a safe no-op, not an AttributeError.
        cam._register_camera_sanity()


class _FakeApp:
    def __init__(self, notifier):
        class _State:
            pass
        self.state = _State()
        self.state.notifier = notifier


def _make_service(monkeypatch, maker, *, enabled, autonomous):
    from backend.services import remediation_service as rs_module
    monkeypatch.setattr(rs_module, "async_session", maker)
    notifier = _FakeNotifier()
    svc = rs_module.RemediationService(
        _FakeApp(notifier),
        enabled=enabled, autonomous=autonomous,
        max_auto_per_day=6, action_cooldown_seconds=1800,
    )
    return svc, notifier


class TestRemediationGuardrails:
    async def test_propose_only_does_not_execute(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, notifier = _make_service(monkeypatch, maker, enabled=True, autonomous=False)

        out = await svc.execute_or_propose("recover_camera", source="camera", reason="test")
        assert out["result"] == "proposed"
        # An audit row exists, tier=propose.
        async with maker() as s:
            row = (await s.execute(select(RemediationLog))).scalar_one()
        assert row.tier == "propose"
        assert row.result == "proposed"
        assert len(notifier.calls) == 1
        await engine.dispose()

    async def test_unknown_action_errors(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, _ = _make_service(monkeypatch, maker, enabled=True, autonomous=True)
        out = await svc.execute_or_propose("delete_everything")
        assert out["result"] == "error"
        assert "unknown action" in out["detail"]
        await engine.dispose()

    async def test_daily_ceiling_skips(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        # Pre-seed 6 executed auto rows in the last 24h → at ceiling.
        now = datetime.now(timezone.utc)
        async with maker() as s:
            for i in range(6):
                s.add(RemediationLog(
                    timestamp=now - timedelta(minutes=10 * (i + 1)),
                    action="recover_camera", source="camera",
                    tier="auto", result="executed",
                ))
            await s.commit()

        svc, _ = _make_service(monkeypatch, maker, enabled=True, autonomous=True)
        out = await svc.execute_or_propose("set_source_trust", source="camera",
                                           params={"trusted": True})
        assert out["result"] == "skipped"
        assert "ceiling" in out["detail"]
        await engine.dispose()

    async def test_autonomous_executes_whitelisted_action(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, notifier = _make_service(monkeypatch, maker, enabled=True, autonomous=True)

        # set_source_trust(trusted=True) needs a source_trust on app.state;
        # give it a stub that records the clear_mark call.
        class _ST:
            def __init__(self): self.cleared = []
            def clear_mark(self, name): self.cleared.append(name)
            def mark(self, name, **k): pass
        st = _ST()
        svc._app.state.source_trust = st

        out = await svc.execute_or_propose("set_source_trust", source="camera",
                                           params={"trusted": True})
        assert out["result"] == "executed"
        assert st.cleared == ["camera"]
        await engine.dispose()

    async def test_dnd_suppresses_push_but_keeps_audit(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, notifier = _make_service(monkeypatch, maker, enabled=True, autonomous=False)

        class _Automation:
            def is_dnd_active(self):
                return True
        svc._app.state.automation = _Automation()

        out = await svc.execute_or_propose("recover_camera", source="camera", reason="t")
        # Proposal still recorded...
        assert out["result"] == "proposed"
        async with maker() as s:
            row = (await s.execute(select(RemediationLog))).scalar_one()
        assert row.result == "proposed"
        # ...but no push fired during DND.
        assert len(notifier.calls) == 0
        await engine.dispose()

    async def test_no_dnd_fires_push(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, notifier = _make_service(monkeypatch, maker, enabled=True, autonomous=False)

        class _Automation:
            def is_dnd_active(self):
                return False
        svc._app.state.automation = _Automation()

        await svc.execute_or_propose("recover_camera", source="camera", reason="t")
        assert len(notifier.calls) == 1
        await engine.dispose()

    async def test_disabled_status_reports_disabled(self, monkeypatch):
        maker, engine = await _memory_sessionmaker()
        svc, _ = _make_service(monkeypatch, maker, enabled=False, autonomous=False)
        status = await svc.status()
        assert status["mode"] == "disabled"
        await engine.dispose()
