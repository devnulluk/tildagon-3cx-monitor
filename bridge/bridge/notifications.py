"""Bounded in-memory notifications and an optional read-only ntfy subscriber.

No notification can invoke an action, open a URL, download an image, or write to
the PBX. Subscriber diagnostics never contain payloads, topics or credentials.
"""
import asyncio
from collections import OrderedDict
import hashlib
import json
import math
import os
import re
import secrets
import time
from urllib.parse import quote, urlsplit

import aiohttp

TYPES = frozenset(("info", "success", "warning", "failure"))
STYLES = frozenset(("card", "toast", "progress", "badge"))
ICONS = frozenset(("info", "check", "warning", "error", "bell", "server", "download", "upload",
                   "backup", "lock", "phone", "message", "heart", "cloud"))
DEFAULT_ICONS = {"info": "info", "success": "check", "warning": "warning", "failure": "error"}
ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z", re.ASCII)
MAX_ITEMS, MAX_HISTORY = 16, 256
MAX_TITLE_BYTES, MAX_BODY_BYTES = 80, 320
DEFAULT_TTL, MAX_TTL = 300, 86400
MAX_LINE_BYTES = 8192


class NotificationError(ValueError):
    """A deliberately fixed, payload-free validation error."""
    def __init__(self):
        super().__init__("Invalid notification request")


def _require(condition):
    if not condition:
        raise NotificationError()


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value, limit, multiline=False):
    _require(isinstance(value, str))
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if not multiline:
        value = value.replace("\n", " ")
    value = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127 or multiline and c == "\n")
    try:
        return value.strip().encode("utf-8")[:limit].decode("utf-8", errors="ignore").strip()
    except UnicodeError:
        raise NotificationError() from None


def _fields(payload):
    _require(isinstance(payload, dict))
    allowed = {"id", "title", "body", "message", "type", "priority", "style", "icon",
               "progress", "ttl", "ttl_seconds", "version", "attachments"}
    _require(not (set(payload) - allowed))
    if "attachments" in payload:
        # Current Apprise sends this key even when no attachment is supplied.
        # Empty compatibility metadata is accepted; file contents never are.
        _require(isinstance(payload["attachments"], list) and not payload["attachments"])
    _require(not ("message" in payload and "body" in payload))
    _require(not ("ttl" in payload and "ttl_seconds" in payload))
    if "version" in payload:
        _require(payload["version"] in ("1.0", 1, 1.0) and not isinstance(payload["version"], bool))
    result = {}
    if "id" in payload:
        _require(isinstance(payload["id"], str) and ID_PATTERN.fullmatch(payload["id"]))
        result["id"] = payload["id"]
    if "title" in payload:
        result["title"] = _text(payload["title"], MAX_TITLE_BYTES)
    if "body" in payload or "message" in payload:
        result["body"] = _text(payload.get("body", payload.get("message")), MAX_BODY_BYTES, multiline=True)
    for key, choices in (("type", TYPES), ("style", STYLES), ("icon", ICONS)):
        if key in payload:
            _require(isinstance(payload[key], str) and payload[key] in choices)
            result[key] = payload[key]
    if "priority" in payload:
        value = payload["priority"]
        _require(isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5)
        result["priority"] = value
    if "progress" in payload:
        value = payload["progress"]
        _require(value is None or _finite(value) and 0 <= value <= 100)
        result["progress"] = value
    ttl = payload.get("ttl_seconds", payload.get("ttl"))
    if ttl is not None:
        _require(isinstance(ttl, int) and not isinstance(ttl, bool) and 1 <= ttl <= MAX_TTL)
        result["ttl_seconds"] = ttl
    elif "ttl" in payload or "ttl_seconds" in payload:
        raise NotificationError()
    return result


