"""Small bounded HTTP client with verified MicroPython HTTPS.

Unlike the badge's frozen requests client, HTTPS here always authenticates the
server with a supplied DER trust root and the URL hostname. No redirects follow.
The caller runs this whole function in async_helpers.unblock().
"""

import json
import socket
import time

MAX_BODY = 32768
MAX_HEADERS = 8192
MAX_REQUEST_BODY = 1024


class ClockError(ValueError):
    pass


class TLSError(ValueError):
    pass


class HTTPError(ValueError):
    pass


def parse_url(url):
    if not isinstance(url, str) or len(url) > 1024:
        raise HTTPError("INVALID BRIDGE URL")
    if any(ord(character) < 33 or ord(character) > 126 for character in url):
        raise HTTPError("INVALID BRIDGE URL")
    if "?" in url or "#" in url or "@" in url or "\\" in url:
        raise HTTPError("INVALID BRIDGE URL")
    if url.startswith("https://"):
        secure, rest, default_port = True, url[8:], 443
    elif url.startswith("http://"):
        secure, rest, default_port = False, url[7:], 80
    else:
        raise HTTPError("INVALID BRIDGE URL")
    parts = rest.split("/", 1)
    authority = parts[0]
    path = "/" + parts[1] if len(parts) == 2 else "/"
    port = default_port
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            raise HTTPError("INVALID BRIDGE HOST")
        host = authority[1:end]
        suffix = authority[end + 1:]
        if not host or any(character not in "0123456789abcdefABCDEF:." for character in host):
            raise HTTPError("INVALID BRIDGE HOST")
        if suffix:
            if not suffix.startswith(":") or not suffix[1:].isdigit():
                raise HTTPError("INVALID BRIDGE PORT")
            port = int(suffix[1:])
    else:
        if authority.count(":") > 1:
            raise HTTPError("INVALID BRIDGE HOST")
        fields = authority.split(":", 1)
        host = fields[0]
        if len(fields) == 2:
            if not fields[1].isdigit():
                raise HTTPError("INVALID BRIDGE PORT")
            port = int(fields[1])
        if not host or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for character in host):
            raise HTTPError("INVALID BRIDGE HOST")
        if host.startswith(".") or host.endswith(".") or ".." in host:
            raise HTTPError("INVALID BRIDGE HOST")
    if not 1 <= port <= 65535:
        raise HTTPError("INVALID BRIDGE PORT")
    return secure, host, port, authority, path


def _ticks():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def _elapsed(start):
    now = _ticks()
    return time.ticks_diff(now, start) if hasattr(time, "ticks_diff") else now - start


def _remaining(start, timeout):
    remaining = timeout - _elapsed(start) / 1000
    if remaining <= 0:
        raise OSError("Bridge request timed out")
    return remaining


def _check_clock():
    # The TLS implementation validates exact certificate validity dates too.
    # This preliminary check gives an actionable message after an RTC reset.
    try:
        year = time.gmtime()[0]
    except Exception:
        raise ClockError("SET BADGE CLOCK")
    if year < 2024:
        raise ClockError("SET BADGE CLOCK")


def _read_trust_root(ca_file):
    try:
        with open(ca_file, "rb") as handle:
            trust_root = handle.read(16385)
        if not trust_root or len(trust_root) > 16384:
            raise ValueError("Invalid trust root size")
        return trust_root
    except Exception:
        raise TLSError("TLS CA / FIRMWARE ERROR")


def _tls_context(ca_file, trust_root=None):
    _check_clock()
    try:
        # The badge's pinned MicroPython exposes its native module as `tls`.
        # Its CA loader takes DER bytes positionally. CPython and newer builds
        # provide `ssl` with the standard cadata keyword instead.
        try:
            import tls as ssl
            native_tls = True
        except ImportError:
            import ssl
            native_tls = False
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        # CPython has this property; MicroPython does the hostname check through
        # server_hostname combined with CERT_REQUIRED instead.
        if hasattr(context, "check_hostname"):
            context.check_hostname = True
        if trust_root is None:
            trust_root = _read_trust_root(ca_file)
        if native_tls:
            context.load_verify_locations(trust_root)
        else:
            context.load_verify_locations(cadata=trust_root)
        return context
    except Exception:
        raise TLSError("TLS CA / FIRMWARE ERROR")


