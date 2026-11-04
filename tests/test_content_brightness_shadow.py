"""Synthetic only: no capture, backend, or device calls."""
import numpy as np
import pytest

from backend.services.pc_agent.content_brightness_shadow import ContentSignal, propose
from backend.services.pc_agent import screen_sync_agent as screen


def frame(color=255):
    return np.full((30, 50, 3), color, dtype=np.uint8)


def sustained(pixels=None, media=False):
    box = ContentSignal()
    for t in (10, 12.5, 15, 17.5):
        box.publish(frame() if pixels is None else pixels, media, t, t + 100)
    return box


def candidate(s, **overrides):
    args = dict(mode="working", period="late_night", shipped_target=15,
                samsung_vcp_max=50, mapping_accepted=True, media_trustworthy=True,
                manual_override=False)
    args.update(overrides)
    return propose(s, **args)


def test_white_text_accent_native_mapping():
    pixels = frame()
    pixels[:4] = 15
    pixels[4] = [0, 80, 255]
    s = sustained(pixels).snapshot(17.5, 117.5)
    assert s.white_share > .7
    assert candidate(s).percent == 2
    assert candidate(s).native == 1
    assert 1 / 50 * 100 == 2


@pytest.mark.parametrize("color", [0, 30, 128, 200, [255, 255, 0]])
def test_nonwhite_content(color):
    s = sustained(frame(color)).snapshot(17.5, 117.5)
    assert not s.sustained
    assert candidate(s).percent == 15


@pytest.mark.parametrize("media", [True, None])
def test_white_video(media):
    s = sustained(media=media).snapshot(17.5, 117.5)
    assert candidate(s).percent == 15


@pytest.mark.parametrize("kwargs", [dict(mode="gaming"), dict(mode="sleeping"),
    dict(period="day"), dict(manual_override=True), dict(mapping_accepted=False),
    dict(media_trustworthy=False), dict(samsung_vcp_max=100)])
def test_policy_gates(kwargs):
    s = sustained().snapshot(17.5, 117.5)
    assert candidate(s, **kwargs).percent == 15


def test_missing_stale_clock_and_recovery():
    assert candidate(None).percent == 15
    for now, wall in [(24, 124), (16, 116), (18, 200)]:
        box = sustained()
        assert box.snapshot(now, wall) is None
        box.publish(frame(), False, now + 2.5, wall + 2.5)
        assert not box.snapshot(now + 2.5, wall + 2.5).sustained


def test_flash_release_and_gap():
    box = ContentSignal()
    box.publish(frame(), False, 10, 110)
    assert not box.snapshot(10, 110).sustained
    box = sustained()
    for t in (20, 22.5):
        box.publish(frame(20), False, t, t + 100)
        assert box.snapshot(t, t + 100).sustained
    box.publish(frame(20), False, 25, 125)
    assert not box.snapshot(25, 125).sustained
    box = sustained()
    box.publish(frame(), False, 40, 140)
    assert not box.snapshot(40, 140).sustained


def test_shadow_reuses_capture_and_preserves_payload(monkeypatch):
    monkeypatch.setattr(screen, "_foreground_media_active", lambda: False)
    monkeypatch.setattr(screen.time, "monotonic", lambda: 10)
    monkeypatch.setattr(screen.time, "time", lambda: 110)
    box = ContentSignal()
    payload = screen._build_color_payload((1, 2, 3), 17)
    screen._publish_content_shadow(frame(), payload["foreground_media"], box)
    assert payload == {"source": "desktop", "r": 1, "g": 2, "b": 3,
                       "luma": 17, "foreground_media": False}
    assert box.snapshot(10, 110).white_share == 1
    assert ContentSignal().snapshot(10, 110) is None
    assert not hasattr(box.snapshot(10, 110), "pixels")


def test_delayed_processing_does_not_refresh_capture_age():
    box = ContentSignal()
    screen._publish_content_shadow(frame(), False, box, 10, 110)
    assert box.snapshot(20, 120) is None


