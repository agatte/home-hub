"""
Tests for the multi-light ScreenSyncService.

Dual-region screen sync drives L2 from the left half of the screen and L5
from the right half. These tests verify the three properties that make
that independence real:

  - per-light EMA smoothing state (L2 and L5 don't share `_last_hue`)
  - per-(mode, light_id) brightness caps (gaming L2=240, gaming L5=60)
  - unknown light ids are silently dropped (defense for typo'd payloads)
"""
import pytest

from backend.services import screen_sync as ss


class _FakeHue:
    """Minimal hue stub that records the last set_light call per light_id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> None:
        self.calls.append((light_id, state))

    def last_for(self, light_id: str) -> dict:
        for lid, state in reversed(self.calls):
            if lid == light_id:
                return state
        raise KeyError(f"no call for {light_id}")


@pytest.mark.asyncio
async def test_per_light_ema_state_independent():
    """L2's smoothing must not leak into L5's smoothing state."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # L2 sees a pure red sequence.
    for _ in range(5):
        await sync.apply_color("2", 220, 40, 40, mode="gaming")
    l2_state = hue.last_for("2")

    # L5 sees a pure blue sequence (first time L5 is touched — EMA starts
    # from 0 for L5, not from L2's red prior).
    await sync.apply_color("5", 40, 40, 220, mode="gaming")
    l5_state = hue.last_for("5")

    # Sanity: L2 settled around red-ish hue (≈ 65535 wrap or 0), L5 around blue
    # hue (~43000–44000 in Hue's 0-65535 space, which is ~240° in degrees).
    # The point is that L5's first smoothed value should be ~30% of pure blue
    # from a starting prior of 0, not pulled by L2's red EMA.
    assert l5_state["bri"] != l2_state["bri"], (
        "L5 brightness should reflect blue's value, not L2's red prior"
    )
    # The per-light state dicts should each hold a non-zero last value.
    assert sync._last_hue["2"] != sync._last_hue["5"]


@pytest.mark.asyncio
async def test_gaming_caps_differ_per_light():
    """L2 gaming max is 240, L5 gaming max is 180 — bright white must clamp differently."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Pure white = max brightness signal. Run enough frames for EMA to settle.
    for _ in range(20):
        await sync.apply_color("2", 255, 255, 255, mode="gaming")
        await sync.apply_color("5", 255, 255, 255, mode="gaming")

    l2_bri = hue.last_for("2")["bri"]
    l5_bri = hue.last_for("5")["bri"]

    assert l2_bri > l5_bri, f"L2 should outshine L5 on bright frames (L2={l2_bri}, L5={l5_bri})"
    # L2 clamps to 240, L5 clamps to 60 (per MODE_MAX_BRIGHTNESS).
    assert l2_bri <= 240
    assert l5_bri <= 60


@pytest.mark.asyncio
async def test_unknown_light_id_is_noop():
    """Typo'd light ids must not silently apply to a real light."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    await sync.apply_color("99", 220, 40, 40, mode="gaming")
    assert hue.calls == []


@pytest.mark.asyncio
async def test_watching_zone_cap_overrides_per_light():
    """Bed+reclined caps differ per light (L2=25, L5=20)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Run enough frames for EMA to converge near the cap.
    for _ in range(30):
        await sync.apply_color(
            "2", 255, 255, 255, mode="watching", zone="bed", posture="reclined"
        )
        await sync.apply_color(
            "5", 255, 255, 255, mode="watching", zone="bed", posture="reclined"
        )

    l2_bri = hue.last_for("2")["bri"]
    l5_bri = hue.last_for("5")["bri"]

    # Caps are 25 / 20; EMA on pure white will sit at the cap.
    assert l2_bri <= 25
    assert l5_bri <= 20
    assert l2_bri >= l5_bri


@pytest.mark.asyncio
async def test_set_cap_override_targets_l2_by_default():
    """The watching-posture sliders write L2-only — back-compat with existing call sites."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Slider raises L2's reclined cap from 25 → 50. L5's stays at 20.
    sync.set_cap_override("watching", "bed", "reclined", 50)

    assert sync.get_cap("watching", "2", "bed", "reclined") == 50
    assert sync.get_cap("watching", "5", "bed", "reclined") == 20


@pytest.mark.asyncio
async def test_target_lights_exposes_both():
    """`target_light` returns the primary (L2); `target_lights` returns the full list."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    assert sync.target_light == "2"
    assert sync.target_lights == ["2", "5"]


@pytest.mark.asyncio
async def test_per_light_sat_boost():
    """L2 gets +20% sat boost; L5 stays neutral. Same RGB → different sat output."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Feed identical strongly-saturated red to both lights; both EMA states
    # start at 0 so the first frame is `alpha * target` for each axis.
    await sync.apply_color("2", 220, 40, 40, mode="gaming")
    await sync.apply_color("5", 220, 40, 40, mode="gaming")

    l2_state = hue.last_for("2")
    l5_state = hue.last_for("5")

    # Both should be in HSB mode with the same hue (red is red).
    assert abs(l2_state["hue"] - l5_state["hue"]) < 100, (
        f"hue should match for same RGB: L2={l2_state['hue']} L5={l5_state['hue']}"
    )
    # L2's sat should be higher than L5's because of the +20% boost.
    assert l2_state["sat"] > l5_state["sat"], (
        f"L2 should be more saturated than L5 (L2={l2_state['sat']}, L5={l5_state['sat']})"
    )


