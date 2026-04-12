"""
Weather service — fetches and caches current conditions from OpenWeatherMap.
"""
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.weather")

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
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
                    OWM_CURRENT_URL,
                    params={
                        "q": self._city,
                        "appid": self._api_key,
                        "units": "imperial",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                # Fetch 5-day/3-hour forecast for today's actual high/low.
                # The current weather endpoint's temp_min/temp_max are just
                # the current temperature — useless for daily range.
                day_high, day_low = await self._fetch_daily_range(client)

            weather = {
                "temp": round(data["main"]["temp"]),
                "feels_like": round(data["main"]["feels_like"]),
                "temp_min": day_low if day_low is not None else round(data["main"]["temp_min"]),
                "temp_max": day_high if day_high is not None else round(data["main"]["temp_max"]),
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
                f" (H:{weather['temp_max']}° L:{weather['temp_min']}°)"
            )
            return weather

        except Exception as e:
            logger.error(f"Weather fetch failed: {e}", exc_info=True)
            # Return stale cache if available
            if self._cache:
                return self._cache
            return None

    async def _fetch_daily_range(
        self, client: httpx.AsyncClient
    ) -> tuple[Optional[int], Optional[int]]:
        """
        Get today's actual high/low from the OWM 5-day/3-hour forecast.

        Scans all forecast entries for the current date (UTC-based date
        from the API's dt_txt field) and returns (high, low).
        """
        try:
            resp = await client.get(
                OWM_FORECAST_URL,
                params={
                    "q": self._city,
                    "appid": self._api_key,
                    "units": "imperial",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            from datetime import datetime, timezone

            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            temps = [
                entry["main"]["temp"]
                for entry in data.get("list", [])
                if entry.get("dt_txt", "").startswith(today_str)
            ]

            if not temps:
                return None, None

            return round(max(temps)), round(min(temps))

        except Exception as e:
            logger.warning(f"Forecast fetch failed (high/low unavailable): {e}")
            return None, None
