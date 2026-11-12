"""Own-user presence through the installed 3CX V20 Update 9 Web Client API.

This is the same private MyPhone protocol used by that PBX's Web Client, not the
public Call Control API. It needs a separate grant for the configured own user.
Only self ProfileId changes and targeted contact-number reads are encoded;
TargetExtension and bulk contact downloads are never supported.
No authentication secret, MyInfo payload, or server error body is logged.
"""

import asyncio
import base64
import json
import math
import os
from pathlib import Path
from http.cookies import SimpleCookie, CookieError
from email.utils import formatdate
import tempfile
import time
from urllib.parse import urlsplit

import aiohttp
from yarl import URL

from .transport import validate_pbx_url
from .model import normalize_number, text

MAX_RESPONSE = 128 * 1024
MAX_GRANT_BYTES = 65536
MAX_GRANT_COOKIES = 32
FINGERPRINT = {"name": "Webclient", "version": "20.0.9.0", "isHuman": True}
GET_MY_INFO = bytes.fromhex("08 66 b2 06 02 08 01")


class PresenceError(Exception):
    """Sanitized failure; the original server payload must not escape."""


class PresenceAuthError(PresenceError):
    pass


def _varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise PresenceError("Invalid MyPhone response")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise PresenceError("Invalid MyPhone response")


def _fields(data):
    if not isinstance(data, bytes) or len(data) > MAX_RESPONSE:
        raise PresenceError("Invalid MyPhone response")
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field, wire = tag >> 3, tag & 7
        if not field or field > 536870911:
            raise PresenceError("Invalid MyPhone response")
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if offset + size > len(data):
                raise PresenceError("Invalid MyPhone response")
            value, offset = data[offset:offset + size], offset + size
        elif wire == 2:
            size, offset = _read_varint(data, offset)
            if size > MAX_RESPONSE or offset + size > len(data):
                raise PresenceError("Invalid MyPhone response")
            value, offset = data[offset:offset + size], offset + size
        else:
            raise PresenceError("Invalid MyPhone response")
        yield field, wire, value


def _message(data, message_id):
    identifier, body = None, None
    for field, wire, value in _fields(data):
        if field == 1:
            if wire != 0 or identifier is not None:
                raise PresenceError("Invalid MyPhone response")
            identifier = value
        elif field == message_id:
            if wire != 2 or body is not None:
                raise PresenceError("Invalid MyPhone response")
            body = value
    if identifier != message_id or body is None:
        raise PresenceError("Unexpected MyPhone response")
    return body


def _string(value, limit=80):
    if not isinstance(value, bytes) or len(value) > limit * 4:
        raise PresenceError("Invalid MyPhone response")
    try:
        result = value.decode("utf-8")
    except UnicodeError:
        raise PresenceError("Invalid MyPhone response") from None
    if len(result) > limit or any(ord(character) < 32 for character in result):
        raise PresenceError("Invalid MyPhone response")
    return result


