"""
Tests for the ambient-lux brightness multiplier.

Covers:
  - ``lux_to_multiplier``: the piecewise-linear curve at boundaries and midpoints.
  - ``_apply_lux_multiplier``: guard conditions (mode scope, camera state,
    calibration, staleness) and the arithmetic (per-light, kitchen-pair
    preservation, bounds clamping).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services.automation_engine import (
    LUX_CURVE,
    LUX_MODES,
    LUX_STALE_SECONDS,
    AutomationEngine,
    lux_to_multiplier,
)


# ---------------------------------------------------------------------------
# lux_to_multiplier — pure curve behavior
# ---------------------------------------------------------------------------

class TestLuxToMultiplier:
    """Verify the piecewise-linear lux → multiplier curve."""

    def test_dark_anchor(self):
        assert lux_to_multiplier(40.0) == pytest.approx(1.15)

    def test_mid_anchor(self):
        assert lux_to_multiplier(90.0) == pytest.approx(1.00)

    def test_bright_anchor(self):
        assert lux_to_multiplier(180.0) == pytest.approx(0.85)

    def test_below_range_clamps_to_bright_lift(self):
        assert lux_to_multiplier(0.0) == pytest.approx(1.15)
        assert lux_to_multiplier(-50.0) == pytest.approx(1.15)

    def test_above_range_clamps_to_dim(self):
        assert lux_to_multiplier(255.0) == pytest.approx(0.85)
        assert lux_to_multiplier(1000.0) == pytest.approx(0.85)

    def test_midpoint_dark_to_normal(self):
        # lux=65 is midway between anchors (40, 1.15) and (90, 1.00)
        # Expected: 1.15 + (65-40)/(90-40) * (1.00-1.15) = 1.15 - 0.075 = 1.075
        assert lux_to_multiplier(65.0) == pytest.approx(1.075)

    def test_midpoint_normal_to_bright(self):
        # lux=135 is midway between (90, 1.00) and (180, 0.85)
        # Expected: 1.00 + (135-90)/(180-90) * (0.85-1.00) = 1.00 - 0.075 = 0.925
        assert lux_to_multiplier(135.0) == pytest.approx(0.925)

    def test_monotonically_decreasing(self):
        values = [lux_to_multiplier(l) for l in range(0, 256, 10)]
        for a, b in zip(values, values[1:]):
            assert b <= a + 1e-9, "curve must be monotonically non-increasing"

    def test_curve_definition_matches_spec(self):
        # Sanity check: anchors are what the spec committed to.
        assert LUX_CURVE == [(40.0, 1.15), (90.0, 1.00), (180.0, 0.85)]


# ---------------------------------------------------------------------------
# lux_to_multiplier — baseline-shifted behavior
# ---------------------------------------------------------------------------

class TestLuxToMultiplierWithBaseline:
    """Verify baseline-relative curve behavior.

    The baseline argument shifts the curve so the user's calibrated "normal
    room" reading sits at multiplier = 1.00. Default baseline of 90 matches
    the raw anchors, preserving original behavior for legacy callers.
    """

    def test_default_baseline_preserves_original_curve(self):
        # Without a baseline kwarg, legacy behavior is unchanged.
        assert lux_to_multiplier(40.0) == pytest.approx(1.15)
        assert lux_to_multiplier(90.0) == pytest.approx(1.00)
        assert lux_to_multiplier(180.0) == pytest.approx(0.85)

    def test_baseline_90_matches_default(self):
        # Explicit baseline=90 produces the same numbers as the default arg.
        for lux in (0.0, 40.0, 65.0, 90.0, 120.0, 180.0, 255.0):
            assert lux_to_multiplier(lux, 90.0) == pytest.approx(lux_to_multiplier(lux))

    def test_baseline_141_lux_at_baseline_is_neutral(self):
        # The core Anthony-room case: calibrated at 141 → 141 should be 1.00×.
        assert lux_to_multiplier(141.0, 141.0) == pytest.approx(1.00)

    def test_baseline_141_lux_below_baseline_lifts(self):
        # Effective lux = 91 - 141 + 90 = 40 → full 1.15 lift.
        assert lux_to_multiplier(91.0, 141.0) == pytest.approx(1.15)

    def test_baseline_141_lux_above_baseline_dims(self):
        # Effective lux = 231 - 141 + 90 = 180 → full 0.85 dim.
        assert lux_to_multiplier(231.0, 141.0) == pytest.approx(0.85)

    def test_baseline_141_midpoint(self):
        # lux=180, baseline=141 → effective 129 → interp between (90,1.00) and (180,0.85)
        # frac = (129-90)/(180-90) = 0.4333..., mult = 1.00 + 0.4333*(-0.15) = 0.935
        assert lux_to_multiplier(180.0, 141.0) == pytest.approx(0.935, abs=1e-3)

    def test_baseline_fixes_the_0_94_bug(self):
        # Before fix: lux=141, baseline=90 → 0.94 (dimming the user's normal room).
        # After fix: lux=141, baseline=141 → 1.00 (no change at normal room).
        before = lux_to_multiplier(141.0, 90.0)
        after = lux_to_multiplier(141.0, 141.0)
        assert before < 1.0  # confirms the bug was real
        assert after == pytest.approx(1.00)  # confirms the fix resolves it

    def test_shift_is_translation_not_reshape(self):
        # The curve is translated by (baseline - 90), not reshaped. For any
        # baseline, f(lux, baseline) must equal f(lux - baseline + 90, 90).
        # The curve is asymmetric (50-dark / 90-bright swings), so only this
        # per-point identity holds — not a single global "slope".
        for baseline in (60.0, 90.0, 120.0, 141.0, 200.0):
            for offset in (-60, -30, -10, 0, 10, 30, 60, 100):
                lux = baseline + offset
                shifted_lux = 90.0 + offset
                assert lux_to_multiplier(lux, baseline) == pytest.approx(
                    lux_to_multiplier(shifted_lux, 90.0), abs=1e-9
                )

    def test_baseline_50_clamps_dim_side_early(self):
        # Low baseline — a bright lux gets dimmed by reaching anchor sooner.
        # lux=140 with baseline=50 → effective 180 → 0.85 (full clamp).
        assert lux_to_multiplier(140.0, 50.0) == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# _apply_lux_multiplier — engine method
# ---------------------------------------------------------------------------

def _make_engine(mock_hue, mock_hue_v2, mock_ws) -> AutomationEngine:
    return AutomationEngine(hue=mock_hue, hue_v2=mock_hue_v2, ws_manager=mock_ws)


def _fake_camera(ema_lux: float | None, *, age_seconds: float = 0.0,
                 enabled: bool = True, paused: bool = False,
                 baseline_lux: float | None = None) -> SimpleNamespace:
    """Build a duck-typed stand-in for the camera service.

    The engine reads ``enabled``, ``_paused``, ``ema_lux``, ``last_lux_update``,
    and ``baseline_lux`` via getattr — SimpleNamespace matches exactly without
    needing MediaPipe. ``baseline_lux=None`` simulates a legacy calibration
    (no baseline persisted yet) and should make the curve fall back to 90.
    """
    last = None
    if ema_lux is not None:
        last = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return SimpleNamespace(
        enabled=enabled,
        _paused=paused,
        ema_lux=ema_lux,
        last_lux_update=last,
        baseline_lux=baseline_lux,
    )


class TestApplyLuxMultiplierGuards:
    """Every guard path returns the state unchanged."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return _make_engine(mock_hue, mock_hue_v2, mock_ws)

    def test_mode_not_in_lux_modes_returns_unchanged(self, engine):
        engine.set_camera_service(_fake_camera(40.0))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "gaming") is state

    def test_watching_not_modulated(self, engine):
        # Deliberate: watching stays static even though presence is similar
        engine.set_camera_service(_fake_camera(40.0))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "watching") is state

    def test_cooking_not_modulated(self, engine):
        engine.set_camera_service(_fake_camera(40.0))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "cooking") is state

    def test_no_camera_service_returns_unchanged(self, engine):
        state = {"1": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        assert result is state

    def test_disabled_camera_returns_unchanged(self, engine):
        engine.set_camera_service(_fake_camera(40.0, enabled=False))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "working") is state

    def test_paused_camera_returns_unchanged(self, engine):
        engine.set_camera_service(_fake_camera(40.0, paused=True))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "working") is state

    def test_uncalibrated_camera_returns_unchanged(self, engine):
        # ema_lux=None represents "calibration missing" (CameraService.ema_lux
        # property returns None when _calibrated is false)
        engine.set_camera_service(_fake_camera(None))
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "working") is state

    def test_stale_reading_returns_unchanged(self, engine):
        engine.set_camera_service(
            _fake_camera(40.0, age_seconds=LUX_STALE_SECONDS + 5)
        )
        state = {"1": {"on": True, "bri": 200}}
        assert engine._apply_lux_multiplier(state, "working") is state


