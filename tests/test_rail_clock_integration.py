"""Railway faces remain display preferences and yield to live phone state."""

import copy
import sys
import unittest
from unittest.mock import patch

import test_theme_integration as theme_fixture


RAIL_CLOCKS = ("mondaine", "great_british_railways")


class RailClockIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = theme_fixture.ThemeIntegrationTests()

    def test_saved_rail_face_preserves_theme_brightness_and_only_saves_display_preferences(self):
        for style in RAIL_CLOCKS:
            with self.subTest(style=style):
                saved = {"threecx_monitor.clock_style": style,
                         "threecx_monitor.theme": "ocean"}
                module, monitor, hardware, settings = self.fixture.monitor(saved=saved)
                self.assertEqual(monitor.clock_style, style)
                self.assertEqual(monitor.themes.selection, "ocean")
                brightness = (monitor.controller.ring_brightness, monitor.controller.eeh_brightness)
                self.assertEqual(settings.writes, [])
                self.fixture.key(module, monitor, "K")
                self.assertTrue(monitor.settings_open)
                self.fixture.key(module, monitor, "LEFT")
                self.fixture.key(module, monitor, "RIGHT")
                with patch.dict(sys.modules, {"settings": settings}), patch.object(module, "post_json") as post:
                    self.fixture.key(module, monitor, "ENTER")
                self.assertFalse(monitor.settings_open)
                self.assertEqual(settings.values["threecx_monitor.clock_style"], style)
                self.assertEqual(settings.values["threecx_monitor.theme"], "ocean")
                self.assertEqual((monitor.controller.ring_brightness, monitor.controller.eeh_brightness), brightness)
                self.assertGreaterEqual(settings.saves, 1)
                self.assertIsNone(monitor.controls.pending)
                post.assert_not_called()

    def test_live_call_or_offline_source_preempts_both_rail_renderers(self):
        for style in RAIL_CLOCKS:
            for reason in ("ringing", "connected", "offline"):
                with self.subTest(style=style, reason=reason):
                    module, monitor, hardware, settings = self.fixture.monitor(config={"clock_style": style})
                    self.fixture.clock_page(monitor)
                    if reason == "offline":
                        payload = copy.deepcopy(monitor.controller.payload)
                        payload.update(connected=False, status="PBX unavailable", age_seconds=None)
                        monitor.controller.accept(payload, monitor.clock_ms)
                    else:
                        self.fixture.incoming(monitor, state=reason)
                    with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as draw:
                        with patch.object(module, "post_json") as post:
                            words = [record["text"] for record in self.fixture.draw(monitor)]
                    draw.assert_not_called()
                    post.assert_not_called()
                    self.assertIsNone(monitor.controls.pending)
                    if reason != "connected":
                        self.assertIn("OFFLINE" if reason == "offline" else "Partner", words)
                    else:
                        # A connected call returns to the live BLF view;
                        # selecting own-call detail remains an explicit action.
                        self.assertTrue(words)

    def test_showcase_includes_both_rail_faces_for_every_theme_without_saving_tour_preferences(self):
        module, monitor, hardware, settings = self.fixture.monitor(
            config={"clock_style": "radar", "theme": "ocean"})
        preferences = (monitor.clock_style, monitor.themes.selection)
        self.assertTrue(monitor._start_showcase())
        visited = set()
        with patch.object(module, "post_json") as post:
            for index in range(monitor.showcase.count):
                stage = monitor.showcase.stage(index)
                if stage["feature"] != "clock" or stage["clock"] not in RAIL_CLOCKS:
                    continue
                self.assertTrue(monitor._showcase_seek(index))
                with patch.object(module, "draw_clock_content", wraps=module.draw_clock_content) as draw:
                    records = self.fixture.draw(monitor)
                self.assertEqual(draw.call_args.args[1], stage["clock"])
                self.assertIn("DEMO", records[-1]["text"])
                self.assertFalse(monitor.controller.payload["controls"]["enabled"])
                self.assertIsNone(monitor.controls.pending)
                visited.add((stage["theme"], stage["clock"]))
            self.assertEqual(visited, {(key, clock) for key, name, available in monitor.showcase.themes
                                       for clock in RAIL_CLOCKS})
            self.assertEqual(settings.writes, [])
            monitor._end_showcase()
            post.assert_not_called()
        self.assertEqual((monitor.clock_style, monitor.themes.selection), preferences)


if __name__ == "__main__":
    unittest.main()
