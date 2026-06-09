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
    """L2 gaming max is 240, L5 gaming max is 75 — bright white must clamp differently."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Pure white = max brightness signal. Run enough frames for EMA to settle.
    for _ in range(20):
        await sync.apply_color("2", 255, 255, 255, mode="gaming")
        await sync.apply_color("5", 255, 255, 255, mode="gaming")

    l2_bri = hue.last_for("2")["bri"]
    l5_bri = hue.last_for("5")["bri"]

    assert l2_bri > l5_bri, f"L2 should outshine L5 on bright frames (L2={l2_bri}, L5={l5_bri})"
    # L2 clamps to 240, L5 clamps to 75 (per MODE_MAX_BRIGHTNESS; 60→75 curator 6/02).
    assert l2_bri <= 240
    assert l5_bri <= 75


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

    # Brighter yellow (160,160,0) so the comp-scaled target lands ABOVE the
    # raised L5 floor (40) — otherwise the floor masks the damping. High
    # chroma_luma → comp scales it down toward (but not to) the floor.
    for _ in range(20):
        await sync.apply_color("5", 160, 160, 0, mode="gaming")
    yellow_bri = hue.last_for("5")["bri"]

    # Same channel intensity, pure blue (0,0,160) — chroma_luma low, scale
    # clamped to 1.0 → target hits the cap.
    hue2 = _FakeHue()
    sync2 = ss.ScreenSyncService(hue_service=hue2, target_light_ids=["2", "5"])
    for _ in range(20):
        await sync2.apply_color("5", 0, 0, 160, mode="gaming")
    blue_bri = hue2.last_for("5")["bri"]

    # Both land within the L5 [40, 75] gaming band (floor 25→40, cap 60→75,
    # curator 6/02). Allow slack for EMA asymptotic convergence + int-cast.
    assert 38 <= yellow_bri <= 76
    assert 38 <= blue_bri <= 76
    # Yellow (high luma) is damped below blue (low luma, clamped to 1.0). The
    # raised floor compresses the low end, so the gap is smaller than the old
    # [25,60] band gave — but the damping direction must still hold clearly.
    assert yellow_bri < blue_bri * 0.85, (
        f"luma comp not damping yellow enough: yellow={yellow_bri} blue={blue_bri}"
    )


@pytest.mark.asyncio
async def test_period_keyed_caps_take_precedence():
    """When a `period` is passed, MODE_MAX_BRIGHTNESS_PERIOD wins over the
    time-agnostic table. Stage-2 (2026-05-31) inverted the L5 relationship:
    gaming evening L5 cap = 95, ABOVE the day flat cap 60 — the accent should
    read more present in a dark room than in daylight (the L5 inversion fix)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Saturate pure deep-blue (low-luma → no comp damping). Day uses flat cap=75.
    for _ in range(20):
        await sync.apply_color("5", 0, 0, 255, mode="gaming", period="day")
    day_bri = hue.last_for("5")["bri"]

    # Evening uses the period-keyed cap=95.
    hue2 = _FakeHue()
    sync2 = ss.ScreenSyncService(hue_service=hue2, target_light_ids=["2", "5"])
    for _ in range(20):
        await sync2.apply_color("5", 0, 0, 255, mode="gaming", period="evening")
    evening_bri = hue2.last_for("5")["bri"]

    # The period table takes precedence: evening's 95 cap lands above the day
    # flat 75, proving the (mode, period, light) lookup wins.
    assert evening_bri > day_bri, (
        f"evening period cap (95) should exceed day flat cap (75) "
        f"(day={day_bri} evening={evening_bri})"
    )
    assert day_bri <= 75
    assert evening_bri <= 95


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


# -----------------------------------------------------------------------------
# Gaming-day ambient lift — lux × weather scaling on cap + floor
# -----------------------------------------------------------------------------


def test_scale_for_ambient_gaming_day_clouds_lifts_envelope():
    """Cloudy daytime gaming lifts L2's floor 130 → ~153 (1.07 lux × 1.10)."""
    out = ss.ScreenSyncService._scale_for_ambient(
        130, mode="gaming", period="day",
        lux_multiplier=1.07, weather_condition="clouds",
    )
    # 130 × 1.07 × 1.10 = 153.01 → int truncates to 153
    assert out == 153


