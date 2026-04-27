"""Tests for ConfidenceFusion ensemble math.

Companion to test_fusion_factors.py which covers input-sanitization and
constellation plumbing. This file locks down the actual fusion decision
logic: staleness filtering, weight normalization, late-night decay, mode
scoring, agreement, threshold gates, and weight-learning math.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services.ml import confidence_fusion
from backend.services.ml.confidence_fusion import (
    AUTO_APPLY_THRESHOLD,
    DEFAULT_WEIGHTS,
    OVERRIDE_THRESHOLD,
    SIGNAL_SOURCES,
    STALE_SIGNAL_SECONDS,
    SUGGEST_THRESHOLD,
    ConfidenceFusion,
    Signal,
)


@pytest.fixture(autouse=True)
def _force_daytime(monkeypatch):
    """Force _is_late_night_local() to False for every test so the
    process-lane decay (active 22:00–06:00) doesn't silently skew weight
    math when the test suite runs in off-hours. TestLateNightDecay
    overrides this with its own monkeypatch."""
    monkeypatch.setattr(
        confidence_fusion, "_is_late_night_local", lambda: False,
    )


def _age_signal(fusion: ConfidenceFusion, source: str, seconds: float) -> None:
    """Backdate an already-reported signal by `seconds` from now."""
    sig = fusion._signals[source]
    fusion._signals[source] = Signal(
        source=sig.source,
        mode=sig.mode,
        confidence=sig.confidence,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=seconds),
        factors=sig.factors,
    )


class TestStaleness:
    """Signals older than STALE_SIGNAL_SECONDS are filtered out of the
    active set. Stale lanes still appear in the `signals` detail dict but
    never contribute to the fusion math.

    report_signal always stamps now(), so these tests reconstruct the
    underlying Signal with a backdated timestamp.
    """

    def test_signal_older_than_threshold_is_excluded(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.9)
        _age_signal(fusion, "process", STALE_SIGNAL_SECONDS + 1)
        assert fusion.compute_fusion() is None

    def test_signal_just_under_threshold_is_still_active(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.9)
        _age_signal(fusion, "process", STALE_SIGNAL_SECONDS - 1)
        result = fusion.compute_fusion()
        assert result is not None
        assert result["fused_mode"] == "working"

    def test_all_stale_returns_none(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.9)
        fusion.report_signal("camera", "idle", 0.8)
        _age_signal(fusion, "process", STALE_SIGNAL_SECONDS + 1)
        _age_signal(fusion, "camera", STALE_SIGNAL_SECONDS + 1)
        assert fusion.compute_fusion() is None

    def test_stale_signal_detail_marked_stale_and_disagreeing(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.9)
        fusion.report_signal("camera", "working", 0.8)
        _age_signal(fusion, "process", STALE_SIGNAL_SECONDS + 1)
        result = fusion.compute_fusion()
        assert result is not None
        proc = result["signals"]["process"]
        assert proc["stale"] is True
        assert proc["agrees"] is False  # False even though mode would match
        assert proc["last_update"] is not None
        assert proc["mode"] == "working"


class TestWeightNormalization:
    def test_single_active_signal_normalized_to_one(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("camera", "idle", 0.77)
        result = fusion.compute_fusion()
        assert result is not None
        assert result["fused_mode"] == "idle"
        # Single active signal: normalized weight = 1.0, score = 0.77
        assert result["fused_confidence"] == pytest.approx(0.77, abs=1e-4)

    def test_stale_weight_redistributed_to_active(self):
        fusion = ConfidenceFusion()
        # Two signals vote the same mode at conf 1.0. Unreported lanes'
        # weights get redistributed → fused_confidence must reach 1.0.
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        result = fusion.compute_fusion()
        assert result["fused_confidence"] == pytest.approx(1.0, abs=1e-4)

    def test_unreported_lanes_contribute_nothing(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "gaming", 0.6)
        result = fusion.compute_fusion()
        assert result is not None
        assert result["fused_confidence"] == pytest.approx(0.6, abs=1e-4)
        for src in ("camera", "audio_ml", "rule_engine", "presence"):
            assert result["signals"][src]["mode"] is None


class TestLateNightDecay:
    def test_solo_process_at_night_still_reaches_full_confidence(self, monkeypatch):
        """With only the process lane reporting, late-night decay scales
        its pre-normalization weight but after redistribution it's still
        the only voter → normalized weight = 1.0."""
        monkeypatch.setattr(
            confidence_fusion, "_is_late_night_local", lambda: True,
        )
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.8)
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "working"
        assert result["fused_confidence"] == pytest.approx(0.8, abs=1e-4)

    def test_night_decay_flips_winner(self, monkeypatch):
        """process (0.344) alone vs camera (0.196) + rule_engine (0.098):
        - day:   process=0.344 > combined=0.294  → working wins
        - night: process*0.6=0.206 < combined=0.294 → relax wins
        """
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "relax", 1.0)
        fusion.report_signal("rule_engine", "relax", 1.0)

        monkeypatch.setattr(
            confidence_fusion, "_is_late_night_local", lambda: False,
        )
        assert fusion.compute_fusion()["fused_mode"] == "working"

        monkeypatch.setattr(
            confidence_fusion, "_is_late_night_local", lambda: True,
        )
        assert fusion.compute_fusion()["fused_mode"] == "relax"

    def test_decay_only_touches_process_lane(self, monkeypatch):
        """Night flag on, but process never reports. Camera+audio_ml
        both vote relax at conf 0.5 — their weights must NOT be decayed,
        so the fused confidence stays 0.5."""
        monkeypatch.setattr(
            confidence_fusion, "_is_late_night_local", lambda: True,
        )
        fusion = ConfidenceFusion()
        fusion.report_signal("camera", "relax", 0.5)
        fusion.report_signal("audio_ml", "relax", 0.5)
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "relax"
        assert result["fused_confidence"] == pytest.approx(0.5, abs=1e-4)


class TestModeScoring:
    def test_same_mode_votes_sum(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        result = fusion.compute_fusion()
        assert result["fused_confidence"] == pytest.approx(1.0, abs=1e-4)

    def test_higher_weighted_score_wins_not_mode_priority(self):
        """Automation engine's mode priority puts gaming (5) above idle (1),
        but fusion uses weighted score only. camera+audio_ml for idle must
        outweigh rule_engine for gaming."""
        fusion = ConfidenceFusion()
        fusion.report_signal("camera", "idle", 1.0)       # 0.164
        fusion.report_signal("audio_ml", "idle", 1.0)     # 0.123
        fusion.report_signal("rule_engine", "gaming", 1.0)  # 0.082
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "idle"

    def test_fused_confidence_rounded_to_four_decimals(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0 / 3.0)
        result = fusion.compute_fusion()
        assert result["fused_confidence"] == 0.3333

    def test_confidence_clamped_on_report(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.5)
        fusion.report_signal("camera", "relax", -0.5)
        result = fusion.compute_fusion()
        # Clamped: process=1.0, camera=0.0. Working wins on non-zero vote.
        assert result["fused_mode"] == "working"
        assert result["signals"]["process"]["confidence"] == 1.0
        assert result["signals"]["camera"]["confidence"] == 0.0


class TestAgreement:
    def test_three_of_three_agreement_is_one(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        fusion.report_signal("audio_ml", "working", 1.0)
        result = fusion.compute_fusion()
        assert result["agreement"] == 1.0

    def test_three_of_five_agreement(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        fusion.report_signal("presence", "working", 1.0)
        fusion.report_signal("audio_ml", "idle", 1.0)
        fusion.report_signal("rule_engine", "idle", 1.0)
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "working"
        assert result["agreement"] == pytest.approx(0.6, abs=1e-4)

    def test_stale_signals_excluded_from_agreement_denominator(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        fusion.report_signal("audio_ml", "idle", 1.0)
        _age_signal(fusion, "audio_ml", STALE_SIGNAL_SECONDS + 1)
        result = fusion.compute_fusion()
        # Active: {process, camera} both vote working → 2/2 = 1.0
        assert result["agreement"] == 1.0


class TestThresholdGates:
    def test_auto_apply_fires_at_exact_threshold(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", AUTO_APPLY_THRESHOLD)
        result = fusion.compute_fusion()
        assert result["fused_confidence"] == AUTO_APPLY_THRESHOLD
        assert result["auto_apply"] is True
        assert result["can_override"] is True

    def test_auto_apply_blocked_just_below_threshold(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 0.949)
        result = fusion.compute_fusion()
        assert result["fused_confidence"] == 0.949
        assert result["auto_apply"] is False
        # Still above OVERRIDE_THRESHOLD (0.92) with full agreement.
        assert result["can_override"] is True

    def test_can_override_requires_both_confidence_and_agreement(self):
        """Custom weights craft fused_confidence=0.92, agreement=0.80 —
        the exact edge where can_override is expected to trigger."""
        fusion = ConfidenceFusion()
        fusion._weights = {
            "process":     0.23,
            "camera":      0.23,
            "audio_ml":    0.23,
            "presence":    0.23,
            "rule_engine": 0.08,
        }
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        fusion.report_signal("audio_ml", "working", 1.0)
        fusion.report_signal("presence", "working", 1.0)
        fusion.report_signal("rule_engine", "gaming", 1.0)
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "working"
        assert result["fused_confidence"] == pytest.approx(0.92, abs=1e-4)
        assert result["agreement"] == pytest.approx(0.80, abs=1e-4)
        assert result["can_override"] is True
        assert result["auto_apply"] is False  # 0.92 < 0.95

    def test_can_override_blocked_when_agreement_too_low(self):
        """Custom weights: fused_confidence=0.92 but only 3 of 5 signals
        vote for the winner → agreement=0.6 < 0.80 → can_override=False."""
        fusion = ConfidenceFusion()
        fusion._weights = {
            "process":     0.50,
            "camera":      0.25,
            "audio_ml":    0.17,
            "presence":    0.04,
            "rule_engine": 0.04,
        }
        fusion.report_signal("process", "working", 1.0)
        fusion.report_signal("camera", "working", 1.0)
        fusion.report_signal("audio_ml", "working", 1.0)
        fusion.report_signal("presence", "gaming", 1.0)
        fusion.report_signal("rule_engine", "gaming", 1.0)
        result = fusion.compute_fusion()
        assert result["fused_mode"] == "working"
        assert result["fused_confidence"] == pytest.approx(0.92, abs=1e-4)
        assert result["agreement"] == pytest.approx(0.6, abs=1e-4)
        assert result["can_override"] is False


class TestWeightLearning:
    def test_uniform_accuracy_produces_equal_weights(self):
        fusion = ConfidenceFusion()
        fusion.update_weights_from_accuracy({src: 0.8 for src in SIGNAL_SOURCES})
        expected = 1.0 / len(SIGNAL_SOURCES)
        for src in SIGNAL_SOURCES:
            assert fusion._weights[src] == pytest.approx(expected, abs=1e-4)
        assert sum(fusion._weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_zero_accuracy_zeroes_that_source(self):
        fusion = ConfidenceFusion()
        acc = {src: 0.5 for src in SIGNAL_SOURCES}
        acc["rule_engine"] = 0.0
        fusion.update_weights_from_accuracy(acc)
        assert fusion._weights["rule_engine"] == 0.0
        assert sum(fusion._weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_missing_source_falls_back_to_default(self):
        fusion = ConfidenceFusion()
        fusion.update_weights_from_accuracy({"process": 0.9})
        raw_sum = 0.9 + sum(
            DEFAULT_WEIGHTS[s] for s in SIGNAL_SOURCES if s != "process"
        )
        assert fusion._weights["process"] == pytest.approx(0.9 / raw_sum, abs=1e-4)
        assert sum(fusion._weights.values()) == pytest.approx(1.0, abs=1e-4)

    def test_all_zero_accuracy_keeps_weights_unchanged(self, caplog):
        fusion = ConfidenceFusion()
        original = dict(fusion._weights)
        with caplog.at_level("WARNING", logger="home_hub.ml"):
            fusion.update_weights_from_accuracy({src: 0.0 for src in SIGNAL_SOURCES})
        assert fusion._weights == original
        assert any("zero" in r.message.lower() for r in caplog.records)


class TestGetState:
    def test_schema_shape(self):
        state = ConfidenceFusion().get_state()
        assert set(state.keys()) == {
            "weights", "signal_count", "sources", "latest_fusion", "thresholds",
        }
        assert state["sources"] == list(SIGNAL_SOURCES)
        assert state["signal_count"] == 0
        assert state["latest_fusion"] is None

    def test_thresholds_expose_constants(self):
        state = ConfidenceFusion().get_state()
        assert state["thresholds"] == {
            "auto_apply": AUTO_APPLY_THRESHOLD,
            "override": OVERRIDE_THRESHOLD,
            "suggest": SUGGEST_THRESHOLD,
            "stale_seconds": STALE_SIGNAL_SECONDS,
        }


class TestReportSignalRobustness:
    def test_unknown_source_silently_dropped(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("garbage_source", "working", 0.9)
        assert "garbage_source" not in fusion._signals

    def test_invalid_mode_silently_dropped(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "not_a_mode", 0.9)
        assert "process" not in fusion._signals

    def test_non_numeric_confidence_does_not_raise(self):
        fusion = ConfidenceFusion()
        # fire-and-forget invariant: invalid types must never propagate.
        fusion.report_signal("process", "working", "not_a_number")
        assert "process" not in fusion._signals
