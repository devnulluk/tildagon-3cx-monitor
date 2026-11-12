import unittest
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from bridge.server import DEMO_CONFIG, DemoSource, create_app, main


class FakeSource:
    snapshot = []
    connected = True
    age_seconds = 0.0
    status = "live"


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source = FakeSource()
        self.token = "a" * 32
        self.client = TestClient(TestServer(create_app(DEMO_CONFIG, self.source, token=self.token)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_state_requires_bearer_and_does_not_cache(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"X-API-Key": self.token}):
            response = await self.client.get("/v1/state", headers=headers)
            self.assertEqual(response.status, 401)
            self.assertEqual(await response.json(), {"error": "unauthorized"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = await self.client.get("/v1/state", headers={"Authorization": "Bearer " + self.token})
        self.assertEqual(response.status, 200)
        self.assertIsInstance(await response.json(), dict)

    async def test_health_contains_no_call_or_config_data(self):
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(set(body), {"status", "connected", "stale", "demo"})
        self.assertEqual(body["status"], "ok")

    async def test_health_detects_stale_and_disconnected(self):
        self.source.age_seconds = 6
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 503)
        self.assertTrue((await response.json())["stale"])
        self.source.age_seconds = 0
        self.source.connected = False
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 503)
        self.assertFalse((await response.json())["connected"])

    async def test_health_before_first_snapshot_is_stale(self):
        self.source.age_seconds = float("inf")
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 503)
        self.assertTrue((await response.json())["stale"])

    async def test_call_actions_are_not_routes(self):
        response = await self.client.post("/callcontrol/100/participants/1/drop")
        self.assertEqual(response.status, 404)

    async def test_demo_needs_no_token_and_is_labelled(self):
        demo = TestClient(TestServer(create_app(DEMO_CONFIG, DemoSource(DEMO_CONFIG), demo=True)))
        await demo.start_server()
        try:
            response = await demo.get("/v1/state")
            self.assertEqual(response.status, 200)
            self.assertTrue((await response.json())["demo"])
        finally:
            await demo.close()


class AuthenticationConfigurationTests(unittest.TestCase):
    def test_live_token_is_required_and_long_enough(self):
        for token in (None, "short", "nonascii" + "é" * 30, "with spaces" * 5):
            with self.subTest(token=token), self.assertRaises(ValueError):
                create_app(DEMO_CONFIG, FakeSource(), token=token)


class EnvironmentConfigurationTests(unittest.TestCase):
    def test_expired_or_invalid_presence_grant_keeps_monitor_and_call_service_running(self):
        from bridge.presence import PresenceAuthError
        marker = "sensitive-expired-grant-marker"
        config = dict(DEMO_CONFIG, own_extension="200")
        environment = {"BRIDGE_CONFIG_JSON": json.dumps(config),
                       "PBX_URL": "https://pbx.invalid", "PBX_CLIENT_ID": "badge",
                       "PBX_CLIENT_SECRET": "pbx-secret", "BRIDGE_TOKEN": "r" * 32,
                       "BRIDGE_CONTROL_TOKEN": "c" * 32,
                       "PBX_USER_TOKEN_FILE": "/data/own-user-grant.json"}
        source = FakeSource()
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch("bridge.server.ThreeCXTransport", return_value=source), \
                mock.patch("bridge.presence.presence_provider_from_env",
                           side_effect=PresenceAuthError(marker)) as provider, \
                mock.patch("bridge.server.create_app", return_value="fake-app") as create, \
                mock.patch("bridge.server.web.run_app") as run, \
                self.assertLogs("bridge.server", level="WARNING") as logs:
            main([])
        provider.assert_called_once_with("https://pbx.invalid", "200")
        self.assertIs(create.call_args.args[1], source)
        self.assertIsNone(create.call_args.kwargs["presence_provider"])
        self.assertEqual(create.call_args.kwargs["control_token"], "c" * 32)
        self.assertFalse(create.call_args.kwargs["demo"])
        self.assertEqual(run.call_args.args[0], "fake-app")
        self.assertIn("call monitoring remains enabled", " ".join(logs.output))
        self.assertNotIn(marker, " ".join(logs.output))

    def test_token_format_environment_is_passed_to_live_transport(self):
        environment = {"BRIDGE_CONFIG_JSON": json.dumps(DEMO_CONFIG),
                       "PBX_URL": "https://pbx.invalid", "PBX_CLIENT_ID": "badge",
                       "PBX_CLIENT_SECRET": "secret", "BRIDGE_TOKEN": "a" * 32,
                       "PBX_TOKEN_FORMAT": "urlencoded"}
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch("bridge.server.ThreeCXTransport") as transport, \
                mock.patch("bridge.server.create_app"), \
                mock.patch("bridge.server.web.run_app"):
            main([])
        self.assertEqual(transport.call_args.kwargs["token_format"], "urlencoded")

    def test_invalid_token_format_cli_fails_safely(self):
        marker = "sensitive_token_format_marker"
        environment = {"BRIDGE_CONFIG_JSON": json.dumps(DEMO_CONFIG),
                       "PBX_URL": "https://pbx.invalid", "PBX_CLIENT_ID": "badge",
                       "PBX_CLIENT_SECRET": "secret", "BRIDGE_TOKEN": "a" * 32,
                       "PBX_TOKEN_FORMAT": marker}
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch("bridge.server.web.run_app") as run, \
                contextlib.redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as stopped:
                main([])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn(marker, error.getvalue())
        run.assert_not_called()

    def test_config_json_environment_is_validated_and_used(self):
        config = dict(DEMO_CONFIG, own_extension="200", own_name="Environment user")
        with mock.patch.dict(os.environ, {"BRIDGE_CONFIG_JSON": json.dumps(config)}, clear=True), \
                mock.patch("bridge.server.create_app") as create, \
                mock.patch("bridge.server.web.run_app") as run:
            main(["--demo"])
        self.assertEqual(create.call_args.args[0]["own_extension"], "200")
        self.assertEqual(create.call_args.args[0]["own_name"], "Environment user")
        self.assertTrue(create.call_args.kwargs["demo"])
        run.assert_called_once()

    def test_invalid_environment_json_fails_without_echoing_contents(self):
        marker = "sensitive_config_value_123"
        for value in ("", '{"' + marker + '":',
                      json.dumps(dict(DEMO_CONFIG, own_extension="invalid " + marker))):
            with self.subTest(value=value), \
                    mock.patch.dict(os.environ, {"BRIDGE_CONFIG_JSON": value}, clear=True), \
                    mock.patch("bridge.server.web.run_app") as run, \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as stopped:
                    main(["--demo"])
                self.assertEqual(stopped.exception.code, 2)
                run.assert_not_called()
                self.assertNotIn(marker, error.getvalue())

    def test_explicit_file_overrides_environment(self):
        config = dict(DEMO_CONFIG, own_extension="201")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with mock.patch.dict(os.environ, {"BRIDGE_CONFIG_JSON": "invalid"}, clear=True), \
                    mock.patch("bridge.server.create_app") as create, \
                    mock.patch("bridge.server.web.run_app"):
                main(["--demo", "--config", str(path)])
        self.assertEqual(create.call_args.args[0]["own_extension"], "201")
