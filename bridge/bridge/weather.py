"""Cached Open-Meteo forecasts for one explicitly configured badge location.

The free endpoint is for personal/non-commercial use. Commercial deployments
must supply an Open-Meteo subscription key. UK 15-minute rain values are
interpolated model forecasts, never minute-accurate radar observations.
"""

import asyncio
from datetime import datetime
import json
import math
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

MAX_RESPONSE = 50_000
SOURCE_URL = "https://open-meteo.com/"
ATTRIBUTION = "Weather data: Open-Meteo (CC BY 4.0)"
CONDITIONS = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Heavy freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Heavy freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


class WeatherError(Exception):
    """Sanitized forecast error; never includes coordinates, key or payload."""


def _number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and minimum <= value <= maximum else None


def _epoch(value):
    value = _number(value, 1_577_836_800, 4_102_444_800)
    return int(value) if value is not None and value.is_integer() else None


def _series(payload, section, key, unit, upper):
    data, units = payload.get(section), payload.get(section + "_units")
    if not isinstance(data, dict) or not isinstance(units, dict) or units.get(key) != unit or units.get("time") != "unixtime":
        return []
    times, values = data.get("time"), data.get(key)
    if (not isinstance(times, list) or not isinstance(values, list)
            or not times or len(times) != len(values) or len(times) > 64):
        return []
    result = []
    for stamp, value in zip(times, values):
        stamp = _epoch(stamp)
        if stamp is None or (result and stamp <= result[-1][0]):
            return []
        result.append((stamp, _number(value, 0, upper)))
    return result


def _prepare(payload, now, zone_name):
    if not isinstance(payload, dict) or payload.get("error") or payload.get("timezone") != zone_name:
        raise WeatherError("Weather forecast response is invalid")
    current, units = payload.get("current"), payload.get("current_units")
    if (not isinstance(current, dict) or not isinstance(units, dict)
            or units.get("time") != "unixtime" or units.get("temperature_2m") != "°C"
            or units.get("apparent_temperature") != "°C" or units.get("wind_speed_10m") != "km/h"):
        raise WeatherError("Weather forecast units are invalid")
    stamp = _epoch(current.get("time"))
    temperature = _number(current.get("temperature_2m"), -100, 70)
    if stamp is None or stamp > now + 120 or stamp < now - 1800 or temperature is None:
        raise WeatherError("Current weather forecast is unavailable")
    code = _number(current.get("weather_code"), 0, 99)
    code = int(code) if code is not None and code.is_integer() else None
    is_day = current.get("is_day")
    is_day = bool(is_day) if isinstance(is_day, int) and not isinstance(is_day, bool) and is_day in (0, 1) else None
    result = {"current": {"temperature_c": temperature,
                           "apparent_temperature_c": _number(current.get("apparent_temperature"), -120, 90),
                           "weather_code": code, "condition": CONDITIONS.get(code, "Unknown"),
                           "is_day": is_day, "wind_kmh": _number(current.get("wind_speed_10m"), 0, 500),
                           "forecast_at": stamp},
              "rain": _series(payload, "minutely_15", "precipitation", "mm", 200),
              "probability": _series(payload, "hourly", "precipitation_probability", "%", 100),
              "days": []}
    daily, daily_units = payload.get("daily"), payload.get("daily_units")
    if (isinstance(daily, dict) and isinstance(daily_units, dict)
            and all(daily_units.get(key) == "unixtime" for key in ("time", "sunrise", "sunset"))):
        dates, sunrises, sunsets = daily.get("time"), daily.get("sunrise"), daily.get("sunset")
        if (all(isinstance(values, list) for values in (dates, sunrises, sunsets))
                and len(dates) == len(sunrises) == len(sunsets) and len(dates) <= 3):
            for day, sunrise, sunset in zip(dates, sunrises, sunsets):
                day, sunrise, sunset = _epoch(day), _epoch(sunrise), _epoch(sunset)
                if (day is not None and sunrise is not None and sunset is not None
                        and -90_000 <= day - now <= 172_800
                        and day <= sunrise < sunset <= day + 90_000):
                    result["days"].append((day, sunrise, sunset))
    return result


