"""Forecast/HTTP/cache tests use synthetic data and make no network requests."""

import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from bridge.weather import MAX_RESPONSE, WeatherService

NOW = int(datetime(2026, 11, 11, 12, 7, tzinfo=timezone.utc).timestamp())


def forecast(now=NOW):
    quarter, hour, day = now // 900 * 900, now // 3600 * 3600, now // 86400 * 86400
    return {"timezone": "Europe/London", "utc_offset_seconds": 0,
            "current_units": {"time": "unixtime", "temperature_2m": "°C", "apparent_temperature": "°C", "wind_speed_10m": "km/h"},
            "current": {"time": quarter, "temperature_2m": 9.1, "apparent_temperature": 7.0,
                        "weather_code": 3, "is_day": 1, "wind_speed_10m": 12},
            "minutely_15_units": {"time": "unixtime", "precipitation": "mm"},
            "minutely_15": {"time": [quarter + index * 900 for index in range(8)],
                            "precipitation": [0, 0, 0.2, 0.4, 0, 0, 0, 0]},
            "hourly_units": {"time": "unixtime", "precipitation_probability": "%"},
            "hourly": {"time": [hour + index * 3600 for index in range(5)],
                       "precipitation_probability": [5, 20, 50, 40, 10]},
            "daily_units": {"time": "unixtime", "sunrise": "unixtime", "sunset": "unixtime"},
            "daily": {"time": [day, day + 86400], "sunrise": [day + 7 * 3600 + 10 * 60, day + 86400 + 7 * 3600 + 12 * 60],
                      "sunset": [day + 16 * 3600 + 15 * 60, day + 86400 + 16 * 3600 + 14 * 60]}}


class Content:
    def __init__(self, raw):
        self.raw = raw
    async def iter_chunked(self, size):
        for start in range(0, len(self.raw), size):
            yield self.raw[start:start + size]