def test_scale_for_ambient_watching_l2_now_lifts():
    """D4 task #7: watching L2 (fabric room-light) now tracks ambient too —
    the user wants the bedroom brighter when dark while watching, not just
    gaming. Bounded by the 1.40 combined ceiling."""
    out = ss.ScreenSyncService._scale_for_ambient(
        25, mode="watching", period="day",
        lux_multiplier=1.30, weather_condition="thunderstorm",
        light_id="2",
    )
    # watching-day thunderstorm = 1.10; 25 × min(1.40, 1.30 × 1.10 = 1.43) =
    # 25 × 1.40 = 35
    assert out == 35


def test_scale_for_ambient_evening_now_lifts():
    """D4 task #7: gaming evening L2 lifts — the gate is widened past day-only
    so the night-time room (when the user actually games) gets the top-up."""
    out = ss.ScreenSyncService._scale_for_ambient(
        150, mode="gaming", period="evening",
        lux_multiplier=1.20, weather_condition="rain",
        light_id="2",
    )
    # gaming-evening rain = 1.07; 150 × min(1.40, 1.20 × 1.07 = 1.284) =
    # 150 × 1.284 = 192.6 → 192
    assert out == 192


def test_scale_for_ambient_l5_excluded_from_lift():
    """L5's clear seeded-glass housing is a glare-prone point source, NOT a
    room-light lever — it is excluded from the ambient lift entirely and rides
    its static per-period caps regardless of mode/period/multiplier. This also
    closes the latent day-path gap (L5 day cap 75 × 1.40 = 105 > the 90 glare
    ceiling from build 4adce9f)."""
    for period in ("day", "evening", "night", "late_night"):
        out = ss.ScreenSyncService._scale_for_ambient(
            95, mode="gaming", period=period,
            lux_multiplier=1.30, weather_condition="thunderstorm",
            light_id="5",
        )
        assert out == 95, f"L5 must not be lifted (period={period})"


def test_scale_for_ambient_l2_ceiling_bounds_lift():
    """The 1.40 combined ceiling still bounds L2's lift so a dark-room storm
    can't run the fabric shade away (worst case lux 1.30 × weather 1.20)."""
    out = ss.ScreenSyncService._scale_for_ambient(
        150, mode="gaming", period="day",
        lux_multiplier=1.30, weather_condition="thunderstorm",
        light_id="2",
    )
    # 150 × min(1.40, 1.30 × 1.20 = 1.56) = 150 × 1.40 = 210
    assert out == 210


def test_scale_for_ambient_no_weather_uses_lux_only():
    """Clear weather (no FUNCTIONAL_WEATHER_BRIGHTNESS match) still applies lux."""
    out = ss.ScreenSyncService._scale_for_ambient(
        130, mode="gaming", period="day",
        lux_multiplier=1.20, weather_condition=None,
    )
    # 130 × 1.20 × 1.0 = 156
    assert out == 156


def test_get_floor_gaming_day_clouds_lifts_l2():
    """End-to-end check on the public get_floor entry point."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    floor = sync.get_floor(
        "gaming", "2", period="day",
        lux_multiplier=1.07, weather_condition="clouds",
    )
    # L2 gaming-day floor 130→150 (curator 6/02) × 1.07 lux × ~1.10 clouds.
    assert floor == 176


def test_get_cap_gaming_day_clouds_lifts_l2():
    """End-to-end check on get_cap — L2 cap 240 × 1.07 × 1.10 → clamped 254."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    cap = sync.get_cap(
        "gaming", "2", zone=None, posture=None, period="day",
        lux_multiplier=1.07, weather_condition="clouds",
    )
    # 240 × 1.07 × 1.10 = 282.5 → clamped to 254
    assert cap == 254


