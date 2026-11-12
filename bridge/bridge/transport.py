"""Authenticated, read-only access to the supported 3CX Call Control API.

Only token acquisition uses POST. All PBX state reads use GET; this module
contains no call actions, audio endpoints, or remote request proxy.
"""

import asyncio
import json
import logging
import math
import time
from urllib.parse import quote, urlsplit

import aiohttp


LOG = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class BridgeTransportError(Exception):
    """A deliberately sanitized PBX failure safe to show in bridge diagnostics."""


def validate_pbx_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("PBX_URL must be an HTTPS origin without credentials or a path")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("PBX_URL has an invalid port") from exc
    return value.rstrip("/")


class ThreeCXTransport:
    def __init__(self, url, client_id, client_secret, refresh_seconds=2.0,
                 request_timeout=8.0, token_format="multipart"):
        self._base_url = validate_pbx_url(url)
        if not client_id or not client_secret:
            raise ValueError("PBX_CLIENT_ID and PBX_CLIENT_SECRET are required")
        self._client_id = client_id
        self._client_secret = client_secret
        if token_format not in ("multipart", "urlencoded"):
            raise ValueError("PBX_TOKEN_FORMAT must be multipart or urlencoded")
        self._token_format = token_format
        self._refresh_seconds = float(refresh_seconds)
        if not math.isfinite(self._refresh_seconds) or self._refresh_seconds <= 0:
            raise ValueError("Refresh interval must be positive")
        self._request_timeout = request_timeout
        self._session = None
        self._token = None
        self._token_deadline = 0.0
        self._token_lock = asyncio.Lock()
        self._read_limit = asyncio.Semaphore(4)
        self._dirty = asyncio.Event()
        self._generation = 0
        self._snapshot = []
        self._last_success = None
        self._ws_connected = False
        self._healthy = False
        self._status = "connecting"
        self._directions = {}

    @property
    def snapshot(self):
        return self._snapshot

    @property
    def age_seconds(self):
        if self._last_success is None:
            return float("inf")
        return max(0.0, time.monotonic() - self._last_success)

    @property
    def connected(self):
        return self._ws_connected and self._healthy

    @property
    def status(self):
        return self._status

    async def _json(self, response):
        if response.content_length and response.content_length > MAX_RESPONSE_BYTES:
            raise BridgeTransportError("PBX response too large")
        data = bytearray()
        async for chunk in response.content.iter_chunked(16384):
            data.extend(chunk)
            if len(data) > MAX_RESPONSE_BYTES:
                raise BridgeTransportError("PBX response too large")
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BridgeTransportError("Invalid PBX response") from exc

    async def _get_token(self):
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_deadline:
                return self._token
            form = {"grant_type": "client_credentials", "client_id": self._client_id,
                    "client_secret": self._client_secret}
            if self._token_format == "multipart":
                # The original official 3CX Call Control example uses multipart,
                # including its May 2026 version before PBX V20 Update 9. Newer
                # examples also support URL encoding; select it explicitly when
                # needed rather than retrying credentials in another format.
                form_data = aiohttp.FormData(default_to_multipart=True)
                for name, value in form.items():
                    form_data.add_field(name, value)
            else:
                form_data = form
            async with self._session.post(self._base_url + "/connect/token", data=form_data,
                                          allow_redirects=False) as response:
                if response.status != 200:
                    raise BridgeTransportError("PBX authentication failed")
                body = await self._json(response)
            if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
                raise BridgeTransportError("Invalid PBX token response")
            token = body["access_token"]
            try:
                lifetime = float(body.get("expires_in", 3600))
            except (ValueError, TypeError) as exc:
                raise BridgeTransportError("Invalid PBX token lifetime") from exc
            if not token or not math.isfinite(lifetime) or lifetime <= 0:
                raise BridgeTransportError("Invalid PBX token response")
            self._token = token
            self._token_deadline = time.monotonic() + max(0.1, lifetime * 0.8)
            return token

    async def _get(self, path, allow_missing=False):
        # Paths are generated locally from validated snapshot fields, never from
        # a WebSocket event or an incoming badge request.
        for attempt in range(2):
            token = await self._get_token()
            async with self._session.get(self._base_url + path,
                                         headers={"Authorization": "Bearer " + token,
                                                  "Accept": "application/json"},
                                         allow_redirects=False) as response:
                if response.status == 401 and attempt == 0:
                    if self._token == token:
                        self._token = None
                    continue
                if response.status == 404 and allow_missing:
                    return None
                if response.status != 200:
                    raise BridgeTransportError("PBX state read failed")
                return await self._json(response)
        raise BridgeTransportError("PBX authorization failed")

    async def _participant(self, dn, summary):
        if not isinstance(summary, dict) or not isinstance(summary.get("id"), int):
            raise BridgeTransportError("Invalid participant summary")
        participant_id = summary["id"]
        if participant_id < 0 or isinstance(participant_id, bool):
            raise BridgeTransportError("Invalid participant identifier")
        path = "/callcontrol/{}/participants/{}".format(quote(dn, safe=""), participant_id)
        async with self._read_limit:
            detail = await self._get(path, allow_missing=True)
        if detail is None:
            return None
        if (not isinstance(detail, dict) or not isinstance(detail.get("id"), int)
                or isinstance(detail.get("id"), bool) or detail.get("id") != participant_id
                or detail.get("dn", dn) != dn
                or not isinstance(detail.get("status"), str)):
            raise BridgeTransportError("Invalid participant state")
        return dict(detail, dn=dn)

    async def _fetch_snapshot(self):
        dns = await self._get("/callcontrol")
        if not isinstance(dns, list):
            raise BridgeTransportError("Invalid PBX state snapshot")
        result = []
        seen = set()
        for entry in dns:
            if (not isinstance(entry, dict) or not isinstance(entry.get("dn"), str)
                    or not entry["dn"] or entry["dn"] in seen
                    or not isinstance(entry.get("participants"), list)
                    or not isinstance(entry.get("devices"), list)):
                raise BridgeTransportError("Invalid DN state")
            seen.add(entry["dn"])
            # gather retains only complete snapshots. Any failed detail read
            # fails the refresh, while a 404 means a leg ended during the read.
            details = await asyncio.gather(*[
                self._participant(entry["dn"], item) for item in entry["participants"]
            ])
            result.append(dict(entry, participants=[p for p in details if p is not None]))
        directions = {}
        for entry in result:
            for participant in entry["participants"]:
                callid = participant.get("callid")
                valid_callid = (isinstance(callid, int) and not isinstance(callid, bool) and callid > 0)
                key = (entry["dn"], callid)
                direction = self._directions.get(key, "unknown") if valid_callid else "unknown"
                if (participant.get("party_dn") == "MakeCall"
                        or participant.get("party_caller_id") == "MakeCall"):
                    direction = "outbound"
                elif participant.get("originated_by_dn") == entry["dn"]:
                    direction = "outbound"
                elif direction == "unknown":
                    if participant["status"] == "Dialing":
                        direction = "outbound"
                    elif participant["status"] == "Ringing":
                        direction = "inbound"
                if valid_callid:
                    directions[key] = direction
                participant["_direction"] = direction
        self._directions = directions
        return result

    def _invalidate(self, sequence_gap=False):
        self._generation += 1
        self._dirty.set()
        if sequence_gap:
            self._healthy = False
            self._status = "resynchronizing"

    async def _refresh_worker(self):
        while self._ws_connected:
            try:
                await asyncio.wait_for(self._dirty.wait(), self._refresh_seconds)
            except asyncio.TimeoutError:
                pass
            self._dirty.clear()
            generation = self._generation
            try:
                snapshot = await self._fetch_snapshot()
            except (BridgeTransportError, aiohttp.ClientError, asyncio.TimeoutError):
                self._healthy = False
                self._status = "state unavailable"
                LOG.warning("PBX state refresh failed")
                # A bounded pause also prevents a busy loop during an event storm.
                await asyncio.sleep(min(self._refresh_seconds, 1.0))
                continue
            self._snapshot = snapshot
            self._last_success = time.monotonic()
            self._healthy = self._ws_connected and generation == self._generation
            self._status = "live" if self._healthy else "synchronizing"
            if not self._healthy:
                self._dirty.set()

    async def run(self):
        retry_seconds = 1.0
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        trace = aiohttp.TraceConfig()

        async def reject_redirect(session, context, parameters):
            raise BridgeTransportError("PBX redirects are not allowed")

        # ws_connect follows redirects internally and has no public switch to
        # disable them. Reject them before a second request can be made.
        trace.on_request_redirect.append(reject_redirect)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False,
                                         trace_configs=[trace]) as session:
            self._session = session
            try:
                while True:
                    worker = None
                    try:
                        token = await self._get_token()
                        ws_url = self._base_url.replace("https://", "wss://", 1) + "/callcontrol/ws"
                        # A periodic GET maintains token freshness. The socket
                        # reconnects naturally if the server expires its session.
                        async with session.ws_connect(
                            ws_url, headers={"Authorization": "Bearer " + token},
                            heartbeat=20.0, max_msg_size=65536,
                        ) as ws:
                            self._ws_connected = True
                            self._healthy = False
                            # PBX restarts can reuse call IDs. A new socket must
                            # rebuild both state and inferred direction history.
                            self._directions.clear()
                            self._status = "synchronizing"
                            self._invalidate()
                            last_sequence = None
                            worker = asyncio.create_task(self._refresh_worker())
                            retry_seconds = 1.0
                            async for message in ws:
                                if message.type == aiohttp.WSMsgType.TEXT:
                                    try:
                                        packet = json.loads(message.data)
                                        sequence = packet["sequence"]
                                        event = packet["event"]
                                        if (not isinstance(sequence, int) or isinstance(sequence, bool)
                                                or not isinstance(event, dict)):
                                            raise ValueError()
                                        gap = (last_sequence is not None
                                               and sequence != last_sequence + 1)
                                        last_sequence = sequence
                                        kind = event.get("event_type")
                                        entity = event.get("entity", "")
                                        if gap or (kind in (0, 1) and isinstance(entity, str)
                                                   and (entity == "/callcontrol"
                                                        or entity.startswith("/callcontrol/"))):
                                            self._invalidate(sequence_gap=gap)
                                    except (ValueError, TypeError, KeyError):
                                        # Unknown/malformed data cannot leave an apparently
                                        # trusted cache; request a fresh snapshot.
                                        self._invalidate(sequence_gap=True)
                                elif message.type == aiohttp.WSMsgType.ERROR:
                                    break
                    except (BridgeTransportError, aiohttp.ClientError, asyncio.TimeoutError):
                        self._token = None
                        LOG.warning("PBX event connection unavailable; retrying")
                    finally:
                        self._ws_connected = False
                        self._healthy = False
                        self._status = "disconnected"
                        if worker:
                            worker.cancel()
                            await asyncio.gather(worker, return_exceptions=True)
                    await asyncio.sleep(retry_seconds)
                    retry_seconds = min(retry_seconds * 2.0, 30.0)
            finally:
                self._session = None
                self._ws_connected = False
                self._healthy = False
                self._status = "disconnected"
