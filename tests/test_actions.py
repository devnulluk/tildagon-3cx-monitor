import asyncio
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from bridge.actions import ActionController, ActionError


class Source:
    connected = True
    age_seconds = 0.0

    def __init__(self):
        self.snapshot = [{"dn": "200", "devices": [{"dn": "200"}], "participants": []}]

    async def _get_token(self):
        return "test-pbx-token"

    async def _json(self, response):
        return await response.json()


class PresenceProvider:
    def __init__(self):
        self.state = "available"
        self.writes = []
        self.reads = 0
        self.ignore_write = False
        self.fail_read = False

    async def get_presence(self):
        self.reads += 1
        if self.fail_read:
            raise RuntimeError("private provider detail")
        return {"state": self.state, "confirmed": True,
                "profile": "Out of office" if self.state == "dnd" else "Available"}

    async def set_dnd(self, enabled):
        self.writes.append(enabled)
        if not self.ignore_write:
            self.state = "dnd" if enabled else "available"


CONFIG = {"own_extension": "200", "stale_after_seconds": 5,
          "speed_dials": [{"id": "TB", "label": "TB", "number": "223"},
                          {"id": "KZ", "label": "Partner", "number": "+441632960005"}]}


class ActionsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source = Source()
        self.posts = []
        self.response_status = 202
        self.response_body = {"finalstatus": "Success", "result": None}
        self.hold = None
        self.entered = asyncio.Event()
        app = web.Application()

        async def make_call(request):
            self.assertEqual(request.match_info["dn"], "200")
            self.assertEqual(request.headers["Authorization"], "Bearer test-pbx-token")
            self.posts.append(await request.json())
            self.entered.set()
            if self.hold:
                await self.hold.wait()
            return web.json_response(self.response_body, status=self.response_status)

        app.router.add_post("/callcontrol/{dn}/makecall", make_call)
        self.server = TestServer(app)
        await self.server.start_server()
        self.source._base_url = str(self.server.make_url("")).rstrip("/")
        self.source._session = aiohttp.ClientSession()
        self.actions = ActionController(self.source, CONFIG)

    async def asyncTearDown(self):
        if self.hold:
            self.hold.set()
        await self.actions.close()
        await self.source._session.close()
        await self.server.close()

    async def call(self, target="TB", request_id="a" * 32, session_id=None):
        return await self.actions.make_call(target, request_id,
                                            self.actions.session_id if session_id is None else session_id)

    async def test_only_configured_own_extension_and_server_destination_used(self):
        result = await self.call()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.posts, [{"destination": "223"}])

    async def test_external_number_not_disclosed_in_capabilities(self):
        caps = self.actions.capabilities()
        self.assertTrue(caps["call"])
        self.assertFalse(caps["dnd"])
        self.assertEqual(caps["targets"], [{"id": "TB", "label": "TB", "extension": "223"},
                                                {"id": "KZ", "label": "Partner"}])
        self.assertEqual(self.actions.own_presence["state"], "unknown")
        self.assertFalse(self.actions.own_presence["confirmed"])

    async def test_raw_or_unknown_destination_is_rejected(self):
        for target in ("999", "+441632960005", "*32", "other", {"number": "223"}):
            with self.subTest(target=target), self.assertRaises(ActionError) as error:
                await self.call(target=target)
            self.assertEqual(error.exception.http_status, 400)
        self.assertEqual(self.posts, [])

    async def test_stale_server_epoch_is_rejected_before_post(self):
        with self.assertRaises(ActionError) as error:
            await self.call(session_id="previous-server-session")
        self.assertEqual(error.exception.code, "stale_session")
        self.assertEqual(self.posts, [])

    async def test_request_id_is_required(self):
        for request_id in (None, "short", "x" * 97, "whitespace is invalid"):
            with self.subTest(request_id=request_id), self.assertRaises(ActionError):
                await self.call(request_id=request_id)
        self.assertEqual(self.posts, [])

    async def test_identical_request_returns_cached_result_without_second_call(self):
        first = await self.call()
        second = await self.call()
        self.assertEqual(first, second)
        self.assertEqual(len(self.posts), 1)

    async def test_same_request_id_with_different_body_is_conflict(self):
        await self.call()
        with self.assertRaises(ActionError) as error:
            await self.call(target="KZ")
        self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assertEqual(len(self.posts), 1)

    async def test_new_request_is_rate_limited_during_cooldown(self):
        await self.call()
        with self.assertRaises(ActionError) as error:
            await self.call(request_id="b" * 32)
        self.assertEqual(error.exception.code, "cooldown")
        self.assertEqual(error.exception.http_status, 429)

    async def test_concurrent_duplicate_is_one_write_and_other_request_blocked(self):
        self.hold = asyncio.Event()
        first = asyncio.create_task(self.call())
        await asyncio.wait_for(self.entered.wait(), 1)
        duplicate = asyncio.create_task(self.call())
        with self.assertRaises(ActionError) as error:
            await self.call(request_id="b" * 32)
        self.assertEqual(error.exception.code, "action_in_progress")
        self.hold.set()
        self.assertEqual(await first, await duplicate)
        self.assertEqual(len(self.posts), 1)

    async def test_caller_cancellation_does_not_cancel_or_repeat_write(self):
        self.hold = asyncio.Event()
        first = asyncio.create_task(self.call())
        await asyncio.wait_for(self.entered.wait(), 1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.hold.set()
        result = await self.call()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(self.posts), 1)

    async def test_timeout_is_unknown_and_cached_without_retry(self):
        self.actions.REQUEST_TIMEOUT = 0.2
        self.hold = asyncio.Event()
        request = asyncio.create_task(self.call())
        await asyncio.wait_for(self.entered.wait(), 1)
        result = await request
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(await self.call(), result)
        self.assertEqual(len(self.posts), 1)
        self.hold.set()

    async def test_rejected_authorization_is_not_retried(self):
        self.response_status = 401
        for _ in range(2):
            with self.assertRaises(ActionError) as error:
                await self.call()
            self.assertEqual(error.exception.code, "pbx_rejected")
        self.assertEqual(len(self.posts), 1)

    async def test_rejected_operation_does_not_expose_pbx_detail(self):
        self.response_body = {"finalstatus": "Failed", "reasontext": "sensitive-marker"}
        with self.assertRaises(ActionError) as error:
            await self.call()
        self.assertNotIn("sensitive-marker", str(error.exception))

    async def test_http_5xx_is_unknown_without_retry(self):
        self.response_status = 500
        result = await self.call()
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(await self.call(), result)
        self.assertEqual(len(self.posts), 1)

    async def test_offline_stale_unregistered_busy_are_blocked(self):
        situations = [
            (False, 0, [{"dn": "200", "devices": [{}], "participants": []}], "bridge_offline"),
            (True, 6, [{"dn": "200", "devices": [{}], "participants": []}], "stale_state"),
            (True, float("inf"), [], "stale_state"),
            (True, 0, [], "own_unavailable"),
            (True, 0, [{"dn": "200", "devices": [], "participants": []}], "own_unavailable"),
            (True, 0, [{"dn": "200", "devices": [{}], "participants": [{"status": "Connected"}]}], "own_busy"),
        ]
        for index, (connected, age, snapshot, code) in enumerate(situations):
            with self.subTest(code=code):
                self.source.connected, self.source.age_seconds, self.source.snapshot = connected, age, snapshot
                actions = ActionController(self.source, CONFIG)
                with self.assertRaises(ActionError) as error:
                    await actions.make_call("TB", str(index) * 32, actions.session_id)
                self.assertEqual(error.exception.code, code)
                self.assertFalse(actions.capabilities()["call"])
                await actions.close()
        self.assertEqual(self.posts, [])

    async def test_history_is_never_evicted_to_allow_a_duplicate(self):
        self.actions.MAX_HISTORY = 1
        self.actions.COOLDOWN_SECONDS = 0
        first = await self.call()
        with self.assertRaises(ActionError) as error:
            await self.call(request_id="b" * 32)
        self.assertEqual(error.exception.code, "history_full")
        self.assertEqual(await self.call(), first)
        self.assertEqual(len(self.posts), 1)

    async def test_demo_call_never_contacts_pbx(self):
        demo = ActionController(self.source, CONFIG, demo=True)
        result = await demo.make_call("TB", "a" * 32, demo.session_id)
        self.assertEqual(result["status"], "demo")
        self.assertEqual(self.posts, [])
        await demo.close()

    async def test_dnd_unsupported_default_does_not_claim_state(self):
        with self.assertRaises(ActionError) as error:
            await self.actions.set_dnd(True, "a" * 32, self.actions.session_id)
        self.assertEqual(error.exception.code, "dnd_unavailable")
        self.assertEqual(self.posts, [])

    async def test_dnd_write_once_and_confirm_from_fresh_readback(self):
        provider = PresenceProvider()
        actions = ActionController(self.source, CONFIG, presence_provider=provider)
        result = await actions.set_dnd(True, "a" * 32, actions.session_id)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(provider.writes, [True])
        self.assertEqual(provider.reads, 2)
        self.assertTrue(actions.own_presence["confirmed"])
        self.assertEqual(actions.own_presence["state"], "dnd")
        self.assertEqual(await actions.set_dnd(True, "a" * 32, actions.session_id), result)
        self.assertEqual(provider.writes, [True])
        await actions.close()

    async def test_dnd_already_requested_state_does_not_write(self):
        provider = PresenceProvider()
        actions = ActionController(self.source, CONFIG, presence_provider=provider)
        result = await actions.set_dnd(False, "a" * 32, actions.session_id)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(provider.writes, [])
        await actions.close()

    async def test_dnd_unconfirmed_write_is_unknown_and_never_retried(self):
        provider = PresenceProvider()
        provider.ignore_write = True
        actions = ActionController(self.source, CONFIG, presence_provider=provider)
        result = await actions.set_dnd(True, "a" * 32, actions.session_id)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(await actions.set_dnd(True, "a" * 32, actions.session_id), result)
        self.assertFalse(actions.own_presence["confirmed"])
        self.assertEqual(provider.writes, [True])
        await actions.close()

    async def test_dnd_requires_boolean_and_readable_current_presence(self):
        provider = PresenceProvider()
        actions = ActionController(self.source, CONFIG, presence_provider=provider)
        with self.assertRaises(ActionError):
            await actions.set_dnd("true", "a" * 32, actions.session_id)
        provider.fail_read = True
        with self.assertRaises(ActionError) as error:
            await actions.set_dnd(True, "a" * 32, actions.session_id)
        self.assertEqual(error.exception.code, "presence_unavailable")
        self.assertNotIn("private provider detail", str(error.exception))
        self.assertEqual(provider.writes, [])
        await actions.close()

    async def test_presence_becomes_unknown_when_stale_or_disconnected(self):
        self.actions._set_presence({"state": "dnd", "profile": "Out of office", "confirmed": True})
        self.assertEqual(self.actions.own_presence["state"], "dnd")
        self.actions._presence_age = 6
        self.assertEqual(self.actions.own_presence["state"], "unknown")
        self.assertFalse(self.actions.own_presence["confirmed"])
        self.actions._presence_age = 0
        self.source.connected = False
        self.assertFalse(self.actions.own_presence["confirmed"])


class ActionsConfigurationTests(unittest.TestCase):
    def test_invalid_speed_dials_are_rejected_without_echoing_numbers(self):
        for targets in ([{"id": "TB", "number": "*32"}],
                        [{"id": "TB", "number": "223"}, {"id": "TB", "number": "224"}],
                        [{"id": "TB", "number": "sensitive-number-marker"}]):
            with self.subTest(targets=targets), self.assertRaises(ValueError) as error:
                ActionController(Source(), dict(CONFIG, speed_dials=targets))
            self.assertNotIn("sensitive-number-marker", str(error.exception))
