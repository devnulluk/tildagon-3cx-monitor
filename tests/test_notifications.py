"""Synthetic inbox expiry, dismissal and native rich-notification rendering."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/notifications.py"
spec = importlib.util.spec_from_file_location("notifications_under_test", PATH)
notifications = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notifications)


def item(key="fixture-1", **values):
    result = {"id": key, "title": "Backup completed", "body": "All example files are safe",
              "type": "success", "priority": 3, "style": "card", "icon": "check",
              "progress": None, "ttl_seconds": 120, "age_seconds": 0}
    result.update(values)
    return result


class InboxTests(unittest.TestCase):
    def test_urgent_red_breathing_is_slow_continuous_bounded_and_periodic(self):
        colours=[notifications.urgent_eeh_colour(t) for t in range(0,8001,20)]
        self.assertEqual(min(c[0] for c in colours),64)
        self.assertEqual(max(c[0] for c in colours),255)
        self.assertTrue(all(c[1:]==(0,0) for c in colours))
        self.assertTrue(all(abs(a[0]-b[0])<=4 for a,b in zip(colours,colours[1:])))
        self.assertEqual(colours[0],colours[200])
        self.assertEqual(colours[100],(255,0,0))

    def test_source_and_local_elapsed_age_expire_at_the_original_deadline(self):
        inbox = notifications.NotificationInbox()
        self.assertTrue(inbox.observe([item(ttl_seconds=10, age_seconds=2)], 1000))
        self.assertEqual(inbox.current(4000)["age_seconds"], 5)
        inbox.observe([item(ttl_seconds=10, age_seconds=0)], 6000)
        self.assertIsNotNone(inbox.current(8999))
        self.assertIsNone(inbox.current(9000))
        self.assertEqual(inbox.count, 0)
        inbox.observe([item(ttl_seconds=10, age_seconds=0)], 9001)
        self.assertIsNone(inbox.current(9001))

    def test_unseen_expired_cached_notification_is_never_replayed_with_a_reset_age(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item(ttl_seconds=10, age_seconds=11)], 0)
        self.assertIsNone(inbox.current(0))
        inbox.observe([item(ttl_seconds=10, age_seconds=0)], 1000)
        self.assertIsNone(inbox.current(1000))

    def test_local_dismissal_survives_updates_omission_and_reappearance(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item()], 0)
        self.assertIsNone(inbox.dismiss(1000))
        inbox.observe([], 2000)
        inbox.observe([item(body="Changed content", progress=80)], 3000)
        self.assertIsNone(inbox.current(3000))
        inbox.observe([item("new-lifetime")], 4000)
        self.assertEqual(inbox.current(4000)["id"], "new-lifetime")

    def test_same_id_content_update_does_not_restart_arrival_or_extend_lifetime(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item(ttl_seconds=10, progress=10)], 0)
        revision = inbox.revision
        inbox.observe([item(ttl_seconds=100, age_seconds=0, body="Uploading", progress=75)], 4000)
        current = inbox.current(4000)
        self.assertEqual((current["body"], current["progress"]), ("Uploading", 75))
        self.assertEqual(current["ttl_seconds"], 10)
        self.assertEqual(inbox.entered_ms, 0)
        self.assertGreater(inbox.revision, revision)
        self.assertIsNone(inbox.current(10000))

    def test_repeated_identical_snapshots_do_not_replay_arrival(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item()], 0)
        revision = inbox.revision
        self.assertFalse(inbox.observe([item(age_seconds=1)], 1000))
        self.assertEqual(inbox.revision, revision)
        self.assertEqual(inbox.entered_ms, 0)

    def test_priority_preemption_and_manual_browsing_have_distinct_arrival_times(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item("normal")], 0)
        inbox.observe([item("low", priority=1), item("normal")], 1000)
        self.assertEqual(inbox.current(1000)["id"], "normal")
        inbox.observe([item("urgent", priority=5), item("low", priority=1), item("normal")], 2000)
        self.assertEqual(inbox.current(2000)["id"], "urgent")
        self.assertEqual(inbox.entered_ms, 2000)
        self.assertEqual(inbox.next(1, 3000)["id"], "normal")
        self.assertEqual(inbox.entered_ms, 3000)
        self.assertEqual(inbox.next(-1, 4000)["id"], "urgent")

    def test_new_equal_priority_item_can_replace_an_older_hidden_popup(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item("old")], 0)
        inbox.observe([item("new"), item("old")], 20000)
        self.assertEqual(inbox.current(20000)["id"], "new")
        self.assertEqual(inbox.entered_ms, 20000)

    def test_source_removal_is_not_replayed_from_a_later_old_snapshot(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item()], 0)
        inbox.observe([], 1000)
        self.assertIsNone(inbox.current(1000))
        inbox.observe([item()], 2000)
        self.assertIsNone(inbox.current(2000))

    def test_malformed_top_level_data_does_not_clear_valid_inbox(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item()], 0)
        for value in (None, {}, "unexpected", 1):
            inbox.observe(value, 1000)
            self.assertEqual(inbox.current(1000)["id"], "fixture-1")

    def test_snapshot_and_returned_values_cannot_mutate_internal_state(self):
        inbox = notifications.NotificationInbox()
        source = [item()]
        before = copy.deepcopy(source)
        inbox.observe(source, 0)
        current = inbox.current(1000)
        self.assertEqual(source, before)
        self.assertFalse(any(key.startswith("_") for key in current))
        current["title"] = "Changed outside inbox"
        source[0]["title"] = "Changed original snapshot"
        self.assertEqual(inbox.current(1000)["title"], "Backup completed")

    def test_bounded_input_first_duplicate_and_tombstone_storage(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item("same", title="Newest copy"), item("same", title="Old copy")]
                      + [item("n%d" % i) for i in range(30)], 0)
        self.assertEqual(inbox.count, 15)
        inbox.next(-1, 0)
        self.assertEqual(next(entry for entry in inbox._items if entry["id"] == "same")["title"], "Newest copy")
        expired = item("expired", ttl_seconds=1, age_seconds=2)
        for index in range(90):
            inbox.observe([expired, item("fresh%d" % index)], index * 1000)
        self.assertLessEqual(len(inbox._dead), 64)
        inbox.observe([item("expired"), item("fresh89")], 90000)
        self.assertNotEqual(inbox.current(90000)["id"], "expired")

    def test_invalid_identity_age_and_ttl_fail_closed(self):
        cases = [None, [], "unexpected", item(id=[]), item(id="../escape"), item(id="x" * 65),
                 item(age_seconds=None), item(age_seconds=True), item(age_seconds=math.nan),
                 item(age_seconds=math.inf), item(ttl_seconds=math.nan), item(ttl_seconds=0),
                 item(ttl_seconds=86401)]
        for value in cases:
            with self.subTest(value=value):
                inbox = notifications.NotificationInbox()
                inbox.observe([value], 0)
                self.assertIsNone(inbox.current(0))

    def test_untrusted_optional_fields_are_bounded_and_do_not_become_remote_actions(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item(title="A" * 100 + "\x1b", body="B" * 400, type=[], priority=True,
                            style="https://example.invalid", icon="https://example.invalid/icon.png",
                            progress=math.inf, actions=["open-url"], image="https://example.invalid")], 0)
        current = inbox.current(0)
        self.assertEqual((len(current["title"]), len(current["body"])), (80, 320))
        self.assertEqual((current["type"], current["priority"], current["style"], current["icon"]),
                         ("info", 3, "card", "info"))
        self.assertIsNone(current["progress"])
        self.assertNotIn("actions", current)
        self.assertNotIn("image", current)

    def test_backwards_or_invalid_local_clock_cannot_extend_expiry(self):
        inbox = notifications.NotificationInbox()
        inbox.observe([item(ttl_seconds=10)], 0)
        self.assertEqual(inbox.current(5000)["age_seconds"], 5)
        self.assertEqual(inbox.current(1000)["age_seconds"], 5)
        self.assertEqual(inbox.current(math.nan)["age_seconds"], 5)
        self.assertIsNone(inbox.current(10000))


class Canvas:
    CENTER = 1
    MIDDLE = 2
    ARITIES = {"save": 0, "restore": 0, "translate": 2, "rgb": 3, "arc": 6,
               "rectangle": 4, "round_rectangle": 5, "move_to": 2, "line_to": 2,
               "curve_to": 6, "fill": 0, "stroke": 0, "text": 1}
    def __init__(self):
        self.operations = []
        self.words = []
        self.font_size = 18
        self.depth = 0
        self.position = (0, 0)

    def text_width(self, text):
        return len(text) * self.font_size * .5

    def __getattr__(self, name):
        if name not in self.ARITIES:
            raise AssertionError("Unsupported native API: " + name)
        def method(*args):
            if len(args) != self.ARITIES[name]:
                raise AssertionError("Wrong native API arity: " + name)
            if name != "text" and any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in args):
                raise AssertionError("Nonfinite native argument")
            if name == "save": self.depth += 1
            if name == "restore": self.depth -= 1
            if name == "move_to": self.position = args
            if name == "text": self.words.append((args[0], self.font_size, self.position))
            if name == "rgb" and not all(0 <= v <= 1 for v in args):
                raise AssertionError("Invalid RGB")
            self.operations.append((name, args))
            return self
        return method


class NotificationRenderTests(unittest.TestCase):
    def test_all_types_styles_and_icons_use_supported_native_api(self):
        for kind in notifications.TYPES:
            for style in notifications.STYLES:
                for icon in notifications.ICONS:
                    with self.subTest(kind=kind, style=style, icon=icon):
                        ctx = Canvas()
                        self.assertTrue(notifications.draw_notification(ctx, item(type=kind, style=style, icon=icon), 750, 0))
                        self.assertEqual(ctx.depth, 0)
                        self.assertLess(sum(name in ("fill", "stroke") for name, args in ctx.operations), 50)
                        self.assertFalse(any(name in ("image", "texture", "linear_gradient") for name, args in ctx.operations))

    def test_invalid_or_expired_entries_leave_canvas_untouched(self):
        for value in (None, {}, item(age_seconds=120), item(progress=math.nan, age_seconds=None)):
            ctx = Canvas()
            self.assertFalse(notifications.draw_notification(ctx, value, 0, 0))
            self.assertEqual(ctx.operations, [])

    def test_title_and_body_stay_readable_and_width_bounded_for_long_words(self):
        ctx = Canvas()
        notifications.draw_notification(ctx, item(title="A" * 80, body="Longword" * 40), 1000, 0)
        titles = [(word, size, position) for word, size, position in ctx.words if size == 26]
        bodies = [(word, size, position) for word, size, position in ctx.words if size == 18]
        self.assertEqual(len(titles), 2)
        self.assertEqual(len(bodies), 3)
        self.assertTrue(all(len(word) * size * .5 <= 176 for word, size, p in titles))
        self.assertTrue(all(len(word) * size * .5 <= 156 for word, size, p in bodies))

    def test_progress_includes_honest_zero_and_complete_readouts(self):
        for progress in (0, 1, 50, 100):
            ctx = Canvas()
            notifications.draw_notification(ctx, item(progress=progress, style="progress"), 1000, 0)
            self.assertIn(("%d%%" % progress, 20, (0, 98)), ctx.words)
            tracks = [args for name, args in ctx.operations if name == "round_rectangle" and args[1] == 76]
            self.assertEqual(len(tracks), 1 if progress == 0 else 2)
            if progress:
                self.assertAlmostEqual(tracks[-1][2], 132 * progress / 100)

    def test_arrival_animation_settles_and_does_not_need_frame_history(self):
        early, late = Canvas(), Canvas()
        notifications.draw_notification(early, item(), 100, 100)
        notifications.draw_notification(late, item(), 1000, 100)
        self.assertIn(("translate", (0, 11)), early.operations)
        self.assertIn(("translate", (0, 0)), late.operations)

    def test_leds_are_dim_bounded_and_respect_user_zero_brightness(self):
        for kind in notifications.TYPES:
            for now in (0, 200, 1000):
                frame = notifications.led_frame(item(type=kind), now, 1)
                self.assertEqual(len(frame), 12)
                self.assertTrue(all(type(v) is int and 0 <= v <= 63 for rgb in frame for v in rgb))
                dim = notifications.led_frame(item(type=kind), now, .05)
                self.assertTrue(all(0 <= v <= 12 for rgb in dim for v in rgb))
        self.assertEqual(notifications.led_frame(item(), 0, 0), [(0, 0, 0)] * 12)
        self.assertEqual(notifications.led_frame(item(age_seconds=120), 0, 1), [(0, 0, 0)] * 12)


if __name__ == "__main__":
    unittest.main()
