from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.pc_agent import monitor_brightness as mb


class _FakeVCP:
    def __init__(self, *, current: int = 29, maximum: int = 50, raw_caps: str = "") -> None:
        self.current = current
        self.maximum = maximum
        self.raw_caps = raw_caps

    def get_vcp_feature(self, code: int):
        assert code == 0x10
        return self.current, self.maximum

    def get_vcp_capabilities(self) -> str:
        return self.raw_caps




class _FakeGainVCP:
    def __init__(self, *, fail_once_code: int | None = None) -> None:
        self.values = {0x16: [50, 100], 0x18: [50, 100], 0x1A: [50, 100]}
        self.fail_once_code = fail_once_code
        self.set_calls: list[tuple[int, int]] = []

    def get_vcp_feature(self, code: int):
        current, maximum = self.values[code]
        return current, maximum

    def set_vcp_feature(self, code: int, value: int) -> None:
        self.set_calls.append((code, value))
        if self.fail_once_code == code:
            self.fail_once_code = None
            raise RuntimeError("synthetic gain write failure")
        self.values[code][0] = value

    def get_vcp_capabilities(self) -> str:
        return ""


class _FakeMonitor:
    def __init__(self, *, structured_caps=None, structured_error=None, vcp=None) -> None:
        self.structured_caps = structured_caps or {}
        self.structured_error = structured_error
        self.vcp = vcp or _FakeVCP()
        self.set_presets: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_vcp_capabilities(self):
        if self.structured_error is not None:
            raise self.structured_error
        return self.structured_caps

    def set_color_preset(self, preset) -> None:
        self.set_presets.append(preset)


class _FakeSBC:
    def __init__(self, raw: int = 29, *, apply_write: bool = True) -> None:
        self.raw = raw
        self.apply_write = apply_write
        self.set_calls: list[tuple[int, int | None]] = []
        self.get_calls: list[int | None] = []

    def get_brightness(self, display=None):
        self.get_calls.append(display)
        return [self.raw]

    def set_brightness(self, value, display=None) -> None:
        self.set_calls.append((value, display))
        if self.apply_write:
            self.raw = value


def _reset_caches(monkeypatch) -> None:
    monkeypatch.setattr(mb, "_PRIMARY_LUMINANCE_MAX", None)
    monkeypatch.setattr(mb, "_SUPPORTED_COLOR_PRESETS", None)


def test_brightness_scale_helpers_support_non_100_vcp_range():
    assert mb._raw_to_percent(29, 50) == 58
    assert mb._percent_to_raw(80, 50) == 40
    assert mb._percent_to_raw(100, 50) == 50
    assert mb._percent_to_raw(0, 50) == 0


def test_primary_luminance_max_reads_and_caches_monitor_vcp(monkeypatch):
    monitor = _FakeMonitor(vcp=_FakeVCP(current=29, maximum=50))
    fake_mc = SimpleNamespace(get_monitors=lambda: [monitor])
    _reset_caches(monkeypatch)
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(mb, "monitorcontrol", fake_mc)

    assert mb._primary_luminance_max() == 50
    monitor.vcp.maximum = 80
    assert mb._primary_luminance_max() == 50


def test_get_current_brightness_returns_normalized_percent(monkeypatch):
    fake_sbc = _FakeSBC(raw=29)
    monkeypatch.setattr(mb, "_HAS_SBC", True)
    monkeypatch.setattr(mb, "sbc", fake_sbc)
    monkeypatch.setattr(mb, "_PRIMARY_LUMINANCE_MAX", 50)

    assert mb.get_current_brightness() == 58
    assert fake_sbc.get_calls == [mb.PRIMARY_DISPLAY_INDEX]


def test_set_brightness_scales_to_native_range_and_verifies(monkeypatch):
    fake_sbc = _FakeSBC(raw=29, apply_write=True)
    monkeypatch.setattr(mb, "_HAS_SBC", True)
    monkeypatch.setattr(mb, "sbc", fake_sbc)
    monkeypatch.setattr(mb, "_PRIMARY_LUMINANCE_MAX", 50)

    assert mb.set_brightness(80) is True
    assert fake_sbc.set_calls == [(40, mb.PRIMARY_DISPLAY_INDEX)]
    assert fake_sbc.raw == 40


