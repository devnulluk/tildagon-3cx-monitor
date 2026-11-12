"""Bounded theme-major showcase and synthetic payload contracts; no I/O."""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "badge"


def load(name, filename, package=False):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename,
                                                submodule_search_locations=[str(ROOT)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


showcase = load("showcase_under_test", "showcase.py")
themes = load("showcase_themes", "themes.py")
clocks = load("showcase_clocks", "clocks.py", package=True)
controller = load("showcase_controller", "controller.py")
love = load("showcase_love", "love.py")
notifications = load("showcase_notifications", "notifications.py")
astronomy = load("showcase_astronomy", "astronomy.py")


def engine(**values):
    return showcase.Showcase(themes.ThemeManager().catalog(), clocks.get_clock_catalog(), **values)


class ShowcaseSequenceTests(unittest.TestCase):
    def test_every_theme_has_every_clock_and_the_complete_feature_set_before_next_theme(self):
        show = engine()
        self.assertEqual(len(show.themes), 13)
        self.assertEqual(len(show.clocks), 9)
        self.assertEqual(show.count, 521)
        self.assertEqual(show.count * show.step_ms, 2605000)
        expected_features = {"intro", "weather", "rain", "clock", "moon", "meteors", "team",
                             "team_detail", "call", "notification", "presence", "settings"}
        seen_order, last = [], None
        for key, name, available in show.themes:
            stages = [show.stage(index) for index in range(show.count) if show.stage(index)["theme"] == key]
            self.assertEqual(len(stages), 41 if key == "christmas" else 40)
            self.assertEqual(stages[0]["feature"], "intro")
            self.assertEqual({stage["clock"] for stage in stages if stage["feature"] == "clock"}, set(clocks.CLOCKS))
            self.assertEqual({stage["weather_kind"] for stage in stages if stage["feature"] == "weather"},
                             {"day", "night", "rain", "storm", "snow", "fog"})
            self.assertTrue(expected_features <= {stage["feature"] for stage in stages})
            self.assertEqual({stage["scene"] for stage in stages if stage["feature"] == "call"},
                             {"ddi", "internal", "queue", "priority", "partner", "connected", "partner_connected"})
            self.assertEqual({stage["presence"] for stage in stages if stage["feature"] == "presence"},
                             {"available", "away", "dnd"})
            self.assertEqual({stage["notification"] for stage in stages if stage["feature"] == "notification"},
                             {"info", "success", "warning", "failure", "progress25", "progress75"})
        for index in range(show.count):
            theme = show.stage(index)["theme"]
            if theme != last:
                self.assertNotIn(theme, seen_order)
                seen_order.append(theme)
                last = theme
        self.assertEqual(seen_order, [value[0] for value in show.themes])

    def test_elapsed_time_not_call_count_drives_steps_wrap_and_repeat(self):
        show = engine()
        self.assertEqual(show.current(100000)["index"], 0)
        first = show.current(100000)
        self.assertEqual(show.current(104999)["index"], 0)
        self.assertEqual(show.current(105000)["index"], 1)
        wrapped = show.current(100000 + show.count * 5000)
        self.assertEqual((wrapped["index"], wrapped["loop"]), (0, 1))
        self.assertNotEqual(wrapped["id"], first["id"])
        far = show.current(100000 + show.count * 5000 * 10000 + 1234)
        self.assertEqual((far["index"], far["loop"], far["elapsed_ms"]), (0, 10000, 1234))

    def test_pause_manual_navigation_and_resume_do_not_accumulate_hidden_time(self):
        show = engine()
        show.current(0)
        show.toggle_pause(1250)
        paused = show.current(20000)
        self.assertTrue(show.paused)
        self.assertEqual((paused["index"], paused["elapsed_ms"]), (0, 1250))
        next_stage = show.advance(1, 21000)
        self.assertEqual((next_stage["index"], next_stage["elapsed_ms"]), (1, 0))
        self.assertTrue(show.paused)
        show.toggle_pause(22000)
        self.assertEqual(show.current(26000)["index"], 1)
        self.assertEqual(show.current(27000)["index"], 2)

    def test_manual_previous_and_theme_navigation_wrap_safely(self):
        show = engine()
        self.assertEqual(show.advance(-1, 0)["index"], show.count - 1)
        self.assertEqual(show.advance(1, 0)["index"], 0)
        self.assertEqual(show.next_theme(1, 0)["theme"], "christmas")
        self.assertEqual(show.next_theme(-1, 0)["theme"], "original")
        self.assertEqual(show.next_theme(-1, 0)["theme"], "retro")
        self.assertEqual(show.current(0)["step_index"], 0)

    def test_side_effect_free_stage_lookup_and_copied_catalogs(self):
        catalog = [{"id": "original", "name": "Original", "secret": "not copied"},
                   {"id": "photo", "name": "Photo", "available": False}]
        clocks_input = clocks.get_clock_catalog()
        show = showcase.Showcase(catalog, clocks_input)
        before = show.current(100)
        for index in range(show.count):
            stage = show.stage(index)
            self.assertNotIn("secret", stage)
            stage["theme"] = "outside mutation"
        self.assertEqual(show.current(100), before)
        catalog[0]["name"] = "Changed"
        clocks_input[0]["id"] = "Changed"
        self.assertEqual(show.current(100)["theme_name"], "Original")
        unavailable = next(show.stage(i) for i in range(show.count) if show.stage(i)["theme"] == "photo")
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["render_theme"], "original")
        self.assertNotIn("secret", repr(vars(show)))

    def test_catalog_input_and_step_bounds_are_finite_and_bounded(self):
        for value in (None, [], "bad"):
            show = showcase.Showcase(value, value)
            self.assertEqual(show.themes, (("original", "Original", True),))
        many = [{"id": "theme_%d" % index, "name": "Theme"} for index in range(100)]
        show = showcase.Showcase(many, ["clock_%d" % i for i in range(100)])
        self.assertEqual((len(show.themes), len(show.clocks)), (29, 16))
        self.assertLess(show.count, 1400)
        for value in (0, 249, 60001, True, None, math.inf, math.nan):
            with self.assertRaises(ValueError): engine(step_ms=value)
        before = show.current(0)
        for value in (None, True, "bad", math.inf, math.nan):
            self.assertEqual(show.advance(value, 0), before)
            self.assertEqual(show.next_theme(value, 0), before)

    def test_visit_ids_stay_stable_within_stage_but_change_after_manual_reentry(self):
        show = engine()
        first = show.current(0)
        self.assertEqual(first["id"], show.current(4000)["id"])
        show.advance(1, 4000)
        replayed = show.advance(-1, 4000)
        self.assertEqual(replayed["index"], first["index"])
        self.assertNotEqual(replayed["id"], first["id"])
        self.assertEqual(replayed["remaining_ms"], 5000)


