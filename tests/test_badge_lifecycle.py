"""Real asyncio cancellation of the actual app; fake transport, no PBX/network."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import test_badge as support
import test_state_client_security as security


class BadgeBackgroundLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_cancellation_closes_inflight_state_client_without_keypress(self):
        module, monitor, hardware = support.BadgeAppTests.live_monitor()
        harness = security.Harness()
        socket_created, socket_closed = threading.Event(), threading.Event()
        original_socket = harness.socket
        def blocked_socket(*args):
            wire = original_socket(*args)
            wire.block_next_read = True
            original_close = wire.close
            def close():
                original_close()
                socket_closed.set()
            wire.close = close
            socket_created.set()
            return wire
        harness.socket = blocked_socket
        unblock_entered = asyncio.Event()
        async def unblock(function, periodic, *args, **kwargs):
            unblock_entered.set()
            # Cancelling this await does not stop the native worker, matching
            # firmware async_helpers.unblock's resource-lifetime challenge.
            return await asyncio.to_thread(function, *args, **kwargs)
        wifi = types.SimpleNamespace(status=lambda: True)
        helper = types.SimpleNamespace(unblock=unblock)
        with tempfile.TemporaryDirectory() as directory:
            ca = Path(directory) / "public-root.der"
            ca.write_bytes(b"public-test-root")
            monitor.config["ca_file"] = str(ca)
            # Replace this client's module reference, not socket.socket globally:
            # Windows asyncio uses the real socket type for its own wakeup pipe.
            fake_socket = types.SimpleNamespace(SOCK_STREAM=1, socket=harness.socket,
                getaddrinfo=lambda *args: [(2, 1, 0, "", ("127.0.0.1", 443))])
            with ExitStack() as stack:
                stack.enter_context(patch.object(support.http_client, "socket", fake_socket))
                stack.enter_context(patch.object(support.http_client.time, "gmtime", return_value=(2026, 11, 12, 0, 0, 0, 3, 316, 0)))
                stack.enter_context(patch.object(support.http_client, "_read_trust_root", return_value=ca.read_bytes()))
                stack.enter_context(patch.dict(sys.modules, {"tls": harness.tls, "wifi": wifi, "async_helpers": helper}))
                task = asyncio.create_task(monitor.background_task())
                wire = None
                try:
                    await asyncio.wait_for(unblock_entered.wait(), 2)
                    self.assertTrue(await asyncio.to_thread(socket_created.wait, 2))
                    wire = harness.wires[0]
                    self.assertTrue(await asyncio.to_thread(wire.entered.wait, 2))
                    self.assertTrue(monitor.state_client._busy)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    # No _stop/F/Esc path was invoked. The background wrapper's
                    # finally made shutdown terminal but left active TLS intact.
                    self.assertFalse(monitor._stopping)
                    self.assertTrue(monitor.state_client._closed)
                    self.assertFalse(wire.closed)
                    self.assertFalse(hardware.leds[1:13] == [(0, 0, 0)] * 12)
                    wire.release.set()
                    self.assertTrue(await asyncio.to_thread(socket_closed.wait, 2))
                    self.assertTrue(wire.closed)
                    self.assertNotIn(threading.get_ident(), wire.close_threads)
                    self.assertIsNone(monitor.state_client._stream)
                    self.assertIsNone(monitor.state_client._context)
                finally:
                    if wire is not None:
                        wire.release.set()
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    monitor.state_client.close()

    async def test_poll_error_keeps_client_usable_until_background_is_cancelled(self):
        module, monitor, unused = support.BadgeAppTests.live_monitor()
        attempted = asyncio.Event()
        async def failed_poll(function, periodic, *args, **kwargs):
            attempted.set()
            raise module.HTTPError("HTTP 503")
        with patch.dict(sys.modules, {"wifi": types.SimpleNamespace(status=lambda: True),
                                    "async_helpers": types.SimpleNamespace(unblock=failed_poll)}):
            task = asyncio.create_task(monitor.background_task())
            try:
                await asyncio.wait_for(attempted.wait(), 2)
                self.assertFalse(monitor.state_client._closed)
                self.assertEqual(monitor.controller.last_error, "HTTP 503")
                self.assertFalse(task.done())
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(monitor.state_client._closed)

    async def test_normal_configuration_rejection_also_closes_background_resources(self):
        module, monitor, unused = support.BadgeAppTests.live_monitor()
        monitor.config["bridge_url"] = "not-a-bridge-url"
        await monitor.background_task()
        self.assertEqual(monitor.controller.last_error, "SET BRIDGE URL")
        self.assertTrue(monitor.state_client._closed)
        self.assertIsNone(monitor.state_client._stream)


if __name__ == "__main__":
    unittest.main()
