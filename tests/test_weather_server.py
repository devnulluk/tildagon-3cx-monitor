"""Weather integration remains independent of PBX health and control auth."""

import contextlib
import copy
import io
import json
import os
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from bridge.config import validate_config, validate_weather_config
from bridge.server import DEMO_CONFIG, create_app, main


LOCATION = {"enabled": True, "latitude": 51.5007, "longitude": -0.1246,
            "location": "Westmoor", "timezone": "Europe/London"}
TOKEN = "r" * 32


class Source:
    snapshot = []
    connected = True
    age_seconds = 0.0
    status = "live"


class FakeWeather:
    def __init__(self, fail_start=False, fail_snapshot=False, fail_close=False):
        self.started = self.closed = self.reads = 0
        self.fail_start, self.fail_snapshot, self.fail_close = fail_start, fail_snapshot, fail_close
    async def start(self):
        self.started += 1
        if self.fail_start:
            raise RuntimeError("private-weather-key-marker")
    async def close(self):
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("private-weather-key-marker")
    def snapshot(self):
        self.reads += 1
        if self.fail_snapshot:
            raise RuntimeError("https://weather.invalid/?apikey=private-weather-key-marker&latitude=51.5007")
        return {"enabled": True, "available": False, "status": "pending",
                "source": "Open-Meteo", "location": "Westmoor",
                "local_clock": "12:07", "now_unix": 1794398820,
                "rain_next_hour": {"status": "unknown", "precipitation_mm": None}}


class WeatherServerTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, config=None, **kwargs):
        config = copy.deepcopy(config or DEMO_CONFIG)
        client = TestClient(TestServer(create_app(config, Source(), token=TOKEN, **kwargs)))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def test_injected_weather_starts_once_and_only_authenticated_state_contains_it(self):
        weather = FakeWeather()
        client = await self.client(weather=weather)
        self.assertEqual(weather.started, 1)
        for path in ("/v1/state", "/healthz"):
            response = await client.get(path)
            body = await response.json()
            self.assertNotIn("weather", body)
        self.assertEqual(weather.reads, 0)
        response = await client.get("/v1/state", headers={"Authorization": "Bearer " + TOKEN})
        body = await response.json()
        self.assertEqual(body["weather"]["local_clock"], "12:07")
        self.assertEqual(body["weather"]["rain_next_hour"]["status"], "unknown")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(weather.reads, 1)
        await client.close()
        self.assertEqual(weather.closed, 1)

    async def test_weather_snapshot_failure_does_not_interrupt_pbx_health_or_state(self):
        weather = FakeWeather(fail_snapshot=True)
        client = await self.client(weather=weather)
        response = await client.get("/v1/state", headers={"Authorization": "Bearer " + TOKEN})
        body = await response.json()
        self.assertEqual(response.status, 200)
        self.assertTrue(body["connected"])
        self.assertFalse(body["weather"]["available"])
        self.assertEqual(body["weather"]["rain_next_hour"]["status"], "unknown")
        self.assertNotIn("private-weather-key-marker", repr(body))
        self.assertNotIn("51.5007", repr(body))
        health = await client.get("/healthz")
        self.assertEqual(health.status, 200)
        self.assertEqual(set(await health.json()), {"status", "connected", "stale", "demo"})

    async def test_enabled_config_constructs_only_fixed_location_and_env_subscription_key(self):
        config = dict(copy.deepcopy(DEMO_CONFIG), weather=LOCATION)
        weather = FakeWeather()
        with mock.patch("bridge.weather.WeatherService", return_value=weather) as factory, \
                mock.patch.dict(os.environ, {"WEATHER_API_KEY": "private-weather-key-marker"}, clear=True):
            client = await self.client(config)
        factory.assert_called_once_with(51.5007, -0.1246, location="Westmoor", timezone="Europe/London",
                                        api_key="private-weather-key-marker")
        self.assertEqual(weather.started, 1)
        await client.close()
        self.assertEqual(weather.closed, 1)

    async def test_disabled_and_demo_modes_never_construct_or_start_weather(self):
        for demo in (False, True):
            config = dict(copy.deepcopy(DEMO_CONFIG), weather=dict(LOCATION, enabled=demo))
            weather = FakeWeather()
            with mock.patch("bridge.weather.WeatherService") as factory:
                client = await self.client(config, demo=demo, **({"weather": weather} if demo else {}))
            factory.assert_not_called()
            self.assertEqual(weather.started, 0)
            response = await client.get("/v1/state", headers={"Authorization": "Bearer " + TOKEN})
            self.assertEqual((await response.json())["weather"], {"enabled": False})
            await client.close()

    async def test_start_and_close_errors_have_fixed_logs_and_monitor_remains_available(self):
        weather = FakeWeather(fail_start=True, fail_close=True)
        with self.assertLogs("bridge.server", level="WARNING") as logs:
            client = await self.client(weather=weather)
            health = await client.get("/healthz")
            self.assertEqual(health.status, 200)
            await client.close()
        self.assertEqual(weather.closed, 1)
        self.assertNotIn("private-weather-key-marker", " ".join(logs.output))


class WeatherConfigTests(unittest.TestCase):
    def test_absent_weather_defaults_disabled_and_enabled_coordinates_are_normalized(self):
        self.assertFalse(validate_config(copy.deepcopy(DEMO_CONFIG))["weather"]["enabled"])
        config = validate_config(dict(copy.deepcopy(DEMO_CONFIG), weather=dict(LOCATION)))
        self.assertEqual(config["weather"], LOCATION)
        self.assertEqual(validate_weather_config({"enabled": False}),
                         {"enabled": False, "location": "", "timezone": "Europe/London"})

    def test_config_rejects_invalid_types_ranges_nonfinite_labels_timezone_and_extra_keys(self):
        cases = [None, [], True, {"enabled": "true"}, {"enabled": True},
                 dict(LOCATION, latitude=True), dict(LOCATION, latitude=float("nan")),
                 dict(LOCATION, latitude=91), dict(LOCATION, longitude=float("inf")),
                 dict(LOCATION, longitude=-181), dict(LOCATION, location="a" * 81),
                 dict(LOCATION, location="bad\nplace"), dict(LOCATION, location="bad\x7fplace"),
                 dict(LOCATION, location="bad\x85place"), dict(LOCATION, timezone="UTC"),
                 dict(LOCATION, apikey="private-weather-key-marker"), dict(LOCATION, url="https://private.invalid")]
        for weather in cases:
            with self.subTest(weather=weather), self.assertRaises(ValueError) as error:
                validate_config(dict(copy.deepcopy(DEMO_CONFIG), weather=weather))
            self.assertNotIn("private-weather-key-marker", str(error.exception))
            self.assertNotIn("private.invalid", str(error.exception))

    def test_invalid_weather_main_errors_are_sanitized_and_never_start_http_or_transport(self):
        marker = "private-weather-key-marker"
        config = dict(copy.deepcopy(DEMO_CONFIG), weather=dict(LOCATION, latitude=marker))
        with mock.patch.dict(os.environ, {"BRIDGE_CONFIG_JSON": json.dumps(config)}, clear=True), \
                mock.patch("bridge.server.web.run_app") as run, \
                mock.patch("bridge.server.ThreeCXTransport") as transport, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as stopped:
                main([])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn(marker, stderr.getvalue())
        run.assert_not_called()
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
