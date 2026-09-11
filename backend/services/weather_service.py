"""
Weather service — fetches and caches current conditions from the NWS API.

Uses api.weather.gov (National Weather Service) for current observations,
daily forecasts, and active severe weather alerts. No API key required.
Replaces the previous OpenWeatherMap integration for better real-time
storm detection and free severe weather alerts.
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("home_hub.weather")

NWS_BASE = "https://api.weather.gov"
NWS_ALERTS_URL = f"{NWS_BASE}/alerts/active"
SUNRISE_SUNSET_URL = "https://api.sunrise-sunset.org/json"
NWS_HEADERS = {
    "User-Agent": "HomeHub/1.0 (https://github.com/agatte/home-hub)",
    "Accept": "application/geo+json",
}

CACHE_TTL = 300  # 5 minutes (down from 10 — NWS is free, no rate concern)
ALERT_CACHE_TTL = 120  # 2 minutes for alerts (storms move fast)
POINT_METADATA_TTL = 86400  # 24 hours — re-resolve NWS point metadata daily
ASTRO_CACHE_TTL = 86400  # retained for legacy callers; sun refresh is date-keyed
OBSERVATION_FRESHNESS_MAX_SECONDS = 75 * 60
OBSERVATION_FUTURE_SKEW_SECONDS = 5 * 60
ALERT_MAX_AUTHORITY_SECONDS = 6 * 60 * 60
ALERT_ACTUATOR_GRACE_SECONDS = 10 * 60
_STATION_ID_RE = re.compile(r"^[A-Z0-9]{3,8}$")

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


def _condition_family(description: str | None) -> str | None:
    """Return the canonical coarse provider family without lighting policy."""
    if not description:
        return None
    desc = description.lower()
    if any(token in desc for token in ("thunder", "tornado", "hurricane")):
        return "thunderstorm"
    if any(token in desc for token in ("snow", "sleet", "ice", "freezing rain")):
        return "snow"
    if any(token in desc for token in ("rain", "drizzle", "shower", "flood")):
        return "rain"
    if any(token in desc for token in ("wind", "breezy", "gust")):
        return "wind"
    if any(token in desc for token in ("cloud", "overcast")):
        return "clouds"
    if any(token in desc for token in ("clear", "fair", "sunny")):
        return "clear"
    return "other"


class WeatherService:
    """Cached NWS weather data provider with severe weather alerts."""

    def __init__(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        location_label: str = "Indianapolis",
        preferred_stations: str | list[str] = "",
    ) -> None:
        if (latitude is None) != (longitude is None):
            raise ValueError("Weather latitude and longitude must be configured together")
        self._cache: Optional[dict[str, Any]] = None
        self._cache_time: float = 0
        self._cache_is_stale_fallback: bool = False
        self._alert_cache: Optional[list[dict[str, Any]]] = None
        self._alert_cache_time: float = 0
        # IDs of alerts active as of the last fetch — used to emit the
        # "active alerts" log only on novelty, not every 2-min re-poll (#26).
        self._seen_alert_ids: set[str] = set()
        # Sunrise/sunset (Unix timestamps, from sunrise-sunset.org)
        self._sunrise: Optional[int] = None
        self._sunset: Optional[int] = None
        self._astro_cache_time: float = 0
        self._astro_cache_date: str | None = None
        self._latitude = latitude
        self._longitude = longitude
        self._configured = latitude is not None and longitude is not None
        self._location_label = location_label
        values = preferred_stations.split(",") if isinstance(preferred_stations, str) else preferred_stations
        self._preferred_stations = [
            value.strip().upper()
            for value in values
            if _STATION_ID_RE.fullmatch(value.strip().upper())
        ]
        self._forecast_url: str | None = None
        self._grid_url: str | None = None
        self._stations_url: str | None = None
        self._point_stations: list[str] = []
        self._point_metadata_time: float = 0
        self._grid_id: str | None = None
        self._grid_x: int | None = None
        self._grid_y: int | None = None
        self._station_id: str | None = None
        self._source_observation_at: datetime | None = None
        self._last_fetch_at: datetime | None = None
        self._sky_cover: dict[str, Any] | None = None
        self._background_tasks: list[asyncio.Task] = []
        self._point_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """Whether an explicit home point is configured for weather authority."""
        return self._configured

    async def start(self) -> None:
        """Start non-blocking backend-owned weather refresh loops."""
        if not self._configured or self._background_tasks:
            return
        self._background_tasks = [
            asyncio.create_task(self._poll_current()),
            asyncio.create_task(self._poll_alerts()),
            asyncio.create_task(self._poll_metadata()),
        ]

    async def close(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks = []

    async def _poll_current(self) -> None:
        while True:
            await self.get_current()
            await asyncio.sleep(CACHE_TTL)

    async def _poll_alerts(self) -> None:
        while True:
            await self.refresh_alerts()
            await asyncio.sleep(ALERT_CACHE_TTL)

    async def _poll_metadata(self) -> None:
        while True:
            try:
                async with httpx.AsyncClient(timeout=10.0, headers=NWS_HEADERS) as client:
                    await self._ensure_point_metadata(client, force=True)
                    await self._fetch_sky_cover(client)
                    await self._fetch_sunrise_sunset(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Weather metadata refresh failed: %s", exc)
            await asyncio.sleep(POINT_METADATA_TTL)

    def get_cached(self) -> Optional[dict[str, Any]]:
        """Return last-known display weather with any live severe override."""
        if self._cache is None:
            return None
        weather = self._cache.copy()
        alert_description = self._get_alert_description()
        if alert_description:
            weather["description"] = alert_description
            now = datetime.now(tz=TZ)
            weather["icon"] = _nws_icon_code(alert_description, 6 <= now.hour < 20)
        return weather

    def get_cache_snapshot(self) -> dict[str, Any]:
        """Return canonical display/diagnostic weather context without I/O."""
        display_weather = self.get_cached()
        provider_description = self._cache.get("description") if self._cache else None
        display_severe_override = self._get_alert_description()
        severe_override = self._get_authoritative_alert_description()
        effective_description = severe_override or provider_description
        raw_source_age = (
            (datetime.now(timezone.utc) - self._source_observation_at).total_seconds()
            if self._source_observation_at is not None
            else None
        )
        source_age = max(0.0, raw_source_age) if raw_source_age is not None else None
        cache_age = max(0.0, time.time() - self._cache_time) if self._cache_time > 0 else None
        source_fresh = bool(
            raw_source_age is not None
            and -OBSERVATION_FUTURE_SKEW_SECONDS <= raw_source_age <= OBSERVATION_FRESHNESS_MAX_SECONDS
            and not self._cache_is_stale_fallback
        )
        alert_fresh = severe_override is not None
        alert_feed_age = self._alert_feed_age_seconds()
        legacy_age = source_age if source_age is not None else cache_age
        provenance = (
            "home_point_alert" if alert_fresh else
            "station_observation" if source_fresh else
            "stale_display" if display_weather is not None else "missing"
        )
        return {
            "condition": effective_description,
            "condition_family": _condition_family(effective_description),
            "provider_description": provider_description,
            "severe_alert_override": severe_override,
            "display_severe_alert_override": display_severe_override,
            "severe_alert_count": len(self._locally_active_alerts()),
            "alert_feed_age_seconds": round(alert_feed_age, 3) if alert_feed_age is not None else None,
            "alert_actuator_usable": alert_fresh,
            "provenance": provenance,
            "observed_at": self._source_observation_at.isoformat() if self._source_observation_at else None,
            "fetched_at": self._last_fetch_at.isoformat() if self._last_fetch_at else None,
            "age_seconds": round(legacy_age, 3) if legacy_age is not None else None,
            "cache_age_seconds": round(cache_age, 3) if cache_age is not None else None,
            "fresh": alert_fresh or source_fresh,
            "actuator_usable": alert_fresh or source_fresh,
            "stale_fallback": self._cache_is_stale_fallback,
            "configured": self._configured,
            "location_label": self._location_label,
            "station_id": self._station_id,
            "grid_id": self._grid_id,
            "grid_x": self._grid_x,
            "grid_y": self._grid_y,
            "gridpoint": (
                f"{self._grid_id} {self._grid_x},{self._grid_y}"
                if self._grid_id is not None and self._grid_x is not None and self._grid_y is not None
                else None
            ),
            "sky_cover": self._sky_cover,
            "sunrise": self._sunrise,
            "sunset": self._sunset,
            "polling_active": bool(self._background_tasks),
        }

    def get_cached_alerts(self) -> list[dict[str, Any]]:
        """Return cached active weather alerts."""
        return self._locally_active_alerts()

    def _alert_feed_age_seconds(self) -> float | None:
        if self._alert_cache_time <= 0:
            return None
        return max(0.0, time.time() - self._alert_cache_time)

    def _get_authoritative_alert_description(self) -> Optional[str]:
        """Return severe override only while the alert feed is recently verified."""
        age = self._alert_feed_age_seconds()
        if age is None or age > ALERT_ACTUATOR_GRACE_SECONDS:
            return None
        return self._get_alert_description()

    def get_actuator_context(self) -> Optional[dict[str, Any]]:
        """Return weather safe for actuation; stale ordinary weather is neutral."""
        alert_description = self._get_authoritative_alert_description()
        if alert_description:
            return {
                "weather": {"description": alert_description},
                "alerts": self.get_cached_alerts(),
                "provenance": "home_point_alert",
            }
        if not self._cache or not self._source_observation_at or self._cache_is_stale_fallback:
            return None
        age = (datetime.now(timezone.utc) - self._source_observation_at).total_seconds()
        if age < -OBSERVATION_FUTURE_SKEW_SECONDS or age > OBSERVATION_FRESHNESS_MAX_SECONDS:
            return None
        return {
            "weather": self._cache.copy(),
            "station_id": self._station_id,
            "source_observation_at": self._source_observation_at.isoformat(),
            "source_observation_age_seconds": round(max(0.0, age), 3),
            "fetched_at": self._last_fetch_at.isoformat() if self._last_fetch_at else None,
            "sky_cover": self._sky_cover,
            "provenance": "station_observation",
        }

    async def get_current(self) -> Optional[dict[str, Any]]:
        """Get current weather conditions.

        Returns cached data if fresh (< 5 min old). Otherwise fetches
        from the NWS API. Returns the same dict shape as the old OWM
        service for backward compatibility.
        """
        if not self._configured:
            return None
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self.get_cached()

        try:
            async with httpx.AsyncClient(
                timeout=10.0, headers=NWS_HEADERS,
            ) as client:
                obs = await self._fetch_observations(client)
                if not obs:
                    self._cache_is_stale_fallback = self._cache is not None
                    return self.get_cached()  # Return stale display data on failure

                # Fetch forecast for high/low (less frequent, piggyback)
                day_high, day_low = await self._fetch_daily_range(client)

                # Grid sky cover is retained as source provenance only. Its
                # interpretation belongs to a later lighting policy change.
                if self._grid_url:
                    await self._fetch_sky_cover(client)

                # Fetch alerts on a faster cadence
                await self._fetch_alerts(client)

                # Fetch sunrise/sunset (cached 24h, separate API)
                await self._fetch_sunrise_sunset(client)

            weather = self._build_weather_dict(obs, day_high, day_low)
            self._cache = weather
            self._cache_time = now
            self._cache_is_stale_fallback = False
            self._last_fetch_at = datetime.now(timezone.utc)
            logger.info(
                "Weather updated: %d°F, %s (H:%s° L:%s°)",
                weather["temp"],
                weather["description"],
                weather.get("temp_max", "?"),
                weather.get("temp_min", "?"),
            )
            return self.get_cached()

        except Exception as e:
            logger.error("Weather fetch failed: %s", e, exc_info=True)
            if self._cache:
                self._cache_is_stale_fallback = True
                return self.get_cached()
            return None

    async def refresh_alerts(self) -> list[dict[str, Any]]:
        """Fetch alerts independently (for faster polling in automation loop)."""
        now = time.time()
        if self._alert_cache is not None and (now - self._alert_cache_time) < ALERT_CACHE_TTL:
            return self._locally_active_alerts()

        try:
            async with httpx.AsyncClient(
                timeout=10.0, headers=NWS_HEADERS,
            ) as client:
                await self._fetch_alerts(client)
        except Exception as e:
            logger.error("Alert fetch failed: %s", e, exc_info=True)

        return self._locally_active_alerts()

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
            "city": self._location_label,
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
        best_severity = -1

        for alert in self._locally_active_alerts():
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
        """Fetch a fresh usable observation, preferring configured stations."""
        if not await self._ensure_point_metadata(client):
            return None
        candidates = list(dict.fromkeys(self._preferred_stations + self._point_stations))
        for station_id in candidates:
            if not _STATION_ID_RE.fullmatch(station_id):
                continue
            try:
                resp = await client.get(f"{NWS_BASE}/stations/{station_id}/observations/latest")
                resp.raise_for_status()
                observation = resp.json()
                observed_at = self._observation_timestamp(observation)
                if not self._observation_is_usable(observation, observed_at):
                    logger.info("NWS station %s has no fresh usable observation", station_id)
                    continue
                self._station_id = station_id
                self._source_observation_at = observed_at
                return observation
            except httpx.HTTPStatusError as exc:
                logger.warning("NWS observation request failed for %s: %s", station_id, exc)
            except Exception as exc:
                logger.warning("NWS observation fetch error for %s: %s", station_id, exc)
        return None

    async def _ensure_point_metadata(
        self, client: httpx.AsyncClient, *, force: bool = False,
    ) -> bool:
        """Resolve/cache NWS point URLs and its ranked station collection."""
        if not self._configured:
            return False
        if (
            not force
            and self._stations_url
            and time.time() - self._point_metadata_time < POINT_METADATA_TTL
        ):
            return True
        async with self._point_lock:
            if (
                not force
                and self._stations_url
                and time.time() - self._point_metadata_time < POINT_METADATA_TTL
            ):
                return True
            try:
                resp = await client.get(f"{NWS_BASE}/points/{self._latitude},{self._longitude}")
                resp.raise_for_status()
                props = resp.json().get("properties", {})
                forecast_url = self._validated_nws_url(props.get("forecast"), "/gridpoints/")
                grid_url = self._validated_nws_url(props.get("forecastGridData"), "/gridpoints/")
                stations_url = self._validated_nws_url(props.get("observationStations"), "/gridpoints/")
                if not all((forecast_url, grid_url, stations_url)):
                    logger.warning("NWS point response included an invalid endpoint")
                    return False
                stations_response = await client.get(stations_url)
                stations_response.raise_for_status()
                point_stations = [
                    station_id
                    for station_id in (
                        self._station_id_from_feature(feature)
                        for feature in stations_response.json().get("features", [])
                    )
                    if station_id
                ][:8]
                self._forecast_url = forecast_url
                self._grid_url = grid_url
                self._stations_url = stations_url
                self._grid_id = props.get("gridId") if isinstance(props.get("gridId"), str) else None
                self._grid_x = props.get("gridX") if isinstance(props.get("gridX"), int) else None
                self._grid_y = props.get("gridY") if isinstance(props.get("gridY"), int) else None
                self._point_stations = point_stations
                self._point_metadata_time = time.time()
                return True
            except Exception as exc:
                logger.warning("NWS point discovery failed: %s", exc)
                return bool(self._stations_url and self._forecast_url)

    @staticmethod
    def _validated_nws_url(value: Any, path_prefix: str) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme == "https"
            and parsed.netloc.lower() == "api.weather.gov"
            and parsed.path.startswith(path_prefix)
        ):
            return value
        return None

    @staticmethod
    def _station_id_from_feature(feature: dict[str, Any]) -> str | None:
        feature_id = feature.get("id", "")
        station_id = feature.get("properties", {}).get("stationIdentifier")
        candidate = station_id or feature_id.rsplit("/", 1)[-1]
        if not isinstance(candidate, str):
            return None
        candidate = candidate.strip().upper()
        return candidate if _STATION_ID_RE.fullmatch(candidate) else None

    @staticmethod
    def _observation_timestamp(observation: dict[str, Any]) -> datetime | None:
        value = observation.get("properties", {}).get("timestamp")
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _observation_is_usable(
        observation: dict[str, Any], observed_at: datetime | None,
    ) -> bool:
        props = observation.get("properties", {})
        temperature = props.get("temperature", {}).get("value")
        description = props.get("textDescription")
        if observed_at is None or temperature is None or not isinstance(description, str) or not description.strip():
            return False
        age = (datetime.now(timezone.utc) - observed_at).total_seconds()
        return -OBSERVATION_FUTURE_SKEW_SECONDS <= age <= OBSERVATION_FRESHNESS_MAX_SECONDS

    async def _fetch_daily_range(
        self, client: httpx.AsyncClient,
    ) -> tuple[Optional[int], Optional[int]]:
        """Get today's high/low from the NWS 7-day forecast."""
        try:
            resp = await client.get(self._forecast_url)
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

    async def _fetch_sky_cover(self, client: httpx.AsyncClient) -> None:
        """Cache the raw skyCover interval covering now with provenance."""
        if not self._grid_url:
            return
        try:
            resp = await client.get(self._grid_url)
            resp.raise_for_status()
            props = resp.json().get("properties", {})
            values = props.get("skyCover", {}).get("values", [])
            selected = self._select_grid_value(values, datetime.now(timezone.utc))
            self._sky_cover = {
                "value": selected.get("value") if selected else None,
                "valid_time": selected.get("validTime") if selected else None,
                "grid_id": self._grid_id,
                "updated_at": props.get("updateTime"),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.warning("NWS sky cover fetch failed: %s", exc)

    @staticmethod
    def _select_grid_value(
        values: list[dict[str, Any]], now: datetime,
    ) -> dict[str, Any] | None:
        for item in values:
            if item.get("value") is None:
                continue
            valid_time = item.get("validTime")
            if not isinstance(valid_time, str) or "/" not in valid_time:
                continue
            start_text, duration_text = valid_time.split("/", 1)
            try:
                start = datetime.fromisoformat(start_text.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue
            match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration_text)
            if not match:
                continue
            duration_seconds = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
            if start <= now < datetime.fromtimestamp(start.timestamp() + duration_seconds, timezone.utc):
                return item
        return None

    @staticmethod
    def _alert_id(alert: dict[str, Any]) -> str:
        """Stable identity for an alert: the NWS feature id, else a composite of
        event + onset + expires (covers any alert that arrives without an id)."""
        return alert.get("id") or (
            f"{alert.get('event', '')}|{alert.get('onset')}|{alert.get('expires')}"
        )

    def _novel_alerts(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return alerts that were not active as of the previous fetch, then
        refresh the seen-set to the currently-active IDs. Called every fetch
        (including the empty case), so an alert that expires drops out of the
        set and will be treated as novel again if it later reappears (#26)."""
        novel = [a for a in alerts if self._alert_id(a) not in self._seen_alert_ids]
        self._seen_alert_ids = {self._alert_id(a) for a in alerts}
        return novel

    def _locally_active_alerts(self) -> list[dict[str, Any]]:
        """Return alerts that are locally credible as active right now."""
        now = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        for alert in self._alert_cache or []:
            begins = alert.get("onset") or alert.get("effective") or alert.get("sent")
            ends = alert.get("ends") or alert.get("expires")
            begin_dt = self._parse_alert_time(begins)
            end_dt = self._parse_alert_time(ends)
            if begin_dt is not None and begin_dt > now:
                continue
            if end_dt is not None:
                if end_dt <= now:
                    continue
            elif begin_dt is None or (now - begin_dt).total_seconds() > ALERT_MAX_AUTHORITY_SECONDS:
                continue
            active.append(alert)
        return active

    @staticmethod
    def _parse_alert_time(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    async def _fetch_alerts(self, client: httpx.AsyncClient) -> bool:
        """Fetch active weather alerts for the configured home point."""
        now = time.time()
        if (
            self._alert_cache is not None
            and (now - self._alert_cache_time) < ALERT_CACHE_TTL
        ):
            return True

        try:
            if self._latitude is None or self._longitude is None:
                return False
            resp = await client.get(
                NWS_ALERTS_URL,
                params={
                    "point": f"{self._latitude},{self._longitude}",
                    "status": "actual",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            alerts = []
            for feature in features:
                props = feature.get("properties", {})
                alerts.append({
                    # NWS feature-level id (stable URN per alert) — used for
                    # novelty dedup (#26). Composite fallback in _alert_id().
                    "id": feature.get("id", ""),
                    "event": props.get("event", ""),
                    "severity": props.get("severity", ""),
                    "urgency": props.get("urgency", ""),
                    "certainty": props.get("certainty", ""),
                    "headline": props.get("headline", ""),
                    "description": props.get("description", ""),
                    "sent": props.get("sent"),
                    "effective": props.get("effective"),
                    "onset": props.get("onset"),
                    "expires": props.get("expires"),
                    "ends": props.get("ends"),
                    "sender": props.get("senderName", ""),
                })

            self._alert_cache = alerts
            self._alert_cache_time = now

            # Emit only on novelty — the same active alert is otherwise re-logged
            # every 2-min poll for its whole lifetime (#26). _novel_alerts also
            # updates the seen-set, so an alert that expires drops out and will
            # re-fire if it later reappears.
            novel = self._novel_alerts(alerts)
            if novel:
                events = [a["event"] for a in novel]
                logger.info("New weather alert(s): %s", ", ".join(events))
            return True

        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            # NWS API is slow/flaky at off-peak hours — transient network
            # blips burn Sentry quota at ERROR but aren't actionable. The
            # 2-minute alert cache cycle will retry; the user sees stale alerts
            # for one cycle, no degradation otherwise.
            logger.warning("NWS alert fetch transient (%s): %s", type(e).__name__, e)
        except Exception as e:
            logger.error("NWS alert fetch failed: %s", e, exc_info=True)
        return False

    async def _fetch_sunrise_sunset(self, client: httpx.AsyncClient) -> None:
        """Fetch sunrise/sunset for the configured point once per local date."""
        if not self._configured:
            return
        today = datetime.now(TZ).date().isoformat()
        if self._sunrise and self._astro_cache_date == today:
            return

        try:
            resp = await client.get(
                SUNRISE_SUNSET_URL,
                params={"lat": self._latitude, "lng": self._longitude, "formatted": 0},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "OK":
                logger.warning("Sunrise-sunset API status: %s", data.get("status"))
                return

            results = data.get("results", {})
            sunrise_iso = results.get("sunrise")
            sunset_iso = results.get("sunset")

            if sunrise_iso and sunset_iso:
                sunrise_dt = datetime.fromisoformat(sunrise_iso)
                sunset_dt = datetime.fromisoformat(sunset_iso)
                self._sunrise = int(sunrise_dt.timestamp())
                self._sunset = int(sunset_dt.timestamp())
                self._astro_cache_time = time.time()
                self._astro_cache_date = today
                logger.info(
                    "Sunrise/sunset updated: rise=%s, set=%s",
                    sunrise_dt.astimezone(TZ).strftime("%I:%M %p"),
                    sunset_dt.astimezone(TZ).strftime("%I:%M %p"),
                )

        except Exception as exc:
            logger.warning("Sunrise-sunset fetch failed: %s", exc)