def decode_my_info(data):
    """Whitelist identity and profile fields; discard private device/password data."""
    body = _message(data, 201)
    selected = {}
    for field, wire, value in _fields(body):
        if field in (3, 10, 13, 14, 27, 28):
            if field in selected or wire != (2 if field in (3, 13) else 0):
                raise PresenceError("Invalid MyPhone presence fields")
            selected[field] = value
    number = _string(selected.get(3), 32)
    profiles = {}
    for field, wire, value in _fields(selected.get(13, b"")):
        if field != 2:
            continue
        if wire != 2 or len(profiles) >= 32:
            raise PresenceError("Invalid MyPhone profiles")
        profile_id, profile_name = None, None
        for entry, entry_wire, entry_value in _fields(value):
            if entry == 2:
                if entry_wire != 0 or profile_id is not None:
                    raise PresenceError("Invalid MyPhone profile")
                profile_id = entry_value
            elif entry == 3:
                if entry_wire != 2 or profile_name is not None:
                    raise PresenceError("Invalid MyPhone profile")
                profile_name = _string(entry_value)
        if not isinstance(profile_id, int) or profile_name is None:
            raise PresenceError("Invalid MyPhone profile")
        # Protobuf int32 negative values normally use a ten-byte sign-extended
        # varint. The bounded generic reader returns its unsigned wire value.
        # U9 includes unselectable CUSTOM entries with Id -1/-2 alongside the
        # real forwarding profiles; these must not invalidate the whole list.
        if 0x80000000 <= profile_id <= 0xFFFFFFFF:
            profile_id -= 0x100000000
        elif 0xFFFFFFFF80000000 <= profile_id <= 0xFFFFFFFFFFFFFFFF:
            profile_id -= 0x10000000000000000
        if profile_id < 0:
            continue
        if not 0 < profile_id < 2147483648 or profile_id in profiles:
            raise PresenceError("Invalid MyPhone profile")
        profiles[profile_id] = profile_name
    profile_id = selected.get(28) if selected.get(27) == 1 else selected.get(10)
    profile = profiles.get(profile_id)
    if profile is None:
        raise PresenceError("Current MyPhone profile was not supplied")
    if any(selected.get(field, 0) not in (0, 1) for field in (14, 27)):
        raise PresenceError("Invalid MyPhone presence flags")
    if selected.get(14) == 1 and profile != "Out of office":
        # The legacy DND flag is independent of forwarding profiles on older
        # configurations. Changing ProfileId alone cannot safely claim that
        # DND is off, or choose a toggle direction from contradictory state.
        raise PresenceError("Legacy DND conflicts with the current profile")
    state = "dnd" if profile == "Out of office" else "available" if profile == "Available" else "away"
    return {"number": number, "profile_id": profile_id, "profiles": profiles,
            "state": state, "profile": profile}


def encode_profile_change(profile_id):
    if isinstance(profile_id, bool) or not isinstance(profile_id, int) or not 0 < profile_id < 2147483648:
        raise ValueError("Invalid own-user profile ID")
    change = b"\x08" + _varint(profile_id)
    # GenericMessage { MessageId:103, ChangeStatus:{ProfileId:...} }.
    return b"\x08\x67" + _varint((103 << 3) | 2) + _varint(len(change)) + change


def decode_acknowledge(data):
    success = None
    for field, wire, value in _fields(_message(data, 207)):
        if field == 1:
            if wire != 0 or success is not None or value not in (0, 1):
                raise PresenceError("Invalid MyPhone acknowledgement")
            success = bool(value)
    if success is not True:
        raise PresenceError("PBX did not accept the presence change")


def encode_contact_lookup(number):
    """U9 RequestExactMatch193, restricted to the user's visible phonebooks."""
    if (not isinstance(number, str) or not number.isascii() or not 7 <= len(number.lstrip("+")) <= 15
            or not number.lstrip("+").isdigit() or number.count("+") > 1
            or ("+" in number and not number.startswith("+"))):
        raise ValueError("Invalid phonebook lookup number")
    value = number.encode("ascii")
    # Number1, DnType2=0 (no PBX DN search), Company3, Personal4,
    # Bridge5=false, Group6=true. Same flags as the installed UI context.
    body = b"\x0a" + _varint(len(value)) + value + b"\x10\x00\x18\x01\x20\x01\x28\x00\x30\x01"
    return b"\x08" + _varint(193) + _varint((193 << 3) | 2) + _varint(len(body)) + body


def encode_extension_lookup(extension):
    """The same exact193 read, restricted to one local Extension DN (mask1)."""
    if (not isinstance(extension, str) or not extension.isascii()
            or not extension.isdigit() or not 1 <= len(extension) <= 6):
        raise ValueError("Invalid directory lookup extension")
    value = extension.encode("ascii")
    # DnType.Extension=1. Do not search company/personal/bridge/group books.
    body = b"\x0a" + _varint(len(value)) + value + b"\x10\x01\x18\x00\x20\x00\x28\x00\x30\x00"
    return b"\x08" + _varint(193) + _varint((193 << 3) | 2) + _varint(len(body)) + body