class Response:
    def __init__(self, payload, status=200, declared_size=True, gate=None):
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.content_length = len(self.raw) if declared_size else None
        self.content = Content(self.raw)
        self.gate = gate
    async def __aenter__(self):
        if self.gate:
            await self.gate.wait()
        return self
    async def __aexit__(self, *unused):
        return None


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    async def close(self):
        self.closed = True


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    def service(self, responses=None, now=NOW, **kwargs):
        clock = [0.0]
        wall = [float(now)]
        session = Session(responses or [])
        service = WeatherService(51.5007, -0.1246, location="Westmoor", session=session,
                                 clock=lambda: clock[0], wall_clock=lambda: wall[0], **kwargs)
        self.addAsyncCleanup(service.close)
        return service, session, clock, wall

    async def test_request_is_https_read_only_metric_bounded_and_uses_exact_location(self):
        service, session, clock, wall = self.service([Response(forecast())])
        self.assertTrue(await service.refresh())
        url, args = session.calls[0]
        self.assertEqual(url, "https://api.open-meteo.com/v1/forecast")
        self.assertFalse(args["allow_redirects"])
        self.assertEqual(args["params"]["latitude"], "51.5007")
        self.assertEqual(args["params"]["longitude"], "-0.1246")
        self.assertEqual(args["params"]["timezone"], "Europe/London")
        self.assertEqual(args["params"]["timeformat"], "unixtime")
        self.assertEqual(args["params"]["forecast_days"], "2")
        self.assertEqual(args["params"]["minutely_15"], "precipitation")
        value = service.snapshot()
        self.assertTrue(value["available"])
        self.assertEqual(value["current"]["temperature_c"], 9.1)
        self.assertEqual(value["current"]["apparent_temperature_c"], 7)
        self.assertEqual(value["current"]["condition"], "Overcast")
        self.assertEqual(value["current"]["wind_kmh"], 12)
        self.assertEqual(value["source"], "Open-Meteo")
        self.assertIn("CC BY", value["attribution"])
        self.assertNotIn("latitude", value)

    async def test_next_hour_uses_complete_real_bins_and_forecast_onset_range(self):
        service, unused, clock, wall = self.service([Response(forecast())])
        await service.refresh()
        rain = service.snapshot()["rain_next_hour"]
        self.assertEqual(rain["window_start"], NOW)
        self.assertEqual(rain["window_end"], NOW + 3600)
        self.assertEqual(rain["status"], "rain_likely")
        self.assertEqual(rain["precipitation_mm"], 0.6)
        self.assertEqual(rain["onset_minutes"], [8, 23])
        self.assertTrue(rain["interpolated"])
        self.assertEqual(rain["basis"], "model_forecast")
        self.assertEqual(rain["peak_overlapping_hourly_probability_percent"], 50)
        self.assertNotIn("probability_percent", rain)

    async def test_partial_first_and_last_bin_amounts_are_proportional_not_whole_bins(self):
        payload = forecast()
        payload["minutely_15"]["precipitation"] = [1] * 8
        service, unused, clock, wall = self.service([Response(payload)])
        await service.refresh()
        rain = service.snapshot()["rain_next_hour"]
        self.assertEqual(rain["precipitation_mm"], 4.0)
        self.assertEqual(rain["onset_minutes"], [0, 8])

    async def test_zero_only_means_dry_when_the_entire_next_hour_has_data(self):
        payload = forecast()
        payload["minutely_15"]["precipitation"] = [0] * 8
        service, unused, clock, wall = self.service([Response(payload)])
        await service.refresh()
        self.assertEqual(service.snapshot()["rain_next_hour"]["status"], "dry_likely")
        self.assertEqual(service.snapshot()["rain_next_hour"]["precipitation_mm"], 0)

    async def test_missing_null_sparse_duplicate_or_wrong_unit_bins_are_unknown(self):
        for change in ("missing", "null", "sparse", "short", "duplicate", "unit", "negative", "boolean"):
            with self.subTest(change=change):
                payload = forecast()
                if change == "missing":
                    del payload["minutely_15"]
                elif change == "null":
                    payload["minutely_15"]["precipitation"][2] = None
                elif change == "sparse":
                    del payload["minutely_15"]["time"][2]
                    del payload["minutely_15"]["precipitation"][2]
                elif change == "short":
                    payload["minutely_15"]["time"] = payload["minutely_15"]["time"][:3]
                    payload["minutely_15"]["precipitation"] = [0] * 3
                elif change == "duplicate":
                    payload["minutely_15"]["time"][2] = payload["minutely_15"]["time"][1]
                elif change == "unit":
                    payload["minutely_15_units"]["precipitation"] = "inch"
                elif change == "negative":
                    payload["minutely_15"]["precipitation"][2] = -1
                else:
                    payload["minutely_15"]["precipitation"][2] = False
                service, unused, clock, wall = self.service([Response(payload)])
                self.assertTrue(await service.refresh())
                rain = service.snapshot()["rain_next_hour"]
                self.assertEqual(rain["status"], "unknown")
                self.assertIsNone(rain["precipitation_mm"])

    async def test_missing_probability_does_not_invent_a_chance_or_discard_rain_amount(self):
        payload = forecast()
        payload["hourly"]["precipitation_probability"][1] = None
        service, unused, clock, wall = self.service([Response(payload)])
        await service.refresh()
        rain = service.snapshot()["rain_next_hour"]
        self.assertEqual(rain["status"], "rain_likely")
        self.assertIsNone(rain["peak_overlapping_hourly_probability_percent"])

    async def test_forecast_window_moves_with_clock_in_cached_data(self):
        service, unused, clock, wall = self.service([Response(forecast())])
        await service.refresh()
        wall[0] += 600
        clock[0] += 600
        rain = service.snapshot()["rain_next_hour"]
        self.assertEqual(rain["window_start"], NOW + 600)
        self.assertEqual(rain["window_end"], NOW + 4200)
        self.assertEqual(rain["onset_minutes"], [0, 13])

    async def test_stale_forecast_hides_weather_and_rain_but_clock_remains_valid(self):
        service, unused, clock, wall = self.service([Response(forecast())])
        await service.refresh()
        wall[0] += 1801
        clock[0] += 1801
        value = service.snapshot()
        self.assertFalse(value["available"])
        self.assertTrue(value["stale"])
        self.assertEqual(value["status"], "stale")
        self.assertIsNone(value["current"])
        self.assertEqual(value["rain_next_hour"]["status"], "unknown")
        self.assertIsNone(value["rain_next_hour"]["precipitation_mm"])
        self.assertEqual(value["local_clock"], "12:37")
        self.assertEqual(value["local_date_iso"], "2026-11-11")

    async def test_failed_refresh_keeps_last_good_until_stale_and_is_rate_bounded(self):
        service, session, clock, wall = self.service([Response(forecast()), Response({}, status=503)])
        await service.refresh()
        await service.refresh()
        self.assertEqual(len(session.calls), 1)
        clock[0] += 600
        wall[0] += 600
        self.assertFalse(await service.refresh())
        value = service.snapshot()
        self.assertTrue(value["available"])
        self.assertEqual(value["age_seconds"], 600)
        self.assertEqual(value["error"], "Weather update unavailable")

    async def test_future_or_old_current_observation_is_never_marked_live(self):
        for offset in (121, -1801):
            payload = forecast()
            payload["current"]["time"] = NOW + offset
            service, unused, clock, wall = self.service([Response(payload)])
            self.assertFalse(await service.refresh())
            self.assertFalse(service.snapshot()["available"])
            self.assertEqual(service.snapshot()["rain_next_hour"]["status"], "unknown")

    async def test_sunset_and_next_days_sunrise_have_correct_countdown(self):
        payload = forecast()
        sunset = payload["daily"]["sunset"][0]
        service, unused, clock, wall = self.service([Response(payload)])
        await service.refresh()
        daylight = service.snapshot()["daylight"]
        self.assertEqual(daylight["next_event"], "sunset")
        self.assertEqual(daylight["remaining_seconds"], sunset - NOW)
        after = sunset + 60
        payload = forecast(after)
        service2, unused, clock2, wall2 = self.service([Response(payload)], now=after)
        await service2.refresh()
        daylight = service2.snapshot()["daylight"]
        self.assertFalse(daylight["is_day"])
        self.assertEqual(daylight["daylight_remaining_seconds"], 0)
        self.assertEqual(daylight["next_event"], "sunrise")
        self.assertEqual(daylight["next_event_unix"], payload["daily"]["sunrise"][1])
        self.assertEqual(daylight["remaining_seconds"], payload["daily"]["sunrise"][1] - after)
        self.assertEqual(daylight["next_event_local"], "07:12")

    async def test_london_clock_is_independent_of_forecast_and_handles_dst_transition(self):
        for stamp, expected, offset in ((datetime(2026, 7, 1, 12, tzinfo=timezone.utc), "13:00", 3600),
                                        (datetime(2026, 10, 25, 0, 55, tzinfo=timezone.utc), "01:55", 3600),
                                        (datetime(2026, 10, 25, 1, 5, tzinfo=timezone.utc), "01:05", 0)):
            service, unused, clock, wall = self.service(now=int(stamp.timestamp()))
            value = service.snapshot()
            self.assertFalse(value["available"])
            self.assertEqual(value["local_clock"], expected)
            self.assertEqual(value["utc_offset_seconds"], offset)

    async def test_daily_fixed_offset_boundary_cannot_replace_today_with_tomorrow_across_dst(self):
        now = int(datetime(2026, 10, 25, 12, 7, tzinfo=timezone.utc).timestamp())
        today = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp())
        payload = forecast(now)
        # Simulate the API daily array retaining the pre-fallback +01 offset:
        # tomorrow's boundary maps to23:00 today under the now-correct GMT zone.
        payload["daily"] = {"time": [today - 3600, today + 86400 - 3600],
                            "sunrise": [today + 7 * 3600, today + 86400 + 7 * 3600 + 120],
                            "sunset": [today + 16 * 3600 + 1800, today + 86400 + 16 * 3600 + 1740]}
        service, unused, clock, wall = self.service([Response(payload)], now=now)
        await service.refresh()
        value = service.snapshot()
        self.assertEqual(value["sunrise_unix"], payload["daily"]["sunrise"][0])
        self.assertEqual(value["sunset_unix"], payload["daily"]["sunset"][0])
        self.assertEqual(value["daylight"]["next_event"], "sunset")
        self.assertEqual(value["daylight"]["remaining_seconds"], payload["daily"]["sunset"][0] - now)

    async def test_missing_daylight_data_stays_unknown(self):
        payload = forecast()
        del payload["daily"]
        service, unused, clock, wall = self.service([Response(payload)])
        await service.refresh()
        value = service.snapshot()
        self.assertIsNone(value["sunrise_unix"])
        self.assertIsNone(value["daylight"]["next_event"])

    async def test_http_errors_redirects_bad_json_and_oversize_responses_are_sanitized(self):
        for response in (Response({}, 302), Response(b"not JSON"), Response(b"x" * (MAX_RESPONSE + 1)),
                         Response(b"x" * (MAX_RESPONSE + 1), declared_size=False),
                         aiohttp.ClientError("https://customer-api.open-meteo.com?apikey=private-key&latitude=51.5007")):
            service, session, clock, wall = self.service([response], api_key="private-key")
            self.assertFalse(await service.refresh())
            value = service.snapshot()
            self.assertFalse(value["available"])
            self.assertNotIn("private-key", repr(value))
            self.assertNotIn("51.5007", repr(value))
            self.assertEqual(session.calls[0][0], "https://customer-api.open-meteo.com/v1/forecast")

    async def test_start_is_nonblocking_close_cancels_and_releases_lock(self):
        gate = asyncio.Event()
        service, session, clock, wall = self.service([Response(forecast(), gate=gate)])
        await service.start()
        await service.start()
        await asyncio.sleep(0)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(service._lock.locked())
        await service.close()
        self.assertTrue(service._task.done())
        self.assertFalse(service._lock.locked())
        self.assertFalse(await service.refresh())

    async def test_invalid_coordinates_timing_and_timezone_fail_before_network(self):
        for kwargs in ({"latitude": float("nan")}, {"latitude": True}, {"longitude": 181},
                       {"poll_interval": 10}, {"poll_interval": float("nan")}, {"stale_after": 500},
                       {"request_timeout": 0}, {"timezone": "UTC"}, {"api_key": "bad\nkey"}):
            args = {"latitude": 51.5007, "longitude": -0.1246}
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                WeatherService(**args)


if __name__ == "__main__":
    unittest.main()
