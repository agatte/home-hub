"""Tests for ConfidenceFusion sub-factor plumbing (analytics constellation)."""

from backend.services.ml.confidence_fusion import (
    MAX_FACTORS_PER_LANE,
    SIGNAL_SOURCES,
    ConfidenceFusion,
    _clean_factors,
)


class TestCleanFactors:
    """The _clean_factors normalizer protects the fusion store from bad input."""

    def test_none_returns_empty(self):
        assert _clean_factors(None) == []

    def test_empty_returns_empty(self):
        assert _clean_factors([]) == []

    def test_valid_entry_passes_through(self):
        cleaned = _clean_factors([
            {
                "key": "zone",
                "label": "Zone",
                "value": "desk",
                "display": "desk",
                "impact": 0.8,
            },
        ])
        assert len(cleaned) == 1
        assert cleaned[0]["key"] == "zone"
        assert cleaned[0]["label"] == "Zone"
        assert cleaned[0]["display"] == "desk"
        assert cleaned[0]["impact"] == 0.8
        assert cleaned[0]["stale"] is False

    def test_missing_key_dropped(self):
        assert _clean_factors([{"label": "no key", "impact": 0.5}]) == []

    def test_impact_clamped(self):
        cleaned = _clean_factors([
            {"key": "a", "impact": 9.9},
            {"key": "b", "impact": -3.0},
        ])
        assert cleaned[0]["impact"] == 1.0
        assert cleaned[1]["impact"] == 0.0

    def test_impact_defaults_when_invalid(self):
        cleaned = _clean_factors([{"key": "x", "impact": "nope"}])
        assert cleaned[0]["impact"] == 0.5

    def test_display_falls_back_to_value_string(self):
        cleaned = _clean_factors([{"key": "x", "value": 42}])
        assert cleaned[0]["display"] == "42"

    def test_label_falls_back_to_key(self):
        cleaned = _clean_factors([{"key": "zone", "value": "desk"}])
        assert cleaned[0]["label"] == "zone"

    def test_stale_coerced_to_bool(self):
        cleaned = _clean_factors([
            {"key": "a", "stale": 1},
            {"key": "b", "stale": 0},
        ])
        assert cleaned[0]["stale"] is True
        assert cleaned[1]["stale"] is False

    def test_capped_at_max(self):
        overflow = [{"key": f"k{i}", "impact": 0.5} for i in range(MAX_FACTORS_PER_LANE + 3)]
        assert len(_clean_factors(overflow)) == MAX_FACTORS_PER_LANE

    def test_non_dict_entry_skipped(self):
        cleaned = _clean_factors([
            "bad",
            {"key": "ok", "impact": 0.3},
        ])
        assert len(cleaned) == 1
        assert cleaned[0]["key"] == "ok"


class TestFusionReportsFactors:
    """compute_fusion() must expose the latest factors on every lane entry."""

    def _factors_for(self, key: str) -> list[dict]:
        return [{
            "key": key,
            "label": key.title(),
            "value": f"v_{key}",
            "display": f"v_{key}",
            "impact": 0.7,
        }]

    def test_all_lanes_always_present(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "gaming", 1.0, factors=self._factors_for("fg"))
        result = fusion.compute_fusion()
        assert result is not None
        for src in SIGNAL_SOURCES:
            assert src in result["signals"]
            assert "factors" in result["signals"][src]

    def test_factors_round_trip(self):
        fusion = ConfidenceFusion()
        fusion.report_signal(
            "camera", "idle", 0.9, factors=self._factors_for("zone"),
        )
        result = fusion.compute_fusion()
        cam_factors = result["signals"]["camera"]["factors"]
        assert len(cam_factors) == 1
        assert cam_factors[0]["key"] == "zone"
        assert cam_factors[0]["display"] == "v_zone"

    def test_empty_when_no_factors_supplied(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0)
        result = fusion.compute_fusion()
        assert result["signals"]["process"]["factors"] == []

    def test_unreported_lanes_get_empty_factors(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("process", "working", 1.0, factors=self._factors_for("fg"))
        result = fusion.compute_fusion()
        # Lanes that never reported still appear with empty factors
        for src in ("camera", "audio_ml", "behavioral", "rule_engine"):
            assert result["signals"][src]["factors"] == []

    def test_factors_replaced_on_subsequent_report(self):
        fusion = ConfidenceFusion()
        fusion.report_signal("camera", "idle", 0.8, factors=self._factors_for("first"))
        fusion.report_signal("camera", "idle", 0.9, factors=self._factors_for("second"))
        result = fusion.compute_fusion()
        assert result["signals"]["camera"]["factors"][0]["key"] == "second"

    def test_invalid_factors_dropped_not_stored(self):
        fusion = ConfidenceFusion()
        fusion.report_signal(
            "process",
            "working",
            1.0,
            factors=[
                {"key": "good", "impact": 0.5},
                {"missing_key": True},  # dropped
                "garbage",  # dropped
            ],
        )
        result = fusion.compute_fusion()
        factors = result["signals"]["process"]["factors"]
        assert len(factors) == 1
        assert factors[0]["key"] == "good"