def decode_contact_lookup(data, number, country_code="44"):
    """Whitelist a matching display name; discard address, email and CRM data."""
    contacts = [value for field, wire, value in _fields(_message(data, 240))
                if field == 1 and wire == 2]
    if not contacts:
        return None
    if len(contacts) != 1:
        raise PresenceError("Invalid MyPhone contact response")
    selected = {}
    phone_fields = (4, 8, 9, 11, 12, 14)
    for field, wire, value in _fields(contacts[0]):
        if field in (2, 3, 7) or field in phone_fields:
            if wire != 2 or field in selected:
                raise PresenceError("Invalid MyPhone contact response")
            selected[field] = _string(value, 40 if field in phone_fields else 120)
    # The installed UI maps Number4 to mobile, fields8/9 to mobile2/home,
    # 11/12 to business/business2 and14 to other. Address fields10/13/etc
    # contain title/email and must never participate in number matching.
    actual = {normalize_number(selected.get(field, ""), country_code) for field in phone_fields}
    expected = normalize_number(number, country_code)
    # Never trust suffix-based PBX matching or a different number's stale frame.
    if not expected or expected not in actual:
        return None
    name = text(" ".join(selected.get(field, "").strip() for field in (2, 3)).strip(), 100)
    if not name:
        name = text(selected.get(7, ""), 100)
    if not name or normalize_number(name, country_code) == expected:
        return None
    return {"number": expected, "name": name}


def decode_extension_lookup(data, extension):
    """Only exact local-user ExtensionNumber5 and actual FirstName2 survive."""
    contacts = [value for field, wire, value in _fields(_message(data, 240))
                if field == 1 and wire == 2]
    if not contacts:
        return None
    if len(contacts) != 1:
        raise PresenceError("Invalid MyPhone directory response")
    selected = {}
    for field, wire, value in _fields(contacts[0]):
        if field in (2, 3, 5, 6, 24):
            if field in selected or wire != (0 if field in (6, 24) else 2):
                raise PresenceError("Invalid MyPhone directory response")
            selected[field] = value if wire == 0 else _string(value, 120 if field != 5 else 32)
    # LocalUser=0, Extension=1 in the installed U9 schema. The UI also
    # accepts a LocalUser with absent DnType; never accept a different type.
    if (selected.get(5) != extension or selected.get(6, 0) != 0
            or (24 in selected and selected[24] != 1)):
        return None
    first = text(selected.get(2, ""), 80).strip()
    if not first or not any(character.isalpha() for character in first) or any(character.isdigit() for character in first):
        return None
    full = text(first + " " + selected.get(3, ""), 100).strip()
    return {"number": extension, "name": full, "first_name": first}


