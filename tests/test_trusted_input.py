from backend.services.pc_agent.trusted_input import (
    RI_KEY_BREAK,
    RI_MOUSE_LEFT_BUTTON_DOWN,
    RI_MOUSE_WHEEL,
    WM_KEYDOWN,
    trusted_keyboard_event_is_intentional,
    trusted_mouse_flags_are_intentional,
    trusted_wake_device_label,
)


def test_keychron_k10_raw_input_device_is_trusted():
    assert (
        trusted_wake_device_label(
            r"\\?\HID#VID_05AC&PID_024F&MI_00#8&abc&0&0000"
        )
        == "keychron_k10"
    )


def test_wired_gaming_mouse_raw_input_device_is_trusted():
    assert (
        trusted_wake_device_label(
            r"\\?\HID#VID_258A&PID_0036&MI_00#8&abc&0&0000"
        )
        == "wired_gaming_mouse"
    )


def test_logitech_unifying_receiver_is_not_trusted_for_sleep_wake():
    assert (
        trusted_wake_device_label(
            r"\\?\HID#VID_046D&PID_C52B&MI_01#8&abc&0&0000"
        )
        is None
    )


def test_unknown_or_missing_device_is_not_trusted():
    assert trusted_wake_device_label(r"\\?\HID#VID_1234&PID_ABCD#x") is None
    assert trusted_wake_device_label(None) is None

def test_mouse_motion_without_button_or_wheel_is_not_intentional():
    assert trusted_mouse_flags_are_intentional(0) is False
    assert trusted_mouse_flags_are_intentional(RI_MOUSE_LEFT_BUTTON_DOWN) is True
    assert trusted_mouse_flags_are_intentional(RI_MOUSE_WHEEL) is True


def test_keyboard_key_down_counts_but_key_up_or_generic_packet_does_not():
    assert trusted_keyboard_event_is_intentional(
        flags=0, vkey=0x41, message=WM_KEYDOWN,
    ) is True
    assert trusted_keyboard_event_is_intentional(
        flags=RI_KEY_BREAK, vkey=0x41, message=WM_KEYDOWN,
    ) is False
    assert trusted_keyboard_event_is_intentional(
        flags=0, vkey=0, message=WM_KEYDOWN,
    ) is False
    assert trusted_keyboard_event_is_intentional(
        flags=0, vkey=0x41, message=0,
    ) is False
