"""Real localhost persistent HTTP/TLS; no external network or PBX requests."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

import test_badge_http as support

client = support.client


@contextmanager
def persistent_server(folder=None):
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def get_request(self):
            request, address = super().get_request()
            self.accepted += 1
            return request, address
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.server.calls.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/disconnect":
                self.close_connection = True
                return
            body = b'{"ok":true}'
            if self.path == "/http10":
                self.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Length: 11\r\nConnection: keep-alive\r\n\r\n" + body)
                self.close_connection = True
                return
            if self.path == "/extra":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n" + body + b"EXTRA")
                return
            self.send_response(302 if self.path == "/redirect" else 200)
            if self.path == "/redirect":
                self.send_header("Location", "/must-not-follow")
            if self.path in ("/chunked", "/bad-trailer"):
                self.send_header("Transfer-Encoding", "chunked")
            elif self.path == "/eof":
                self.send_header("Connection", "close")
                self.close_connection = True
            else:
                self.send_header("Content-Length", "99" if self.path == "/truncated" else str(len(body)))
            if self.path == "/malformed":
                self.send_header("Transfer-Encoding", "chunked")
            if self.path in ("/close", "/truncated", "/malformed", "/redirect"):
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            try:
                if self.path in ("/chunked", "/bad-trailer"):
                    trailer = b"Content-Length: 999\r\n" if self.path == "/bad-trailer" else b"X-Note: yes\r\n"
                    self.wfile.write(b"b\r\n" + body + b"\r\n0\r\n" + trailer + b"\r\n")
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.server.calls.append(("POST", self.path, self.headers.get("Authorization"), body))
            self.send_response(202)
            response = b'{"status":"accepted"}'
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response)
            self.close_connection = True
    httpd = Server(("127.0.0.1", 0), Handler)
    httpd.accepted, httpd.calls = 0, []
    if folder:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(folder / "server.pem", folder / "server.key")
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield ("https" if folder else "http") + "://localhost:" + str(httpd.server_port), httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(2)


class StateClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        support.make_certificates(cls.folder)
        cls.other = cls.folder / "other"
        cls.other.mkdir()
        support.make_certificates(cls.other)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @contextmanager
    def session(self, secure=False):
        pool = client.StateClient()
        resolve = client.socket.getaddrinfo
        def loopback(host, port, *args):
            return resolve("127.0.0.1" if host == "localhost" else host, port, *args)
        with persistent_server(self.folder if secure else None) as (url, server):
            try:
                # Avoid Windows' unrelated IPv6-refused delay; TLS still
                # verifies the DNS name localhost against the generated cert.
                with patch.object(client.socket, "getaddrinfo", side_effect=loopback):
                    yield pool, url, server
            finally:
                pool.close()

    def get(self, pool, url, path="/state", token="read-token", ca=None):
        return pool.get(url + path, token, str(ca or self.folder / "root.der"), timeout=2)

    def test_http_and_verified_tls_reuse_one_socket_for_length_and_chunked_snapshots(self):
        for secure in (False, True):
            with self.subTest(secure=secure), self.session(secure) as (pool, url, server):
                for path in ("/state", "/chunked", "/state"):
                    self.assertEqual(self.get(pool, url, path), {"ok": True})
                self.assertEqual(server.accepted, 1)
                self.assertEqual(len(server.calls), 3)
                self.assertTrue(all(call[2] == "Bearer read-token" for call in server.calls))
                if secure:
                    self.assertIsNotNone(pool._context)
                    self.assertEqual(pool._context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(pool._context.check_hostname)

    def test_connection_close_http10_eof_and_unread_bytes_are_never_reused(self):
        for path in ("/close", "/http10", "/eof", "/extra"):
            with self.subTest(path=path), self.session() as (pool, url, server):
                self.assertEqual(self.get(pool, url, path), {"ok": True})
                self.assertIsNone(pool._stream)
                self.assertEqual(self.get(pool, url), {"ok": True})
                self.assertEqual(server.accepted, 2)

    def test_bad_framing_truncation_disconnect_and_redirect_fail_once_then_next_poll_is_fresh(self):
        for path in ("/malformed", "/truncated", "/disconnect", "/redirect", "/bad-trailer"):
            with self.subTest(path=path), self.session() as (pool, url, server):
                with self.assertRaises((client.HTTPError, OSError)):
                    self.get(pool, url, path)
                self.assertEqual(len(server.calls), 1)
                self.assertIsNone(pool._stream)
                self.assertEqual(self.get(pool, url), {"ok": True})
                self.assertEqual(server.accepted, 2)
                self.assertEqual(len(server.calls), 2)

    def test_token_and_origin_changes_open_new_connections(self):
        with self.session() as (pool, url, first), persistent_server() as (other_url, second):
            self.get(pool, url)
            self.get(pool, url, token="other-read-token")
            self.assertEqual(first.accepted, 2)
            self.get(pool, other_url, token="other-read-token")
            self.assertEqual(second.accepted, 1)
            self.get(pool, url)
            self.assertEqual(first.accepted, 3)

    def test_ca_changed_in_place_invalidates_tls_pool_and_rejects_before_bearer(self):
        with tempfile.TemporaryDirectory() as directory, self.session(True) as (pool, url, server):
            ca = Path(directory) / "ca.der"
            ca.write_bytes((self.folder / "root.der").read_bytes())
            self.get(pool, url, ca=ca)
            ca.write_bytes((self.other / "root.der").read_bytes())
            with self.assertRaises(client.TLSError):
                self.get(pool, url, ca=ca)
            self.assertEqual(len(server.calls), 1)
            self.assertIsNone(pool._stream)
            ca.write_bytes((self.folder / "root.der").read_bytes())
            self.get(pool, url, ca=ca)
            self.assertEqual(len(server.calls), 2)

    def test_bad_clock_and_hostname_fail_closed_even_after_success(self):
        with self.session(True) as (pool, url, server):
            self.get(pool, url)
            with patch.object(client.time, "gmtime", return_value=(2000, 1, 1, 0, 0, 0, 0, 0)):
                with self.assertRaises(client.ClockError):
                    self.get(pool, url)
            self.assertIsNone(pool._stream)
            with self.assertRaises(client.TLSError):
                self.get(pool, url.replace("localhost", "127.0.0.1"))
            self.assertEqual(len(server.calls), 1)

    def test_idle_and_total_age_bounds_open_fresh_sockets(self):
        with self.session() as (pool, url, server), patch.object(client, "_ticks") as ticks:
            ticks.return_value = 0
            self.get(pool, url)
            ticks.return_value = 4999
            self.get(pool, url)
            self.assertEqual(server.accepted, 1)
            ticks.return_value = 9999
            self.get(pool, url)
            self.assertEqual(server.accepted, 2)
            pool.MAX_IDLE_MS = 1000000
            ticks.return_value = 129999
            self.get(pool, url)
            self.assertEqual(server.accepted, 3)

    def test_post_remains_separate_exactly_once_and_does_not_consume_state_pool(self):
        with self.session(True) as (pool, url, server):
            self.get(pool, url)
            result = client.post_json(url + "/control", "control-token", {"enabled": True}, str(self.folder / "root.der"))
            self.assertEqual(result["http_status"], 202)
            self.get(pool, url)
            self.assertEqual(server.accepted, 2)
            self.assertEqual([call[0] for call in server.calls], ["GET", "POST", "GET"])
            self.assertEqual(json.loads(server.calls[1][3]), {"enabled": True})

    def test_close_is_terminal_and_releases_pool(self):
        with self.session() as (pool, url, server):
            self.get(pool, url)
            pool.close()
            pool.close()
            self.assertIsNone(pool._stream)
            self.assertIsNone(pool._context)
            with self.assertRaisesRegex(client.HTTPError, "CLOSED"):
                self.get(pool, url)
            self.assertEqual(len(server.calls), 1)

    def test_native_exact_read_tls_handles_short_framed_messages_without_waiting_for_eof(self):
        class Stream:
            def __init__(self):
                self.buffer = b""
                self.writes = self.closed = 0
            def write(self, request):
                self_test.assertEqual(self.buffer, b"")
                self.writes += 1
                if self.writes == 2:
                    self.buffer = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nb\r\n{"ok":true}\r\n0\r\nX-End: yes\r\n\r\n'
                else:
                    self.buffer = b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{"ok":true}'
                return len(request)
            def read(self, count):
                # The live peer keeps this stream open. An over-read would
                # wait for bytes from a future request and then time out.
                self_test.assertLessEqual(count, len(self.buffer), "native TLS over-read")
                value, self.buffer = self.buffer[:count], self.buffer[count:]
                return value
            def close(self):
                self.closed += 1
        class Raw:
            def settimeout(self, value): pass
            def connect(self, address): pass
            def close(self): pass
        class Context:
            def wrap_socket(self, sock, *, server_hostname):
                self_test.assertEqual(server_hostname, "badge.invalid")
                return stream
        self_test, stream, raw, context = self, Stream(), Raw(), Context()
        pool = client.StateClient()
        try:
            with patch.object(client, "_tls_context", return_value=context), \
                    patch.object(client.socket, "getaddrinfo", return_value=[(2, 1, 0, "", ("192.0.2.1", 443))]), \
                    patch.object(client.socket, "socket", return_value=raw) as sockets:
                for unused in range(3):
                    self.assertEqual(pool.get("https://badge.invalid/v1/state", "token", str(self.folder / "root.der")), {"ok": True})
                self.assertEqual(sockets.call_count, 1)
                self.assertEqual(stream.writes, 3)
                self.assertEqual(stream.closed, 0)
                self.assertIs(pool._context, context)
        finally:
            pool.close()
        self.assertEqual(stream.closed, 1)


if __name__ == "__main__":
    unittest.main()