class NotificationBroker:
    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self._clock, self._wall_clock = clock, wall_clock
        self._items = OrderedDict()
        self._history = OrderedDict()

    def _retire(self, identity):
        self._items.pop(identity, None)
        self._history[identity] = None
        self._history.move_to_end(identity)
        while len(self._history) > MAX_HISTORY:
            self._history.popitem(last=False)

    def _purge(self):
        now = self._clock()
        for identity, item in list(self._items.items()):
            if now >= item["_expires"]:
                self._retire(identity)

    def remove(self, identity):
        self._retire(identity)

    def clear_prefix(self, prefix):
        for identity in list(self._items):
            if identity.startswith(prefix):
                self._retire(identity)

    def submit(self, payload, *, age_seconds=0):
        fields = _fields(payload)
        _require(_finite(age_seconds) and age_seconds >= 0)
        self._purge()
        identity = fields.pop("id", None)
        if identity in self._history:
            return {"status": "expired", "id": identity}
        current = self._items.get(identity)
        body = ({key: value for key, value in current.items() if not key.startswith("_")}
                if current else {"title": "Notification", "body": "", "type": "info", "priority": 3,
                                 "style": "card", "icon": "info", "progress": None,
                                 "ttl_seconds": DEFAULT_TTL})
        body.update(fields)
        _require(bool(body.get("title") or body.get("body")) and
                 (current is not None or "title" in fields or "body" in fields))
        if "type" in fields and "icon" not in fields:
            body["icon"] = DEFAULT_ICONS[body["type"]]
        if body["progress"] is not None and "style" not in fields and current is None:
            body["style"] = "progress"
        fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).digest()
        if identity is None:
            for previous_id, previous in self._items.items():
                if previous["_fingerprint"] == fingerprint:
                    return {"status": "duplicate", "id": previous_id}
            identity = secrets.token_hex(12)
        now = self._clock()
        received = min(current["_received"], now - age_seconds) if current else now - age_seconds
        expires = received + body["ttl_seconds"]
        if current:
            expires = min(expires, current["_expires"])
        if now >= expires:
            self._retire(identity)
            return {"status": "expired", "id": identity}
        if current and current["_fingerprint"] == fingerprint:
            # A replay may establish an earlier publish time even though its
            # content is identical. Tighten age/expiry before deduplicating.
            current["_received"] = received
            current["_expires"] = expires
            current["_received_wall"] = min(current["_received_wall"], self._wall_clock() - age_seconds)
            current["ttl_seconds"] = max(1, int(round(expires - received)))
            return {"status": "duplicate", "id": identity}
        body["ttl_seconds"] = max(1, int(round(expires - received)))
        body.update(_fingerprint=fingerprint, _received=received, _expires=expires,
                    _received_wall=(min(current["_received_wall"], self._wall_clock() - age_seconds)
                                    if current else self._wall_clock() - age_seconds))
        self._items[identity] = body
        while len(self._items) > MAX_ITEMS:
            self._retire(next(iter(self._items)))
        return {"status": "updated" if current else "accepted", "id": identity}

    def snapshot(self):
        self._purge()
        now = self._clock()
        return [dict({key: value for key, value in item.items() if not key.startswith("_")},
                     id=identity, received=int(item["_received_wall"]),
                     age_seconds=max(0.0, now - item["_received"]))
                for identity, item in reversed(self._items.items())]


