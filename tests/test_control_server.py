"""HTTP control boundary checks. Every action uses a fake; no PBX is contacted."""
import asyncio
import copy
import json
import unittest

from aiohttp.test_utils import TestClient, TestServer

from bridge.server import create_app


class FakeSource:
    connected = True
    age_seconds = 0.1
    status = "live"
    snapshot = [{"dn": "200", "type": "Wextension",
                 "devices": [{"device_id": "test-phone"}], "participants": []}]


class FakeActions:
    def __init__(self):
        self.calls = []
        self.dnd_requests = []
        self.call_result = {"status": "accepted", "request_id": "boot-000000000001"}
        self.dnd_result = {"status": "confirmed", "enabled": True, "request_id": "boot-000000000001"}
        self.failure = None
        self.own_presence = {"state": "available", "confirmed": True,
                             "profile": "Available", "age_seconds": 0.1}

    def capabilities(self):
        return {"enabled": True, "call": True, "dnd": True,
                "session_id": "0123456789abcdef0123456789abcdef",
                "targets": [{"id": key, "label": key} for key in ("TB", "PD", "JH", "SM", "KZ")]}

    async def make_call(self, target, request_id, session_id):
        self.calls.append((target, request_id, session_id))
        if self.failure:
            raise self.failure
        return dict(self.call_result)

    async def set_dnd(self, enabled, request_id, session_id):
        self.dnd_requests.append((enabled, request_id, session_id))
        if self.failure:
            raise self.failure
        return dict(self.dnd_result)


class ControlServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.read_token = "read-" + "r" * 32
        self.control_token = "control-" + "c" * 32
        self.source = FakeSource()
        self.actions = FakeActions()
        self.config = {"own_extension": "200", "own_name": "Mark",
                       "team": [{"extension": "223", "name": "TB"}]}
        self.client = TestClient(TestServer(create_app(
            self.config, self.source, token=self.read_token,
            control_token=self.control_token, actions=self.actions)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def headers(self, token=None, **extra):
        return {"Authorization": "Bearer " + (token or self.control_token), **extra}

    @staticmethod
    def call_body(**changes):
        return {"target": "TB", "request_id": "boot-000000000001", "session_id": "0123456789abcdef0123456789abcdef", **changes}

    @staticmethod
    def dnd_body(**changes):
        return {"enabled": True, "request_id": "boot-000000000001", "session_id": "0123456789abcdef0123456789abcdef", **changes}

    async def test_read_token_and_missing_auth_cannot_call_or_change_dnd(self):
        for path, body in (("call", self.call_body()), ("dnd", self.dnd_body())):
            for headers in ({}, self.headers(self.read_token), self.headers("wrong")):
                with self.subTest(path=path, headers=bool(headers)):
                    response = await self.client.post("/v1/control/" + path, json=body, headers=headers)
                    self.assertEqual(response.status, 401)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(self.actions.calls, [])
        self.assertEqual(self.actions.dnd_requests, [])

    async def test_call_forwards_only_target_id_and_intent_identifiers(self):
        response = await self.client.post("/v1/control/call", json=self.call_body(), headers=self.headers())
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), self.actions.call_result)
        self.assertEqual(self.actions.calls, [("TB", "boot-000000000001", "0123456789abcdef0123456789abcdef")])
        self.assertEqual(self.actions.dnd_requests, [])

    async def test_dnd_is_explicit_boolean_and_returns_confirmed_result(self):
        for desired in (True, False):
            self.actions.dnd_result = {"status": "confirmed", "enabled": desired}
            response = await self.client.post("/v1/control/dnd", json=self.dnd_body(enabled=desired), headers=self.headers())
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["enabled"], desired)
        self.assertEqual(self.actions.dnd_requests,
                         [(True, "boot-000000000001", "0123456789abcdef0123456789abcdef"), (False, "boot-000000000001", "0123456789abcdef0123456789abcdef")])

    async def test_pending_and_unknown_results_are_202_without_claiming_confirmation(self):
        for state in ("pending", "unknown"):
            self.actions.call_result = {"status": state, "request_id": "boot-000000000001"}
            self.actions.dnd_result = {"status": state, "request_id": "boot-000000000001"}
            for route, body in (("call", self.call_body()), ("dnd", self.dnd_body())):
                with self.subTest(state=state, route=route):
                    response = await self.client.post("/v1/control/" + route, json=body, headers=self.headers())
                    self.assertEqual(response.status, 202)
                    value = await response.json()
                    self.assertEqual(value["status"], state)
                    self.assertNotIn("confirmed", value)

    async def test_origin_requests_are_rejected_even_with_control_token(self):
        for origin in ("https://unrelated.example", "null"):
            response = await self.client.post("/v1/control/call", json=self.call_body(),
                                              headers=self.headers(Origin=origin))
            self.assertEqual(response.status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertEqual(self.actions.calls, [])

    async def test_extra_destination_source_and_action_fields_are_rejected(self):
        for extra in ({"source": "223"}, {"extension": "223"}, {"destination": "07700900123"},
                      {"action": "drop"}, {"target_number": "900"}):
            with self.subTest(extra=list(extra)):
                response = await self.client.post("/v1/control/call", json=self.call_body(**extra), headers=self.headers())
                self.assertEqual(response.status, 400)
        response = await self.client.post("/v1/control/dnd", json=self.dnd_body(toggle=True), headers=self.headers())
        self.assertEqual(response.status, 400)
        self.assertEqual(self.actions.calls, [])
        self.assertEqual(self.actions.dnd_requests, [])

    async def test_dnd_rejects_values_that_are_not_actual_booleans(self):
        for value in ("true", "false", 1, 0, None, {}, []):
            with self.subTest(value=value):
                response = await self.client.post("/v1/control/dnd", json=self.dnd_body(enabled=value), headers=self.headers())
                self.assertEqual(response.status, 400)
        self.assertEqual(self.actions.dnd_requests, [])

    async def test_required_intent_fields_and_string_types_are_enforced(self):
        for route, original in (("call", self.call_body()), ("dnd", self.dnd_body())):
            for field in ("request_id", "session_id"):
                bodies = []
                missing = dict(original)
                del missing[field]
                bodies.append(missing)
                bodies.extend(dict(original, **{field: value}) for value in (None, 123, {}, [], ""))
                for body in bodies:
                    with self.subTest(route=route, field=field, value=body.get(field)):
                        response = await self.client.post("/v1/control/" + route, json=body, headers=self.headers())
                        self.assertEqual(response.status, 400)
        for value in (123, None, {}, []):
            response = await self.client.post("/v1/control/call", json=self.call_body(target=value), headers=self.headers())
            self.assertEqual(response.status, 400)
        self.assertEqual(self.actions.calls, [])
        self.assertEqual(self.actions.dnd_requests, [])

    async def test_non_object_invalid_json_and_oversized_bodies_do_not_dispatch(self):
        for value in ([], None, "TB", 1):
            response = await self.client.post("/v1/control/call", json=value, headers=self.headers())
            self.assertEqual(response.status, 400)
        response = await self.client.post("/v1/control/call", data=b"{broken", headers=self.headers(**{"Content-Type": "application/json"}))
        self.assertEqual(response.status, 400)
        response = await self.client.post("/v1/control/call", data=b"{" + b"x" * 4000,
                                          headers=self.headers(**{"Content-Type": "application/json"}))
        self.assertEqual(response.status, 413)
        self.assertEqual(self.actions.calls, [])

    async def test_state_exposes_confirmed_presence_but_never_control_secret(self):
        before = copy.deepcopy(self.source.snapshot)
        response = await self.client.get("/v1/state", headers=self.headers(self.read_token))
        self.assertEqual(response.status, 200)
        value = await response.json()
        self.assertEqual(value["own"]["presence"], self.actions.own_presence)
        self.assertTrue(value["controls"]["enabled"])
        rendered = json.dumps(value)
        self.assertNotIn(self.control_token, rendered)
        self.assertNotIn(self.read_token, rendered)
        self.assertEqual(self.source.snapshot, before)

    async def test_disabled_controls_reject_writes_and_are_advertised_disabled(self):
        client = TestClient(TestServer(create_app(self.config, self.source, token=self.read_token)))
        await client.start_server()
        try:
            response = await client.get("/v1/state", headers=self.headers(self.read_token))
            self.assertFalse((await response.json())["controls"]["enabled"])
            for route, body in (("call", self.call_body()), ("dnd", self.dnd_body())):
                response = await client.post("/v1/control/" + route, json=body, headers=self.headers())
                self.assertEqual(response.status, 503)
        finally:
            await client.close()

    async def test_unexpected_backend_error_is_sanitized_json(self):
        marker = "secret-from-fake-backend-should-never-escape"
        self.actions.failure = RuntimeError(marker)
        response = await self.client.post("/v1/control/call", json=self.call_body(), headers=self.headers())
        self.assertEqual(response.status, 500)
        value = await response.json()
        self.assertIsInstance(value, dict)
        self.assertNotIn(marker, json.dumps(value))
        self.assertNotIn(self.control_token, json.dumps(value))

    async def test_action_errors_preserve_http_status_and_safe_code_message(self):
        from bridge.actions import ActionError
        for code, status, message in (
            ("own_busy", 409, "Extension 200 is busy"),
            ("stale_state", 503, "Call state is stale"),
            ("dnd_unavailable", 501, "DND control is unavailable"),
        ):
            with self.subTest(code=code):
                self.actions.failure = ActionError(code, status, message)
                response = await self.client.post("/v1/control/dnd", json=self.dnd_body(),
                                                  headers=self.headers())
                self.assertEqual(response.status, status)
                self.assertEqual(await response.json(), {"error": code, "message": message})
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_control_routes_accept_post_only_and_do_not_expose_call_proxy(self):
        for route in ("call", "dnd"):
            response = await self.client.get("/v1/control/" + route, headers=self.headers())
            self.assertEqual(response.status, 405)
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        for route in ("/callcontrol/200/makecall", "/v1/control/drop", "/v1/control/transfer"):
            response = await self.client.post(route, json={}, headers=self.headers())
            self.assertEqual(response.status, 404)

    async def test_action_shutdown_finishes_before_transport_session_is_closed(self):
        events = []

        class LifecycleSource(FakeSource):
            async def run(self):
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("transport_closed")

        class LifecycleActions(FakeActions):
            async def run(self):
                await asyncio.Event().wait()

            async def close(self):
                events.append("actions_closed")

        client = TestClient(TestServer(create_app(
            self.config, LifecycleSource(), token=self.read_token,
            control_token=self.control_token, actions=LifecycleActions())))
        await client.start_server()
        await asyncio.sleep(0)
        await client.close()
        self.assertIn("actions_closed", events)
        self.assertIn("transport_closed", events)
        self.assertLess(events.index("actions_closed"), events.index("transport_closed"))

    async def test_real_actions_read_supplied_presence_provider_and_close_it_before_transport(self):
        events = []

        class LifecycleSource(FakeSource):
            async def run(self):
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append("transport_closed")

        class PresenceProvider:
            def __init__(self):
                self.read = asyncio.Event()
                self.closed = 0
                self.writes = []

            async def get_presence(self):
                self.read.set()
                return {"state": "available", "profile": "Available", "confirmed": True}

            async def set_dnd(self, enabled):
                self.writes.append(enabled)

            async def close(self):
                self.closed += 1
                events.append("presence_closed")

        provider = PresenceProvider()
        client = TestClient(TestServer(create_app(
            self.config, LifecycleSource(), token=self.read_token,
            control_token=self.control_token, presence_provider=provider)))
        await client.start_server()
        try:
            await asyncio.wait_for(provider.read.wait(), timeout=1)
            for _ in range(5):
                response = await client.get("/v1/state", headers=self.headers(self.read_token))
                value = await response.json()
                if value["own"]["presence"]["confirmed"]:
                    break
                await asyncio.sleep(0)
            self.assertEqual(value["own"]["presence"]["state"], "available")
            self.assertTrue(value["own"]["presence"]["confirmed"])
            self.assertTrue(value["controls"]["dnd"])
            self.assertEqual(provider.writes, [])
        finally:
            await client.close()
        self.assertEqual(provider.closed, 1)
        self.assertLess(events.index("presence_closed"), events.index("transport_closed"))


class ControlTokenConfigurationTests(unittest.TestCase):
    def test_control_token_cannot_be_the_read_token(self):
        token = "same-token-" + "x" * 32
        with self.assertRaises(ValueError):
            create_app({"own_extension": "200", "team": [{"extension": "223"}]},
                       FakeSource(), token=token, control_token=token)

    def test_weak_or_header_unsafe_control_tokens_are_rejected(self):
        for token in ("", "short", "nonascii" + "é" * 30,
                      "contains spaces" * 3, "line-break-" + "x" * 30 + "\r\n"):
            with self.subTest(token=repr(token)), self.assertRaises(ValueError):
                create_app({"own_extension": "200", "team": [{"extension": "223"}]},
                           FakeSource(), token="read-" + "r" * 32,
                           control_token=token)


if __name__ == "__main__":
    unittest.main()
