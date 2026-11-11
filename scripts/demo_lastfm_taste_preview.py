"""Print only fictional offline ranking evidence; no arguments or account access."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.lastfm_taste_preview import demo

if __name__ == "__main__":
    print(json.dumps(asyncio.run(demo()), indent=2, sort_keys=True))
