"""OpenRGB diagnostic probe for the desk peripherals.

Modes:
  (default)  read-only dump of modes / active mode / cached colors
  --flash    drive the KEYBOARD bright magenta for ~12s (re-writing)
  --diag     two-phase test to isolate whether the Keychron needs a
             set_mode to physically redraw, or whether a bare set_color
             is enough:
               Phase 1 (~7s): set_mode(Custom) + RED, re-issued each tick
               Phase 2 (~7s): set_color GREEN only (no set_mode)
             If the board shows RED in phase 1 but does NOT turn GREEN in
             phase 2, the firmware only redraws on set_mode.

Run on the desktop (project venv):
  venv\\Scripts\\python.exe -m scripts.probe_openrgb_keyboard [--flash|--diag]
"""
from __future__ import annotations

import sys
import time

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, ModeColors, RGBColor

HOST, PORT = "127.0.0.1", 6742


def _dump(targets) -> None:
    for d in targets:
        print(f"\n=== {d.name}  (type={d.type.name}) ===")
        active_idx = d.active_mode
        for i, m in enumerate(d.modes):
            try:
                cm = m.color_mode.name if isinstance(m.color_mode, ModeColors) else str(m.color_mode)
            except Exception:
                cm = repr(getattr(m, "color_mode", "?"))
            marker = " <-- ACTIVE" if i == active_idx else ""
            print(f"  mode[{i}] {m.name!r:24} color_mode={cm}{marker}")
        print(f"  leds: {len(d.leds)}  colors(cached, first 3): "
              f"{[(c.red, c.green, c.blue) for c in d.colors[:3]]}")


def _custom_name(kb) -> str | None:
    by_lower = {m.name.lower(): m.name for m in kb.modes}
    return by_lower.get("custom")


def _flash(targets) -> None:
    kb = next((d for d in targets if d.type == DeviceType.KEYBOARD), None)
    if kb is None:
        print("No keyboard detected.")
        return
    cm = _custom_name(kb)
    if cm:
        kb.set_mode(cm)
        print(f"set keyboard mode -> {cm}")
    magenta = RGBColor(255, 0, 255)
    print("Driving keyboard bright magenta for ~12s — WATCH THE KEYBOARD...")
    end = time.time() + 12.0
    n = 0
    while time.time() < end:
        kb.set_color(magenta)
        n += 1
        time.sleep(0.4)
    print(f"done ({n} writes).")


def _diag(targets) -> None:
    kb = next((d for d in targets if d.type == DeviceType.KEYBOARD), None)
    if kb is None:
        print("No keyboard detected.")
        return
    cm = _custom_name(kb)
    red, green = RGBColor(255, 0, 0), RGBColor(0, 255, 0)

    print(">>> PHASE 1 (~7s): set_mode(Custom)+RED each tick — WATCH KEYBOARD")
    end = time.time() + 7.0
    while time.time() < end:
        if cm:
            kb.set_mode(cm)
        kb.set_color(red)
        time.sleep(0.5)

    print(">>> PHASE 2 (~7s): set_color(GREEN) only, NO set_mode — WATCH KEYBOARD")
    end = time.time() + 7.0
    while time.time() < end:
        kb.set_color(green)
        time.sleep(0.5)

    print("done. Report: did it show RED in phase 1? did it turn GREEN in phase 2?")


def main() -> int:
    client = OpenRGBClient(HOST, PORT, name="homehub-probe")
    targets = [
        d for d in client.devices
        if d.type in (DeviceType.MOUSE, DeviceType.KEYBOARD)
    ]
    if not targets:
        print("No mouse/keyboard detected by OpenRGB SDK.")
        return 1

    if "--flash" in sys.argv:
        _flash(targets)
    elif "--diag" in sys.argv:
        _diag(targets)
    else:
        _dump(targets)

    client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