class _Reader:
    def __init__(self, stream, timeout_socket, start, timeout):
        self.stream = stream
        self.timeout_socket = timeout_socket
        self.start = start
        self.timeout = timeout
        self.buffer = b""

    def chunk(self, limit=512):
        self.timeout_socket.settimeout(_remaining(self.start, self.timeout))
        if hasattr(self.stream, "recv"):
            return self.stream.recv(limit)
        if hasattr(self.stream, "read1"):
            return self.stream.read1(limit)
        return self.stream.read(limit)

    def line(self, limit=MAX_HEADERS):
        while True:
            end = self.buffer.find(b"\r\n")
            if end >= 0:
                if end + 2 > limit:
                    raise HTTPError("HTTP HEADERS TOO LARGE")
                line, self.buffer = self.buffer[:end], self.buffer[end + 2:]
                return line
            if len(self.buffer) >= limit:
                raise HTTPError("HTTP HEADERS TOO LARGE")
            # Native MicroPython TLS.read(n) fills n bytes. Request only one
            # header byte there; a keepalive peer need not send any body yet.
            short_read = hasattr(self.stream, "recv") or hasattr(self.stream, "read1")
            chunk = self.chunk(512 if short_read else 1)
            if not chunk:
                raise HTTPError("TRUNCATED HTTP RESPONSE")
            self.buffer += chunk

    def exact(self, length):
        result = bytearray()
        while length:
            if not self.buffer:
                self.buffer = self.chunk(min(512, length))
                if not self.buffer:
                    raise HTTPError("TRUNCATED HTTP RESPONSE")
            take = min(length, len(self.buffer))
            result.extend(self.buffer[:take])
            self.buffer = self.buffer[take:]
            length -= take
        return bytes(result)


def _read_response(reader, return_status=False, connection_info=None):
    status_line = reader.line(256)
    parts = status_line.split(b" ", 2)
    if len(parts) < 2 or parts[0] not in (b"HTTP/1.0", b"HTTP/1.1") or len(parts[1]) != 3 or not parts[1].isdigit():
        raise HTTPError("INVALID HTTP RESPONSE")
    status = int(parts[1])
    if (not return_status and status != 200) or (return_status and status not in (200, 202) and not 400 <= status <= 599):
        # Never forward a bearer token to a redirect target, even same-origin.
        raise HTTPError("HTTP " + str(status))
    headers = {}
    total = len(status_line) + 2
    while True:
        line = reader.line(MAX_HEADERS - total)
        total += len(line) + 2
        if not line:
            break
        if b":" not in line or line[:1] in (b" ", b"\t"):
            raise HTTPError("INVALID HTTP HEADERS")
        key, value = line.split(b":", 1)
        try:
            key, value = key.decode("ascii").lower(), value.decode("ascii").strip()
        except UnicodeError:
            raise HTTPError("INVALID HTTP HEADERS")
        if not key or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in key):
            raise HTTPError("INVALID HTTP HEADERS")
        if any(ord(character) < 32 and character != "\t" for character in value):
            raise HTTPError("INVALID HTTP HEADERS")
        if key in ("content-length", "transfer-encoding") and key in headers:
            raise HTTPError("AMBIGUOUS HTTP LENGTH")
        if key == "connection" and key in headers:
            value = headers[key] + "," + value
        headers[key] = value
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPError("UNSUPPORTED HTTP ENCODING")
    transfer = headers.get("transfer-encoding", "").lower()
    length = headers.get("content-length")
    if transfer and (transfer != "chunked" or length is not None):
        raise HTTPError("AMBIGUOUS HTTP LENGTH")
    if transfer == "chunked":
        body = bytearray()
        while True:
            size = reader.line(128).split(b";", 1)[0].strip()
            if not size or any(character not in b"0123456789abcdefABCDEF" for character in size):
                raise HTTPError("INVALID HTTP CHUNK")
            size = int(size, 16)
            if size == 0:
                trailers = 0
                while True:
                    line = reader.line(MAX_HEADERS - trailers)
                    trailers += len(line) + 2
                    if not line:
                        break
                    if connection_info is not None:
                        if b":" not in line or line[:1] in (b" ", b"\t"):
                            raise HTTPError("INVALID HTTP TRAILERS")
                        try:
                            key, value = line.split(b":", 1)
                            key, value = key.decode("ascii").lower(), value.decode("ascii")
                        except UnicodeError:
                            raise HTTPError("INVALID HTTP TRAILERS")
                        if (not key or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in key)
                                or any(ord(c) < 32 and c != "\t" for c in value)
                                or key in ("content-length", "transfer-encoding", "connection", "host", "upgrade", "trailer")):
                            raise HTTPError("INVALID HTTP TRAILERS")
                break
            if len(body) + size > MAX_BODY:
                raise HTTPError("HTTP RESPONSE TOO LARGE")
            body.extend(reader.exact(size))
            if reader.exact(2) != b"\r\n":
                raise HTTPError("INVALID HTTP CHUNK")
        body = bytes(body)
    elif length is not None:
        if not length.isdigit() or len(length) > 8:
            raise HTTPError("INVALID HTTP LENGTH")
        length = int(length)
        if length > MAX_BODY:
            raise HTTPError("HTTP RESPONSE TOO LARGE")
        body = reader.exact(length)
    else:
        body = bytearray(reader.buffer)
        reader.buffer = b""
        while True:
            chunk = reader.chunk()
            if not chunk:
                break
            if len(body) + len(chunk) > MAX_BODY:
                raise HTTPError("HTTP RESPONSE TOO LARGE")
            body.extend(chunk)
        body = bytes(body)
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPError("INVALID JSON RESPONSE")
    if connection_info is not None:
        connection = [item.strip().lower() for item in headers.get("connection", "").split(",") if item.strip()]
        connection_info["reusable"] = bool(parts[0] == b"HTTP/1.1" and (length is not None or transfer == "chunked")
            and "close" not in connection and all(item == "keep-alive" for item in connection)
            and "upgrade" not in headers and not reader.buffer)
    return (status, value) if return_status else value


