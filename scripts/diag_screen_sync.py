"""One-shot diagnostic for the screen-sync agent. Shows which monitor it's
capturing and what RGB it would POST right now (mirrored to all target lamps)."""
from backend.services.pc_agent.screen_sync_agent import capture_dominant_color
import mss

with mss.mss() as sct:
    print(f"Monitors detected: {len(sct.monitors) - 1}")
    for i, m in enumerate(sct.monitors):
        marker = " <- PRIMARY (agent samples this)" if i == 1 else ""
        print(f"  monitor[{i}]: {m}{marker}")

rgb = capture_dominant_color()
print()
if rgb is None:
    print("Agent capture returned None")
else:
    r, g, b = rgb
    print(f"Agent would POST right now: RGB=({r:3d},{g:3d},{b:3d})  hex=#{r:02x}{g:02x}{b:02x}")
    print("(mirrored to all sync.target_lights — currently L2 + L5)")