def test_set_brightness_returns_false_when_monitor_ignores_write(monkeypatch):
    fake_sbc = _FakeSBC(raw=29, apply_write=False)
    monkeypatch.setattr(mb, "_HAS_SBC", True)
    monkeypatch.setattr(mb, "sbc", fake_sbc)
    monkeypatch.setattr(mb, "_PRIMARY_LUMINANCE_MAX", 50)
    monkeypatch.setattr(mb, "BRIGHTNESS_VERIFY_DELAY_S", 0.0)

    assert mb.set_brightness(80) is False
    assert fake_sbc.set_calls == [(40, mb.PRIMARY_DISPLAY_INDEX)]
    assert len(fake_sbc.get_calls) == mb.BRIGHTNESS_VERIFY_ATTEMPTS


def test_failed_brightness_write_is_not_claimed_by_reconciler(monkeypatch):
    reconciler = mb.Reconciler()
    monkeypatch.setattr(mb, "get_current_brightness", lambda: 58)
    monkeypatch.setattr(mb, "set_brightness", lambda _target: False)
    monkeypatch.setattr(mb, "set_color_preset", lambda _period: False)
    monkeypatch.setattr(mb.time, "time", lambda: 100.0)

    reconciler.reconcile("watching", "day", None, None)

    assert reconciler._last_applied_brightness is None
    assert reconciler._manual_override_until == 0.0


def test_parse_samsung_raw_capability_color_presets():
    if mb.ColorPreset is None:
        pytest.skip("monitorcontrol not installed")
    raw = (
        "(prot(monitor)type(lcd)model(LEMON25)"
        "vcp(02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60(11 0F ) "
        "62 87 8D CC mswhql(1)mccs_ver(2.0)))"
    )

    assert mb._parse_color_presets_from_raw_capabilities(raw) == [
        mb.ColorPreset.COLOR_TEMP_6500K,
        mb.ColorPreset.COLOR_TEMP_9300K,
        mb.ColorPreset.COLOR_TEMP_USER1,
        mb.ColorPreset.COLOR_TEMP_USER2,
    ]


def test_supported_color_presets_falls_back_to_raw_vendor_caps(monkeypatch):
    if mb.ColorPreset is None:
        pytest.skip("monitorcontrol not installed")
    raw = "(vcp(10 12 14(05 08 0B 0C) mswhql(1)))"
    monitor = _FakeMonitor(
        structured_error=ValueError("invalid literal for int() with base 16: 'mswhql'"),
        vcp=_FakeVCP(raw_caps=raw),
    )
    _reset_caches(monkeypatch)
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(mb, "monitorcontrol", SimpleNamespace(get_monitors=lambda: [monitor]))

    assert mb._supported_color_presets() == [
        mb.ColorPreset.COLOR_TEMP_6500K,
        mb.ColorPreset.COLOR_TEMP_9300K,
        mb.ColorPreset.COLOR_TEMP_USER1,
        mb.ColorPreset.COLOR_TEMP_USER2,
    ]


def test_5000k_does_not_silently_fall_back_to_6500k(monkeypatch):
    if mb.ColorPreset is None:
        pytest.skip("monitorcontrol not installed")
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(
        mb,
        "_supported_color_presets",
        lambda: [
            mb.ColorPreset.COLOR_TEMP_6500K,
            mb.ColorPreset.COLOR_TEMP_9300K,
            mb.ColorPreset.COLOR_TEMP_USER1,
            mb.ColorPreset.COLOR_TEMP_USER2,
        ],
    )

    assert mb._resolve_preset("COLOR_TEMP_6500K") == mb.ColorPreset.COLOR_TEMP_6500K
    assert mb._resolve_preset("COLOR_TEMP_5000K") is None


