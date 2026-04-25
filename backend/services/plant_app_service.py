"""
Plant app integration — authenticates and polls plant status from the external plant care app.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("home_hub.plant_app")

CACHE_TTL = 600  # 10 minutes


class PlantAppService:
    """Polls the plant care app API for plant status data."""

    def __init__(
        self,
        api_url: str,
        email: str,
        password: str,
        allow_insecure: bool = False,
    ) -> None:
        # Reject plain http:// at construction. The login body carries
        # email + password as JSON; cleartext over LAN means anyone with
        # packet capture (a roommate's laptop, a compromised IoT device)
        # walks away with credentials that are very likely reused on
        # other services. Auto-upgrading http→https would silently fail
        # if the API doesn't speak TLS, so we hard-fail and force the
        # operator to either fix the URL or set the explicit escape
        # hatch — the choice has to be conscious.
        parsed = urlparse(api_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"PLANT_APP_API_URL has unsupported scheme {parsed.scheme!r}; "
                "expected https://"
            )
        if parsed.scheme == "http" and not allow_insecure:
            raise ValueError(
                "PLANT_APP_API_URL is http:// — credentials would be sent in "
                "cleartext. Use https:// or set PLANT_APP_ALLOW_INSECURE=1 "
                "to acknowledge the risk explicitly."
            )

        self._api_url = api_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: Optional[str] = None
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: float = 0
        self._insecure = parsed.scheme == "http"

    async def _login(self) -> bool:
        """Authenticate with the plant app and store JWT token."""
        if self._insecure:
            # Re-emit on every auth attempt so the insecure mode never
            # quietly drifts into "background normal."
            logger.warning(
                "Plant app authenticating over plain HTTP — credentials in "
                "cleartext (PLANT_APP_ALLOW_INSECURE=1)"
            )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._api_url}/api/auth/login",
                    json={"email": self._email, "password": self._password},
                )
                resp.raise_for_status()
                data = resp.json()
                self._token = data.get("token") or data.get("accessToken")
                if self._token:
                    logger.info("Plant app authenticated")
                    return True
                # Don't log the response body — it can contain echoed
                # input fields, internal IDs, or upstream error text.
                logger.error(
                    "Plant app login: response had no token (status=%d)",
                    resp.status_code,
                )
                return False
        except Exception as e:
            logger.error("Plant app login failed: %s", e)
            return False

    async def _fetch_plants(self) -> Optional[list[dict]]:
        """Fetch all plants from the plant app API."""
        if not self._token:
            if not await self._login():
                return None

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._api_url}/api/plants",
                    headers={"Authorization": f"Bearer {self._token}"},
                )

                # Token expired — re-login and retry once
                if resp.status_code == 401:
                    logger.info("Plant app token expired, re-authenticating")
                    if not await self._login():
                        return None
                    resp = await client.get(
                        f"{self._api_url}/api/plants",
                        headers={"Authorization": f"Bearer {self._token}"},
                    )

                resp.raise_for_status()
                data = resp.json()

                # Handle both paginated and non-paginated responses
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data

        except Exception as e:
            logger.error("Plant app fetch failed: %s", e)
            return None

    async def get_status(self) -> Optional[dict[str, Any]]:
        """
        Get aggregated plant status.

        Returns cached data if fresh (< 10 min old). Otherwise fetches
        from the plant app API.

        Returns:
            Dict with total, needs_water, overdue, next_watering, healthy,
            needs_attention — or None on failure.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        plants = await self._fetch_plants()
        if plants is None:
            if self._cache:
                return self._cache
            return None

        today = datetime.now(tz=timezone.utc).date()
        total = len(plants)
        needs_water = 0
        overdue = 0
        healthy = 0
        needs_attention = 0
        next_watering_date = None
        next_watering_plant = None

        for plant in plants:
            # Parse next watering date
            nwd_str = plant.get("nextWateringDate")
            if nwd_str:
                try:
                    nwd = datetime.fromisoformat(nwd_str.replace("Z", "+00:00")).date()
                    if nwd <= today:
                        needs_water += 1
                    if nwd < today:
                        overdue += 1
                    if next_watering_date is None or nwd < next_watering_date:
                        next_watering_date = nwd
                        next_watering_plant = plant.get("name", "Unknown")
                except (ValueError, TypeError):
                    pass

            # Health status from latest health check
            health_checks = plant.get("healthChecks", [])
            if health_checks:
                latest = health_checks[0] if isinstance(health_checks, list) else None
                if latest:
                    status = latest.get("status", "")
                    if status == "Healthy":
                        healthy += 1
                    elif status in ("Needs Attention", "Critical"):
                        needs_attention += 1

        # Format next watering
        next_watering = None
        if next_watering_date and next_watering_plant:
            diff = (next_watering_date - today).days
            if diff < 0:
                next_watering = {"plant": next_watering_plant, "label": f"{abs(diff)}d overdue"}
            elif diff == 0:
                next_watering = {"plant": next_watering_plant, "label": "today"}
            elif diff == 1:
                next_watering = {"plant": next_watering_plant, "label": "tomorrow"}
            else:
                next_watering = {"plant": next_watering_plant, "label": f"in {diff} days"}

        summary = {
            "total": total,
            "needs_water": needs_water,
            "overdue": overdue,
            "healthy": healthy,
            "needs_attention": needs_attention,
            "next_watering": next_watering,
        }

        self._cache = summary
        self._cache_time = now
        logger.info(
            "Plant status updated: %d total, %d need water, %d overdue",
            total, needs_water, overdue,
        )
        return summary
