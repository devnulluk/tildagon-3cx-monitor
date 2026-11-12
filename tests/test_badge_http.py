"""Real loopback HTTP/TLS checks for the MicroPython-compatible badge client."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("badge_http_under_test", ROOT / "badge/http_client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def make_certificates(folder):
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Badge unit test CA")])
    root = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=7)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256())
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])).issuer_name(name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=7)).add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True).sign(key, hashes.SHA256())
    folder.joinpath("root.der").write_bytes(root.public_bytes(serialization.Encoding.DER))
    folder.joinpath("server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    folder.joinpath("server.key").write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))


@contextmanager
def server(secure=False, folder=None):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append({"method": "POST", "path": self.path,
                          "authorization": self.headers.get("Authorization"),
                          "content_type": self.headers.get("Content-Type"),
                          "content_length": self.headers.get("Content-Length"),
                          "accept_encoding": self.headers.get("Accept-Encoding"),
                          "body": body})
            self.close_connection = True
            if self.path == "/disconnect":
                return
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/should-not-be-requested")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = int(self.path.rsplit("/", 1)[-1]) if self.path.startswith("/error/") else 202
            response = ({"error": "rejected", "message": "Control rejected"} if status >= 400
                        else {"status": "accepted", "message": "Call requested", "http_status": 999})
            if self.path == "/array":
                response = [1, 2]
            encoded = json.dumps(response).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept-Encoding")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/should-not-be-requested")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            if self.path == "/chunked":
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b'7\r\n{"ok": \r\n5\r\ntrue}\r\n0\r\nX-End: yes\r\n\r\n')
            elif self.path == "/oversize":
                self.send_header("Content-Length", str(client.MAX_BODY + 1))
                self.end_headers()
            elif self.path == "/chunked-oversize":
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"8001\r\n")
            elif self.path == "/truncated":
                self.send_header("Content-Length", "20")
                self.end_headers()
                self.wfile.write(b"{}")
            elif self.path == "/ambiguous":
                self.send_header("Content-Length", "12")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
            elif self.path == "/close":
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            else:
                self.send_header("Content-Length", "12")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            self.close_connection = True
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    if secure:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(folder / "server.pem", folder / "server.key")
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield ("https" if secure else "http") + "://localhost:" + str(httpd.server_port), calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=2)


class BadgeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        make_certificates(cls.folder)
        other = cls.folder / "other"
        other.mkdir()
        make_certificates(other)
        cls.wrong_ca = other / "root.der"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_http_bearer_only_in_header_identity_encoding_and_json(self):
        with server() as (url, calls):
            self.assertEqual(client.get_json(url + "/v1/state", "test-token"), {"ok": True})
        self.assertEqual(calls, [("/v1/state", "Bearer test-token", "identity")])

    def test_verified_https_trust_root_and_hostname(self):
        with server(True, self.folder) as (url, calls):
            self.assertEqual(client.get_json(url + "/v1/state", "test-token", str(self.folder / "root.der")), {"ok": True})
        self.assertEqual(len(calls), 1)

    def test_https_rejects_untrusted_root_before_sending_token(self):
        with server(True, self.folder) as (url, calls):
            with self.assertRaises(client.TLSError):
                client.get_json(url, "test-token", str(self.wrong_ca))
        self.assertEqual(calls, [])

    def test_https_rejects_wrong_hostname_before_sending_token(self):
        with server(True, self.folder) as (url, calls):
            with self.assertRaises(client.TLSError):
                client.get_json(url.replace("localhost", "127.0.0.1"), "test-token", str(self.folder / "root.der"))
        self.assertEqual(calls, [])

    def test_missing_ca_and_reset_clock_fail_closed(self):
        with self.assertRaises(client.TLSError):
            client.get_json("https://localhost", "test-token", str(self.folder / "missing.der"))
        with patch.object(client.time, "gmtime", return_value=(2000, 1, 1, 0, 0, 0, 0, 0)):
            with self.assertRaises(client.ClockError):
                client.get_json("https://localhost", "test-token", str(self.folder / "root.der"))

    def test_pinned_native_tls_module_uses_positional_only_der_ca_loader(self):
        seen = []
        class NativeContext:
            def __init__(self, protocol):
                self.verify_mode = None
                seen.append(("protocol", protocol))
            def load_verify_locations(self, certificate, /):
                seen.append(("ca", certificate))
        native_tls = types.SimpleNamespace(SSLContext=NativeContext, PROTOCOL_TLS_CLIENT=19, CERT_REQUIRED=2)
        with patch.dict(sys.modules, {"tls": native_tls}):
            context = client._tls_context(str(self.folder / "root.der"))
        self.assertEqual(context.verify_mode, native_tls.CERT_REQUIRED)
        self.assertEqual(seen, [("protocol", 19), ("ca", (self.folder / "root.der").read_bytes())])

    def test_native_tls_stream_hostname_handshake_timeout_and_bearer_order(self):
        seen = []
        class NativeStream:
            response = b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n{"ok": true}'
            def write(self, request):
                seen.append(("write", request))
                return len(request)
            def read(self, length):
                result, self.response = self.response[:length], self.response[length:]
                return result
            def close(self):
                seen.append(("stream-close",))
        stream = NativeStream()
        class RawSocket:
            def settimeout(self, value):
                seen.append(("timeout", value))
            def connect(self, address):
                seen.append(("connect", address))
            def close(self):
                seen.append(("raw-close",))
        raw = RawSocket()
        class NativeContext:
            def __init__(self, protocol):
                self.verify_mode = None
            def load_verify_locations(self, certificate, /):
                self.certificate = certificate
            def wrap_socket(self, sock, *, server_hostname):
                self_test.assertEqual(self.verify_mode, 2)
                self_test.assertIs(sock, raw)
                self_test.assertEqual(seen[-1][0], "timeout")
                seen.append(("handshake", server_hostname))
                return stream
        self_test = self
        native_tls = types.SimpleNamespace(SSLContext=NativeContext, PROTOCOL_TLS_CLIENT=19, CERT_REQUIRED=2)
        with patch.dict(sys.modules, {"tls": native_tls}), patch.object(client.socket, "getaddrinfo", return_value=[(2, 1, 0, "", ("192.0.2.1", 443))]), patch.object(client.socket, "socket", return_value=raw):
            value = client.get_json("https://badge.example/v1/state", "test-token", str(self.folder / "root.der"))
        self.assertEqual(value, {"ok": True})
        handshake = next(index for index, event in enumerate(seen) if event[0] == "handshake")
        request = next(index for index, event in enumerate(seen) if event[0] == "write")
        self.assertLess(handshake, request)
        self.assertEqual(seen[handshake], ("handshake", "badge.example"))
        self.assertIn(b"Authorization: Bearer test-token\r\n", seen[request][1])
        self.assertEqual(seen[-2:], [("stream-close",), ("raw-close",)])

    def test_redirect_is_never_followed(self):
        with server() as (url, calls):
            with self.assertRaisesRegex(client.HTTPError, "HTTP 302"):
                client.get_json(url + "/redirect", "test-token")
        self.assertEqual(len(calls), 1)

    def test_chunked_and_connection_close_bodies(self):
        with server() as (url, calls):
            self.assertEqual(client.get_json(url + "/chunked", "test-token"), {"ok": True})
            self.assertEqual(client.get_json(url + "/close", "test-token"), {"ok": True})

    def test_oversize_truncated_and_ambiguous_responses_rejected(self):
        with server() as (url, calls):
            for path in ("oversize", "chunked-oversize", "truncated", "ambiguous"):
                with self.subTest(path=path), self.assertRaises(client.HTTPError):
                    client.get_json(url + "/" + path, "test-token")

    def test_invalid_urls_and_header_injection_rejected_before_network(self):
        for url in ("https://bridge/path?token=bad", "https://user:pass@bridge", "https://bridge/#fragment", "https://bridge/\r\nInjected: true", "ftp://bridge", "https://bridge:0", "https://bridge:99999", "https://bridge\\evil", "https://", "https://[bad"):
            with self.subTest(url=url), self.assertRaises(client.HTTPError):
                client.get_json(url, "test-token")
        for token in ("", "token\r\nInjected: true", "hello world", "non-ascii-£"):
            with self.subTest(token=token), self.assertRaises(client.HTTPError):
                client.get_json("http://localhost", token)

    def test_post_bearer_exact_json_length_and_accepted_status(self):
        payload = {"target": "TB", "request_id": "a" * 32, "session_id": "b" * 32}
        with server() as (url, calls):
            result = client.post_json(url + "/v1/control/call", "test-control-token", payload)
        self.assertEqual(result["http_status"], 202)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(len(calls), 1)
        sent = calls[0]
        self.assertEqual(sent["path"], "/v1/control/call")
        self.assertEqual(sent["authorization"], "Bearer test-control-token")
        self.assertEqual(sent["content_type"], "application/json")
        self.assertEqual(sent["accept_encoding"], "identity")
        self.assertEqual(int(sent["content_length"]), len(sent["body"]))
        self.assertEqual(json.loads(sent["body"]), payload)
        self.assertNotIn(b"test-control-token", sent["body"])
        self.assertNotIn(b": ", sent["body"])

    def test_post_json_errors_are_returned_with_real_http_status(self):
        statuses = (400, 401, 403, 409, 413, 415, 422, 429, 500, 501, 502, 503, 504)
        with server() as (url, calls):
            for status in statuses:
                with self.subTest(status=status):
                    result = client.post_json(url + "/error/" + str(status), "test-control-token", {"enabled": True})
                    self.assertEqual(result["http_status"], status)
                    self.assertEqual(result["error"], "rejected")
        self.assertEqual(len(calls), len(statuses))

    def test_verified_https_post_and_untrusted_ca_rejects_before_token_send(self):
        with server(True, self.folder) as (url, calls):
            result = client.post_json(url + "/v1/control/dnd", "test-control-token", {"enabled": True},
                                      str(self.folder / "root.der"))
            self.assertEqual(result["http_status"], 202)
            with self.assertRaises(client.TLSError):
                client.post_json(url + "/v1/control/dnd", "test-control-token", {"enabled": True},
                                 str(self.wrong_ca))
        self.assertEqual(len(calls), 1)

    def test_post_redirect_and_ambiguous_disconnect_never_retry(self):
        with server() as (url, calls):
            with self.assertRaisesRegex(client.HTTPError, "HTTP 302"):
                client.post_json(url + "/redirect", "test-control-token", {"enabled": True})
            self.assertEqual(len(calls), 1)
            with self.assertRaises(client.HTTPError):
                client.post_json(url + "/disconnect", "test-control-token", {"enabled": True})
            self.assertEqual(len(calls), 2)

    def test_post_payload_is_bounded_before_network_and_errors_are_fixed_text(self):
        payloads = (None, [1], {"text": "x" * client.MAX_REQUEST_BODY}, {"invalid": object()})
        with patch.object(client.socket, "getaddrinfo") as resolve:
            for payload in payloads:
                with self.subTest(payload_type=type(payload).__name__), self.assertRaises(client.HTTPError) as error:
                    client.post_json("http://localhost/v1/control/call", "test-control-token", payload)
                self.assertIn(str(error.exception), ("INVALID CONTROL PAYLOAD", "CONTROL PAYLOAD TOO LARGE"))
            resolve.assert_not_called()

    def test_post_non_object_response_is_rejected(self):
        with server() as (url, calls):
            with self.assertRaisesRegex(client.HTTPError, "INVALID CONTROL RESPONSE"):
                client.post_json(url + "/array", "test-control-token", {})
        self.assertEqual(len(calls), 1)

    def test_post_unicode_json_content_length_counts_encoded_bytes(self):
        payload = {"label": "Partner £"}
        with server() as (url, calls):
            client.post_json(url + "/control", "test-control-token", payload)
        self.assertEqual(int(calls[0]["content_length"]), len(calls[0]["body"]))
        self.assertEqual(json.loads(calls[0]["body"].decode("utf-8")), payload)

    def test_unsupported_method_and_get_payload_rejected_before_network(self):
        with patch.object(client.socket, "getaddrinfo") as resolve:
            with self.assertRaises(client.HTTPError):
                client.request_json("http://localhost", "test-token", method="DELETE")
            with self.assertRaises(client.HTTPError):
                client.request_json("http://localhost", "test-token", method="GET", payload={})
            resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