class MyPhonePresenceProvider:
    def __init__(self, url, own_extension="200", refresh_token=None, username=None,
                 password=None, security_code=None, session=None, request_timeout=6,
                 token_file=None):
        self._base_url = validate_pbx_url(url)
        self._own = str(own_extension)
        if not self._own.isdigit() or len(self._own) > 16:
            raise ValueError("Own presence requires a numeric extension")
        self._username = str(username or self._own)
        if self._username != self._own:
            raise ValueError("Own presence credentials must match own_extension")
        self._token_file = Path(token_file) if token_file else None
        self._stored_cookies = []
        self._restored_cookies = False
        self._saved_grant = None
        self._refresh_token = refresh_token
        self._password = password
        self._security_code = security_code
        # A newly supplied explicit grant or password + second factor is an
        # intentional recovery bootstrap. Never mix it with old cookies.
        fresh_grant = bool(refresh_token or (password and security_code))
        if self._token_file and not fresh_grant:
            self._load_grant()
        if not self._refresh_token and not password and not self._stored_cookies:
            raise ValueError("A separate own-user refresh token or password grant is required")
        self._session = session
        self._owns_session = session is None
        self._request_timeout = request_timeout
        self._access_token = None
        self._token_deadline = 0.0
        self._session_key = None
        self._session_pass = None
        self._ws = None
        self._ws_reader = None
        self._ws_ready = asyncio.Event()
        self._ws_frames = asyncio.Queue(maxsize=16)
        self._contact_frames = asyncio.Queue(maxsize=16)
        self._ws_error = None
        self._identity_verified_key = None
        self._authenticated_once = False
        self._auth_failed = False
        self._closed = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _grant_error():
        return PresenceAuthError("Stored own-user authentication grant is invalid or does not match")

    def _load_grant(self):
        try:
            if self._token_file.is_symlink():
                raise self._grant_error()
            if not self._token_file.exists():
                return
            with self._token_file.open("rb") as handle:
                raw = handle.read(MAX_GRANT_BYTES + 1)
            if len(raw) > MAX_GRANT_BYTES:
                raise self._grant_error()
            value = json.loads(raw)
            if (not isinstance(value, dict)
                    or set(value) != {"version", "origin", "own_extension", "refresh_token", "cookies"}
                    or value["version"] != 1 or value["origin"] != self._base_url
                    or value["own_extension"] != self._own):
                raise self._grant_error()
            refresh = value["refresh_token"]
            if refresh is not None and (not isinstance(refresh, str) or not refresh
                                       or len(refresh) > 16384
                                       or any(ord(c) < 33 or ord(c) > 126 for c in refresh)):
                raise self._grant_error()
            cookies = value["cookies"]
            if not isinstance(cookies, list) or len(cookies) > MAX_GRANT_COOKIES:
                raise self._grant_error()
            selected = []
            seen = set()
            for cookie in cookies:
                if (not isinstance(cookie, dict)
                        or set(cookie) != {"name", "value", "path", "secure", "http_only", "same_site", "expires_at"}):
                    raise self._grant_error()
                name, text, path = cookie["name"], cookie["value"], cookie["path"]
                if (not isinstance(name, str) or not 1 <= len(name) <= 256
                        or not isinstance(text, str) or len(text) > 16384
                        or any(ord(c) < 32 or ord(c) > 126 for c in text)
                        or not isinstance(path, str) or not path.startswith("/") or len(path) > 1024
                        or any(ord(c) < 33 or ord(c) > 126 for c in path)
                        or not self._cookie_path_matches(path)
                        or not isinstance(cookie["secure"], bool)
                        or not isinstance(cookie["http_only"], bool)
                        or not isinstance(cookie["same_site"], str)
                        or cookie["same_site"].lower() not in ("", "lax", "strict", "none")):
                    raise self._grant_error()
                cookie["same_site"] = {"": "", "lax": "Lax", "strict": "Strict", "none": "None"}[cookie["same_site"].lower()]
                jar = SimpleCookie()
                jar[name] = text  # Validate a cookie name without executing data.
                if (name, path) in seen:
                    raise self._grant_error()
                seen.add((name, path))
                deadline = cookie["expires_at"]
                if deadline is not None:
                    if (isinstance(deadline, bool) or not isinstance(deadline, (float, int))
                            or not math.isfinite(deadline) or deadline <= 0):
                        raise self._grant_error()
                    formatdate(deadline, usegmt=True)  # Reject dates the platform cannot restore.
                    if deadline <= time.time():
                        continue
                selected.append(cookie)
            if not refresh and not selected:
                raise self._grant_error()
            self._refresh_token = refresh
            self._stored_cookies = selected
        except PresenceAuthError:
            raise
        except (OSError, ValueError, TypeError, KeyError, OverflowError, CookieError):
            raise self._grant_error() from None

    @staticmethod
    def _cookie_path_matches(path):
        return path == "/" or "/connect/token" == path or "/connect/token".startswith(path.rstrip("/") + "/")

    def _restore_grant_cookies(self):
        if self._restored_cookies:
            return
        if self._stored_cookies:
            jar = getattr(self._session, "cookie_jar", None)
            if jar is None:
                raise PresenceAuthError("Own-user cookie storage is unavailable")
            for entry in self._stored_cookies:
                cookies = SimpleCookie()
                cookies[entry["name"]] = entry["value"]
                morsel = cookies[entry["name"]]
                morsel["path"] = entry["path"]
                morsel["secure"] = entry["secure"]
                morsel["httponly"] = entry["http_only"]
                if entry["same_site"]:
                    morsel["samesite"] = entry["same_site"]
                if entry["expires_at"] is not None:
                    morsel["expires"] = formatdate(entry["expires_at"], usegmt=True)
                # No Domain attribute: restore as host-only, never a wildcard
                # or parent-domain cookie, and bind the store to the full origin.
                jar.update_cookies(cookies, response_url=URL(self._base_url + "/connect/token"))
        self._restored_cookies = True

    def _persist_grant(self):
        if not self._token_file:
            return
        jar = getattr(self._session, "cookie_jar", None)
        cookies = []
        if jar is not None:
            url = URL(self._base_url + "/connect/token")
            sent = jar.filter_cookies(url)
            host = urlsplit(self._base_url).hostname
            for morsel in jar:
                domain = morsel["domain"].lstrip(".").lower()
                path = morsel["path"] or "/"
                active = sent.get(morsel.key)
                if (not domain or not (domain == host or host.endswith("." + domain))
                        or not self._cookie_path_matches(path) or active is None
                        or active.value != morsel.value):
                    continue
                deadline = getattr(jar, "_expirations", {}).get((morsel["domain"], path.rstrip("/"), morsel.key))
                same_site = {"": "", "lax": "Lax", "strict": "Strict", "none": "None"}.get(morsel["samesite"].lower(), "")
                cookies.append({"name": morsel.key, "value": morsel.value, "path": path,
                                "secure": bool(morsel["secure"]), "http_only": bool(morsel["httponly"]),
                                "same_site": same_site, "expires_at": deadline})
        value = {"version": 1, "origin": self._base_url, "own_extension": self._own,
                 "refresh_token": self._refresh_token, "cookies": cookies}
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if (len(raw) > MAX_GRANT_BYTES or len(cookies) > MAX_GRANT_COOKIES
                or (not self._refresh_token and not cookies)):
            raise PresenceError("Own-user authentication grant could not be stored")
        if raw == self._saved_grant:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self._token_file.parent,
                                             prefix=".own-user-grant-", delete=False) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._token_file)
            os.chmod(self._token_file, 0o600)
            self._saved_grant = raw
        except OSError:
            raise PresenceError("Own-user authentication grant could not be stored") from None
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    async def _http(self):
        if self._closed:
            raise PresenceError("Own presence provider is closed")
        if self._session is None:
            trace = aiohttp.TraceConfig()
            async def reject_redirect(session, context, parameters):
                raise PresenceError("Own-user service redirects are not allowed")
            trace.on_request_redirect.append(reject_redirect)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._request_timeout),
                cookie_jar=aiohttp.CookieJar(), trust_env=False,
                trace_configs=[trace],
            )
        self._restore_grant_cookies()
        return self._session

    async def _body(self, response):
        if response.content_length and response.content_length > MAX_RESPONSE:
            raise PresenceError("MyPhone response is too large")
        data = bytearray()
        async for chunk in response.content.iter_chunked(16384):
            data.extend(chunk)
            if len(data) > MAX_RESPONSE:
                raise PresenceError("MyPhone response is too large")
        return bytes(data)

    async def _post_json(self, path, payload=None, form=None, headers=None, auth=False):
        session = await self._http()
        kwargs = {"allow_redirects": False, "headers": headers or {"Accept": "application/json"}}
        if form is not None:
            # The installed U9 MyPhone worker posts a native FormData refresh
            # grant. Preserve multipart encoding on this PBX, including when
            # only the cookie-based grant fields are present.
            data = aiohttp.FormData(default_to_multipart=True)
            for name, value in form.items():
                data.add_field(name, value)
            kwargs["data"] = data
        else:
            kwargs["json"] = payload
        async with session.post(self._base_url + path, **kwargs) as response:
            if response.status != 200:
                if response.status in (400, 401, 403) and auth:
                    self._auth_failed = True
                    raise PresenceAuthError("Own-user authentication requires a new grant")
                raise PresenceError("Own-user authentication service is unavailable")
            raw = await self._body(response)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise PresenceError("Invalid own-user authentication response") from None
        if not isinstance(value, dict):
            raise PresenceError("Invalid own-user authentication response")
        return value

    async def _token(self):
        if self._auth_failed:
            raise PresenceAuthError("Own-user authentication requires a new grant")
        if self._access_token and time.monotonic() < self._token_deadline:
            return self._access_token
        if not self._refresh_token and not self._authenticated_once and not self._stored_cookies:
            login = {"Username": self._username, "Password": self._password}
            if self._security_code:
                login["SecurityCode"] = self._security_code
            value = await self._post_json("/webclient/api/Login/GetAccessToken", login, auth=True)
            if value.get("Status") == "Required2FA":
                self._auth_failed = True
                raise PresenceAuthError("Own-user authentication requires a security code")
            self._authenticated_once = True
            self._security_code = None
        form = {"grant_type": "refresh_token", "client_id": "Webclient"}
        if self._refresh_token:
            form["refresh_token"] = self._refresh_token
        value = await self._post_json("/connect/token", form=form, auth=True)
        token = value.get("access_token")
        try:
            lifetime = float(value.get("expires_in", 0))
        except (TypeError, ValueError):
            raise PresenceError("Invalid own-user access token") from None
        if not isinstance(token, str) or not token or not math.isfinite(lifetime) or lifetime <= 0:
            raise PresenceError("Invalid own-user access token")
        self._access_token = token
        self._token_deadline = time.monotonic() + lifetime * 0.75
        # Rotated grants remain private and are stored, when configured, only
        # after a fresh own-user identity readback. Never expose them in state.
        if isinstance(value.get("refresh_token"), str) and value["refresh_token"]:
            self._refresh_token = value["refresh_token"]
        # This JWT was just returned by the configured PBX over verified TLS,
        # not supplied as an arbitrary assertion. Its explicit own-user claim
        # can preserve a bootstrap grant before asynchronous MyInfo is received.
        # Every actual profile write still requires fresh MyInfo identity.
        try:
            encoded = token.split(".")[1]
            if len(encoded) > 16384:
                raise ValueError()
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            own_claim = isinstance(claims, dict) and claims.get("unique_name") == self._own
        except (ValueError, TypeError, IndexError, UnicodeError):
            own_claim = False
        if own_claim:
            self._persist_grant()
        return token

    async def _ensure_session(self):
        token = await self._token()
        if self._session_key is None:
            value = await self._post_json(
                "/webclient/api/MyPhone/session", FINGERPRINT,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, auth=True,
            )
            key = value.get("sessionKey")
            session_pass = value.get("pass")
            if not isinstance(key, str) or not key or len(key) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise PresenceError("Invalid own-user MyPhone session")
            if (not isinstance(session_pass, str) or not session_pass or len(session_pass) > 2048
                    or any(ord(c) < 33 or ord(c) > 126 for c in session_pass)):
                raise PresenceError("Invalid own-user MyPhone session")
            self._session_key = key
            self._session_pass = session_pass

    def _queue_frame(self, frame, queue=None):
        queue = self._ws_frames if queue is None else queue
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(frame)

    async def _consume_notifications(self):
        try:
            async for message in self._ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    if message.data == "START":
                        self._ws_ready.set()
                    elif message.data in ("NOT AUTH", "STOP"):
                        raise PresenceAuthError("Own-user notification session expired")
                    # ADDP is a server heartbeat; the installed worker sends no reply.
                elif message.type == aiohttp.WSMsgType.BINARY:
                    raw = bytes(message.data)
                    identifier = next((value for field, wire, value in _fields(raw)
                                       if field == 1 and wire == 0), None)
                    if identifier == 201:
                        self._queue_frame(raw)
                    elif identifier == 240:
                        self._queue_frame(raw, self._contact_frames)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise PresenceError("Own-user notification channel is unavailable")
        except asyncio.CancelledError:
            raise
        except PresenceError as error:
            self._ws_error = error
        except Exception:
            # aiohttp exceptions can include the private session URL. Discard
            # them rather than exposing the sessionId/pass query parameters.
            self._ws_error = PresenceError("Own-user notification channel is unavailable")
        finally:
            if not self._closed:
                self._ws_error = self._ws_error or PresenceError("Own-user notification channel closed")
                self._ws_ready.set()
                self._queue_frame(None)
                self._queue_frame(None, self._contact_frames)

    async def _ensure_notifications(self):
        await self._ensure_session()
        if self._ws is None or self._ws.closed:
            self._ws_ready.clear()
            self._ws_error = None
            session = await self._http()
            try:
                self._ws = await session.ws_connect(
                    self._base_url.replace("https://", "wss://", 1) + "/ws/webclient",
                    params={"sessionId": self._session_key, "pass": self._session_pass},
                    origin=self._base_url,
                    max_msg_size=MAX_RESPONSE,
                )
            except Exception:
                raise PresenceError("Own-user notification channel is unavailable") from None
            self._ws_reader = asyncio.create_task(self._consume_notifications())
        try:
            await asyncio.wait_for(self._ws_ready.wait(), self._request_timeout)
        except asyncio.TimeoutError:
            raise PresenceError("Own-user notification channel did not start") from None
        if self._ws_error:
            raise self._ws_error

    async def _close_notifications(self):
        if self._ws_reader:
            self._ws_reader.cancel()
            await asyncio.gather(self._ws_reader, return_exceptions=True)
            self._ws_reader = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._ws_ready.clear()
        self._ws_error = None
        while not self._ws_frames.empty():
            self._ws_frames.get_nowait()
        while not self._contact_frames.empty():
            self._contact_frames.get_nowait()

    async def _wire(self, body, retry_read=False):
        for attempt in range(2 if retry_read else 1):
            await self._ensure_session()
            session = await self._http()
            async with session.post(
                self._base_url + "/MyPhone/MPWebService.asmx", data=body,
                headers={"MyPhoneSession": self._session_key, "Content-Type": "application/octet-stream",
                         "Accept": "application/octet-stream", "ngsw-bypass": "bypass"},
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403) and retry_read and attempt == 0:
                    self._session_key = None
                    self._access_token = None
                    continue
                if response.status != 200:
                    raise PresenceError("Own-user MyPhone request failed")
                return await self._body(response)
        raise PresenceAuthError("Own-user MyPhone session expired")

    async def _read(self, identity_only=False):
        for attempt in range(2):
            received_full = False
            try:
                await self._ensure_notifications()
                # Discard frames captured before this explicit state request.
                # GetMyInfo returns an HTTP acknowledgement; full MyInfo arrives
                # asynchronously through the already-started notification socket.
                while not self._ws_frames.empty():
                    self._ws_frames.get_nowait()
                decode_acknowledge(await self._wire(GET_MY_INFO))
                deadline = time.monotonic() + self._request_timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PresenceError("Fresh own-user presence was not received")
                    try:
                        raw = await asyncio.wait_for(self._ws_frames.get(), remaining)
                    except asyncio.TimeoutError:
                        raise PresenceError("Fresh own-user presence was not received") from None
                    if raw is None:
                        raise self._ws_error or PresenceError("Own-user notification channel closed")
                    fields = list(_fields(_message(raw, 201)))
                    # Unsolicited delta notifications omit identity/profiles.
                    # A new explicit GetMyInfo must yield a full snapshot.
                    if not any(field == 1 and wire == 0 and value == 1 for field, wire, value in fields):
                        continue
                    received_full = True
                    identities = [value for field, wire, value in fields if field == 3 and wire == 2]
                    if len(identities) != 1 or _string(identities[0], 32) != self._own:
                        self._auth_failed = True
                        raise PresenceAuthError("Own-user identity did not match the configured extension")
                    # Identity and the authentication grant remain valid even
                    # if an unfamiliar profile later fails strict decoding.
                    self._persist_grant()
                    self._identity_verified_key = self._session_key
                    if identity_only:
                        return {"number": self._own}
                    info = decode_my_info(raw)
                    if info["number"] != self._own:
                        self._auth_failed = True
                        raise PresenceAuthError("Own-user identity did not match the configured extension")
                    return info
            except PresenceAuthError:
                if self._auth_failed or attempt:
                    raise
            except (PresenceError, aiohttp.ClientError, asyncio.TimeoutError):
                if received_full:
                    raise
                if attempt:
                    raise PresenceError("Fresh own-user presence is unavailable") from None
            await self._close_notifications()
            self._session_key = self._session_pass = None
            self._access_token = None
        raise PresenceError("Fresh own-user presence is unavailable")

    @staticmethod
    def _public(info):
        return {"state": info["state"], "profile": info["profile"], "confirmed": True, "age_seconds": 0.0}

    async def get_presence(self):
        async with self._lock:
            return self._public(await self._read())

    async def _lookup_exact(self, body, decode, timeout):
        try:
            async with asyncio.timeout(min(max(float(timeout), 0.05), 4.5)):
                async with self._lock:
                    await self._ensure_notifications()
                    if self._identity_verified_key != self._session_key:
                        await self._read(identity_only=True)
                    if self._auth_failed:
                        raise PresenceAuthError("Own-user authentication requires a new grant")
                    while not self._contact_frames.empty():
                        self._contact_frames.get_nowait()
                    raw = await self._wire(body)
                    identifiers = [value for field, wire, value in _fields(raw) if field == 1 and wire == 0]
                    if identifiers == [207]:
                        # Installed U9's HTTP transport returns240 directly.
                        # Also handle an acknowledged asynchronous response,
                        # isolated from MyInfo notifications on the same socket.
                        decode_acknowledge(raw)
                        raw = await self._contact_frames.get()
                        if raw is None:
                            raise PresenceError("Own-user phonebook channel is unavailable")
                    return decode(raw)
        except asyncio.CancelledError:
            raise
        except PresenceAuthError:
            raise
        except Exception:
            # HTTP exceptions may carry URLs or bodies. Keep caller data and
            # session credentials out of all outward-facing failure messages.
            raise PresenceError("Own-user phonebook lookup is unavailable") from None

    async def lookup_contact(self, number, country_code="44", timeout=4.5):
        """Read one active caller's exact match without delaying controls >5s."""
        normalized = normalize_number(number, country_code)
        body = encode_contact_lookup(normalized)
        return await self._lookup_exact(body, lambda raw: decode_contact_lookup(raw, normalized, country_code), timeout)

    async def lookup_extension(self, extension, timeout=4.5):
        """Read one current internal peer through the same self-scoped grant."""
        body = encode_extension_lookup(extension)
        return await self._lookup_exact(body, lambda raw: decode_extension_lookup(raw, extension), timeout)

    async def set_dnd(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("DND state must be a boolean")
        async with self._lock:
            before = await self._read()  # Fresh identity check immediately before any write.
            target = "Out of office" if enabled else "Available"
            matches = [key for key, name in before["profiles"].items() if name == target]
            if len(matches) != 1:
                raise PresenceError("The required own-user presence profile is unavailable")
            if before["profile"] == target:
                return self._public(before)
            # One self-only write, with no retry after timeout, disconnect, or an
            # unsuccessful acknowledgement. Never include TargetExtension.
            decode_acknowledge(await self._wire(encode_profile_change(matches[0])))
            for attempt in range(3):
                after = await self._read()
                if after["profile"] == target:
                    return self._public(after)
                if attempt < 2:
                    await asyncio.sleep(0.15)
            raise PresenceError("The own-user presence change was not confirmed")

    async def close(self):
        self._closed = True
        await self._close_notifications()
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session_key = None
        self._session_pass = None
        self._access_token = None
        self._refresh_token = None
        self._password = None
        self._security_code = None


def presence_provider_from_env(url, own_extension="200", environment=None):
    """Return None until the user explicitly supplies a separate own-user grant."""
    env = os.environ if environment is None else environment
    refresh = env.get("PBX_USER_REFRESH_TOKEN")
    password = env.get("PBX_USER_PASSWORD")
    token_file = env.get("PBX_USER_TOKEN_FILE")
    if not refresh and not password and not token_file:
        return None
    if (not refresh and not password and token_file
            and not Path(token_file).exists() and not Path(token_file).is_symlink()):
        return None
    return MyPhonePresenceProvider(
        url, own_extension=own_extension, refresh_token=refresh,
        username=env.get("PBX_USER_USERNAME") or str(own_extension), password=password,
        security_code=env.get("PBX_USER_SECURITY_CODE"),
        token_file=token_file,
    )
