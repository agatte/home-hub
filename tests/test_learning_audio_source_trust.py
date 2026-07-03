from types import SimpleNamespace

import pytest

from backend.api.routes.learning import AudioDecisionReport, log_audio_decision


class _FakeSourceTrust:
    def __init__(self) -> None:
        self.calls = []

    def observe(self, name, value):
        self.calls.append((name, value))


class _FakeMLLogger:
    def __init__(self, source_trust) -> None:
        self.source_trust = source_trust
        self.calls = []

    async def log_decision(self, **kwargs):
        self.calls.append(kwargs)
        assert self.source_trust.calls == [
            ("audio_ml", {"top_score": 0.42, "top_class": "working"})
        ]


@pytest.mark.asyncio
async def test_audio_decision_observes_source_trust_before_logging():
    source_trust = _FakeSourceTrust()
    ml_logger = _FakeMLLogger(source_trust)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(source_trust=source_trust, ml_logger=ml_logger)
        )
    )

    result = await log_audio_decision(
        AudioDecisionReport(
            predicted_mode="working",
            confidence=0.42,
            applied=False,
            factors={"source": "test"},
        ),
        request,
    )

    assert result == {"status": "ok"}
    assert ml_logger.calls == [
        {
            "predicted_mode": "working",
            "confidence": 0.42,
            "decision_source": "audio_ml",
            "factors": {"source": "test"},
            "applied": False,
        }
    ]
