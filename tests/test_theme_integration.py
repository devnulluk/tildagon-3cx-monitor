"""Actual app appearance/settings/call integration; fake hardware, no network."""
import copy
import sys
import time as desktop_time
import types
import unittest
from unittest.mock import patch

import test_badge as support


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []
        self.saves = 0
    def get(self, key, default=None):
        return self.values.get(key, default)
    def set(self, key, value):
        self.values[key] = value
        self.writes.append((key, value))
    def save(self):
        self.saves += 1


class ThemeIntegrationTests(unittest.TestCase):
    def monitor(self, config=None, saved=None):
        module, hardware = support.app_runtime()
        module.time.gmtime = desktop_time.gmtime
        settings = FakeSettings(saved)
        values = dict(module.DEFAULT_CONFIG, demo=False, bridge_url="https://bridge.invalid",
                      token="fixture-read", control_token="fixture-control", partner_name="Partner",
                      partner_numbers=["+447700900123"], matrix={"enabled": False})
        values.update(config or {})
        with patch.object(module, "load_config", return_value=values), patch.dict(sys.modules, {"settings": settings}):
            monitor = module.ThreeCXMonitor()
        payload = copy.deepcopy(support.demo.snapshot("team"))
        payload.update(demo=False, connected=True, age_seconds=0, alert=None)
        for member in payload["team"]:
            member.update(state="idle", calls=[])
        payload["own"].update(state="idle", calls=[], presence={"state": "available", "confirmed": True, "age_seconds": 0})
        payload["weather"] = {"live": True, "stale": False, "age_seconds": 0,
                              "location": "Example place", "now_unix": 1794517620, "utc_offset_seconds": 0,
                              "current": {"temperature_c": 8, "condition": "Overcast", "weather_code": 3},
                              "rain_next_hour": {"status": "dry_likely"}}
        payload["controls"] = {"enabled": True, "call": True, "dnd": True,
                               "session_id": "0123456789abcdef0123456789abcdef",
                               "targets": [{"id": key, "label": key.upper()} for key in ("tb", "pd", "jh", "sm", "kz")]}
        monitor.controller.accept(payload, 0)
        monitor.expansions.keyboard_present = True
        monitor.update(0)
        return module, monitor, hardware, settings

    @staticmethod
    def key(module, monitor, key):
        monitor.expansions.keys.append(key)
        monitor.update(0)

    @staticmethod
    def draw(monitor):
        canvas = support.RecordingCanvas()
        monitor.draw(canvas)
        return canvas.records

    @staticmethod
    def clock_page(monitor):
        assert monitor.idle_pages.preview(monitor.clock_ms)
        monitor.idle_pages.next(1, monitor.clock_ms)
        monitor.idle_pages.next(1, monitor.clock_ms)
        assert monitor.idle_pages.page(monitor.clock_ms) == "clock"

    @staticmethod
    def incoming(monitor, number="+44 7700 900123", name="Example Caller", initials="EC", state="ringing"):
        value = copy.deepcopy(monitor.controller.payload)
        call = {"id": "fixture-call", "state": state, "direction": "inbound", "kind": "queue", "priority": True,
                "peer_number": number, "peer_name": name, "peer_initials": initials, "queue_name": "Example queue"}
        value["own"].update(state="ringing" if state == "ringing" else "busy", calls=[call])
        value["alert"] = call if state == "ringing" else None
        monitor.controller.accept(value, monitor.clock_ms)
        return call

    def test_settings_select_theme_and_clock_independently_then_persist_on_done(self):
        module, monitor, hardware, settings = self.monitor()
        self.key(module, monitor, "T")
        self.assertTrue(monitor.settings_open)
        self.assertEqual(monitor.settings_selected, 2)
        self.key(module, monitor, "RIGHT")
        self.assertEqual(monitor.themes.selection, "christmas")
        self.assertEqual(monitor.clock_style, "original")
        self.key(module, monitor, "DOWN")
        self.key(module, monitor, "RIGHT")
        self.assertEqual(monitor.clock_style, "celestial")
        self.assertEqual(monitor.themes.selection, "christmas")
        with patch.dict(sys.modules, {"settings": settings}):
            self.key(module, monitor, "ENTER")
        self.assertFalse(monitor.settings_open)
        self.assertEqual(settings.values["threecx_monitor.theme"], "christmas")
        self.assertEqual(settings.values["threecx_monitor.clock_style"], "celestial")
        self.assertGreaterEqual(settings.saves, 1)
        self.assertIsNone(monitor.controls.pending)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))

    def test_saved_appearance_restores_without_changing_brightness_or_private_config(self):
        saved = {"threecx_monitor.theme": "ocean", "threecx_monitor.clock_style": "radar"}
        module, monitor, hardware, settings = self.monitor(saved=saved)
        self.assertEqual(monitor.themes.selection, "ocean")
        self.assertEqual(monitor.clock_style, "radar")
        self.assertEqual(monitor.controller.ring_brightness, .15)
        self.assertEqual(monitor.controller.eeh_brightness, .03)
        self.assertEqual(settings.writes, [])

    def test_every_physical_button_in_settings_is_safe_from_call_and_dnd_actions(self):
        for key in "ABCDEF":
            with self.subTest(key=key):
                module, monitor, hardware, settings = self.monitor()
                monitor._open_settings()
                with patch.object(module, "post_json") as post:
                    support.BadgeAppTests.press(module, monitor, key)
                self.assertIsNone(monitor.controls.pending)
                self.assertFalse(monitor._stopping)
                post.assert_not_called()

    def test_custom_clock_is_used_in_original_and_coloured_themes_without_duplicate_time(self):
        module, monitor, hardware, settings = self.monitor()
        monitor.clock_style = "celestial"
        for theme in ("original", "ocean", "kitty"):
            monitor.themes.select(theme)
            self.clock_page(monitor)
            records = self.draw(monitor)
            words = [record["text"] for record in records]
            self.assertIn("CELESTIAL", words)
            local = monitor._local_weather_time(monitor.controller.payload["weather"], 0)
            clock = "%02d:%02d" % (local[3], local[4])
            self.assertEqual(words.count(clock), 1)
            self.assertTrue(any(record["text"] == clock and record["size"] >= 45 for record in records))

    def test_original_clock_selection_keeps_original_dispatch(self):
        module, monitor, hardware, settings = self.monitor()
        self.clock_page(monitor)
        with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as alternate:
            with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as original:
                records = self.draw(monitor)
        alternate.assert_not_called()
        original.assert_called_once()
        self.assertNotIn("CELESTIAL", [record["text"] for record in records])

    def test_incoming_call_immediately_preempts_theme_clock_and_open_settings(self):
        module, monitor, hardware, settings = self.monitor(config={"theme": "cyberpunk", "clock_style": "celestial"})
        self.clock_page(monitor)
        self.incoming(monitor, number="+447700900456")
        monitor._open_settings()
        with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as alternate:
            records = self.draw(monitor)
        words = [record["text"] for record in records]
        self.assertIn("EC", words)
        self.assertNotIn("SETTINGS", words)
        self.assertNotIn("CELESTIAL", words)
        self.assertTrue(any("447700900456" in word.replace("+", "") for word in words))
        alternate.assert_not_called()
        self.assertIsNone(monitor.controls.pending)

    def test_exact_normalized_partner_number_drives_eeh_and_matrix_but_name_spoofs_do_not(self):
        module, monitor, hardware, settings = self.monitor()
        for number, name, initials, expected in (("07700 900123", "Someone", "EX", True),
                                                ("+447700900456", "Partner", "KZ", False),
                                                ("+4477009001239", "Partner", "KZ", False)):
            with self.subTest(number=number):
                self.incoming(monitor, number=number, name=name, initials=initials)
                with patch.object(monitor.expansions, "write_own_status") as eeh:
                    with patch.object(monitor.matrix, "update") as matrix:
                        monitor.update(0)
                self.assertIs(eeh.call_args.kwargs["heartbeat"], expected)
                self.assertIs(matrix.call_args.kwargs["partner"], expected)
                self.assertIsNone(monitor.controls.pending)

    def test_partner_heart_is_cleared_when_source_stales_and_when_own_call_ends(self):
        module, monitor, hardware, settings = self.monitor()
        self.incoming(monitor)
        with patch.object(monitor.expansions, "write_own_status") as eeh:
            with patch.object(monitor.matrix, "update") as matrix:
                monitor.update(0)
                self.assertTrue(eeh.call_args.kwargs["heartbeat"])
                module.time.now += 5000
                monitor.update(5000)
                self.assertFalse(eeh.call_args.kwargs["heartbeat"])
                self.assertFalse(matrix.call_args.kwargs["partner"])
                self.assertFalse(matrix.call_args.args[1])
                records = self.draw(monitor)
                self.assertIn("OFFLINE", [record["text"] for record in records])
                value = copy.deepcopy(monitor.controller.payload)
                value["own"].update(state="idle", calls=[])
                value["alert"] = None
                monitor.controller.accept(value, monitor.clock_ms)
                monitor.update(0)
                self.assertFalse(eeh.call_args.kwargs["heartbeat"])
                self.assertFalse(matrix.call_args.kwargs["partner"])

    def test_teammate_call_cannot_trigger_own_partner_heart(self):
        module, monitor, hardware, settings = self.monitor()
        value = copy.deepcopy(monitor.controller.payload)
        value["team"][0].update(state="busy", calls=[{"id": "team-call", "state": "connected", "kind": "external",
                                                    "peer_name": "Partner", "peer_initials": "KZ", "peer_number": "+447700900123"}])
        monitor.controller.accept(value, monitor.clock_ms)
        with patch.object(monitor.expansions, "write_own_status") as eeh:
            with patch.object(monitor.matrix, "update") as matrix:
                monitor.update(0)
        self.assertFalse(eeh.call_args.kwargs["heartbeat"])
        self.assertFalse(matrix.call_args.kwargs["partner"])


if __name__ == "__main__":
    unittest.main()
