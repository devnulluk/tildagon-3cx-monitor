"""Fake-only checks: never contact a PBX or change a real user's presence."""

import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
from http.cookies import SimpleCookie
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import aiohttp
from yarl import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from bridge import presence


def field(number, value):
    if isinstance(value, bytes):
        return presence._varint((number << 3) | 2) + presence._varint(len(value)) + value
    return presence._varint(number << 3) + presence._varint(value)


def message(number, body):
    return field(1, number) + field(number, body)


def myinfo(number="200", current=1, override=None, profiles=None, legacy_dnd=None):
    if profiles is None:
        profiles = {1: "Available", 2: "Away", 3: "Out of office"}
    items = b"".join(field(2, field(2, key) + field(3, name.encode())) for key, name in profiles.items())
    body = field(1, 1) + field(3, number.encode()) + field(10, current) + field(13, items)
    # Private information must never be returned or logged by this provider.
    body += field(23, b"secret-deskphone-password") + field(5, b"private@example.invalid")
    if override is not None:
        body += field(27, 1) + field(28, override)
    if legacy_dnd is not None:
        body += field(14, int(legacy_dnd))
    return message(201, body)


ACK = message(207, field(1, 1))


class Content:
    def __init__(self, body):
        self.body = body
    async def iter_chunked(self, length):
        yield self.body


class Response:
    def __init__(self, value, status=200, cookies=None):
        if isinstance(value, dict) and "sessionKey" in value:
            value = {"pass": "test-session-pass", **value}
        self.body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.status = status
        self.content_length = len(self.body)
        self.content = Content(self.body)
        self.cookies = SimpleCookie()
        if cookies:
            self.cookies.load(cookies)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookie_jar = aiohttp.CookieJar()
        self.ws_calls = []
        self.sockets = []
        self.auto_start = True
        self.initial_frames = []
        self.prefix_frames = []
        self.ws_error = None
        self.closed = False
    async def close(self):
        if not all(socket.closed for socket in self.sockets):
            raise AssertionError("HTTP session closed before notification socket")
        self.closed = True
    async def ws_connect(self, url, **kwargs):
        self.ws_calls.append((url, kwargs))
        if self.ws_error:
            raise self.ws_error
        socket = NotificationSocket(start=self.auto_start)
        for kind, data in self.initial_frames:
            socket.put(kind, data)
        self.sockets.append(socket)
        return socket
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected HTTP call")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if value.cookies:
            self.cookie_jar.update_cookies(value.cookies, response_url=URL(url))
        if (url.endswith("/MyPhone/MPWebService.asmx") and kwargs.get("data") == presence.GET_MY_INFO
                and value.status == 200 and value.body.startswith(bytes.fromhex("08 c9 01"))):
            # Match the actual U9 protocol: HTTP is an acknowledgement and the
            # MyInfo201 payload arrives independently through the WebSocket.
            for kind, data in self.prefix_frames:
                self.sockets[-1].put(kind, data)
            self.sockets[-1].put(aiohttp.WSMsgType.BINARY, value.body)
            return Response(ACK)
        return value


class NotificationSocket:
    def __init__(self, start=True):
        self.closed = False
        self.messages = asyncio.Queue()
        if start:
            self.put(aiohttp.WSMsgType.TEXT, "START")
    def put(self, kind, data):
        self.messages.put_nowait(types.SimpleNamespace(type=kind, data=data))
    def __aiter__(self):
        return self
    async def __anext__(self):
        value = await self.messages.get()
        if value is None:
            raise StopAsyncIteration
        return value
    async def close(self):
        self.closed = True
        self.messages.put_nowait(None)


def auth_responses():
    return [Response({"access_token": "own-access", "expires_in": 3600}), Response({"sessionKey": "own-session"})]


def form_values(data):
    # Inspect the unconsumed FormData supplied to the fake session. The runtime
    # pins aiohttp, whose field records contain name metadata and field value.
    if not isinstance(data, aiohttp.FormData) or not data.is_multipart:
        raise AssertionError("Expected multipart FormData")
    return {headers["name"]: value for headers, unused, value in data._fields}