def request_json(url, token, method="GET", payload=None, ca_file="ca.der", timeout=5):
    secure, host, port, authority, path = parse_url(url)
    if not isinstance(token, str) or not token or len(token) > 1024 or any(ord(character) < 33 or ord(character) > 126 for character in token):
        raise HTTPError("INVALID BRIDGE TOKEN")
    if method not in ("GET", "POST") or (method == "GET" and payload is not None):
        raise HTTPError("INVALID HTTP METHOD")
    body = b""
    if method == "POST":
        if not isinstance(payload, dict):
            raise HTTPError("INVALID CONTROL PAYLOAD")
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, UnicodeError):
            raise HTTPError("INVALID CONTROL PAYLOAD")
        if len(body) > MAX_REQUEST_BODY:
            raise HTTPError("CONTROL PAYLOAD TOO LARGE")
    context = _tls_context(ca_file) if secure else None
    start = _ticks()
    raw, stream = None, None
    try:
        addresses = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        for family, socktype, protocol, unused, address in addresses:
            try:
                raw = socket.socket(family, socktype)
                raw.settimeout(_remaining(start, timeout))
                raw.connect(address)
                break
            except OSError:
                if raw is not None:
                    raw.close()
                    raw = None
        if raw is None:
            raise OSError("Bridge connection failed")
        stream = raw
        if secure:
            try:
                raw.settimeout(_remaining(start, timeout))
                stream = context.wrap_socket(raw, server_hostname=host)
            except Exception:
                raise TLSError("TLS / CLOCK / HOST ERROR")
        timeout_socket = stream if hasattr(stream, "settimeout") else raw
        request = (
            method + " " + path + " HTTP/1.1\r\nHost: " + authority +
            "\r\nAuthorization: Bearer " + token +
            "\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n" +
            ("Content-Type: application/json\r\nContent-Length: " + str(len(body)) + "\r\n" if method == "POST" else "") +
            "\r\n"
        ).encode("ascii") + body
        offset = 0
        while offset < len(request):
            timeout_socket.settimeout(_remaining(start, timeout))
            if hasattr(stream, "write"):
                sent = stream.write(request[offset:])
            else:
                sent = stream.send(request[offset:])
            if not sent:
                raise OSError("Bridge connection closed")
            offset += sent
        response = _read_response(_Reader(stream, timeout_socket, start, timeout), return_status=method == "POST")
        if method == "POST":
            status, value = response
            if not isinstance(value, dict):
                raise HTTPError("INVALID CONTROL RESPONSE")
            # The server cannot spoof this field through a JSON payload. The
            # app needs the transport status to distinguish rejected actions
            # from requests accepted by the bridge.
            value["http_status"] = status
            return value
        return response
    finally:
        if stream is not None:
            stream.close()
        if raw is not None and raw is not stream:
            raw.close()


def get_json(url, token, ca_file="ca.der", timeout=5):
    return request_json(url, token, ca_file=ca_file, timeout=timeout)


