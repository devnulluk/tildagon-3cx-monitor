"""Actual app notification/sensor integration; fake hardware, no PBX requests."""
import copy
import unittest
from unittest.mock import patch

import test_badge as support
import test_badge_idle as idle_support
import test_notifications as fixtures


class Space:
    def __init__(self):
        self.events = []
        self.motion_valid = False
        self.tilt = (0, 0)
        self.closed = False
    def update(self): pass
    def pop(self):
        events, self.events = self.events, []
        return events
    def close(self): self.closed = True


class Canvas(support.RecordingCanvas):
    def __init__(self):
        super().__init__()
        self.translations = []
    def translate(self, x, y):
        self.translations.append((x, y))
        return self


class BadgeNotificationTests(unittest.TestCase):
    def monitor(self, keyboard=True):
        module, monitor, hardware = idle_support.BadgeIdleTests().monitor(keyboard)
        monitor.space_inputs.close()
        monitor.space_inputs = Space()
        return module, monitor, hardware

    def source(self, monitor, entries=None, **changes):
        value = copy.deepcopy(monitor.controller.payload)
        if entries is not None:
            value["notifications"] = entries
        value.update(changes)
        monitor.controller.accept(value, monitor.clock_ms)
        return value

    def texts(self, monitor):
        canvas = Canvas()
        monitor.draw(canvas)
        return " ".join(record["text"] for record in canvas.records)

    def advance(self, module, monitor, milliseconds, refresh=True):
        idle_support.BadgeIdleTests.advance(module, monitor, milliseconds, refresh)

    def sensor(self, monitor, kind="joystick", action="confirm", **values):
        monitor.space_inputs.events.append(dict(kind=kind, action=action, **values))
        monitor.update(0)

    def test_popup_lasts_ten_seconds_and_retains_notification_in_manual_inbox(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.update(0)
        self.assertIn("Backup completed", self.texts(monitor))
        self.advance(module, monitor, 9999)
        self.assertIn("Backup completed", self.texts(monitor))
        self.advance(module, monitor, 1)
        self.assertNotIn("Backup completed", self.texts(monitor))
        self.assertEqual(monitor.notifications.count, 1)
        monitor.expansions.keys = ["N"]
        monitor.update(0)
        self.assertTrue(monitor.notifications_open)
        self.assertIn("Backup completed", self.texts(monitor))

    def test_same_id_progress_update_never_renews_automatic_popup(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item(progress=10)])
        monitor.update(0)
        entered = monitor._notification_entered
        self.advance(module, monitor, 6000)
        self.source(monitor, [fixtures.item(progress=70)])
        monitor.update(0)
        self.assertEqual(monitor._notification_entered, entered)
        self.advance(module, monitor, 4000)
        self.assertIsNone(monitor._visible_notification(monitor.clock_ms))

    def test_active_own_call_defers_notification_without_dismissing_it(self):
        module, monitor, unused = self.monitor()
        value = self.source(monitor, [fixtures.item()])
        value["own"].update(state="busy", calls=[{"state": "connected", "peer_number": "101"}])
        monitor.update(0)
        self.assertNotIn("Backup completed", self.texts(monitor))
        self.advance(module, monitor, 11000)
        self.assertEqual(monitor.notifications.count, 1)
        value = self.source(monitor)
        value["own"].update(state="idle", calls=[])
        monitor.update(0)
        self.assertIn("Backup completed", self.texts(monitor))
        self.assertEqual(monitor._notification_entered, monitor.clock_ms)

    def test_team_ringing_defers_popup_but_stable_answered_call_allows_it(self):
        module, monitor, unused = self.monitor()
        value = self.source(monitor, [fixtures.item()])
        value["team"][0].update(state="ringing", calls=[{"state": "ringing"}])
        monitor.update(0)
        self.assertIsNone(monitor._visible_notification(monitor.clock_ms))
        value = self.source(monitor)
        value["team"][0].update(state="busy", calls=[{"state": "connected"}])
        monitor.update(0)
        self.assertIn("Backup completed", self.texts(monitor))

    def test_stale_pbx_wins_and_unseen_source_age_counts_before_observation(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item(ttl_seconds=10)])
        module.time.now += 6000
        monitor.update(6000)
        self.assertIn("OFFLINE", self.texts(monitor))
        self.assertNotIn("Backup completed", self.texts(monitor))
        self.assertEqual(monitor.notifications.current(monitor.clock_ms)["age_seconds"], 6)
        self.source(monitor)
        monitor.update(0)
        self.assertIn("Backup completed", self.texts(monitor))
        self.advance(module, monitor, 4000)
        self.assertIsNone(monitor.notifications.current(monitor.clock_ms))

    def test_incoming_priority_call_preempts_popup_and_restores_call_leds(self):
        module, monitor, hardware = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.update(0)
        incoming = {"state": "ringing", "direction": "inbound", "kind": "ddi", "priority": True,
                    "peer_number": "+441632960123", "peer_name": "Example caller"}
        value = self.source(monitor, alert=incoming)
        value["own"].update(state="ringing", calls=[incoming])
        monitor.update(0)
        words = self.texts(monitor)
        self.assertIn("+441632960123", words)
        self.assertNotIn("Backup completed", words)
        self.assertEqual(hardware.leds[1:13], monitor.controller.led_frame(monitor.clock_ms))
        self.assertEqual(monitor.notifications.count, 1)

    def test_settings_and_action_notice_precede_popup(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.settings_open = True
        monitor.update(0)
        self.assertIn("SETTINGS", self.texts(monitor))
        self.assertNotIn("Backup completed", self.texts(monitor))
        monitor.settings_open = False
        monitor.controls.message, monitor.controls.message_until = "ACTION PENDING", 1000
        self.assertNotIn("Backup completed", self.texts(monitor))
        self.advance(module, monitor, 1000)
        self.assertIn("Backup completed", self.texts(monitor))

    def test_keyboard_inbox_shortcut_suppresses_simultaneous_physical_speed_dial(self):
        module, monitor, unused = self.monitor()
        monitor.expansions.keys = ["N"]
        monitor.buttons.values = {"A"}
        monitor.update(0)
        self.assertTrue(monitor.notifications_open)
        self.assertFalse(monitor.controls.is_busy)
        self.assertIn("No notifications", self.texts(monitor))

    def test_inbox_confirm_only_dismisses_even_if_own_view_would_normally_toggle_dnd(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.update(0)
        monitor.controller.own_view = True
        self.sensor(monitor)
        self.assertEqual(monitor.notifications.count, 0)
        self.assertFalse(monitor.controls.is_busy)

    def test_joystick_confirm_and_rotary_touch_are_display_only_in_monitor(self):
        module, monitor, unused = self.monitor()
        monitor.controller.own_view = True
        for unused in range(4):
            self.sensor(monitor)
            self.assertFalse(monitor.controls.is_busy)
        self.sensor(monitor, "touch", "rotate", delta=1)
        self.sensor(monitor, "touch", "select", pad=12)
        self.assertEqual(monitor.controller.selected, 3)
        self.assertTrue(monitor.controller.detail_view)
        self.assertFalse(monitor.controls.is_busy)

    def test_joystick_and_touch_cannot_dismiss_or_navigate_over_an_active_call(self):
        module, monitor, unused = self.monitor()
        value = self.source(monitor, [fixtures.item()])
        value["own"].update(state="busy", calls=[{"state": "connected"}])
        monitor.notifications_open = True
        monitor.update(0)
        self.sensor(monitor)
        self.sensor(monitor, "touch", "select", pad=12)
        self.assertEqual(monitor.notifications.count, 1)
        self.assertEqual(monitor.controller.selected, 0)
        self.assertFalse(monitor.controls.is_busy)

    def test_cancel_returns_to_monitor_without_termination_or_dismissal(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.update(0)
        monitor.notifications_open = True
        monitor.expansions.keys = ["ESCAPE"]
        monitor.update(0)
        self.assertFalse(monitor.notifications_open)
        self.assertFalse(monitor._stopping)
        self.assertEqual(monitor.notifications.count, 1)

    def test_popup_boundary_requires_release_before_button_can_become_phone_control(self):
        module, monitor, unused = self.monitor()
        self.source(monitor, [fixtures.item()])
        monitor.update(0)
        monitor.buttons.values = {"A"}
        self.advance(module, monitor, 400)
        self.assertFalse(monitor.controls.is_busy)
        self.advance(module, monitor, 10000)
        self.assertFalse(monitor.controls.is_busy)
        monitor.buttons.values.clear()
        self.advance(module, monitor, 400)
        monitor.buttons.values = {"A"}
        self.advance(module, monitor, 400)
        self.assertEqual(monitor.controls.pending["target"], "tb")

    def test_notification_led_overlay_ends_after_two_and_a_half_seconds(self):
        module, monitor, hardware = self.monitor()
        self.source(monitor, [fixtures.item(type="info")])
        monitor.update(0)
        self.assertNotEqual(hardware.leds[1:13], monitor.controller.led_frame(monitor.clock_ms))
        self.advance(module, monitor, 2500)
        self.assertEqual(hardware.leds[1:13], monitor.controller.led_frame(monitor.clock_ms))
        self.assertTrue(monitor._visible_notification(monitor.clock_ms))

    def test_idle_rotary_gesture_browses_page_without_dialing_or_exiting_idle(self):
        module, monitor, unused = self.monitor()
        self.advance(module, monitor, 60000)
        page = monitor.idle_pages.page(monitor.clock_ms)
        self.sensor(monitor, "touch", "rotate", delta=1)
        self.assertNotEqual(monitor.idle_pages.page(monitor.clock_ms), page)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
        self.assertFalse(monitor.controls.is_busy)

    def test_tilt_is_opt_in_original_idle_only_and_bounded_to_four_pixels(self):
        module, monitor, unused = self.monitor()
        self.advance(module, monitor, 60000)
        monitor.space_inputs.motion_valid = True
        monitor.space_inputs.tilt = (2, -3)
        with patch.object(module, "draw_idle_face"), patch.object(module, "draw_astro_face", return_value=False), \
                patch.object(module, "draw_theme_face", return_value=False):
            canvas = Canvas()
            monitor.draw(canvas)
            self.assertEqual(canvas.translations, [])
            monitor.config["space_tilt"] = True
            canvas = Canvas()
            monitor.draw(canvas)
            self.assertEqual(canvas.translations, [(4, -4)])
            monitor.themes.select("cyberpunk")
            canvas = Canvas()
            monitor.draw(canvas)
            self.assertEqual(canvas.translations, [])

    def test_stopping_app_closes_sensor_event_subscription(self):
        module, monitor, unused = self.monitor()
        monitor._stop()
        self.assertTrue(monitor.space_inputs.closed)


if __name__ == "__main__":
    unittest.main()
