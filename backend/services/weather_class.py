"""
Weather-class normalizer for the music bandit's context dimension.

Wraps ``light_state_calculator.classify_weather`` (which returns
``Optional[str]``) and folds ``None`` into the ``"clear"`` bucket so the
bandit's arm-key always has a definite weather slot.

Class taxonomy:
    "thunderstorm" / "rain" / "snow" / "clouds" / "golden_hour" / "clear"
        — derived from current weather observations
    "any"
        — sentinel for migration / fallback / cold-start arm copying.
          Never produced by ``classify_for_bandit``; only set explicitly
          by callers that want a weather-agnostic arm.

Kept thin and import-cycle-free: takes a weather dict (caller's choice
of fetch method) and returns a string.
"""
from __future__ import annotations

from typing import Any, Optional

from backend.services.light_state_calculator import classify_weather

# Sentinel for weather-agnostic arms (migration, cold-start, no-data fallback).
WEATHER_ANY = "any"

# Concrete observed classes — set produced by classify_for_bandit().
WEATHER_OBSERVED = frozenset((
    "thunderstorm",
    "rain",
    "snow",
    "clouds",
    "golden_hour",
    "clear",
))


def classify_for_bandit(weather: Optional[dict[str, Any]]) -> str:
    """Return a weather-class string suitable for the music bandit arm key.

    Args:
        weather: A weather dict (``WeatherService.get_cached()`` shape) or
            None when no observation is available.

    Returns:
        One of ``WEATHER_OBSERVED`` for live observations, or
        ``WEATHER_ANY`` when ``weather`` is None (callers can decide whether
        to use the fallback arm or skip context entirely).
    """
    if not weather:
        return WEATHER_ANY
    desc = (weather.get("description") or "").lower()
    return classify_weather(desc, weather) or "clear"
