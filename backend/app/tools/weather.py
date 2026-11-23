"""Weather via Open-Meteo (free, no key): geocoding + current/hourly/daily forecast.
Also yields the scene parameters the UI uses (condition, day/night at the location)."""

from __future__ import annotations

from typing import Any

import httpx

from . import cache

# WMO weather interpretation codes -> (label, scene condition)
WMO = {
    0: ("Clear sky", "clear"), 1: ("Mainly clear", "clear"), 2: ("Partly cloudy", "partly-cloudy"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Dense drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Dense freezing drizzle", "rain"),
    61: ("Slight rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Heavy freezing rain", "rain"),
    71: ("Slight snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent rain showers", "storm"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm with hail", "storm"), 99: ("Thunderstorm with heavy hail", "storm"),
}


async def geocode(name: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
    variants = [name, name.split(",")[0].strip()]
    for q in dict.fromkeys(v for v in variants if v):
        r = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": q, "count": 5, "format": "json"})
        r.raise_for_status()
        results = r.json().get("results") or []
        if results:
            hint = name.lower()
            # prefer a result whose country/admin matches the rest of the query ("Paris, Texas")
            for res in results:
                if any((res.get(k) or "").lower() in hint for k in ("country", "admin1") if res.get(k)) and "," in name:
                    return res
            return results[0]
    return None


async def get_weather(location: str, days: int = 5) -> dict[str, Any]:
    days = max(1, min(int(days or 5), 14))
    key = cache.make_key("weather", location.lower(), days)
    if hit := cache.get(key):
        return hit
    async with httpx.AsyncClient(timeout=15) as client:
        place = await geocode(location, client)
        if not place:
            return {"error": f"Could not find a place called {location!r}."}
        params = {
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": days,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m,cloud_cover",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset,uv_index_max",
        }
        r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        data = r.json()

    cur = data.get("current", {})
    label, condition = WMO.get(cur.get("weather_code", 0), ("Unknown", "cloudy"))
    hourly = data.get("hourly", {})
    now_iso = cur.get("time", "")
    times = hourly.get("time", [])
    start = next((i for i, t in enumerate(times) if t >= now_iso[:13]), 0)
    daily = data.get("daily", {})
    result = {
        "location": {
            "name": place.get("name"), "admin1": place.get("admin1"), "country": place.get("country"),
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": data.get("timezone"),
        },
        "current": {
            "time": now_iso, "temperature_c": cur.get("temperature_2m"), "feels_like_c": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"), "wind_kmh": cur.get("wind_speed_10m"),
            "precipitation_mm": cur.get("precipitation"), "cloud_cover": cur.get("cloud_cover"),
            "condition": label, "is_day": bool(cur.get("is_day", 1)),
        },
        "hourly": [
            {"time": times[i], "temperature_c": hourly["temperature_2m"][i],
             "precip_prob": (hourly.get("precipitation_probability") or [None] * len(times))[i],
             "condition": WMO.get(hourly["weather_code"][i], ("", "cloudy"))[1]}
            for i in range(start, min(start + 24, len(times)))
        ],
        "daily": [
            {"date": d, "condition": WMO.get(daily["weather_code"][i], ("Unknown", ""))[0],
             "scene": WMO.get(daily["weather_code"][i], ("", "cloudy"))[1],
             "max_c": daily["temperature_2m_max"][i], "min_c": daily["temperature_2m_min"][i],
             "precip_prob": daily["precipitation_probability_max"][i], "precip_mm": daily["precipitation_sum"][i],
             "sunrise": daily["sunrise"][i], "sunset": daily["sunset"][i], "uv_max": daily["uv_index_max"][i]}
            for i, d in enumerate(daily.get("time", []))
        ],
        "scene": {"condition": condition, "is_day": bool(cur.get("is_day", 1))},
        "source_url": f"https://open-meteo.com/en/docs#latitude={place['latitude']}&longitude={place['longitude']}",
    }
    cache.set(key, result, ttl=600)
    return result