def test_media_interrupt_requires_full_new_dwell():
    box = sustained()
    box.publish(frame(), None, 20, 120)
    assert not box.snapshot(20, 120).sustained
    for t in (22.5, 25, 27.5):
        box.publish(frame(), False, t, t + 100)
        assert not box.snapshot(t, t + 100).sustained
    box.publish(frame(), False, 30, 130)
    assert box.snapshot(30, 130).sustained


def test_capture_clock_divergence_resets_without_consumer_poll():
    box = sustained()
    box.publish(frame(), False, 20, 900)
    assert not box.snapshot(20, 900).sustained


@pytest.mark.parametrize("pixels", [[], [[255, 255]], "bad", None,
                                    [[float("nan"), 255, 255]], [[256, 255, 255]]])
def test_invalid_pixels_discard_positive_immediately(pixels):
    box = sustained()
    box.publish(pixels, False, 20, 120)
    assert box.snapshot(20, 120) is None
    box.publish(frame(), False, 22.5, 122.5)
    assert not box.snapshot(22.5, 122.5).sustained


@pytest.mark.parametrize("now,wall", [(float("nan"), 120), (20, float("inf"))])
def test_invalid_capture_clocks_discard_positive(now, wall):
    box = sustained()
    box.publish(frame(), False, now, wall)
    assert box.snapshot(20, 120) is None


def test_shadow_processing_failure_invalidates():
    box = sustained()
    screen._publish_content_shadow(None, False, box, 20, 120)
    assert box.snapshot(20, 120) is None


def test_manual_ownership_unknown_is_closed():
    signal = sustained().snapshot(17.5, 117.5)
    assert candidate(signal, manual_override=None).reason == "manual-ownership-unknown"
    assert propose(signal, mode="working", period="late_night",
                   shipped_target=15, samsung_vcp_max=50,
                   mapping_accepted=True, media_trustworthy=True).reason == (
                       "manual-ownership-unknown"
                   )


def test_scalar_info_transition_rate_limit_and_closed_authority(caplog):
    import logging
    from backend.services.pc_agent.content_brightness_shadow import ShadowObserver

    observer = ShadowObserver()
    logger = logging.getLogger("shadow-test")
    signal = sustained().snapshot(17.5, 117.5)
    with caplog.at_level(logging.INFO, logger="shadow-test"):
        for now, sample in [(20, signal), (21, signal), (22, None),
                            (50, None), (80, signal)]:
            observer.observe(sample, now=now, mode="working", period="late_night",
                             shipped_target=15, logger=logger)
    assert len(caplog.records) == 3
    assert "visual_hypothesis_percent=2 retained_percent=15" in caplog.records[0].message
    for record in caplog.records:
        assert "manual_ownership=unknown" in record.message
        assert "mapping_accepted=False media_trustworthy=False native_range_accepted=False" in record.message
        assert "actuation=False" in record.message


@pytest.mark.parametrize("failure", ["missing", "exception", "invalid-color"])
def test_capture_loop_invalidates_without_network_or_hardware(monkeypatch, failure):
    import threading
    from types import SimpleNamespace

    box = sustained()
    stop = threading.Event()
    monkeypatch.setattr(screen.time, "monotonic", lambda: 20)
    monkeypatch.setattr(screen.time, "time", lambda: 120)
    monkeypatch.setattr(screen.httpx, "Client",
                        lambda **kwargs: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(screen.mss, "mss",
                        lambda: SimpleNamespace(close=lambda: None))

    def grab(_):
        stop.set()
        if failure == "exception":
            raise ValueError("synthetic failed capture")
        return frame() if failure == "invalid-color" else None

    monkeypatch.setattr(screen, "_grab_array", grab)
    monkeypatch.setattr(screen, "_color_luma_from_array", lambda _: None)
    screen.run_agent("http://unused.invalid", stop_event=stop, content_signal=box)
    assert box.snapshot(20, 120) is None
