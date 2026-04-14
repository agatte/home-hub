"""
Weather service — fetches and caches current conditions from the NWS API.

Uses api.weather.gov (National Weather Service) for current observations,
daily forecasts, and active severe weather alerts. No API key required.
Replaces the previous OpenWeatherMap integration for better real-time
storm detection and free severe weather alerts.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("home_hub.weather")

# Indianapolis coordinates
LAT, LON = 39.7684, -86.1581
# NWS grid info (static — never changes for a location)
NWS_OFFICE = "IND"
NWS_GRID_X, NWS_GRID_Y = 58, 69
# Nearest observation station (Indianapolis International Airport)
NWS_STATION = "KIND"

NWS_BASE = "https://api.weather.gov"
NWS_OBSERVATIONS_URL = f"{NWS_BASE}/stations/{NWS_STATION}/observations/latest"
NWS_FORECAST_URL = f"{NWS_BASE}/gridpoints/{NWS_OFFICE}/{NWS_GRID_X},{NWS_GRID_Y}/forecast"
NWS_ALERTS_URL = f"{NWS_BASE}/alerts/active"
NWS_HEADERS = {
    "User-Agent": "HomeHub/1.0 (anthonygatte@gmail.com)",
    "Accept": "application/geo+json",
}

CACHE_TTL = 300  # 5 minutes (down from 10 — NWS is free, no rate concern)
ALERT_CACHE_TTL = 120  # 2 minutes for alerts (storms move fast)

TZ = ZoneInfo("America/Indiana/Indianapolis")

# Map NWS textDescription → OWM-style icon codes for frontend compatibility.
# The WeatherCard uses these codes to pick SVG icon paths.
_NWS_TO_OWM_ICON: list[tuple[str, str, str]] = [
    # (keyword in textDescription, day icon, night icon)
    ("thunder", "11d", "11n"),
    ("tornado", "11d", "11n"),
    ("hurricane", "11d", "11n"),
    ("snow", "13d", "13n"),
    ("sleet", "13d", "13n"),
    ("ice", "13d", "13n"),
    ("freezing rain", "13d", "13n"),
    ("drizzle", "09d", "09n"),
    ("rain", "10d", "10n"),
    ("shower", "09d", "09n"),
    ("fog", "50d", "50n"),
    ("mist", "50d", "50n"),
    ("haze", "50d", "50n"),
    ("smoke", "50d", "50n"),
    ("overcast", "04d", "04n"),
    ("cloudy", "03d", "03n"),
    ("mostly cloudy", "04d", "04n"),
    ("partly cloudy", "02d", "02n"),
    ("partly sunny", "02d", "02n"),
    ("mostly sunny", "02d", "02n"),
    ("mostly clear", "02d", "02n"),
    ("few clouds", "02d", "02n"),
    ("fair", "01d", "01n"),
    ("sunny", "01d", "01n"),
    ("clear", "01d", "01n"),
]

# NWS alert event strings that indicate severe weather conditions.
# Used to override the observation description when alerts are active.
_ALERT_WEATHER_MAP: dict[str, str] = {
    "Tornado Warning": "thunderstorm",
    "Tornado Watch": "thunderstorm",
    "Severe Thunderstorm Warning": "thunderstorm",
    "Severe Thunderstorm Watch": "thunderstorm",
    "Flash Flood Warning": "rain",
    "Flood Warning": "rain",
    "Winter Storm Warning": "snow",
    "Blizzard Warning": "snow",
    "Ice Storm Warning": "snow",
}


def _c_to_f(celsius: float | None) -> int | None:
    """Convert Celsius to Fahrenheit, returning None for None input."""
    if celsius is None:
        return None
    return round(celsius * 9 / 5 + 32)


def _kmh_to_mph(kmh: float | None) -> int | None:
    """Convert km/h to mph, returning None for None input."""
    if kmh is None:
        return None
    return round(kmh * 0.621371)


def _compute_feels_like(
    temp_f: int, humidity: float | None, wind_mph: int | None,
) -> int:
    """Compute feels-like temperature from heat index or wind chill."""
    if temp_f >= 80 and humidity is not None:
        # Rothfusz heat index regression
        hi = (
            -42.379
            + 2.04901523 * temp_f
            + 10.14333127 * humidity
            - 0.22475541 * temp_f * humidity
            - 0.00683783 * temp_f ** 2
            - 0.05481717 * humidity ** 2
            + 0.00122874 * temp_f ** 2 * humidity
            + 0.00085282 * temp_f * humidity ** 2
            - 0.00000199 * temp_f ** 2 * humidity ** 2
        )
        return round(hi)
    if temp_f <= 50 and wind_mph is not None and wind_mph > 3:
        # NWS wind chill formula
        wc = (
            35.74
            + 0.6215 * temp_f
            - 35.75 * wind_mph ** 0.16
            + 0.4275 * temp_f * wind_mph ** 0.16
        )
        return round(wc)
    return temp_f


def _nws_icon_code(description: str, is_daytime: bool) -> str:
    """Map NWS text description to an OWM-compatible icon code."""
    desc_lower = description.lower()
    for keyword, day_icon, night_icon in _NWS_TO_OWM_ICON:
        if keyword in desc_lower:
            return day_icon if is_daytime else night_icon
    return "03d" if is_daytime else "03n"


class WeatherService:
    """Cached NWS weather data provider with severe weather alerts."""

    def __init__(self) -> None:
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: float = 0
        self._alert_cache: Optional[list[dict[str, Any]]] = None
        self._alert_cache_time: float = 0
        # Sunrise/sunset from forecast (refreshed with forecast)
        self._sunrise: Optional[int] = None
        self._sunset: Optional[int] = None

    def get_cached(self) -> Optional[dict[str, Any]]:
        """Return the most recent cached weather data (sync, no fetch)."""
        return self._cache

    def get_cached_alerts(self) -> list[dict[str, Any]]:
        """Return cached active weather alerts."""
        return self._alert_cache or []

    async def get_current(self) -> Optional[dict[str, Any]]:
        """Get current weather conditions.

        Returns cached data if fresh (< 5 min old). Otherwise fetches
        from the NWS API. Returns the same dict shape as the old OWM
        service for backward compatibility.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        try:
            async with httpx.AsyncClient(
                timeout=10.0, headers=NWS_HEADERS,
            ) as client:
                obs = await self._fetch_observations(client)
                if not obs:
                    return self._cache  # Return stale on failure

                # Fetch forecast for high/low (less frequent, piggyback)
                day_high, day_low = await self._fetch_daily_range(client)

                # Fetch alerts on a faster cadence
                await self._fetch_alerts(client)

            weather = self._build_weather_dict(obs, day_high, day_low)
            self._cache = weather
            self._cache_time = now
            logger.info(
                "Weather updated: %d°F, %s (H:%s° L:%s°)",
                weather["temp"],
                weather["description"],
                weather.get("temp_max", "?"),
                weather.get("temp_min", "?"),
            )
            return weather

        except Exception as e:
            logger.error("Weather fetch failed: %s", e, exc_info=True)
            if self._cache:
                return self._cache
            return None

    async def refresh_alerts(self) -> list[dict[str, Any]]:
        """Fetch alerts independently (for faster polling in automation loop)."""
        now = time.time()
        if self._alert_cache is not None and (now - self._alert_cache_time) < ALERT_CACHE_TTL:
            return self._alert_cache

        try:
            async with httpx.AsyncClient(
                timeout=10.0, headers=NWS_HEADERS,
            ) as client:
                await self._fetch_alerts(client)
        except Exception as e:
            logger.error("Alert fetch failed: %s", e, exc_info=True)

        return self._alert_cache or []

    def _build_weather_dict(
        self,
        obs: dict[str, Any],
        day_high: Optional[int],
        day_low: Optional[int],
    ) -> dict[str, Any]:
        """Build the weather dict from NWS observation data.

        Maintains the same shape as the old OWM service for backward
        compatibility with the frontend and automation engine.
        """
        props = obs.get("properties", {})

        temp_c = props.get("temperature", {}).get("value")
        temp_f = _c_to_f(temp_c) if temp_c is not None else None
        humidity = props.get("relativeHumidity", {}).get("value")
        wind_kmh = props.get("windSpeed", {}).get("value")
        wind_mph = _kmh_to_mph(wind_kmh)

        # Feels like: use NWS heat index / wind chill if available,
        # otherwise compute from temp/humidity/wind
        heat_index_c = props.get("heatIndex", {}).get("value")
        wind_chill_c = props.get("windChill", {}).get("value")
        if heat_index_c is not None:
            feels_like = _c_to_f(heat_index_c)
        elif wind_chill_c is not None:
            feels_like = _c_to_f(wind_chill_c)
        elif temp_f is not None:
            feels_like = _compute_feels_like(temp_f, humidity, wind_mph)
        else:
            feels_like = temp_f

        description = props.get("textDescription", "")

        # If there are active severe weather alerts, override the description
        # so the automation engine's _classify_weather picks up storms that
        # the observation station hasn't reported yet
        alert_desc = self._get_alert_description()
        if alert_desc:
            description = alert_desc

        now = datetime.now(tz=TZ)
        is_daytime = 6 <= now.hour < 20  # Rough estimate
        icon = _nws_icon_code(description, is_daytime)

        return {
            "temp": temp_f or 0,
            "feels_like": feels_like or temp_f or 0,
            "temp_min": day_low if day_low is not None else (temp_f or 0),
            "temp_max": day_high if day_high is not None else (temp_f or 0),
            "description": description,
            "icon": icon,
            "humidity": round(humidity) if humidity is not None else 0,
            "wind_speed": wind_mph or 0,
            "sunrise": self._sunrise,
            "sunset": self._sunset,
            "city": "Indianapolis",
        }

    def _get_alert_description(self) -> Optional[str]:
        """Check active alerts and return a weather description override.

        If there's an active severe weather alert (e.g. thunderstorm warning),
        return a description string that the automation engine will classify
        correctly, even if the observation station still says 'overcast clouds'.
        """
        if not self._alert_cache:
            return None

        # Find the most severe active alert
        severity_order = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1}
        best_alert = None
        best_severity = 0

        for alert in self._alert_cache:
            event = alert.get("event", "")
            if event in _ALERT_WEATHER_MAP:
                sev = severity_order.get(alert.get("severity", ""), 0)
                if sev > best_severity:
                    best_severity = sev
                    best_alert = alert

        if best_alert:
            event = best_alert["event"]
            mapped = _ALERT_WEATHER_MAP[event]
            logger.info(
                "Alert override: '%s' → description '%s'", event, mapped,
            )
            return mapped

        return None

    async def _fetch_observations(
        self, client: httpx.AsyncClient,
    ) -> Optional[dict[str, Any]]:
        """Fetch latest observation from NWS station."""
        try:
            resp = await client.get(NWS_OBSERVATIONS_URL)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("NWS observation request failed: %s", e)
            return None
        except Exception as e:
            logger.error("NWS observation fetch error: %s", e, exc_info=True)
            return None

    async def _fetch_daily_range(
        self, client: httpx.AsyncClient,
    ) -> tuple[Optional[int], Optional[int]]:
        """Get today's high/low from the NWS 7-day forecast."""
        try:
            resp = await client.get(NWS_FORECAST_URL)
            resp.raise_for_status()
            data = resp.json()

            periods = data.get("properties", {}).get("periods", [])
            if not periods:
                return None, None

            today_str = datetime.now(TZ).strftime("%Y-%m-%d")
            day_high = None
            day_low = None

            for period in periods:
                start = period.get("startTime", "")
                if not start.startswith(today_str):
                    # Only look at periods that overlap today
                    if day_high is not None or day_low is not None:
                        break  # Past today's periods
                    continue

                temp = period.get("temperature")
                if temp is None:
                    continue

                if period.get("isDaytime", True):
                    if day_high is None or temp > day_high:
                        day_high = temp
                else:
                    if day_low is None or temp < day_low:
                        day_low = temp

            return day_high, day_low

        except Exception as e:
            logger.warning("NWS forecast fetch failed: %s", e)
            return None, None

    async def _fetch_alerts(self, client: httpx.AsyncClient) -> None:
        """Fetch active weather alerts for Indianapolis."""
        now = time.time()
        if (
            self._alert_cache is not None
            and (now - self._alert_cache_time) < ALERT_CACHE_TTL
        ):
            return

        try:
            resp = await client.get(
                NWS_ALERTS_URL,
                params={"point": f"{LAT},{LON}", "status": "actual"},
            )
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            alerts = []
            for feature in features:
                props = feature.get("properties", {})
                alerts.append({
                    "event": props.get("event", ""),
                    "severity": props.get("severity", ""),
                    "urgency": props.get("urgency", ""),
                    "certainty": props.get("certainty", ""),
                    "headline": props.get("headline", ""),
                    "description": props.get("description", ""),
                    "onset": props.get("onset"),
                    "expires": props.get("expires"),
                    "sender": props.get("senderName", ""),
                })

            self._alert_cache = alerts
            self._alert_cache_time = now

            if alerts:
                events = [a["event"] for a in alerts]
                logger.info("Active weather alerts: %s", ", ".join(events))

        except Exception as e:
            logger.error("NWS alert fetch failed: %s", e, exc_info=True)
