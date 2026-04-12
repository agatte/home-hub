"""
Morning routine service — replaces the Alexa 6:40 AM weekday routine.

Fetches weather and traffic data, generates a TTS greeting, plays it on
Sonos, and triggers the morning light ramp.

Also provides a sunrise_ramp() coroutine that gradually wakes the bedroom
lamp over 30 minutes before the routine fires — warm candlelight to daylight.
"""
import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger("home_hub.morning")


class MorningRoutineService:
    """
    Executes the morning routine: weather + traffic TTS, light ramp.

    At 6:40 AM ET on weekdays:
    1. Fetch current weather from OpenWeatherMap
    2. Fetch commute traffic from Google Maps Directions API
    3. Generate TTS: "Good morning Anthony. It's 45 degrees and cloudy.
       Your commute is currently 28 minutes with light traffic."
    4. Play on Sonos via existing TTS service
    5. Trigger morning light ramp via automation engine
    """

    def __init__(
        self,
        tts_service,
        automation_engine,
        openweather_key: Optional[str] = None,
        google_maps_key: Optional[str] = None,
        home_address: str = "",
        work_address: str = "",
        morning_volume: int = 40,
    ) -> None:
        self._tts = tts_service
        self._automation = automation_engine
        self._openweather_key = openweather_key
        self._google_maps_key = google_maps_key
        self._home_address = home_address
        self._work_address = work_address
        self._morning_volume = morning_volume

    async def execute(self) -> bool:
        """
        Run the full morning routine.

        Returns:
            True if the routine completed successfully.
        """
        logger.info("Executing morning routine")

        # Build the greeting
        parts = ["Good morning Anthony."]

        # Weather
        weather = await self._fetch_weather()
        if weather:
            parts.append(weather)

        # Traffic
        traffic = await self._fetch_traffic()
        if traffic:
            parts.append(traffic)

        greeting = " ".join(parts)
        logger.info(f"Morning greeting: {greeting}")

        # Play TTS on Sonos
        try:
            await self._tts.speak(greeting, volume=self._morning_volume)
        except Exception as e:
            logger.error(f"Morning TTS failed: {e}")
            return False

        # Trigger morning light ramp
        try:
            if self._automation:
                from backend.services.automation_engine import _morning_ramp
                state = _morning_ramp(minute_in_window=0)
                await self._automation._apply_state(state)
                logger.info("Morning light ramp triggered")
        except Exception as e:
            logger.error(f"Morning light ramp failed: {e}")

        logger.info("Morning routine complete")
        return True

    async def _fetch_weather(self) -> Optional[str]:
        """
        Fetch current weather from OpenWeatherMap.

        Returns:
            Formatted weather string, or None if unavailable.
        """
        if not self._openweather_key:
            logger.warning("No OpenWeatherMap API key — skipping weather")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "q": "Indianapolis,US",
                        "appid": self._openweather_key,
                        "units": "imperial",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            temp = round(data["main"]["temp"])
            feels_like = round(data["main"]["feels_like"])
            conditions = data["weather"][0]["description"]

            result = f"It's {temp} degrees and {conditions}."
            if abs(temp - feels_like) >= 5:
                result += f" Feels like {feels_like}."

            return result

        except Exception as e:
            logger.error(f"Weather fetch failed: {e}")
            return None

    async def sunrise_ramp(self) -> bool:
        """
        Gradual 30-minute bedroom lamp ramp simulating sunrise.

        Runs 30 minutes before the morning routine. Over 15 steps (every 2 min):
        - Color temp:  500 mirek (2000K candlelight) → 250 mirek (4000K daylight)
        - Brightness:  1 (barely visible) → 150 (moderate)
        - Transition:  12 seconds per step for smooth blending

        Only controls light "2" (bedroom lamp). Other lights stay off.
        """
        if not self._automation or not self._automation._hue:
            logger.warning("Sunrise ramp skipped — no Hue service available")
            return False

        hue = self._automation._hue
        LIGHT_ID = "2"  # Bedroom lamp
        STEPS = 15
        INTERVAL_SECONDS = 120  # 2 minutes between steps
        CT_START, CT_END = 500, 250  # Warm → daylight (mirek)
        BRI_START, BRI_END = 1, 150

        logger.info("Sunrise ramp starting — 30 min bedroom lamp warm-up")

        for step in range(STEPS + 1):
            progress = step / STEPS
            ct = int(CT_START + (CT_END - CT_START) * progress)
            bri = int(BRI_START + (BRI_END - BRI_START) * progress)

            await hue.set_light(LIGHT_ID, {
                "on": True,
                "ct": ct,
                "bri": bri,
                "transitiontime": 120,  # 12 seconds
            })

            if step < STEPS:
                await asyncio.sleep(INTERVAL_SECONDS)

        logger.info("Sunrise ramp complete — bedroom lamp at daylight brightness")
        return True

    async def _fetch_traffic(self) -> Optional[str]:
        """
        Fetch commute traffic from Google Maps Directions API.

        Returns:
            Formatted traffic string, or None if unavailable.
        """
        if not self._google_maps_key or not self._home_address or not self._work_address:
            logger.warning("Missing Google Maps key or addresses — skipping traffic")
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params={
                        "origin": self._home_address,
                        "destination": self._work_address,
                        "departure_time": "now",
                        "key": self._google_maps_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") != "OK" or not data.get("routes"):
                return None

            leg = data["routes"][0]["legs"][0]
            normal_seconds = leg["duration"]["value"]
            normal_minutes = round(normal_seconds / 60)

            # Traffic duration (may not always be available)
            traffic_duration = leg.get("duration_in_traffic", {})
            traffic_seconds = traffic_duration.get("value", normal_seconds)
            traffic_minutes = round(traffic_seconds / 60)

            delay = traffic_minutes - normal_minutes

            if delay <= 2:
                status = "with light traffic"
            elif delay <= 10:
                status = f"with moderate traffic, about {delay} minutes slower than usual"
            else:
                status = f"with heavy traffic, about {delay} minutes slower than usual"

            return f"Your commute to work is currently {traffic_minutes} minutes {status}."

        except Exception as e:
            logger.error(f"Traffic fetch failed: {e}")
            return None
