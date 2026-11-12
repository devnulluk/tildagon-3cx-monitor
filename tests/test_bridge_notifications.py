import asyncio
import json
import math
import os
import unittest
from unittest import mock

from bridge.notifications import (ICONS, NotificationBroker, NotificationError,
                                  NtfySubscriber, ntfy_from_env)


class Clock:
    def __init__(self):
        self.now = 100.0
        self.wall = 1000.0
    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.broker = NotificationBroker(lambda: self.clock.now, lambda: self.clock.wall)

    def test_apprise_and_idless_duplicates_keep_the_original_age(self):
        payload = {"version": "1.0", "title": "Backup", "message": "Completed", "type": "success", "attachments": []}
        accepted = self.broker.submit(payload)
        self.clock.advance(12)
        duplicate = self.broker.submit(payload)
        self.assertEqual(duplicate, {"status": "duplicate", "id": accepted["id"]})
        item = self.broker.snapshot()[0]
        self.assertEqual((item["body"], item["icon"], item["age_seconds"]), ("Completed", "check", 12))
        self.assertNotIn("_received", item)

    def test_progress_updates_never_renew_first_expiry(self):
        self.broker.submit({"id": "job", "title": "Backup", "body": "Running", "progress": 1, "ttl_seconds": 20})
        self.clock.advance(9)
        result = self.broker.submit({"id": "job", "progress": 75, "ttl_seconds": 3600})
        self.assertEqual(result["status"], "updated")
        item = self.broker.snapshot()[0]
        self.assertEqual((item["progress"], item["style"], item["ttl_seconds"], item["age_seconds"]), (75, "progress", 20, 9))
        self.assertEqual(item["body"], "Running")
        self.clock.advance(12)
        self.assertEqual(self.broker.snapshot(), [])
        self.assertEqual(self.broker.submit({"id": "job", "title": "Replayed"})["status"], "expired")
        self.assertEqual(self.broker.submit({"id": "new-job", "title": "New event"})["status"], "accepted")

    def test_shorter_ttl_and_wall_clock_jumps_do_not_extend_lifetime(self):
        self.broker.submit({"id": "job", "title": "Example", "ttl": 60})
        self.clock.advance(8)
        self.clock.wall -= 10000
        self.broker.submit({"id": "job", "body": "Update", "ttl": 10})
        self.assertEqual(self.broker.snapshot()[0]["age_seconds"], 8)
        self.clock.advance(3)
        self.assertEqual(self.broker.snapshot(), [])

    def test_identical_replay_can_tighten_age_and_expiry(self):
        payload = {"id": "job", "title": "Example", "ttl_seconds": 100}
        self.broker.submit(payload)
        self.clock.advance(10)
        result = self.broker.submit(payload, age_seconds=50)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(self.broker.snapshot()[0]["age_seconds"], 50)
        self.clock.advance(51)
        self.assertEqual(self.broker.snapshot(), [])

    def test_queue_and_history_are_bounded_and_evictions_do_not_replay(self):
        for index in range(300):
            self.broker.submit({"id": "item-" + str(index), "body": "Example"})
        items = self.broker.snapshot()
        self.assertEqual(len(items), 16)
        self.assertEqual((items[0]["id"], items[-1]["id"]), ("item-299", "item-284"))
        self.assertLessEqual(len(self.broker._history), 256)
        self.assertEqual(self.broker.submit({"id": "item-283", "body": "Replay"})["status"], "expired")

    def test_utf8_caps_preserve_codepoints_and_snapshots_are_copies(self):
        self.broker.submit({"title": "😀" * 100, "body": "☂" * 300 + "\x00", "icon": "cloud"})
        item = self.broker.snapshot()[0]
        self.assertLessEqual(len(item["title"].encode("utf-8")), 80)
        self.assertLessEqual(len(item["body"].encode("utf-8")), 320)
        self.assertNotIn("\x00", item["body"])
        item["body"] = "Changed outside broker"
        self.assertNotEqual(self.broker.snapshot()[0]["body"], item["body"])

    def test_unknown_fields_actions_remote_icons_and_invalid_numbers_are_rejected(self):
        cases = ({"url": "https://example.invalid"}, {"actions": []}, {"image": "https://example.invalid"},
                 {"attachments": [{}]}, {"attachments": None},
                 {"icon": "https://example.invalid/icon.png"}, {"style": "html"}, {"priority": True},
                 {"priority": 6}, {"progress": float("nan")}, {"progress": math.inf}, {"progress": -1},
                 {"ttl_seconds": None}, {"ttl": 0}, {"ttl": 86401}, {"ttl": 5, "ttl_seconds": 6},
                 {"id": "invalid/id"}, {"body": "\ud800"}, {"body": "one", "message": "two"})
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(NotificationError) as error:
                self.broker.submit(dict({"title": "Example"}, **extra))
            self.assertEqual(str(error.exception), "Invalid notification request")


class Content:
    def __init__(self, chunks):
        self.chunks = chunks
    async def iter_chunked(self, amount):
        for chunk in self.chunks:
            yield chunk


class NtfyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.broker = NotificationBroker(lambda: self.clock.now, lambda: self.clock.wall)
        self.subscriber = NtfySubscriber(self.broker, "https://ntfy.example.invalid", "private-topic", "private-token",
                                         clock=lambda: self.clock.now, wall_clock=lambda: self.clock.wall)

    def event(self, **extra):
        return dict({"event": "message", "id": "message-1", "topic": "private-topic", "time": self.clock.wall,
                     "title": "Example", "message": "Example event"}, **extra)

    def test_maps_only_allowlisted_fields_and_discards_remote_actions_images(self):
        self.subscriber.ingest(self.event(tags=["warning", "server"], priority=4,
                                          icon="https://untrusted.invalid/icon", click="https://untrusted.invalid",
                                          actions=[{"action": "http", "url": "https://untrusted.invalid"}],
                                          attachment={"url": "https://untrusted.invalid/image"}))
        item = self.broker.snapshot()[0]
        self.assertEqual((item["type"], item["icon"], item["priority"]), ("warning", "server", 4))
        self.assertTrue(item["id"].startswith("ntfy:"))
        self.assertFalse({"actions", "click", "attachment", "url"} & set(item))
        self.assertIn(item["icon"], ICONS)

    def test_sequence_updates_and_delete_clear_do_not_touch_local_notifications(self):
        self.broker.submit({"id": "local", "title": "Local"})
        self.subscriber.ingest(self.event(sequence_id="same-job"))
        self.clock.advance(8)
        self.subscriber.ingest(self.event(id="message-2", sequence_id="same-job", message="Updated"))
        item = self.broker.snapshot()[0]
        self.assertEqual(item["body"], "Updated")
        self.assertEqual(item["age_seconds"], 8)
        self.subscriber.ingest(self.event(event="message_delete", sequence_id="same-job"))
        self.assertEqual([item["id"] for item in self.broker.snapshot()], ["local"])
        self.subscriber.ingest(self.event(id="different-message"))
        self.subscriber.ingest(self.event(event="message_clear"))
        self.assertEqual([item["id"] for item in self.broker.snapshot()], ["local"])

    def test_old_replayed_messages_and_wrong_topics_do_not_display(self):
        self.subscriber.ingest(self.event(time=self.clock.wall - 301))
        self.assertEqual(self.broker.snapshot(), [])
        with self.assertRaises(NotificationError):
            self.subscriber.ingest(self.event(topic="other-topic"))
        self.assertEqual(self.broker.snapshot(), [])

    async def test_stream_handles_chunk_boundaries_bad_and_oversized_lines(self):
        valid = json.dumps(self.event(message="Unicode ☂ event"), ensure_ascii=False).encode()
        stream = b'{bad json}\n' + b'x' * 9000 + b'\n' + valid + b'\n'
        chunks = [stream[index:index + 17] for index in range(0, len(stream), 17)]
        await self.subscriber._consume(Content(chunks))
        self.assertEqual(self.broker.snapshot()[0]["body"], "Unicode ☂ event")

    def test_https_configuration_rejects_credential_urls_and_invalid_topics(self):
        for url in ("http://ntfy.example.invalid", "https://name:secret@ntfy.example.invalid", "https://ntfy.example.invalid?token=secret"):
            with self.assertRaises(ValueError) as error:
                NtfySubscriber(self.broker, url, "topic")
            self.assertNotIn("secret", str(error.exception))
        with self.assertRaises(ValueError):
            NtfySubscriber(self.broker, "https://ntfy.example.invalid", "topic/other")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ntfy_from_env(self.broker))

    async def test_reconnect_uses_cursor_verified_tls_no_redirect_and_bounded_backoff(self):
        event_line = json.dumps(self.event()).encode() + b'\n'
        calls, delays = [], []
        class Response:
            def __init__(self, status, chunks):
                self.status, self.content = status, Content(chunks)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
        class Session:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return Response(200, [event_line]) if len(calls) == 2 else Response(302, [])
        async def sleep(delay):
            delays.append(delay)
            if len(delays) >= 9:
                raise asyncio.CancelledError()
        subscriber = NtfySubscriber(self.broker, "https://ntfy.example.invalid", "private-topic", "private-token",
                                     session=Session(), clock=lambda: self.clock.now,
                                     wall_clock=lambda: self.clock.wall, sleeper=sleep)
        with self.assertRaises(asyncio.CancelledError):
            await subscriber.run()
        self.assertEqual(delays, [1, 2, 4, 8, 16, 32, 60, 60, 60])
        self.assertEqual(calls[0][1]["params"], {})
        self.assertEqual(calls[2][1]["params"], {"since": "message-1"})
        self.assertTrue(all(call[1]["ssl"] is True and call[1]["allow_redirects"] is False for call in calls))
        self.assertTrue(all(call[1]["headers"]["Authorization"] == "Bearer private-token" for call in calls))
        self.assertFalse(subscriber.connected)
        await subscriber.close()


if __name__ == "__main__":
    unittest.main()
