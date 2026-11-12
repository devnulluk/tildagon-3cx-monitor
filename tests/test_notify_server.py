import contextlib
import io
import json
import os
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from bridge.notifications import NotificationBroker
from bridge.server import DEMO_CONFIG, create_app, main


READ, CONTROL, NOTIFY = "r" * 32, "c" * 32, "n" * 32


class Source:
    snapshot = []
    connected = True
    age_seconds = 0.0
    status = "live"


class Actions:
    own_presence = {"state": "unknown", "confirmed": False, "profile": "", "age_seconds": None}
    def capabilities(self):
        return {"call": False, "dnd": False, "targets": [], "session_id": "0" * 32}


class NotifyServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.broker = NotificationBroker()
        self.source = Source()
        with mock.patch.dict(os.environ, {}, clear=True):
            app = create_app(DEMO_CONFIG, self.source, token=READ, control_token=CONTROL,
                             actions=Actions(), notify_token=NOTIFY, notifications=self.broker)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def post(self, payload, token=NOTIFY, **extra):
        return await self.client.post("/v1/notify", json=payload,
                                      headers={"Authorization": "Bearer " + token, **extra})

    async def test_dedicated_auth_roles_are_separate_and_state_stays_authenticated(self):
        for token in ("wrong", READ, CONTROL):
            response = await self.post({"body": "Example"}, token)
            self.assertEqual(response.status, 401)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = await self.client.get("/v1/state", headers={"Authorization": "Bearer " + NOTIFY})
        self.assertEqual(response.status, 401)
        response = await self.client.post("/v1/control/call", json={}, headers={"Authorization": "Bearer " + NOTIFY})
        self.assertEqual(response.status, 401)
        response = await self.post({"version": "1.0", "title": "Backup", "message": "Complete", "type": "success", "attachments": []})
        self.assertEqual(response.status, 202)
        result = await response.json()
        self.assertNotIn("body", result)
        response = await self.client.get("/v1/state", headers={"Authorization": "Bearer " + READ})
        body = await response.json()
        self.assertEqual(body["notifications"][0]["body"], "Complete")
        self.assertEqual(body["notifications"][0]["icon"], "check")
        self.assertIn("own", body)
        self.assertIn("team", body)

    async def test_id_updates_and_duplicates_return_metadata_without_echoing_text(self):
        payload = {"id": "job", "title": "Backup", "progress": 10}
        response = await self.post(payload)
        self.assertEqual(response.status, 202)
        response = await self.post(payload)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"status": "duplicate", "id": "job"})
        response = await self.post({"id": "job", "progress": 80})
        self.assertEqual(response.status, 202)
        self.assertEqual(self.broker.snapshot()[0]["progress"], 80)

    async def test_invalid_payloads_do_not_echo_sensitive_values_or_accept_remote_actions(self):
        marker = "private-payload-marker"
        for payload in ([], None, {"body": "Example", "url": marker}, {"body": "Example", "icon": marker},
                        {"body": "Example", "priority": marker}, {"body": "Example", "actions": []}):
            response = await self.post(payload)
            self.assertEqual(response.status, 400)
            self.assertNotIn(marker, await response.text())
        response = await self.client.post("/v1/notify", data='{"body":',
                                          headers={"Authorization": "Bearer " + NOTIFY, "Content-Type": "application/json"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.broker.snapshot(), [])

    async def test_browser_origin_and_non_json_are_rejected(self):
        response = await self.post({"body": "Example"}, Origin="https://untrusted.invalid")
        self.assertEqual(response.status, 403)
        response = await self.client.post("/v1/notify", data="Example",
                                          headers={"Authorization": "Bearer " + NOTIFY})
        self.assertEqual(response.status, 400)

    async def test_notification_limit_is_bounded_and_does_not_expand_control_limit(self):
        response = await self.post({"body": "x" * 2000})
        self.assertEqual(response.status, 202)
        self.assertEqual(len(self.broker.snapshot()[0]["body"].encode()), 320)
        response = await self.post({"body": "x" * 5000})
        self.assertEqual(response.status, 413)
        response = await self.client.post("/v1/control/call", json={"body": "x" * 2000},
                                          headers={"Authorization": "Bearer " + CONTROL})
        self.assertEqual(response.status, 413)

    async def test_sixteen_unicode_notifications_keep_the_snapshot_small(self):
        for index in range(16):
            response = await self.post({"id": "n-" + str(index), "title": "😀" * 20, "body": "😀" * 80})
            self.assertEqual(response.status, 202)
        response = await self.client.get("/v1/state", headers={"Authorization": "Bearer " + READ})
        raw = await response.read()
        self.assertLess(len(raw), 16384)
        self.assertEqual(len(json.loads(raw)["notifications"]), 16)

    async def test_notification_failure_never_breaks_state_or_pbx_health(self):
        with mock.patch.object(self.broker, "snapshot", side_effect=RuntimeError("private backend marker")):
            response = await self.client.get("/v1/state", headers={"Authorization": "Bearer " + READ})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["notifications"], [])
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 200)
        self.assertEqual(set(await response.json()), {"status", "connected", "stale", "demo"})
        self.source.connected = False
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 503)


class NotifyConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def test_notify_token_must_be_strong_and_different_from_other_roles(self):
        for value in (READ, CONTROL, "short", "contains space" * 4, "é" * 32, "a" * 31 + "\x7f"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_app(DEMO_CONFIG, Source(), token=READ, control_token=CONTROL,
                           actions=Actions(), notify_token=value)

    async def test_invalid_ntfy_configuration_disables_only_subscription(self):
        marker = "private-url-marker"
        with mock.patch.dict(os.environ, {"NTFY_URL": "http://" + marker, "NTFY_TOPIC": "topic"}, clear=True), \
                self.assertLogs("bridge.server", level="WARNING") as logs:
            app = create_app(DEMO_CONFIG, Source(), token=READ)
        self.assertNotIn(marker, " ".join(logs.output))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/healthz")
            self.assertEqual(response.status, 200)
            response = await client.post("/v1/notify", json={"body": "Example"})
            self.assertEqual(response.status, 503)
        finally:
            await client.close()

    async def test_subscriber_lifecycle_and_failures_are_independent_of_pbx(self):
        subscriber = mock.Mock()
        subscriber.start = mock.AsyncMock(side_effect=RuntimeError("private subscription URL"))
        subscriber.close = mock.AsyncMock()
        app = create_app(DEMO_CONFIG, Source(), token=READ, ntfy_subscriber=subscriber)
        client = TestClient(TestServer(app))
        with self.assertLogs("bridge.server", level="WARNING") as logs:
            await client.start_server()
        self.assertNotIn("private subscription URL", " ".join(logs.output))
        response = await client.get("/healthz")
        self.assertEqual(response.status, 200)
        await client.close()
        subscriber.start.assert_awaited_once()
        subscriber.close.assert_awaited_once()

    async def test_demo_never_starts_an_external_subscription(self):
        subscriber = mock.Mock(start=mock.AsyncMock(), close=mock.AsyncMock())
        with mock.patch.dict(os.environ, {"NTFY_URL": "https://ntfy.example.invalid", "NTFY_TOPIC": "topic"}, clear=True):
            client = TestClient(TestServer(create_app(DEMO_CONFIG, Source(), demo=True, ntfy_subscriber=subscriber)))
        await client.start_server()
        await client.close()
        subscriber.start.assert_not_called()

    def test_cli_passes_notify_token_without_printing_it(self):
        with mock.patch.dict(os.environ, {"NOTIFY_TOKEN": NOTIFY}, clear=True), \
                mock.patch("bridge.server.create_app") as create, mock.patch("bridge.server.web.run_app"), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            main(["--demo"])
        self.assertEqual(create.call_args.kwargs["notify_token"], NOTIFY)
        self.assertNotIn(NOTIFY, error.getvalue())


if __name__ == "__main__":
    unittest.main()
