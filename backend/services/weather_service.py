"""
Weather service — fetches and caches current conditions from OpenWeatherMap.
"""
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.weather")

OWM_URL = "https://api.openweathermap.org/data/2.5/weather"
CACHE_TTL = 600  # 10 minutes


class WeatherService:
    """Cached OpenWeatherMap weather data provider."""

    def __init__(self, api_key: str, city: str = "Indianapolis,US") -> None:
        self._api_key = api_key
        self._city = city
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: float = 0

    def get_cached(self) -> Optional[dict[str, Any]]:
        """Return the most recent cached weather data (sync, no fetch)."""
        return self._cache

    async def get_current(self) -> Optional[dict[str, Any]]:
        """
        Get current weather conditions.

        Returns cached data if fresh (< 10 min old). Otherwise fetches
        from OpenWeatherMap.

        Returns:
            Dict with temp, feels_like, description, humidity, wind_speed,
            icon, sunrise, sunset — or None on failure.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    OWM_URL,
                    params={
                        "q": self._city,
                        "appid": self._api_key,
                        "units": "imperial",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            weather = {
                "temp": round(data["main"]["temp"]),
                "feels_like": round(data["main"]["feels_like"]),
                "temp_min": round(data["main"]["temp_min"]),
                "temp_max": round(data["main"]["temp_max"]),
                "description": data["weather"][0]["description"],
                "icon": data["weather"][0]["icon"],
                "humidity": data["main"]["humidity"],
                "wind_speed": round(data["wind"]["speed"]),
                "sunrise": data["sys"]["sunrise"],
                "sunset": data["sys"]["sunset"],
                "city": data["name"],
            }

            self._cache = weather
            self._cache_time = now
            logger.info(
                f"Weather updated: {weather['temp']}°F, {weather['description']}"
            )
            return weather

        except Exception as e:
            logger.error(f"Weather fetch failed: {e}", exc_info=True)
            # Return stale cache if available
            if self._cache:
                return self._cache
            return None