def test_set_color_preset_targets_primary_monitor_only(monkeypatch):
    if mb.ColorPreset is None:
        pytest.skip("monitorcontrol not installed")
    primary = _FakeMonitor()
    secondary = _FakeMonitor()
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(
        mb, "monitorcontrol", SimpleNamespace(get_monitors=lambda: [primary, secondary])
    )
    monkeypatch.setattr(
        mb, "_resolve_preset", lambda _name: mb.ColorPreset.COLOR_TEMP_6500K
    )

    assert mb.set_color_preset("day") is True
    assert primary.set_presets == [mb.ColorPreset.COLOR_TEMP_6500K]
    assert secondary.set_presets == []


def test_failed_color_attempt_stays_unapplied_and_does_not_hammer(monkeypatch):
    calls: list[str] = []
    reconciler = mb.Reconciler()
    monkeypatch.setattr(
        mb, "set_color_temperature", lambda period: calls.append(period) or False
    )

    reconciler._maybe_apply_color_temperature("night")
    reconciler._maybe_apply_color_temperature("night")

    assert calls == ["night"]
    assert reconciler._last_attempted_period_for_color == "night"
    assert reconciler._last_applied_period_for_color is None


def test_successful_color_attempt_marks_applied(monkeypatch):
    reconciler = mb.Reconciler()
    monkeypatch.setattr(mb, "set_color_temperature", lambda _period: True)

    reconciler._maybe_apply_color_temperature("day")

    assert reconciler._last_attempted_period_for_color == "day"
    assert reconciler._last_applied_period_for_color == "day"


def test_visual_comfort_curve_is_time_dominant_and_activity_bounded():
    assert mb.resolve_target("idle", "day", None, None) == 60
    assert mb.resolve_target("general", "evening", None, None) == 45
    assert mb.resolve_target("working", "night", None, None) == 35
    assert mb.resolve_target("watching", "night", None, None) == 25
    assert mb.resolve_target("working", "late_night", None, None) == 25
    assert mb.resolve_target("watching", "late_night", None, None) == 15
    assert mb.resolve_target("sleeping", "day", None, None) == 5
    for period in ("day", "evening", "night", "late_night"):
        values = [
            mb.resolve_target(mode, period, None, None)
            for mode in ("idle", "general", "working", "gaming", "watching", "relax", "social")
        ]
        assert max(values) - min(values) <= 10


def test_visual_comfort_curve_lux_only_nudges_within_ten_percent():
    assert mb.resolve_target("idle", "day", 200.0, 100.0) == 66
    assert mb.resolve_target("idle", "day", 0.0, 100.0) == 54


def test_rgb_gain_warmth_applies_and_verifies_primary_monitor(monkeypatch):
    vcp = _FakeGainVCP()
    monitor = _FakeMonitor(vcp=vcp)
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(mb, "monitorcontrol", SimpleNamespace(get_monitors=lambda: [monitor]))

    assert mb.set_rgb_gain_warmth("evening") is True
    assert vcp.values[0x16][0] == 50
    assert vcp.values[0x18][0] == 47
    assert vcp.values[0x1A][0] == 43


def test_rgb_gain_partial_failure_rolls_back(monkeypatch):
    vcp = _FakeGainVCP(fail_once_code=0x18)
    monitor = _FakeMonitor(vcp=vcp)
    monkeypatch.setattr(mb, "_HAS_MC", True)
    monkeypatch.setattr(mb, "monitorcontrol", SimpleNamespace(get_monitors=lambda: [monitor]))

    assert mb.set_rgb_gain_warmth("night") is False
    assert {code: values[0] for code, values in vcp.values.items()} == {
        0x16: 50, 0x18: 50, 0x1A: 50,
    }


def test_color_temperature_prefers_rgb_gain_path(monkeypatch):
    monkeypatch.setattr(mb, "_read_primary_rgb_gains", lambda: {
        "red": (50, 100), "green": (50, 100), "blue": (50, 100),
    })
    calls: list[str] = []
    monkeypatch.setattr(mb, "set_rgb_gain_warmth", lambda period: calls.append(period) or True)
    monkeypatch.setattr(mb, "set_color_preset", lambda _period: (_ for _ in ()).throw(AssertionError("preset fallback used")))

    assert mb.set_color_temperature("late_night") is True
    assert calls == ["late_night"]
