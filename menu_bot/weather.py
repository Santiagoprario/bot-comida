from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import urlencode

import httpx


MAR_DEL_PLATA_LAT = -38.0055
MAR_DEL_PLATA_LON = -57.5426


def fetch_weather_context() -> dict[str, dict[str, float | str]]:
    latitude = float(os.getenv("WEATHER_LATITUDE", str(MAR_DEL_PLATA_LAT)))
    longitude = float(os.getenv("WEATHER_LONGITUDE", str(MAR_DEL_PLATA_LON)))
    params = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": os.getenv("WEATHER_TIMEZONE", "America/Argentina/Buenos_Aires"),
            "forecast_days": 7,
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    try:
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}

    daily = payload.get("daily", {})
    result: dict[str, dict[str, float | str]] = {}
    for index, raw_day in enumerate(daily.get("time", [])):
        maximum = _safe_float(daily.get("temperature_2m_max", [None])[index])
        minimum = _safe_float(daily.get("temperature_2m_min", [None])[index])
        precipitation = _safe_float(daily.get("precipitation_sum", [0])[index])
        if maximum is None or minimum is None:
            continue
        result[raw_day] = {
            "max": maximum,
            "min": minimum,
            "precipitation": precipitation or 0,
            "profile": classify_weather(maximum, precipitation or 0),
        }
    return result


def weather_for_day(weather_context: dict[str, dict[str, float | str]], day: date) -> dict[str, float | str] | None:
    return weather_context.get(day.isoformat())


def classify_weather(maximum: float, precipitation: float) -> str:
    if precipitation >= 4:
        return "lluvia"
    if maximum >= 26:
        return "calor"
    if maximum <= 15:
        return "frio"
    return "templado"


def format_weather_summary(weather: dict[str, float | str] | None) -> str:
    if not weather:
        return "Clima: sin datos"
    profile = str(weather["profile"])
    return f"Clima: {profile}, {weather['min']:g}-{weather['max']:g}°C, lluvia {weather['precipitation']:g} mm"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
