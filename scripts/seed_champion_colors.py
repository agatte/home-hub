"""One-shot seed for the ``champion_color_map`` app setting.

Populates the LoL Champion → RGB map consumed by ``LoLChampionService``.
Existing entries are preserved (this is an idempotent merge — already-
present champion names keep their stored color). New champions are added
with the curated baseline color below.

Run from the repo root:

    python -m scripts.seed_champion_colors

Hand-edit the colors via the home-hub MCP or directly via SQL once a
champion's color has been live-tested and the user wants to tune it.
"""
from __future__ import annotations

import asyncio

from backend.api.routes.routines import load_setting, save_setting
from backend.database import init_db
from backend.services.lol_champion_service import CHAMPION_COLOR_MAP_KEY

# Curated initial palette. Each champion's color leans on its signature
# aesthetic — splash art dominant hue, lore color, or fandom association.
# Tune in place after live testing; the service reads the map fresh on
# every champion change, so DB edits take effect immediately.
CURATED_COLORS: dict[str, dict[str, int]] = {
    "Ahri":     {"r": 255, "g": 105, "b": 180},  # Hot pink
    "Lux":      {"r": 255, "g": 220, "b":  90},  # Bright yellow
    "Yasuo":    {"r":  80, "g": 140, "b": 220},  # Wind blue
    "Zed":      {"r": 200, "g":  30, "b":  30},  # Red on black
    "Ezreal":   {"r":  90, "g": 200, "b": 230},  # Cyan
    "Jinx":     {"r": 180, "g":  80, "b": 200},  # Electric purple
    "Akali":    {"r":  90, "g": 180, "b": 130},  # Acid green
    "Thresh":   {"r":  90, "g": 220, "b": 140},  # Lantern green
    "Garen":    {"r": 240, "g": 220, "b": 120},  # Demacian gold
    "Darius":   {"r": 180, "g":  30, "b":  30},  # Noxian red
    "Vi":       {"r": 220, "g":  90, "b": 130},  # Pink-magenta
    "Caitlyn":  {"r": 180, "g": 110, "b": 180},  # Piltover pink-purple
    "Riven":    {"r":  90, "g": 130, "b": 240},  # Exile blue
    "Leona":    {"r": 240, "g": 180, "b":  60},  # Sun gold
    "Diana":    {"r": 180, "g": 200, "b": 240},  # Moon silver-blue
    "Sett":     {"r": 240, "g":  80, "b":  80},  # Warm red
    "Yuumi":    {"r": 240, "g": 200, "b": 240},  # Soft pastel pink
    "Senna":    {"r":  90, "g": 220, "b": 200},  # Shadow teal
    "Aphelios": {"r": 200, "g": 200, "b": 230},  # Moonstone white
    "Kai'Sa":   {"r": 180, "g": 100, "b": 220},  # Void purple
}


async def main() -> None:
    await init_db()

    existing = await load_setting(CHAMPION_COLOR_MAP_KEY)
    merged: dict[str, dict[str, int]] = {**CURATED_COLORS, **(existing or {})}
    # Existing entries win — user-tuned colors aren't clobbered on re-seed.

    new_count = sum(1 for name in CURATED_COLORS if name not in (existing or {}))
    await save_setting(CHAMPION_COLOR_MAP_KEY, merged)

    print(f"Seeded {CHAMPION_COLOR_MAP_KEY}:")
    print(f"  - {len(merged)} total champions in map")
    print(f"  - {new_count} added this run")
    print(f"  - {len(existing or {})} preserved from existing setting")


if __name__ == "__main__":
    asyncio.run(main())