def post_json(url, token, payload, ca_file="ca.der", timeout=5):
    # This method sends exactly one HTTP request. A timeout or disconnect after
    # sending is ambiguous and must never trigger an automatic action retry.
    return request_json(url, token, method="POST", payload=payload, ca_file=ca_file, timeout=timeout)


class StateClient:
    """One bounded GET connection for a serialized worker; never sends POSTs.

    Every failure discards the connection. A failed request is not retried;
    a later poll may establish a new verified connection. close() during a
    worker request defers cleanup until that bounded request finishes, avoiding
    freeing a native TLS socket concurrently with its read/handshake.
    """
    MAX_AGE_MS = 120000
    MAX_IDLE_MS = 5000

    def __init__(self):
        import _thread
        self._lock = _thread.allocate_lock()
        self._raw = self._stream = self._context = None
        self._key = None
        self._created_ms = self._used_ms = None
        self._busy = False
        self._close_requested = False
        self._closed = False

    def _detach(self):
        detached = (self._stream, self._raw, self._context)
        self._stream = self._raw = self._context = None
        self._key = self._created_ms = self._used_ms = None
        return detached

    @staticmethod
    def _dispose(detached):
        stream, raw, context = detached
        for value in (stream, raw if raw is not stream else None):
            if value is not None:
                try:
                    value.close()
                except Exception:
                    pass

    def _discard(self):
        self._dispose(self._detach())

    def close(self):
        with self._lock:
            self._closed = True
            if self._busy:
                self._close_requested = True
                return
            detached = self._detach()
        self._dispose(detached)

    def get(self, url, token, ca_file="ca.der", timeout=5):
        with self._lock:
            if self._closed:
                raise HTTPError("STATE CLIENT CLOSED")
            if self._busy:
                raise HTTPError("STATE REQUEST IN PROGRESS")
            self._busy = True
        try:
            start = _ticks()
            secure, host, port, authority, path = parse_url(url)
            if (not isinstance(token, str) or not token or len(token) > 1024
                    or any(ord(c) < 33 or ord(c) > 126 for c in token)):
                raise HTTPError("INVALID BRIDGE TOKEN")
            _check_clock()
            trust_root = _read_trust_root(ca_file) if secure else None
            key = (secure, host, port, authority, token, str(ca_file), trust_root)
            if (key != self._key or self._stream is None
                    or _elapsed(self._created_ms) >= self.MAX_AGE_MS
                    or _elapsed(self._used_ms) >= self.MAX_IDLE_MS):
                self._discard()
                self._context = _tls_context(ca_file, trust_root) if secure else None
                addresses = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
                for family, socktype, protocol, unused, address in addresses:
                    try:
                        self._raw = socket.socket(family, socktype)
                        self._raw.settimeout(_remaining(start, timeout))
                        self._raw.connect(address)
                        break
                    except OSError:
                        if self._raw is not None:
                            self._raw.close()
                            self._raw = None
                if self._raw is None:
                    raise OSError("Bridge connection failed")
                self._stream = self._raw
                if secure:
                    try:
                        self._raw.settimeout(_remaining(start, timeout))
                        self._stream = self._context.wrap_socket(self._raw, server_hostname=host)
                    except Exception:
                        raise TLSError("TLS / CLOCK / HOST ERROR")
                self._key = key
                self._created_ms = start
            stream = self._stream
            timeout_socket = stream if hasattr(stream, "settimeout") else self._raw
            request = ("GET " + path + " HTTP/1.1\r\nHost: " + authority
                       + "\r\nAuthorization: Bearer " + token
                       + "\r\nAccept: application/json\r\nAccept-Encoding: identity"
                       + "\r\nConnection: keep-alive\r\n\r\n").encode("ascii")
            offset = 0
            while offset < len(request):
                timeout_socket.settimeout(_remaining(start, timeout))
                sent = stream.write(request[offset:]) if hasattr(stream, "write") else stream.send(request[offset:])
                if not sent:
                    raise OSError("Bridge connection closed")
                offset += sent
            reader = _Reader(stream, timeout_socket, start, timeout)
            metadata = {}
            value = _read_response(reader, connection_info=metadata)
            if metadata.get("reusable"):
                self._used_ms = _ticks()
            else:
                self._discard()
            return value
        except BaseException:
            self._discard()
            raise
        finally:
            with self._lock:
                detached = self._detach() if self._closed or self._close_requested else None
                self._close_requested = False
                self._busy = False
            if detached is not None:
                self._dispose(detached)