class _FakeEventLogger:
    """Records log_light_adjustment calls (syncfight-3 logging tests)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log_light_adjustment(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_screen_sync_logs_throttled_adjustment():
    """apply_color records ONE throttled light_adjustments row per light per
    interval, tagged trigger='screen_sync' with the applied values (closes
    syncfight-3); rapid repeats within the interval are throttled, and each
    light throttles independently."""
    import datetime as _dt

    hue = _FakeHue()
    elog = _FakeEventLogger()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    sync.set_event_logger(elog)

    # First synced write to L2 logs once, tagged screen_sync, with applied values.
    await sync.apply_color("2", 0, 0, 255, mode="gaming", period="evening")
    assert len(elog.calls) == 1
    row = elog.calls[0]
    assert row["light_id"] == "2"
    assert row["trigger"] == "screen_sync"
    assert row["mode_at_time"] == "gaming"
    assert "bri_after" in row and "hue_after" in row and "sat_after" in row

    # A rapid second write (within the interval) is throttled — still 1 row.
    await sync.apply_color("2", 0, 0, 255, mode="gaming", period="evening")
    assert len(elog.calls) == 1

    # L5 throttles independently → its first write logs (now 2 total).
    await sync.apply_color("5", 0, 0, 255, mode="gaming", period="evening")
    assert len(elog.calls) == 2
    assert elog.calls[1]["light_id"] == "5"

    # Backdate L2's throttle past the interval → the next L2 write logs again.
    sync._last_log_at["2"] = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
        seconds=ss.SCREEN_SYNC_LOG_INTERVAL_S + 1
    )
    await sync.apply_color("2", 0, 0, 255, mode="gaming", period="evening")
    assert len(elog.calls) == 3


@pytest.mark.asyncio
async def test_screen_sync_no_event_logger_is_safe():
    """With no event logger wired (default None), apply_color must still write
    the bridge and not error — keeps the laptop-loopback + unit-test paths working."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    # No set_event_logger call.
    await sync.apply_color("2", 0, 0, 255, mode="gaming", period="evening")
    assert hue.last_for("2")["bri"] > 0  # the bridge write still happened


@pytest.mark.asyncio
async def test_apply_rust_brightness_holds_ember_and_dims_when_dark():
    """Rust path holds the fixed ember color and maps luma → brightness.

    Pitch-black Rust (luma≈floor input) drops L2 to the period floor; a bright
    daytime scene lifts it toward the cap. Color stays ember regardless — the
    chaotic on-screen color is not synced.
    """
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])

    # Pitch-black night frame → night floor. EMA glides hue/sat/bri from the
    # 0 prior, so drive enough frames to converge (the glide itself is the
    # desired smooth handoff from the color path; steady state is exact ember).
    for _ in range(30):
        await sync.apply_rust_brightness("2", luma=5, period="night")
    dark = hue.last_for("2")
    assert abs(dark["hue"] - ss.RUST_EMBER_HUE) <= 5
    assert abs(dark["sat"] - ss.RUST_EMBER_SAT) <= 2
    assert abs(dark["bri"] - ss.RUST_BRI_ENVELOPE["2"]["night"][0]) <= 2, dark["bri"]

    # Bright daytime frame → day cap.
    for _ in range(30):
        await sync.apply_rust_brightness("2", luma=200, period="day")
    bright = hue.last_for("2")
    assert abs(bright["bri"] - ss.RUST_BRI_ENVELOPE["2"]["day"][1]) <= 2, bright["bri"]
    # Still ember — never the screen color.
    assert abs(bright["hue"] - ss.RUST_EMBER_HUE) <= 5


@pytest.mark.asyncio
async def test_apply_rust_brightness_l5_subordinate_to_l2():
    """L5 must dim WITH L2 and stay below it at the same luma/period — the
    fix for the static-L5-towers-over-dimming-L2 glare-pop (2026-06-08)."""
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    for period in ("day", "night", "late_night"):
        # Same bright scene to both lamps — converge each.
        for _ in range(30):
            await sync.apply_rust_brightness("2", luma=180, period=period)
            await sync.apply_rust_brightness("5", luma=180, period=period)
        assert hue.last_for("5")["bri"] < hue.last_for("2")["bri"], period
        # Same dark scene — L5 still ≤ L2 (both floor, L5's floor is lower).
        for _ in range(30):
            await sync.apply_rust_brightness("2", luma=4, period=period)
            await sync.apply_rust_brightness("5", luma=4, period=period)
        assert hue.last_for("5")["bri"] <= hue.last_for("2")["bri"], period


@pytest.mark.asyncio
async def test_apply_rust_brightness_unknown_light_is_noop():
    hue = _FakeHue()
    sync = ss.ScreenSyncService(hue_service=hue, target_light_ids=["2"])
    await sync.apply_rust_brightness("5", luma=100, period="day")  # 5 not a target
    assert hue.calls == []