def _coverage(series, seconds, start, end):
    """Return actual overlapping forecast bins only when they cover the window."""
    cursor, overlaps = start, []
    for stamp, value in series:
        bin_start, bin_end = stamp - seconds, stamp
        if bin_end <= start or bin_start >= end:
            continue
        if value is None or bin_start > cursor or (cursor > start and bin_start < cursor):
            return None
        left, right = max(start, bin_start), min(end, bin_end)
        overlaps.append((left, right, value, bin_start, bin_end))
        cursor = right
        if cursor >= end:
            return overlaps
    return None


def rain_summary(forecast, now):
    end = now + 3600
    result = {"status": "unknown", "precipitation_mm": None, "onset_minutes": None,
              "window_start": int(now), "window_end": int(end), "resolution_minutes": 15,
              "interpolated": True, "basis": "model_forecast",
              "amount_method": "proportional_overlap_of_15_minute_forecast_bins",
              "rain_threshold_mm": 0.1, "peak_overlapping_hourly_probability_percent": None}
    bins = _coverage(forecast.get("rain", []), 900, now, end)
    if bins is not None:
        amount = sum(value * (right - left) / 900 for left, right, value, unused, unused2 in bins)
        result["precipitation_mm"] = round(amount, 3)
        result["status"] = "rain_likely" if amount >= 0.1 - 1e-9 else "dry_likely"
        if amount >= 0.1 - 1e-9:
            first = next((entry for entry in bins if entry[2] > 0), None)
            if first:
                result["onset_minutes"] = [max(0, math.floor((first[3] - now) / 60)),
                                           min(60, math.ceil((first[4] - now) / 60))]
    probabilities = _coverage(forecast.get("probability", []), 3600, now, end)
    if probabilities is not None:
        result["peak_overlapping_hourly_probability_percent"] = round(max(entry[2] for entry in probabilities), 1)
    return result


