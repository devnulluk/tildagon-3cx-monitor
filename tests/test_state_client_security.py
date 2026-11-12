"""Independent connection-boundary and shutdown tests; no network/PBX calls."""
from contextlib import contextmanager, ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("independent_state_security", ROOT / "badge/http_client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def response(headers=b"", body=b'{"ok":true}', version=b"HTTP/1.1"):
    return version + b" 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n" + headers + b"\r\n" + body


class Wire:
    def __init__(self, owner):
        self.owner = owner
        self.rx = b""
        self.requests = []
        self.closed = False
        self.close_threads = []
        self.block_next_read = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def settimeout(self, value):
        if value <= 0:
            raise AssertionError("Unbounded or expired request")

    def connect(self, address):
        self.address = address

    def write(self, value):
        if self.closed:
            raise OSError("closed test connection")
        self.requests.append(bytes(value))
        self.rx += self.owner.replies.pop(0) if self.owner.replies else response()
        return len(value)

    def recv(self, length):
        if self.block_next_read:
            self.block_next_read = False
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("test read was not released")
        value, self.rx = self.rx[:length], self.rx[length:]
        return value

    def close(self):
        self.close_threads.append(threading.get_ident())
        self.closed = True


class Harness:
    def __init__(self):
        self.wires = []
        self.contexts = []
        self.replies = []
        owner = self

        class NativeContext:
            def __init__(self, protocol):
                self.protocol = protocol
                self.verify_mode = None
                self.check_hostname = False
                self.names = []
                owner.contexts.append(self)

            def load_verify_locations(self, der, /):
                self.ca_bytes = der

            def wrap_socket(self, raw, *, server_hostname):
                if self.verify_mode != 2 or not self.check_hostname:
                    raise AssertionError("TLS verification disabled")
                self.names.append(server_hostname)
                return raw

        self.tls = types.SimpleNamespace(SSLContext=NativeContext, PROTOCOL_TLS_CLIENT=16, CERT_REQUIRED=2)

    def socket(self, *args):
        value = Wire(self)
        self.wires.append(value)
        return value

    @contextmanager
    def patched(self):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {"tls": self.tls}))
            stack.enter_context(patch.object(client.socket, "getaddrinfo", return_value=[(2, 1, 0, "", ("127.0.0.1", 443))]))
            stack.enter_context(patch.object(client.socket, "socket", side_effect=self.socket))
            stack.enter_context(patch.object(client.time, "gmtime", return_value=(2026, 11, 12, 0, 0, 0, 3, 316, 0)))
            yield self


class StateClientSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ca = Path(self.temp.name) / "root.der"
        self.ca.write_bytes(b"public-test-root-a")
        self.session = client.StateClient()
        self.harness = Harness()
        self.url = "https://bridge.example.invalid/v1/state"
        self.token = "unit-read-token"

    def tearDown(self):
        self.session.close()
        self.temp.cleanup()

    def get(self, url=None, token=None, ca=None):
        return self.session.get(url or self.url, token or self.token, str(ca or self.ca))

    def test_native_ca_loader_required_identity_and_connection_reuse(self):
        with self.harness.patched():
            self.assertEqual(self.get(), {"ok": True})
            self.assertEqual(self.get(), {"ok": True})
        self.assertEqual(len(self.harness.contexts), 1)
        context = self.harness.contexts[0]
        self.assertEqual((context.protocol, context.verify_mode, context.check_hostname), (16, 2, True))
        self.assertEqual(context.ca_bytes, self.ca.read_bytes())
        self.assertEqual(context.names, ["bridge.example.invalid"])
        self.assertEqual(len(self.harness.wires), 1)
        for request in self.harness.wires[0].requests:
            self.assertTrue(request.startswith(b"GET /v1/state HTTP/1.1\r\n"))
            self.assertIn(b"Authorization: Bearer unit-read-token\r\n", request)
            self.assertNotIn(self.token.encode(), request.split(b"\r\n", 1)[0])
            self.assertIn(b"Accept-Encoding: identity\r\n", request)

    def test_token_origin_port_and_ca_path_changes_never_reuse_old_wire(self):
        second_ca = self.ca.with_name("other-path.der")
        second_ca.write_bytes(self.ca.read_bytes())
        requests = [(self.url, self.token, self.ca),
                    (self.url, "new-read-token", self.ca),
                    ("https://other.example.invalid/v1/state", "new-read-token", self.ca),
                    ("https://other.example.invalid:9443/v1/state", "new-read-token", self.ca),
                    ("https://other.example.invalid:9443/v1/state", "new-read-token", second_ca)]
        with self.harness.patched():
            for url, token, ca in requests:
                self.get(url, token, ca)
        self.assertEqual(len(self.harness.wires), len(requests))
        for index, (wire, (_, token, _)) in enumerate(zip(self.harness.wires, requests)):
            self.assertEqual(len(wire.requests), 1)
            self.assertIn(("Authorization: Bearer " + token + "\r\n").encode(), wire.requests[0])
            self.assertEqual(wire.closed, index < len(requests) - 1)

    def test_same_ca_path_changed_bytes_reauthenticates_with_new_root(self):
        with self.harness.patched():
            self.get()
            self.ca.write_bytes(b"public-test-root-b")
            self.get()
        self.assertTrue(self.harness.wires[0].closed)
        self.assertEqual([context.ca_bytes for context in self.harness.contexts],
                         [b"public-test-root-a", b"public-test-root-b"])

    def test_clock_reset_and_invalid_input_discard_pool_without_sending_token(self):
        with self.harness.patched():
            self.get()
            with patch.object(client.time, "gmtime", return_value=(2000, 1, 1, 0, 0, 0, 5, 1, 0)):
                with self.assertRaises(client.ClockError):
                    self.get()
            self.assertTrue(self.harness.wires[0].closed)
            self.get()
            with self.assertRaises(client.HTTPError):
                self.session.get(self.url, "bad\r\nInjected: header", str(self.ca))
            self.assertTrue(self.harness.wires[1].closed)
            self.assertEqual([len(wire.requests) for wire in self.harness.wires], [1, 1])

    def test_empty_or_unreadable_ca_after_reuse_closes_prior_session(self):
        with self.harness.patched():
            self.get()
            self.ca.write_bytes(b"")
            with self.assertRaises(client.TLSError):
                self.get()
            self.assertTrue(self.harness.wires[0].closed)
            self.assertEqual(len(self.harness.wires), 1)

    def test_close_is_terminal_even_for_a_late_queued_worker(self):
        self.session.close()
        with self.harness.patched(), self.assertRaisesRegex(client.HTTPError, "CLOSED"):
            self.get()
        self.assertEqual(self.harness.wires, [])
        self.assertEqual(self.harness.contexts, [])

    def _start_blocked_worker(self):
        self.get()
        wire = self.harness.wires[0]
        wire.block_next_read = True
        result = []
        def run():
            try:
                result.append(self.get())
            except BaseException as error:
                result.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        if not wire.entered.wait(2):
            wire.release.set()
            worker.join(3)
            self.fail("Worker did not reach bounded read")
        return wire, worker, result

    def test_on_stop_close_defers_native_stream_disposal_to_worker(self):
        with self.harness.patched():
            wire, worker, result = self._start_blocked_worker()
            try:
                self.session.close()
                self.assertFalse(wire.closed)
                self.assertIsNotNone(self.session._context)
            finally:
                wire.release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [{"ok": True}])
            self.assertEqual(wire.close_threads, [worker.ident])
            self.assertIsNone(self.session._context)
            self.assertIsNone(self.session._stream)
            with self.assertRaisesRegex(client.HTTPError, "CLOSED"):
                self.get()

    def test_concurrent_admission_cannot_discard_or_mix_active_credentials(self):
        with self.harness.patched():
            wire, worker, result = self._start_blocked_worker()
            try:
                with self.assertRaisesRegex(client.HTTPError, "IN PROGRESS"):
                    self.get(token="different-token")
                self.assertFalse(wire.closed)
                self.assertEqual(len(wire.requests), 2)
                self.assertNotIn(b"different-token", b"".join(wire.requests))
            finally:
                wire.release.set()
                worker.join(3)
            self.assertEqual(result, [{"ok": True}])
            self.assertFalse(wire.closed)

    def test_close_racing_final_handoff_cannot_publish_a_live_pool(self):
        handoff_entered, release_handoff, close_attempted = (threading.Event() for _ in range(3))
        class HandoffGate:
            def __init__(self):
                self.inner = threading.Lock()
                self.entries = 0
            def __enter__(self):
                self.inner.acquire()
                self.entries += 1
                if self.entries == 2:
                    handoff_entered.set()
                    if not release_handoff.wait(3):
                        self.inner.release()
                        raise AssertionError("Final handoff was not released")
                return self
            def __exit__(self, *args):
                self.inner.release()
        with self.harness.patched():
            self.get()
            wire = self.harness.wires[0]
            self.session._lock = HandoffGate()
            results = []
            worker = threading.Thread(target=lambda: results.append(self.get()))
            def close():
                close_attempted.set()
                self.session.close()
            closer = threading.Thread(target=close)
            worker.start()
            try:
                self.assertTrue(handoff_entered.wait(2))
                closer.start()
                self.assertTrue(close_attempted.wait(2))
                self.assertFalse(wire.closed)
            finally:
                release_handoff.set()
                worker.join(3)
                if closer.ident is not None:
                    closer.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(closer.is_alive())
            self.assertEqual(results, [{"ok": True}])
            self.assertTrue(self.session._closed)
            self.assertIsNone(self.session._stream)
            self.assertIsNone(self.session._context)
            self.assertEqual(wire.close_threads, [closer.ident])

    def test_connection_tokens_http10_unread_data_and_eof_are_not_reusable(self):
        cases = [response(b"Connection: keep-alive\r\nConnection: close\r\n"),
                 response(b"Connection: keep-alive\r\n", version=b"HTTP/1.0"),
                 response() + b"UNSOLICITED", b'HTTP/1.1 200 OK\r\n\r\n{"ok":true}']
        for raw in cases:
            with self.subTest(response=raw[:60]):
                session = client.StateClient()
                harness = Harness()
                harness.replies = [raw]
                with harness.patched():
                    self.assertEqual(session.get(self.url, self.token, str(self.ca)), {"ok": True})
                self.assertTrue(harness.wires[0].closed)
                self.assertIsNone(session._stream)
                session.close()

    def test_ambiguous_framing_redirect_and_bad_chunk_trailer_never_retry(self):
        cases = [b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nTransfer-Encoding: chunked\r\n\r\n',
                 b'HTTP/1.1 302 Found\r\nLocation: https://elsewhere.invalid/\r\nContent-Length: 0\r\n\r\n',
                 b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nb\r\n{"ok":true}\r\n0\r\nConnection: keep-alive\r\n\r\n']
        for raw in cases:
            with self.subTest(response=raw[:60]):
                session = client.StateClient()
                harness = Harness()
                harness.replies = [raw]
                with harness.patched(), self.assertRaises(client.HTTPError):
                    session.get(self.url, self.token, str(self.ca))
                self.assertEqual(len(harness.wires), 1)
                self.assertEqual(len(harness.wires[0].requests), 1)
                self.assertTrue(harness.wires[0].closed)
                session.close()


if __name__ == "__main__":
    unittest.main()