def _ntfy_id(event):
    value = event.get("sequence_id") or event.get("id")
    _require(isinstance(value, str) and 1 <= len(value) <= 256)
    return "ntfy:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class NtfySubscriber:
    """One verified-HTTPS JSON stream; no writes or arbitrary remote fetches."""
    def __init__(self, broker, url, topic, token=None, *, session=None, clock=time.monotonic,
                 wall_clock=time.time, sleeper=asyncio.sleep):
        try:
            parsed = urlsplit(url)
            valid = (isinstance(url, str) and parsed.scheme == "https" and bool(parsed.hostname)
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                     and (parsed.port is None or 1 <= parsed.port <= 65535)
                     and url.isascii() and not any(ord(c) < 33 or ord(c) == 127 for c in url)
                     and "\\" not in url)
        except (TypeError, ValueError, AttributeError):
            valid = False
        if not valid:
            raise ValueError("NTFY_URL must be a valid HTTPS base URL without credentials or query")
        if not isinstance(topic, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic, re.ASCII):
            raise ValueError("NTFY_TOPIC must be a single ASCII topic name")
        if token is not None and (not isinstance(token, str) or not 1 <= len(token) <= 512
                                  or not token.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ValueError("NTFY_TOKEN must be an ASCII token without whitespace")
        self._broker, self._topic = broker, topic
        self._url = url.rstrip("/") + "/" + quote(topic, safe="") + "/json"
        self._headers = {"User-Agent": "Tildagon3CX/0.6", "Accept": "application/x-ndjson"}
        if token:
            self._headers["Authorization"] = "Bearer " + token
        self._session, self._owns_session = session, session is None
        self._clock, self._wall_clock, self._sleep = clock, wall_clock, sleeper
        self._task, self._closed, self._last_id = None, False, None
        self.connected = False

    def ingest(self, event):
        _require(isinstance(event, dict))
        if event.get("event") in ("open", "keepalive"):
            return
        _require(event.get("topic") == self._topic)
        kind = event.get("event")
        if kind == "message_clear":
            self._broker.clear_prefix("ntfy:")
            return
        if kind == "message_delete":
            self._broker.remove(_ntfy_id(event))
            return
        if kind != "message":
            return
        _require(isinstance(event.get("id"), str) and ID_PATTERN.fullmatch(event["id"]))
        self._last_id = event["id"]
        stamp = event.get("time")
        _require(_finite(stamp) and stamp >= 0)
        age = max(0.0, self._wall_clock() - stamp)
        tags = event.get("tags", [])
        tags = {tag.lower() for tag in tags[:32] if isinstance(tag, str) and len(tag) <= 40} if isinstance(tags, list) else set()
        notification_type = ("failure" if tags & {"failure", "error", "x", "no_entry"} else
                             "warning" if tags & {"warning", "rotating_light", "exclamation"} else
                             "success" if tags & {"success", "white_check_mark", "heavy_check_mark", "tada"} else "info")
        icon = next((value for value in ("backup", "server", "download", "upload", "lock", "phone", "heart", "cloud")
                     if value in tags), DEFAULT_ICONS[notification_type])
        ttl = DEFAULT_TTL
        if "expires" in event:
            _require(_finite(event["expires"]))
            if event["expires"] <= stamp:
                return
            ttl = max(1, min(ttl, int(event["expires"] - stamp)))
        # Remote icon/click/actions/attachments are deliberately not copied.
        self._broker.submit({"id": _ntfy_id(event), "title": event.get("title") or "Notification",
                             "body": event.get("message"), "type": notification_type,
                             "priority": event.get("priority", 3), "icon": icon,
                             "ttl_seconds": ttl}, age_seconds=age)

    async def _consume(self, content):
        line, dropping, processed = bytearray(), False, 0
        async for chunk in content.iter_chunked(1024):
            parts = chunk.split(b"\n")
            for index, piece in enumerate(parts):
                if not dropping:
                    if len(line) + len(piece) <= MAX_LINE_BYTES:
                        line.extend(piece)
                    else:
                        line.clear()
                        dropping = True
                if index < len(parts) - 1:
                    if line and not dropping:
                        try:
                            self.ingest(json.loads(line))
                        except (ValueError, TypeError, UnicodeError):
                            pass
                    line.clear()
                    dropping = False
                    processed += 1
                    if processed % 8 == 0:
                        await asyncio.sleep(0)

    async def start(self):
        if self._task is None and not self._closed:
            self._task = asyncio.create_task(self.run())

    async def run(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=75),
                                                  read_bufsize=8192)
        delay = 1
        try:
            while not self._closed:
                started = self._clock()
                try:
                    parameters = {"since": self._last_id} if self._last_id else {}
                    async with self._session.get(self._url, params=parameters, headers=self._headers,
                                                 allow_redirects=False, ssl=True) as response:
                        if response.status != 200:
                            raise NotificationError()
                        self.connected = True
                        await self._consume(response.content)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Never log an aiohttp exception: it may include a private
                    # subscription URL or credentials from another service.
                    pass
                self.connected = False
                if self._closed:
                    break
                delay = 1 if self._clock() - started >= 30 else delay
                await self._sleep(delay)
                delay = min(60, delay * 2)
        finally:
            self.connected = False

    async def close(self):
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None


def ntfy_from_env(broker):
    url, topic, token = (os.environ.get(key) or None for key in ("NTFY_URL", "NTFY_TOPIC", "NTFY_TOKEN"))
    if url is None and topic is None and token is None:
        return None
    if not url or not topic:
        raise ValueError("NTFY_URL and NTFY_TOPIC must be configured together")
    return NtfySubscriber(broker, url, topic, token)