class TestApplyLuxMultiplierArithmetic:
    """The multiplier produces correct per-light brightness values."""

    @pytest.fixture
    def engine(self, mock_hue, mock_hue_v2, mock_ws):
        return _make_engine(mock_hue, mock_hue_v2, mock_ws)

    def test_working_at_bright_dims_bri(self, engine):
        engine.set_camera_service(_fake_camera(180.0))
        state = {"1": {"on": True, "bri": 200, "ct": 250}}
        result = engine._apply_lux_multiplier(state, "working")
        # multiplier = 0.85, 200 * 0.85 = 170
        assert result["1"]["bri"] == 170
        # ct untouched
        assert result["1"]["ct"] == 250

    def test_working_at_dark_lifts_bri(self, engine):
        engine.set_camera_service(_fake_camera(40.0))
        state = {"1": {"on": True, "bri": 150, "ct": 250}}
        result = engine._apply_lux_multiplier(state, "working")
        # multiplier = 1.15, 150 * 1.15 = 172.5 -> int = 172
        assert result["1"]["bri"] == 172

    def test_kitchen_pair_preserved_in_working(self, engine):
        engine.set_camera_service(_fake_camera(135.0))
        state = {
            "1": {"on": True, "bri": 200, "ct": 233},
            "2": {"on": True, "bri": 254, "ct": 200},
            "3": {"on": True, "bri": 170, "ct": 233},
            "4": {"on": True, "bri": 170, "ct": 233},
        }
        result = engine._apply_lux_multiplier(state, "working")
        # Kitchen pair (L3/L4) must scale together
        assert result["3"]["bri"] == result["4"]["bri"]

    def test_relax_night_low_bri_clamps_to_min_1(self, engine):
        engine.set_camera_service(_fake_camera(180.0))  # multiplier 0.85
        state = {"3": {"on": True, "bri": 1}}
        result = engine._apply_lux_multiplier(state, "relax")
        # int(1 * 0.85) = 0, then clamped to 1
        assert result["3"]["bri"] == 1

    def test_relax_night_low_bri_lift(self, engine):
        engine.set_camera_service(_fake_camera(40.0))  # multiplier 1.15
        state = {"3": {"on": True, "bri": 30}}
        result = engine._apply_lux_multiplier(state, "relax")
        assert result["3"]["bri"] == 34  # int(30 * 1.15) = 34

    def test_off_lights_untouched(self, engine):
        engine.set_camera_service(_fake_camera(40.0))
        state = {
            "1": {"on": True, "bri": 200},
            "2": {"on": False},
        }
        result = engine._apply_lux_multiplier(state, "working")
        assert result["2"] == {"on": False}  # no bri added

    def test_bri_clamp_upper_bound(self, engine):
        engine.set_camera_service(_fake_camera(40.0))  # multiplier 1.15
        state = {"2": {"on": True, "bri": 254}}
        result = engine._apply_lux_multiplier(state, "working")
        # 254 * 1.15 = 292 -> clamped to 254
        assert result["2"]["bri"] == 254

    def test_hysteresis_avoids_tiny_changes(self, engine):
        # Warm up the hysteresis tracker
        engine.set_camera_service(_fake_camera(90.0))  # multiplier = 1.00
        engine._apply_lux_multiplier({"1": {"on": True, "bri": 200}}, "working")
        assert engine._last_lux_multiplier == pytest.approx(1.00)

        # A microscopic change (lux=91 → mult ≈ 0.998) must not count —
        # the engine should keep using 1.00 so the state dict is unchanged.
        engine.set_camera_service(_fake_camera(91.0))
        state = {"1": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        assert result["1"]["bri"] == 200  # unchanged (multiplier effectively 1.0)

    def test_modes_scope_covers_working_and_relax_only(self):
        assert LUX_MODES == frozenset({"working", "relax"})

    def test_baseline_makes_calibrated_room_neutral(self, engine):
        # User's room calibrates at lux=141. At lux=141 the multiplier must
        # be 1.00 → bri must equal the untouched base value.
        engine.set_camera_service(_fake_camera(141.0, baseline_lux=141.0))
        state = {"2": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        assert result["2"]["bri"] == 200  # no modulation at baseline

    def test_baseline_dark_room_lifts_bri(self, engine):
        # lux=91 < baseline=141 → full lift (×1.15).
        engine.set_camera_service(_fake_camera(91.0, baseline_lux=141.0))
        state = {"2": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        # 200 * 1.15 = 229.9999... in binary float; int() truncates to 229.
        assert result["2"]["bri"] == 229

    def test_baseline_bright_room_dims_bri(self, engine):
        # lux=231 > baseline=141 → full dim (×0.85).
        engine.set_camera_service(_fake_camera(231.0, baseline_lux=141.0))
        state = {"2": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        assert result["2"]["bri"] == 170  # int(200 * 0.85)

    def test_missing_baseline_falls_back_to_90(self, engine):
        # Legacy calibration without baseline_lux — the engine defaults to 90,
        # preserving the original (pre-fix) behavior. lux=141 → 0.915×.
        engine.set_camera_service(_fake_camera(141.0, baseline_lux=None))
        state = {"2": {"on": True, "bri": 200}}
        result = engine._apply_lux_multiplier(state, "working")
        # int(200 * 0.915) = 183
        assert result["2"]["bri"] == 183
