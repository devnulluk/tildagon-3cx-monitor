"""New watch faces use existing display-only settings and call interruption."""

import copy
import sys
import unittest
from unittest.mock import patch

import test_theme_integration as theme_fixture


LUXURY = ("haute_celestial", "neon_orrery")
ALL_CLOCKS = (("original", "celestial", "tokyoflash", "radar", "flip", "analogue", "corpus") + LUXURY
              + ("mondaine", "great_british_railways"))


class LuxuryClockIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = theme_fixture.ThemeIntegrationTests()

    def test_all_eleven_styles_are_reachable_in_existing_clock_settings_and_wrap(self):
        module, monitor, hardware, settings = self.fixture.monitor()
        self.fixture.key(module, monitor, "K")
        self.assertTrue(monitor.settings_open)
        observed = [monitor.clock_style]
        for _ in range(len(ALL_CLOCKS) - 1):
            self.fixture.key(module, monitor, "RIGHT")
            observed.append(monitor.clock_style)
        self.assertEqual(tuple(observed), ALL_CLOCKS)
        self.fixture.key(module, monitor, "RIGHT")
        self.assertEqual(monitor.clock_style, "original")
        self.fixture.key(module, monitor, "LEFT")
        self.assertEqual(monitor.clock_style, "great_british_railways")
        self.assertIsNone(monitor.controls.pending)
        self.assertEqual(settings.saves, 0)

    def test_each_new_style_restores_and_persists_without_changing_theme_or_controls(self):
        for style in LUXURY:
            with self.subTest(style=style):
                saved = {"threecx_monitor.clock_style": style, "threecx_monitor.theme": "ocean"}
                module, monitor, hardware, settings = self.fixture.monitor(saved=saved)
                self.assertEqual(monitor.clock_style, style)
                self.assertEqual(monitor.themes.selection, "ocean")
                self.assertEqual(settings.writes, [])
                self.fixture.key(module, monitor, "K")
                with patch.dict(sys.modules, {"settings": settings}), patch.object(module, "post_json") as post:
                    self.fixture.key(module, monitor, "ENTER")
                self.assertFalse(monitor.settings_open)
                self.assertEqual(settings.values["threecx_monitor.clock_style"], style)
                self.assertEqual(settings.values["threecx_monitor.theme"], "ocean")
                self.assertIsNone(monitor.controls.pending)
                post.assert_not_called()

    def test_new_faces_render_single_large_native_time_in_original_and_coloured_themes(self):
        for style in LUXURY:
            for theme in ("original", "ocean", "kitty"):
                with self.subTest(style=style, theme=theme):
                    module, monitor, hardware, settings = self.fixture.monitor(
                        config={"clock_style": style, "theme": theme})
                    self.fixture.clock_page(monitor)
                    records = self.fixture.draw(monitor)
                    local = monitor._local_weather_time(monitor.controller.payload["weather"], 0)
                    time = "%02d:%02d" % (local[3], local[4])
                    primary = [item for item in records if item["text"] == time]
                    self.assertEqual(len(primary), 1)
                    self.assertGreaterEqual(primary[0]["size"], 45)
                    self.assertIsNone(monitor.controls.pending)

    def test_atelier_keeps_bright_status_chrome_over_full_frame_artwork_in_a_light_theme(self):
        module, monitor, hardware, settings = self.fixture.monitor(
            config={"clock_style": "haute_celestial", "theme": "kitty"})
        self.fixture.clock_page(monitor)
        with patch.object(module, "draw_theme_face", wraps=module.draw_theme_face) as themed:
            with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as original:
                records = self.fixture.draw(monitor)
        self.assertEqual(themed.call_args.args[2], "original")
        original.assert_called_once()
        self.assertEqual(monitor.themes.selection, "kitty")
        status = [item for item in records if item["text"] == "MB"]
        self.assertEqual(len(status), 1)
        self.assertTrue(all(channel >= .8 for channel in status[0]["colour"]))
        self.assertIsNone(monitor.controls.pending)

    def test_incoming_call_preempts_each_new_face_before_clock_or_bitmap_dispatch(self):
        for style in LUXURY:
            with self.subTest(style=style):
                module, monitor, hardware, settings = self.fixture.monitor(config={"clock_style": style})
                self.fixture.clock_page(monitor)
                self.fixture.incoming(monitor, number="+447700900456")
                with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as draw:
                    with patch.object(module, "post_json") as post:
                        records = self.fixture.draw(monitor)
                words = [item["text"] for item in records]
                self.assertIn("EC", words)
                self.assertTrue(any("447700900456" in word.replace("+", "") for word in words))
                draw.assert_not_called()
                post.assert_not_called()
                self.assertIsNone(monitor.controls.pending)

    def test_connected_call_and_offline_source_stop_luxury_clock_drawing(self):
        for style in LUXURY:
            for reason in ("connected", "offline"):
                with self.subTest(style=style, reason=reason):
                    module, monitor, hardware, settings = self.fixture.monitor(config={"clock_style": style})
                    self.fixture.clock_page(monitor)
                    if reason == "connected":
                        self.fixture.incoming(monitor, state="connected")
                    else:
                        payload = copy.deepcopy(monitor.controller.payload)
                        payload.update(connected=False, status="PBX unavailable", age_seconds=None)
                        monitor.controller.accept(payload, monitor.clock_ms)
                    with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as draw:
                        records = self.fixture.draw(monitor)
                    draw.assert_not_called()
                    if reason == "offline":
                        self.assertIn("OFFLINE", [item["text"] for item in records])
                    self.assertIsNone(monitor.controls.pending)


if __name__ == "__main__":
    unittest.main()
