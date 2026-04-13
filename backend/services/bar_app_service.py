"""
Bar app integration — polls bar status from the Home Bar app on the LAN.
"""
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.bar_app")

CACHE_TTL = 600  # 10 minutes


class BarAppService:
    """Polls the Home Bar app API for inventory and party status."""

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: float = 0

    async def get_status(self) -> Optional[dict[str, Any]]:
        """Get bar status summary.

        Returns cached data if fresh (< 10 min old). Otherwise fetches
        from the bar app /api/status endpoint.

        Returns dict with total_bottles, makeable_count, party_mode, etc.
        or None on failure.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._api_url}/api/status")
                resp.raise_for_status()
                data = resp.json()

                summary = data.get("bar_summary")
                if summary:
                    self._cache = summary
                    self._cache_time = now
                    logger.info(
                        "Bar status updated: %d bottles, %d makeable, party=%s",
                        summary.get("total_bottles", 0),
                        summary.get("makeable_count", 0),
                        summary.get("party_mode", False),
                    )
                    return summary

                return None

        except Exception as e:
            logger.warning("Bar app fetch failed: %s", e)
            if self._cache:
                return self._cache
            return None