class PresenceWireTests(unittest.TestCase):
    def test_actual_u9_profiles_ignore_negative_custom_sentinels(self):
        profiles = {406: "Custom 2", 407: "Away", 408: "Out of office", 409: "Custom 1",
                    410: "Available", 0xFFFFFFFFFFFFFFFF: "CUSTOM", 0xFFFFFFFFFFFFFFFE: "CUSTOM"}
        value = presence.decode_my_info(myinfo(current=410, profiles=profiles))
        self.assertEqual(value["state"], "available")
        self.assertEqual(value["profile_id"], 410)
        self.assertEqual(value["profiles"], {key: name for key, name in profiles.items() if key < 2147483648})
        self.assertEqual(presence.decode_my_info(myinfo(current=408, profiles=profiles))["state"], "dnd")
        self.assertEqual(presence.encode_profile_change(value["profile_id"]), bytes.fromhex("08 67 ba 06 03 08 9a 03"))

    def test_myinfo_whitelist_drops_passwords_and_uses_effective_override(self):
        value = presence.decode_my_info(myinfo(override=3))
        self.assertEqual(value["state"], "dnd")
        self.assertEqual(value["number"], "200")
        self.assertNotIn("secret", repr(value))
        self.assertNotIn("private@", repr(value))

    def test_profile_change_has_only_own_profile_id(self):
        encoded = presence.encode_profile_change(3)
        self.assertEqual(encoded, bytes.fromhex("08 67 ba 06 02 08 03"))
        body = presence._message(encoded, 103)
        self.assertEqual(list(presence._fields(body)), [(1, 0, 3)])

    def test_legacy_dnd_contradiction_is_rejected_instead_of_showing_available(self):
        with self.assertRaises(presence.PresenceError) as error:
            presence.decode_my_info(myinfo(current=1, legacy_dnd=True))
        self.assertEqual(str(error.exception), "Legacy DND conflicts with the current profile")
        self.assertEqual(presence.decode_my_info(myinfo(current=3, legacy_dnd=True))["state"], "dnd")
        self.assertEqual(presence.decode_my_info(myinfo(current=1, legacy_dnd=False))["state"], "available")

    def test_malformed_duplicate_and_oversize_messages_are_rejected(self):
        values = [b"\xff", b"\x00", message(201, field(3, b"200") + field(3, b"200")), b"x" * (presence.MAX_RESPONSE + 1)]
        for value in values:
            with self.subTest(value=value[:12]), self.assertRaises(presence.PresenceError):
                presence.decode_my_info(value)

    def test_environment_requires_a_separate_explicit_user_grant(self):
        self.assertIsNone(presence.presence_provider_from_env("https://pbx.invalid", environment={"PBX_CLIENT_SECRET": "service-only"}))
        with self.assertRaises(ValueError):
            presence.presence_provider_from_env("https://pbx.invalid", environment={"PBX_USER_USERNAME": "201", "PBX_USER_PASSWORD": "password"})


class PresenceTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, responses, **kwargs):
        session = Session(responses)
        return presence.MyPhonePresenceProvider("https://pbx.invalid", refresh_token="own-refresh", session=session, **kwargs), session

    async def test_explicit_refresh_grant_then_session_then_safe_presence(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo())])
        value = await provider.get_presence()
        self.assertEqual(value, {"state": "available", "profile": "Available", "confirmed": True, "age_seconds": 0.0})
        self.assertEqual(form_values(session.calls[0][1]["data"]), {"grant_type": "refresh_token", "client_id": "Webclient", "refresh_token": "own-refresh"})
        self.assertEqual(session.calls[1][1]["json"], presence.FINGERPRINT)
        self.assertEqual(session.calls[2][1]["data"], presence.GET_MY_INFO)
        self.assertTrue(all(call[1]["allow_redirects"] is False for call in session.calls))
        self.assertEqual(session.ws_calls[0][0], "wss://pbx.invalid/ws/webclient")
        self.assertEqual(session.ws_calls[0][1]["params"], {"sessionId": "own-session", "pass": "test-session-pass"})
        self.assertEqual(session.ws_calls[0][1]["origin"], "https://pbx.invalid")

    async def test_http_get_myinfo_waits_for_start_before_request(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo())])
        session.auto_start = False
        task = asyncio.create_task(provider.get_presence())
        for _ in range(100):
            if session.sockets:
                break
            await asyncio.sleep(0.001)
        self.assertTrue(session.sockets)
        self.assertEqual(len(session.calls), 2)  # No GetMyInfo before START.
        session.sockets[0].put(aiohttp.WSMsgType.TEXT, "ADDP")
        await asyncio.sleep(0)
        self.assertEqual(len(session.calls), 2)
        session.sockets[0].put(aiohttp.WSMsgType.TEXT, "START")
        self.assertEqual((await asyncio.wait_for(task, 1))["state"], "available")
        await provider.close()

    async def test_stale_full_frames_and_partial_updates_do_not_confirm_readback(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo())])
        session.initial_frames = [(aiohttp.WSMsgType.BINARY, myinfo(current=3))]
        partial = message(201, field(1, 3) + field(10, 3))
        session.prefix_frames = [(aiohttp.WSMsgType.TEXT, "ADDP"), (aiohttp.WSMsgType.BINARY, partial)]
        self.assertEqual((await provider.get_presence())["state"], "available")
        await provider.close()

    async def test_websocket_failures_never_expose_private_session_url(self):
        provider, session = self.provider(auth_responses() + auth_responses())
        session.ws_error = aiohttp.ClientError("wss://pbx.invalid/ws/webclient?pass=private-pass-marker")
        with self.assertRaises(presence.PresenceError) as rejected:
            await provider.get_presence()
        self.assertNotIn("private-pass-marker", str(rejected.exception))
        self.assertNotIn("wss://", str(rejected.exception))
        self.assertEqual(len(session.ws_calls), 2)

    async def test_close_stops_reader_and_socket(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo())])
        await provider.get_presence()
        socket = session.sockets[0]
        self.assertFalse(socket.closed)
        await provider.close()
        self.assertTrue(socket.closed)
        self.assertIsNone(provider._ws_reader)

    async def test_access_token_renewal_uses_rotated_refresh_grant(self):
        provider, session = self.provider([
            Response({"access_token": "first-access", "expires_in": 3600, "refresh_token": "first-rotated"}),
            Response({"sessionKey": "own-session"}), Response(myinfo()),
            Response({"access_token": "second-access", "expires_in": 3600, "refresh_token": "second-rotated"}),
            Response(myinfo()),
        ])
        await provider.get_presence()
        provider._token_deadline = 0
        self.assertEqual((await provider.get_presence())["state"], "available")
        self.assertEqual(form_values(session.calls[3][1]["data"])["refresh_token"], "first-rotated")
        self.assertEqual(provider._refresh_token, "second-rotated")
        self.assertEqual(len([url for url, _ in session.calls if url.endswith("/MyPhone/session")]), 1)

    async def test_expired_read_session_reauthenticates_and_rebuilds_once(self):
        provider, session = self.provider(auth_responses() + [
            Response(b"", 401), Response({"access_token": "new-access", "expires_in": 3600}),
            Response({"sessionKey": "new-session"}), Response(myinfo()),
        ])
        self.assertEqual((await provider.get_presence())["state"], "available")
        self.assertEqual(len(session.calls), 6)
        self.assertEqual(session.calls[2][1]["headers"]["MyPhoneSession"], "own-session")
        self.assertEqual(session.calls[5][1]["headers"]["MyPhoneSession"], "new-session")
        self.assertFalse(provider._auth_failed)

    async def test_dnd_on_checks_own_identity_writes_once_and_confirms_readback(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(ACK), Response(myinfo(current=3))])
        value = await provider.set_dnd(True)
        self.assertEqual(value["state"], "dnd")
        writes = [kwargs["data"] for _, kwargs in session.calls if isinstance(kwargs.get("data"), bytes) and kwargs["data"] != presence.GET_MY_INFO]
        self.assertEqual(writes, [presence.encode_profile_change(3)])

    async def test_dnd_off_uses_own_available_profile(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(current=3)), Response(ACK), Response(myinfo())])
        self.assertEqual((await provider.set_dnd(False))["state"], "available")
        self.assertEqual(session.calls[3][1]["data"], presence.encode_profile_change(1))

    async def test_actual_u9_sentinel_profiles_do_not_block_own_dnd_change(self):
        profiles = {406: "Custom 2", 407: "Away", 408: "Out of office", 409: "Custom 1",
                    410: "Available", 0xFFFFFFFFFFFFFFFF: "CUSTOM", 0xFFFFFFFFFFFFFFFE: "CUSTOM"}
        provider, session = self.provider(auth_responses() + [
            Response(myinfo(current=410, profiles=profiles)), Response(ACK),
            Response(myinfo(current=408, profiles=profiles)),
        ])
        value = await provider.set_dnd(True)
        self.assertEqual(value["state"], "dnd")
        self.assertEqual(session.calls[3][1]["data"], presence.encode_profile_change(408))
        writes = [kwargs["data"] for _, kwargs in session.calls
                  if isinstance(kwargs.get("data"), bytes) and kwargs["data"] != presence.GET_MY_INFO]
        self.assertEqual(len(writes), 1)
        await provider.close()

    async def test_wrong_own_identity_cannot_write(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(number="201"))])
        with self.assertRaises(presence.PresenceAuthError):
            await provider.set_dnd(True)
        self.assertEqual(len(session.calls), 3)

    async def test_legacy_dnd_contradiction_blocks_both_write_directions(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                provider, session = self.provider(auth_responses() + [Response(myinfo(legacy_dnd=True))])
                with self.assertRaises(presence.PresenceError) as error:
                    await provider.set_dnd(enabled)
                self.assertEqual(str(error.exception), "Legacy DND conflicts with the current profile")
                self.assertEqual(len(session.calls), 3)
                self.assertEqual(session.calls[-1][1]["data"], presence.GET_MY_INFO)

    async def test_no_write_when_already_at_requested_profile(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(current=3))])
        self.assertEqual((await provider.set_dnd(True))["state"], "dnd")
        self.assertEqual(len(session.calls), 3)

    async def test_write_disconnect_has_no_automatic_retry(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), asyncio.TimeoutError()])
        with self.assertRaises(asyncio.TimeoutError):
            await provider.set_dnd(True)
        self.assertEqual(len(session.calls), 4)

    async def test_failed_ack_is_not_a_success_and_never_retries_write(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(message(207, field(1, 0) + field(5, b"private-error")))])
        with self.assertRaises(presence.PresenceError) as error:
            await provider.set_dnd(True)
        self.assertNotIn("private-error", str(error.exception))
        self.assertEqual(len(session.calls), 4)

    async def test_dnd_requires_expected_profile_to_exist(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(profiles={1: "Available"}))])
        with self.assertRaises(presence.PresenceError):
            await provider.set_dnd(True)
        self.assertEqual(len(session.calls), 3)

    async def test_auth_failure_is_latched_to_prevent_password_lockout_retries(self):
        provider, session = self.provider([Response({"error": "invalid_grant"}, 400)])
        for _ in range(2):
            with self.assertRaises(presence.PresenceAuthError):
                await provider.get_presence()
        self.assertEqual(len(session.calls), 1)

    async def test_password_bootstrap_uses_explicit_own_username_and_refresh_cookie_flow(self):
        session = Session([Response({"Status": "AuthSuccess"})] + auth_responses() + [Response(myinfo())])
        provider = presence.MyPhonePresenceProvider("https://pbx.invalid", username="200", password="own-password", security_code="123456", session=session)
        await provider.get_presence()
        self.assertEqual(session.calls[0][1]["json"], {"Username": "200", "Password": "own-password", "SecurityCode": "123456"})
        self.assertEqual(form_values(session.calls[1][1]["data"]), {"grant_type": "refresh_token", "client_id": "Webclient"})

    async def test_required_second_factor_does_not_retry_login(self):
        session = Session([Response({"Status": "Required2FA"})])
        provider = presence.MyPhonePresenceProvider("https://pbx.invalid", password="own-password", session=session)
        for _ in range(2):
            with self.assertRaises(presence.PresenceAuthError):
                await provider.get_presence()
        self.assertEqual(len(session.calls), 1)


class PersistentGrantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "own-user-grant.json"

    async def asyncTearDown(self):
        self.temp.cleanup()

    def stored(self, **changes):
        value = {"version": 1, "origin": "https://pbx.invalid", "own_extension": "200",
                 "refresh_token": "stored-refresh", "cookies": []}
        value.update(changes)
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def factory(self, **environment):
        return presence.presence_provider_from_env("https://pbx.invalid", environment={
            "PBX_USER_TOKEN_FILE": str(self.path), **environment})

    async def test_missing_store_without_bootstrap_disables_provider(self):
        self.assertIsNone(self.factory())

    async def test_rotated_refresh_grant_survives_restart_without_password(self):
        session = Session([Response({"access_token": "private-access", "expires_in": 3600,
                                     "refresh_token": "rotated-first"}),
                           Response({"sessionKey": "own-session"}), Response(myinfo())])
        provider = presence.MyPhonePresenceProvider("https://pbx.invalid", refresh_token="initial-refresh",
                                                    session=session, token_file=self.path)
        with patch.object(presence.os, "chmod", wraps=os.chmod) as chmod:
            await provider.get_presence()
        self.assertTrue(any(call.args[1] == 0o600 for call in chmod.call_args_list))
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "rotated-first")
        self.assertNotIn("private-access", self.path.read_text())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        restarted = self.factory()
        restarted._session = Session([
            Response({"access_token": "new-private-access", "expires_in": 3600, "refresh_token": "rotated-second"}),
            Response({"sessionKey": "new-session"}), Response(myinfo()),
        ])
        self.assertEqual((await restarted.get_presence())["state"], "available")
        self.assertEqual(form_values(restarted._session.calls[0][1]["data"])["refresh_token"], "rotated-first")
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "rotated-second")

    async def test_cookie_only_grant_is_narrow_and_survives_restart(self):
        session = Session([
            Response({"Status": "AuthSuccess"}, cookies="refresh-cookie=first-private-cookie; Path=/; Secure; HttpOnly; Max-Age=3600"),
            Response({"access_token": "private-access", "expires_in": 3600},
                     cookies="refresh-cookie=rotated-private-cookie; Path=/; Secure; HttpOnly; SameSite=lax; Max-Age=3600"),
            Response({"sessionKey": "own-session"}), Response(myinfo()),
        ])
        irrelevant = SimpleCookie()
        irrelevant.load("unrelated=not-an-auth-cookie; Path=/unrelated; Secure")
        session.cookie_jar.update_cookies(irrelevant, response_url=URL("https://pbx.invalid/unrelated"))
        session.cookie_jar.update_cookies({"alien": "foreign-cookie"}, response_url=URL("https://alien.invalid/"))
        provider = presence.MyPhonePresenceProvider("https://pbx.invalid", password="private-password",
                                                    security_code="654321", session=session, token_file=self.path)
        await provider.get_presence()
        stored = json.loads(self.path.read_text())
        self.assertIsNone(stored["refresh_token"])
        self.assertEqual(len(stored["cookies"]), 1)
        self.assertEqual(stored["cookies"][0]["name"], "refresh-cookie")
        self.assertEqual(stored["cookies"][0]["value"], "rotated-private-cookie")
        self.assertTrue(stored["cookies"][0]["http_only"])
        self.assertEqual(stored["cookies"][0]["same_site"], "Lax")
        deadline = stored["cookies"][0]["expires_at"]
        self.assertGreater(deadline, presence.time.time())
        for secret in ("private-password", "654321", "private-access", "foreign-cookie", "not-an-auth-cookie"):
            self.assertNotIn(secret, self.path.read_text())
        restarted = self.factory()
        restarted._session = Session(auth_responses() + [Response(myinfo())])
        await restarted.get_presence()
        self.assertEqual(form_values(restarted._session.calls[0][1]["data"]),
                         {"grant_type": "refresh_token", "client_id": "Webclient"})
        restored = restarted._session.cookie_jar.filter_cookies(URL("https://pbx.invalid/connect/token"))
        self.assertEqual(restored["refresh-cookie"].value, "rotated-private-cookie")
        self.assertEqual(len(restarted._session.cookie_jar.filter_cookies(URL("https://other.pbx.invalid/connect/token"))), 0)
        restored_deadline = next(iter(restarted._session.cookie_jar._expirations.values()))
        self.assertLessEqual(restored_deadline, deadline)
        self.assertGreaterEqual(restored_deadline, deadline - 1)

    async def test_wrong_origin_identity_and_malformed_store_fail_closed(self):
        for changes in ({"origin": "https://different.invalid"}, {"own_extension": "201"},
                        {"cookies": "private-malformed-marker"}):
            with self.subTest(changes=changes):
                self.stored(**changes)
                with self.assertRaises(presence.PresenceAuthError) as rejected:
                    self.factory()
                self.assertNotIn("private-malformed-marker", str(rejected.exception))
                self.assertNotIn("different.invalid", str(rejected.exception))
        self.path.write_text('{"private-password-marker":', encoding="utf-8")
        with self.assertRaises(presence.PresenceAuthError) as rejected:
            self.factory()
        self.assertNotIn("private-password-marker", str(rejected.exception))

    async def test_expired_cookie_only_grant_is_refused_without_replaying_it(self):
        self.stored(refresh_token=None, cookies=[{
            "name": "refresh-cookie", "value": "expired-private-cookie", "path": "/",
            "secure": True, "http_only": True, "same_site": "lax",
            "expires_at": presence.time.time() - 60,
        }])
        with self.assertRaises(presence.PresenceAuthError) as error:
            self.factory()
        self.assertNotIn("expired-private-cookie", str(error.exception))

    async def test_fresh_password_and_code_replace_any_bad_store_without_loading_it(self):
        self.path.write_text("invalid private previous grant", encoding="utf-8")
        provider = self.factory(PBX_USER_PASSWORD="private-password", PBX_USER_SECURITY_CODE="654321")
        provider._session = Session([Response({"Status": "AuthSuccess"})] + [
            Response({"access_token": "private-access", "expires_in": 3600, "refresh_token": "new-grant"}),
            Response({"sessionKey": "own-session"}), Response(myinfo()),
        ])
        await provider.get_presence()
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "new-grant")
        self.assertEqual(len(provider._session.cookie_jar), 0)
        self.assertNotIn("private-password", self.path.read_text())

    async def test_wrong_fresh_user_identity_is_never_persisted(self):
        provider = self.factory(PBX_USER_PASSWORD="private-password", PBX_USER_SECURITY_CODE="654321")
        provider._session = Session([Response({"Status": "AuthSuccess"})] + auth_responses() + [Response(myinfo(number="201"))])
        with self.assertRaises(presence.PresenceAuthError):
            await provider.get_presence()
        self.assertFalse(self.path.exists())

    async def test_full_own_identity_persists_grant_even_if_profile_is_unrecognized(self):
        provider = self.factory(PBX_USER_PASSWORD="private-password", PBX_USER_SECURITY_CODE="654321")
        provider._session = Session([Response({"Status": "AuthSuccess"}, cookies="refresh-cookie=private-refresh; Path=/; Secure; HttpOnly")] + auth_responses() + [
            Response(myinfo(current=0, profiles={0: "Available"})),
        ])
        with self.assertRaises(presence.PresenceError):
            await provider.get_presence()
        stored = json.loads(self.path.read_text())
        self.assertEqual(stored["own_extension"], "200")
        self.assertTrue(stored["refresh_token"] or stored["cookies"])
        await provider.close()

    async def test_server_returned_own_jwt_can_preserve_grant_before_myinfo(self):
        encoded = base64.urlsafe_b64encode(json.dumps({"unique_name": "200"}).encode()).decode().rstrip("=")
        provider = self.factory(PBX_USER_PASSWORD="private-password", PBX_USER_SECURITY_CODE="654321")
        provider._session = Session([
            Response({"Status": "AuthSuccess"}),
            Response({"access_token": "header." + encoded + ".signature", "expires_in": 3600,
                      "refresh_token": "own-rotated-refresh"}),
        ])
        await provider._token()
        self.assertEqual(json.loads(self.path.read_text())["refresh_token"], "own-rotated-refresh")

    async def test_atomic_replace_failure_keeps_previous_grant_and_removes_temporary(self):
        self.stored()
        original = self.path.read_bytes()
        provider = self.factory()
        provider._session = Session([
            Response({"access_token": "private-access", "expires_in": 3600, "refresh_token": "next-grant"}),
            Response({"sessionKey": "own-session"}), Response(myinfo()),
        ])
        with patch.object(presence.os, "replace", side_effect=OSError("private-storage-error")):
            with self.assertRaises(presence.PresenceError) as error:
                await provider.get_presence()
        self.assertNotIn("private-storage-error", str(error.exception))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
