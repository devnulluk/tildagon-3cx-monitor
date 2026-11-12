import asyncio
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from bridge.transport import BridgeTransportError, ThreeCXTransport, validate_pbx_url


async def eventually(predicate, timeout=2):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), timeout)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tokens = 0
        self.token_status = 200
        self.content_types = []
        self.reads = 0
        self.refuse_once = False
        self.dns = []
        self.details = {}
        self.ws = None
        self.auth_seen = []
        app = web.Application()

        async def token(request):
            self.content_types.append(request.headers.get("Content-Type", ""))
            form = await request.post()
            self.assertEqual(form["grant_type"], "client_credentials")
            self.assertEqual(form["client_id"], "badge")
            self.tokens += 1
            if self.token_status != 200:
                return web.Response(status=self.token_status)
            return web.json_response({"access_token": "token-" + str(self.tokens),
                                      "expires_in": 60})

        async def snapshot(request):
            self.reads += 1
            self.auth_seen.append(request.headers.get("Authorization"))
            if self.refuse_once:
                self.refuse_once = False
                return web.Response(status=401)
            return web.json_response(self.dns)

        async def participant(request):
            detail = self.details.get(int(request.match_info["id"]))
            if detail is None:
                return web.Response(status=404)
            if detail == "failure":
                return web.Response(status=500)
            return web.json_response(detail)

        async def websocket(request):
            self.auth_seen.append(request.headers.get("Authorization"))
            self.ws = web.WebSocketResponse()
            await self.ws.prepare(request)
            async for _ in self.ws:
                pass
            return self.ws

        app.router.add_post("/connect/token", token)
        app.router.add_get("/callcontrol", snapshot)
        app.router.add_get("/callcontrol/ws", websocket)
        app.router.add_get("/callcontrol/{dn}/participants/{id}", participant)
        self.server = TestServer(app)
        await self.server.start_server()
        self.transport = ThreeCXTransport("https://pbx.invalid", "badge", "secret", refresh_seconds=0.03)
        # The runtime constructor forbids HTTP. Tests explicitly replace the
        # private origin to exercise a loopback aiohttp test server.
        self.transport._base_url = str(self.server.make_url("")).rstrip("/")
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1))
        self.transport._session = self.session

    async def asyncTearDown(self):
        await self.session.close()
        await self.server.close()

    async def test_401_renews_token_once_and_empty_snapshot_is_valid(self):
        self.refuse_once = True
        self.assertEqual(await self.transport._fetch_snapshot(), [])
        self.assertEqual(self.tokens, 2)
        self.assertEqual(self.reads, 2)
        self.assertEqual(self.auth_seen, ["Bearer token-1", "Bearer token-2"])

    async def test_default_token_encoding_is_multipart(self):
        self.assertEqual(await self.transport._get_token(), "token-1")
        self.assertTrue(self.content_types[0].startswith("multipart/form-data; boundary="))

    async def test_urlencoded_token_encoding_can_be_selected(self):
        transport = ThreeCXTransport("https://pbx.invalid", "badge", "secret", token_format="urlencoded")
        transport._base_url = self.transport._base_url
        transport._session = self.session
        self.assertEqual(await transport._get_token(), "token-1")
        self.assertEqual(self.content_types, ["application/x-www-form-urlencoded"])

    async def test_rejected_token_does_not_retry_or_echo_secret(self):
        self.token_status = 401
        with self.assertRaises(BridgeTransportError) as rejected:
            await self.transport._get_token()
        self.assertEqual(self.tokens, 1)
        self.assertNotIn("secret", str(rejected.exception))
        self.assertTrue(self.content_types[0].startswith("multipart/form-data"))

    async def test_full_participant_read_404_and_direction_memory(self):
        self.dns = [{"dn": "200", "type": "Wextension", "devices": [],
                     "participants": [{"id": 1}, {"id": 2}]}]
        self.details[1] = {"id": 1, "dn": "200", "status": "Ringing", "callid": 9,
                           "party_did": "+441632960100", "referred_by_dn": "800"}
        snapshot = await self.transport._fetch_snapshot()
        self.assertEqual(len(snapshot[0]["participants"]), 1)
        participant = snapshot[0]["participants"][0]
        self.assertEqual(participant["party_did"], "+441632960100")
        self.assertEqual(participant["_direction"], "inbound")
        self.details[1]["status"] = "Connected"
        snapshot = await self.transport._fetch_snapshot()
        self.assertEqual(snapshot[0]["participants"][0]["_direction"], "inbound")

    async def test_partial_failure_does_not_commit_snapshot(self):
        self.transport._snapshot = [{"dn": "old"}]
        self.dns = [{"dn": "200", "devices": [], "participants": [{"id": 1}]}]
        self.details[1] = "failure"
        with self.assertRaises(BridgeTransportError):
            await self.transport._fetch_snapshot()
        self.assertEqual(self.transport.snapshot, [{"dn": "old"}])

    async def test_malformed_snapshot_fails_closed(self):
        self.dns = {"not": "a snapshot"}
        with self.assertRaises(BridgeTransportError):
            await self.transport._fetch_snapshot()

    async def test_makecall_ringback_is_outbound(self):
        self.dns = [{"dn": "200", "devices": [], "participants": [{"id": 1}]}]
        self.details[1] = {"id": 1, "status": "Ringing", "callid": 1, "party_dn": "MakeCall"}
        snapshot = await self.transport._fetch_snapshot()
        self.assertEqual(snapshot[0]["participants"][0]["_direction"], "outbound")

    async def test_missing_callid_does_not_carry_another_calls_direction(self):
        self.dns = [{"dn": "200", "devices": [], "participants": [{"id": 1}]}]
        self.details[1] = {"id": 1, "status": "Dialing"}
        snapshot = await self.transport._fetch_snapshot()
        self.assertEqual(snapshot[0]["participants"][0]["_direction"], "outbound")
        self.details[1] = {"id": 1, "status": "Connected"}
        snapshot = await self.transport._fetch_snapshot()
        self.assertEqual(snapshot[0]["participants"][0]["_direction"], "unknown")

    async def test_live_websocket_rebuild_and_immediate_disconnect(self):
        self.dns = [{"dn": "200", "devices": [], "participants": []}]
        task = asyncio.create_task(self.transport.run())
        try:
            await eventually(lambda: self.transport.connected)
            initial_reads = self.reads
            await self.ws.send_json(None)
            await eventually(lambda: self.reads > initial_reads)
            await eventually(lambda: self.transport.connected)
            initial_reads = self.reads
            await self.ws.send_json({"sequence": 1, "event": {"event_type": 0,
                                      "entity": "/callcontrol/200"}})
            await eventually(lambda: self.reads > initial_reads)
            await eventually(lambda: self.transport.connected)
            # Sequence gaps cause a rebuild, regardless of event kind.
            initial_reads = self.reads
            await self.ws.send_json({"sequence": 3, "event": {"event_type": 4,
                                      "entity": "request-1"}})
            await eventually(lambda: self.reads > initial_reads)
            await eventually(lambda: self.transport.connected)
            await self.ws.close()
            await eventually(lambda: not self.transport.connected)
            self.assertEqual(self.transport.snapshot[0]["dn"], "200")
            self.assertEqual(self.transport.status, "disconnected")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_refresh_failure_invalidates_previously_live_state(self):
        self.dns = [{"dn": "200", "devices": [], "participants": []}]
        self.transport._ws_connected = True
        self.transport._dirty.set()
        worker = asyncio.create_task(self.transport._refresh_worker())
        try:
            await eventually(lambda: self.transport.connected)
            self.dns = {"broken": True}
            self.transport._invalidate()
            await eventually(lambda: not self.transport.connected)
            self.assertEqual(self.transport.status, "state unavailable")
            self.assertEqual(self.transport.snapshot[0]["dn"], "200")
        finally:
            self.transport._ws_connected = False
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


class TransportConfigurationTests(unittest.TestCase):
    def test_invalid_token_format_fails_without_echoing_value(self):
        with self.assertRaises(ValueError) as rejected:
            ThreeCXTransport("https://pbx.invalid", "badge", "secret", token_format="sensitive_marker")
        self.assertNotIn("sensitive_marker", str(rejected.exception))

    def test_https_origin_required(self):
        self.assertEqual(validate_pbx_url("https://pbx.example:5001/"), "https://pbx.example:5001")
        for value in ("http://pbx.example", "https://user:secret@pbx.example",
                      "https://pbx.example/webclient", "https://pbx.example?token=secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_pbx_url(value)