class WeatherService:
    def __init__(self, latitude, longitude, location="", timezone="Europe/London",
                 api_key=None, session=None, poll_interval=600, stale_after=1800,
                 request_timeout=8, clock=time.monotonic, wall_clock=time.time):
        self._latitude = _number(latitude, -90, 90)
        self._longitude = _number(longitude, -180, 180)
        if self._latitude is None or self._longitude is None:
            raise ValueError("Weather requires valid fixed coordinates")
        poll_interval = _number(poll_interval, 600, 86_400)
        stale_after = _number(stale_after, 600, 86_400)
        request_timeout = _number(request_timeout, 1, 30)
        if poll_interval is None or stale_after is None or request_timeout is None or stale_after < poll_interval:
            raise ValueError("Invalid weather polling or stale interval")
        if not isinstance(location, str) or len(location) > 80 or any(ord(c) < 32 for c in location):
            raise ValueError("Invalid weather location label")
        if timezone != "Europe/London":
            raise ValueError("Weather timezone must be Europe/London")
        try:
            self._zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Europe/London timezone data is required") from None
        if api_key is not None and (not isinstance(api_key, str) or not api_key or len(api_key) > 512
                                   or any(ord(c) < 33 or ord(c) > 126 for c in api_key)):
            raise ValueError("Invalid weather subscription key")
        self._location, self._timezone, self._api_key = location, timezone, api_key
        self._url = "https://customer-api.open-meteo.com/v1/forecast" if api_key else "https://api.open-meteo.com/v1/forecast"
        self._session, self._owns_session = session, session is None
        self._poll_interval, self._stale_after, self._request_timeout = poll_interval, stale_after, request_timeout
        self._clock, self._wall_clock = clock, wall_clock
        self._forecast = None
        self._completed_at = self._fetched_at = self._attempt_at = None
        self._error = None
        self._closed = False
        self._task = None
        self._lock = asyncio.Lock()

    def _params(self):
        params = {"latitude": f"{self._latitude:.4f}", "longitude": f"{self._longitude:.4f}",
                  "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
                  "minutely_15": "precipitation", "hourly": "precipitation_probability",
                  "daily": "sunrise,sunset", "timezone": self._timezone, "timeformat": "unixtime",
                  "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
                  "forecast_days": "2", "forecast_hours": "4", "past_hours": "1",
                  "forecast_minutely_15": "10", "past_minutely_15": "1"}
        if self._api_key:
            params["apikey"] = self._api_key
        return params

    async def _http(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._request_timeout),
                                                  trust_env=False, headers={"User-Agent": "Tildagon3CXWeather/0.5"})
        return self._session

    async def refresh(self):
        if self._closed:
            return False
        async with self._lock:
            if self._attempt_at is not None and self._clock() - self._attempt_at < self._poll_interval:
                return self._forecast is not None
            self._attempt_at = self._clock()
            try:
                session = await self._http()
                async with session.get(self._url, params=self._params(), allow_redirects=False,
                                       headers={"Accept": "application/json"}) as response:
                    if response.status != 200:
                        raise WeatherError("Weather forecast service is unavailable")
                    if response.content_length and response.content_length > MAX_RESPONSE:
                        raise WeatherError("Weather forecast response is too large")
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE:
                            raise WeatherError("Weather forecast response is too large")
                now = self._wall_clock()
                forecast = _prepare(json.loads(raw), now, self._timezone)
                self._forecast = forecast
                self._completed_at, self._fetched_at = self._clock(), int(now)
                self._error = None
                return True
            except asyncio.CancelledError:
                raise
            except Exception:
                # Includes paid-key URLs in aiohttp errors: never log/return them.
                self._error = "Weather update unavailable"
                return False

    def snapshot(self):
        now = int(self._wall_clock())
        local = datetime.fromtimestamp(now, self._zone)
        age = max(0.0, self._clock() - self._completed_at) if self._completed_at is not None else None
        forecast_age = now - self._forecast["current"]["forecast_at"] if self._forecast else None
        live = bool(self._forecast and age is not None and age <= self._stale_after
                    and -120 <= forecast_age <= self._stale_after)
        result = {"enabled": True, "available": live, "live": live,
                  "stale": bool(self._forecast and not live),
                  "status": "live" if live else "stale" if self._forecast else "unavailable" if self._error else "pending",
                  "source": "Open-Meteo", "source_url": SOURCE_URL, "attribution": ATTRIBUTION,
                  "licence_url": "https://creativecommons.org/licenses/by/4.0/", "location": self._location,
                  "timezone": self._timezone, "now_unix": now, "utc_offset_seconds": int(local.utcoffset().total_seconds()),
                  "local_clock": local.strftime("%H:%M"), "local_date": local.strftime("%a %d %b"),
                  "local_date_iso": local.date().isoformat(), "fetched_at": self._fetched_at,
                  "age_seconds": round(age, 1) if age is not None else None, "error": self._error,
                  "current": None, "sunrise_unix": None, "sunset_unix": None,
                  "daylight": {"is_day": None, "remaining_seconds": None, "day_length_seconds": None,
                               "daylight_remaining_seconds": None, "next_event": None,
                               "next_event_seconds": None, "next_event_unix": None, "next_event_local": None},
                  "rain_next_hour": rain_summary({}, now)}
        if not live:
            return result
        result["current"] = dict(self._forecast["current"])
        result["rain_next_hour"] = rain_summary(self._forecast, now)
        for day, sunrise, sunset in self._forecast["days"]:
            # Daily boundary stamps may retain the request's fixed UTC offset
            # across a DST change. The actual sunrise instant identifies the
            # London calendar day without assigning tomorrow to today.
            if datetime.fromtimestamp(sunrise, self._zone).date() != local.date():
                continue
            is_day = sunrise <= now < sunset
            result["sunrise_unix"], result["sunset_unix"] = sunrise, sunset
            result["daylight"].update({"is_day": is_day, "daylight_remaining_seconds": max(0, sunset - now) if is_day else 0,
                                       "day_length_seconds": sunset - sunrise})
        events = sorted((stamp, kind) for unused, sunrise, sunset in self._forecast["days"]
                        for stamp, kind in ((sunrise, "sunrise"), (sunset, "sunset")) if stamp > now)
        if events:
            result["daylight"]["next_event"] = events[0][1]
            result["daylight"]["next_event_seconds"] = events[0][0] - now
            result["daylight"]["remaining_seconds"] = events[0][0] - now
            result["daylight"]["next_event_unix"] = events[0][0]
            result["daylight"]["next_event_local"] = datetime.fromtimestamp(events[0][0], self._zone).strftime("%H:%M")
        return result

    async def start(self):
        if self._closed:
            raise WeatherError("Weather service is closed")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self):
        while not self._closed:
            await self.refresh()
            await asyncio.sleep(self._poll_interval)

    async def close(self):
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._api_key = None