@pytest.mark.asyncio
async def test_l5_luma_comp_dampens_yellow_more_than_blue():
    """L5's perceptual-luminance comp scales high-luma hues (yellow/green) down
    more than low-luma hues (blue/red). Tested at moderate-bright inputs
    where the comp visibly differentiates before the L5 cap clamps both."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Moderate-bright yellow (80,80,0) — v=0.314 chroma_luma~0.886, with
    # comp the target lands below the cap so the damping is visible.
    for _ in range(20):
        await sync.apply_color("5", 80, 80, 0, mode="gaming")
    yellow_bri = hue.last_for("5")["bri"]

    # Same channel intensity, pure blue (0,0,80) — chroma_luma~0.114, scale
    # clamped to 1.0 → target hits the cap.
    hue2 = _FakeHue()
    sync2 = ss.ScreenSyncService(hue_service=hue2, target_light_ids=["2", "5"])
    for _ in range(20):
        await sync2.apply_color("5", 0, 0, 80, mode="gaming")
    blue_bri = hue2.last_for("5")["bri"]

    # Both should land near or within the L5 [25, 60] gaming band — allow
    # one bri unit of slack for EMA asymptotic convergence + int-cast.
    assert 24 <= yellow_bri <= 60
    assert 24 <= blue_bri <= 60
    # At ref=0.25 yellow scales hard (~28% of HSV value); blue is unaffected
    # (clamped to 1.0). Expect yellow ≤ ~half of blue at this input level.
    assert yellow_bri < blue_bri * 0.55, (
        f"luma comp not damping yellow enough: yellow={yellow_bri} blue={blue_bri}"
    )


@pytest.mark.asyncio
async def test_period_keyed_caps_take_precedence():
    """When a `period` is passed, MODE_MAX_BRIGHTNESS_PERIOD wins over the
    time-agnostic table. Gaming evening L5 cap = 50 (vs day 60)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Saturate pure deep-blue (low-luma → no comp damping). Day cap=60.
    for _ in range(20):
        await sync.apply_color("5", 0, 0, 255, mode="gaming", period="day")
    day_bri = hue.last_for("5")["bri"]

    # Evening cap=50.
    hue2 = _FakeHue()
    sync2 = ss.ScreenSyncService(hue_service=hue2, target_light_ids=["2", "5"])
    for _ in range(20):
        await sync2.apply_color("5", 0, 0, 255, mode="gaming", period="evening")
    evening_bri = hue2.last_for("5")["bri"]

    assert day_bri > evening_bri, (
        f"evening cap should be tighter than day (day={day_bri} evening={evening_bri})"
    )
    # Within their respective per-period caps.
    assert day_bri <= 60
    assert evening_bri <= 50


@pytest.mark.asyncio
async def test_late_night_floor_drop_for_l2():
    """L2's late_night floor drops to 110 so dark scenes can dim past the
    default 130 floor (which equals the late_night cap, collapsing range)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Pure black input — bri target should hit the floor.
    for _ in range(30):
        await sync.apply_color("2", 0, 0, 0, mode="gaming", period="late_night")
    bri = hue.last_for("2")["bri"]

    # Floor at late_night should be 110, not 130. Allow 1 unit slack for EMA
    # asymptotic convergence + int-cast.
    assert 108 <= bri <= 112, f"expected floor near 110, got {bri}"


@pytest.mark.asyncio
async def test_l2_no_luma_comp():
    """L2 is NOT luma-compensated — yellow and blue settle at similar bri
    (modulo HSV value differences, which are the same for fully-saturated
    primaries at max channel = 255)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    for _ in range(20):
        await sync.apply_color("2", 255, 255, 0, mode="gaming")
    yellow_bri = hue.last_for("2")["bri"]

    hue2 = _FakeHue()
    sync2 = ss.ScreenSyncService(hue_service=hue2, target_light_ids=["2", "5"])
    for _ in range(20):
        await sync2.apply_color("2", 0, 0, 255, mode="gaming")
    blue_bri = hue2.last_for("2")["bri"]

    # Without luma comp, both fully-saturated primaries hit the same HSV v=1.0
    # and settle at the same L2 cap (240).
    assert abs(yellow_bri - blue_bri) <= 5, (
        f"L2 should not luma-compensate: yellow={yellow_bri} blue={blue_bri}"
    )