class ShowcasePayloadTests(unittest.TestCase):
    def test_every_stage_builds_a_fresh_safe_controller_payload_without_action_capability(self):
        show = engine()
        playback = controller.Controller()
        for index in range(show.count):
            stage = show.stage(index)
            before = copy.deepcopy(stage)
            payload = showcase.snapshot(stage, 1250)
            playback.accept(payload, 1250)
            self.assertTrue(playback.live(1250))
            self.assertTrue(payload["demo"])
            self.assertTrue(payload["connected"])
            self.assertEqual(payload["own"]["extension"], "100")
            self.assertFalse(payload["controls"]["enabled"])
            self.assertFalse(payload["controls"]["call"])
            self.assertFalse(payload["controls"]["dnd"])
            self.assertEqual(stage, before)
            for field in ("token", "control_token", "bridge_url", "password"):
                self.assertNotIn(field, payload)
            payload["team"][0]["name"] = "Outside mutation"
            self.assertEqual(showcase.snapshot(stage, 1250)["team"][0]["name"], "Alex")

    def test_only_partner_call_stages_activate_the_actual_partner_heartbeat(self):
        show = engine()
        config = showcase.demo_config()
        for index in range(show.count):
            stage = show.stage(index)
            payload = showcase.snapshot(stage, 0)
            expected = stage["feature"] == "call" and stage["scene"] in ("partner", "partner_connected")
            self.assertEqual(love.partner_active(payload, True, config, demo=True), expected,
                             (stage["theme"], stage["scene"], stage["feature"]))
            self.assertEqual(love.partner_active(payload, False, config, demo=True), False)

    def test_weather_variants_and_next_hour_totals_are_internally_consistent(self):
        show = engine()
        for index in range(show.count):
            stage = show.stage(index)
            if stage["feature"] not in ("weather", "rain"):
                continue
            weather = showcase.snapshot(stage, 0)["weather"]
            self.assertTrue(weather["live"])
            self.assertEqual(weather["age_seconds"], 0)
            self.assertEqual(weather["location"], "Westmoor")
            wet = stage["weather_kind"] in ("rain", "storm", "snow")
            rain = weather["rain_next_hour"]
            self.assertEqual(rain["status"], "rain_likely" if wet else "dry_likely")
            self.assertEqual(rain["window_end"] - rain["window_start"], 3600)
            self.assertEqual(rain["precipitation_mm"] > 0, wet)
            self.assertEqual(weather["current"]["is_day"], stage["weather_kind"] != "night")

    def test_notifications_render_all_types_and_both_progress_values_with_valid_schema(self):
        show = engine()
        kinds, progresses = set(), set()
        for index in range(show.count):
            stage = show.stage(index)
            if stage["feature"] != "notification": continue
            payload = showcase.snapshot(stage, 0)
            inbox = notifications.NotificationInbox()
            self.assertTrue(inbox.observe(payload["notifications"], 0))
            notice = inbox.current(0)
            self.assertIsNotNone(notice)
            kinds.add(notice["type"])
            if notice["progress"] is not None: progresses.add(notice["progress"])
        self.assertEqual(kinds, {"info", "success", "warning", "failure"})
        self.assertEqual(progresses, {25, 75})

    def test_every_meteor_stage_has_an_actual_supported_active_calendar_shower(self):
        show = engine()
        for index in range(show.count):
            stage = show.stage(index)
            if stage["feature"] != "meteors": continue
            weather = showcase.snapshot(stage, 0)["weather"]
            sky = astronomy.sky_snapshot(weather["now_unix"])
            self.assertTrue(sky["calendar_year_supported"])
            self.assertTrue(any(shower["id"] == "geminids" for shower in sky["active_showers"]))

    def test_advent_only_appears_for_christmas_and_synthetic_dates_match_occasion(self):
        show = engine()
        config = showcase.demo_config()
        manager = themes.ThemeManager(config)
        advent = [show.stage(i) for i in range(show.count) if show.stage(i)["feature"] == "advent"]
        self.assertEqual(len(advent), 1)
        self.assertEqual(advent[0]["theme"], "christmas")
        for theme in ("birthday_self", "birthday_partner", "anniversary", "easter"):
            stage = next(show.stage(i) for i in range(show.count) if show.stage(i)["theme"] == theme)
            date = tuple(int(value) for value in stage["date"].split("-"))
            manager.select(theme)
            resolved = manager.resolve(date + (12, 7, 0, 0))
            self.assertEqual(resolved["event"], theme)
            if theme.startswith("birthday"):
                self.assertIsNotNone(resolved["age"])
            if theme == "anniversary":
                self.assertIsNotNone(resolved["years"])

    def test_live_clock_ticks_even_if_the_feature_sequence_is_paused(self):
        show = engine()
        stage = show.current(0)
        show.toggle_pause(0)
        early = showcase.snapshot(stage, 0)["weather"]
        later = showcase.snapshot(show.current(7000), 7000)["weather"]
        self.assertEqual(later["now_unix"] - early["now_unix"], 7)
        self.assertEqual(show.current(7000)["index"], stage["index"])

    def test_demo_configuration_is_fresh_and_contains_no_connection_identity(self):
        first = showcase.demo_config()
        first["personal_dates"]["birthday_self"] = "changed"
        first["partner_numbers"].clear()
        clean = showcase.demo_config()
        self.assertNotEqual(clean["personal_dates"]["birthday_self"], "changed")
        self.assertTrue(clean["partner_numbers"])
        self.assertFalse(any(key in clean for key in ("bridge_url", "token", "control_token", "username", "password")))


if __name__ == "__main__":
    unittest.main()
