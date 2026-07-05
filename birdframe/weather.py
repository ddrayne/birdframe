"""Edinburgh weather in a few words, from the free Open-Meteo API."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import httpx

_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "rain showers",
    82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thundery", 96: "thundery", 99: "thundery",
}


def _code_to_phrase(code: int) -> str:
    return _CODES.get(int(code), "changeable")


def _default_get(url: str, params: dict) -> dict:
    return httpx.get(url, params=params, timeout=10).json()


def describe_weather(lat: float, lon: float, when: datetime,
                     http_get: Callable[[str, dict], dict] = _default_get) -> str:
    day = when.strftime("%Y-%m-%d")
    # The forecast endpoint covers recent past + today reliably (the archive
    # API lags a day or two), so use it for "today".
    try:
        data = http_get(
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": lat, "longitude": lon, "start_date": day,
             "end_date": day, "daily": "weathercode",
             "timezone": "Europe/London"},
        )
        code = data["daily"]["weathercode"][0]
        return _code_to_phrase(code)
    except Exception:
        return "changeable"
