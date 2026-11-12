"""Neon Orrery legibility, honest astronomy and native-vector budgets."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "badge/clock_cyber.py"
spec = importlib.util.spec_from_file_location("clock_cyber_under_test", PATH)
face = importlib.util.module_from_spec(spec)
spec.loader.exec_module(face)

VALUE = {"clock": "21:07", "date": "12 NOV 2026", "weekday": "THU", "day": "12",
         "hour": 21, "minute": 7, "second": 0}
SKY = {"valid": True, "moon": {"phase_fraction": .25, "illumination_percent": 50}}


class Canvas:
    CENTER, MIDDLE = 1, 2
    ARITIES = {"save": 0, "restore": 0, "rgb": 3, "move_to": 2, "line_to": 2, "text": 1,
               "arc": 6, "fill": 0, "stroke": 0, "round_rectangle": 5, "close_path": 0}
    def __init__(self):
        self.operations = []
        self.words = []
        self.font_size = 14
        self.line_width = 1
        self.saved = 0
        self.max_saved = 0
        self.position = (0, 0)
        self.colour = (0, 0, 0)
        self.edges = 0
        self.max_edges = 0
        self.geometry = []
        self.max_geometry_radius = 0

    def text_width(self, value):
        return len(value) * self.font_size * .52

    def __getattr__(self, name):
        if name not in self.ARITIES:
            raise AssertionError("Unsupported native API: " + name)
        def method(*values):
            if len(values) != self.ARITIES[name]:
                raise AssertionError("Wrong native API arity: " + name)
            if name != "text" and any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise AssertionError("Nonfinite geometry")
            if name == "save":
                self.saved += 1
                self.max_saved = max(self.max_saved, self.saved)
            elif name == "restore":
                self.saved -= 1
            elif name == "rgb":
                if not all(0 <= v <= 1 for v in values): raise AssertionError("Invalid RGB")
                self.colour = values
            elif name in ("move_to", "line_to"):
                self.position = values
                self.geometry.append(math.hypot(*values))
                self.edges += name == "line_to"
            elif name == "arc":
                if values[2] <= 0 or type(values[5]) is not bool: raise AssertionError("Invalid arc")
                self.geometry.append(math.hypot(values[0], values[1]) + values[2])
                self.edges += math.ceil(abs(values[4] - values[3]) * math.sqrt(values[2]))
            elif name == "round_rectangle":
                x, y, width, height, radius = values
                self.geometry.extend(math.hypot(a, b) for a in (x, x + width) for b in (y, y + height))
                self.edges += 16
            elif name == "text":
                self.words.append((values[0], self.font_size, self.position, self.colour))
            elif name in ("stroke", "fill"):
                padding = self.line_width / 2 if name == "stroke" else 0
                self.max_geometry_radius = max(self.max_geometry_radius,
                                               max(self.geometry, default=0) + padding)
                self.max_edges = max(self.max_edges, self.edges)
                self.geometry = []
                self.edges = 0
            self.operations.append((name, values))
            return self
        return method


def render(value=VALUE, sky=SKY, now=12345, elapsed=250, palette=None):
    canvas = Canvas()
    result = face.draw(canvas, value, elapsed, now, palette, sky)
    return result, canvas


class NeonOrreryTests(unittest.TestCase):
    def test_large_complete_time_and_supplied_calendar_are_readable(self):
        result, ctx = render()
        self.assertTrue(result)
        time = [(text, size, point) for text, size, point, colour in ctx.words if text == "21:07"]
        self.assertEqual(time, [("21:07", 48, (0, -8))])
        self.assertIn("12 NOV 2026", [word[0] for word in ctx.words])
        self.assertIn("THU", [word[0] for word in ctx.words])
        self.assertIn("12", [word[0] for word in ctx.words])
        self.assertIn("DECORATIVE ORBITS", [word[0] for word in ctx.words])

    def test_geometry_and_state_stay_within_native_and_dial_limits(self):
        for now in (0, 300, 12345, 1000000, 1000000000000):
            for phase in (0, .25, .5, .75, 1):
                result, ctx = render(now=now, sky={"valid": True, "moon": {"phase_fraction": phase, "illumination_percent": 50}})
                self.assertEqual(ctx.saved, 0)
                self.assertLess(ctx.max_saved, 10)
                self.assertLess(ctx.max_edges, 255)
                self.assertLessEqual(ctx.max_geometry_radius, 101)
                self.assertLess(sum(name in ("fill", "stroke", "text") for name, args in ctx.operations), 100)
                self.assertFalse(any(name in ("image", "texture", "linear_gradient") for name, args in ctx.operations))

    def test_missing_hour_never_invents_time_or_draws_a_timestamp_marker(self):
        bad = dict(VALUE, hour=None, minute=None, second=None, clock="21:07", date="Clock unavailable", day="--")
        _, known = render(elapsed=0)
        _, unknown = render(value=bad, elapsed=0)
        self.assertIn("--:--", [word[0] for word in unknown.words])
        self.assertNotIn("21:07", [word[0] for word in unknown.words])
        marker = lambda ctx: [args for name, args in ctx.operations if name == "arc" and args[2] == 1.4]
        self.assertEqual(len(marker(known)), 1)
        self.assertEqual(marker(unknown), [])
        self.assertEqual(marker(known)[0][:3], (55, 39, 1.4))

    def test_seconds_fraction_uses_local_second_and_elapsed_fraction_not_uptime(self):
        _, first = render(elapsed=0, now=0)
        _, second = render(elapsed=500, now=0)
        marker = lambda ctx: [args[:2] for name, args in ctx.operations if name == "arc" and args[2] == 1.4]
        self.assertNotEqual(marker(first), marker(second))
        _, distant = render(elapsed=0, now=9999999)
        self.assertEqual(marker(first), marker(distant))
        self.assertIn("21:07", [word[0] for word in distant.words])

    def test_missing_or_invalid_moon_is_explicitly_unknown(self):
        for sky in (None, {}, {"valid": False, "moon": SKY["moon"]}, {"valid": True, "moon": "bad"},
                    {"valid": True, "moon": {"phase_fraction": math.nan}},
                    {"valid": True, "moon": {"phase_fraction": True}}):
            with self.subTest(sky=sky):
                _, ctx = render(sky=sky)
                words = [word[0] for word in ctx.words]
                self.assertIn("?", words)
                self.assertIn("MOON UNKNOWN", words)
                self.assertNotIn("MOON ~0%", words)

    def test_quarter_moon_illumination_has_correct_northern_hemisphere_side(self):
        for phase, direction in ((.25, 1), (.75, -1)):
            ctx = Canvas()
            face._moon(ctx, phase)
            points = [values for name, values in ctx.operations if name == "line_to"]
            self.assertTrue(any(x * direction > 12 for x, y in points))
            self.assertTrue(all(x * direction >= -1e-6 for x, y in points))
        _, ctx = render()
        self.assertIn("MOON ~50%", [word[0] for word in ctx.words])

    def test_light_themes_cannot_invert_moon_or_hide_white_time(self):
        light = ((1, 1, 1),) * 6 + (True,)
        _, default = render()
        _, themed = render(palette=light)
        self.assertEqual(default.operations, themed.operations)
        primary = next(word for word in themed.words if word[0] == "21:07")
        self.assertEqual(primary[3], face._WHITE)

    def test_decorative_orbits_animate_without_changing_real_time(self):
        _, first = render(now=0)
        _, changed = render(now=2000)
        self.assertNotEqual(first.operations, changed.operations)
        self.assertEqual(next(word for word in first.words if word[0] == "21:07"),
                         next(word for word in changed.words if word[0] == "21:07"))

    def test_malformed_animation_values_and_input_records_fail_safely(self):
        for value in (None, [], "bad", {}, dict(VALUE, hour=True), dict(VALUE, minute=99)):
            for bad in (None, "bad", [], math.nan, math.inf):
                result, ctx = render(value=value, elapsed=bad, now=bad, palette=["bad"], sky=None)
                self.assertTrue(result)
                self.assertEqual(ctx.saved, 0)
                self.assertIn("--:--", [word[0] for word in ctx.words])

    def test_render_reuses_cached_trigonometry_and_preserves_input_records(self):
        value, sky = copy.deepcopy(VALUE), copy.deepcopy(SKY)
        before = copy.deepcopy((value, sky))
        with patch.object(face.math, "sin", side_effect=AssertionError("Per-frame sine")), \
                patch.object(face.math, "cos", side_effect=AssertionError("Per-frame cosine")):
            render(value=value, sky=sky)
        self.assertEqual((value, sky), before)

    def test_context_restores_even_on_driver_failure(self):
        class Failing(Canvas):
            def rgb(self, *values): raise RuntimeError("Synthetic native failure")
        ctx = Failing()
        with self.assertRaisesRegex(RuntimeError, "Synthetic native failure"):
            face.draw(ctx, VALUE, 0, 0, None, SKY)
        self.assertEqual(ctx.saved, 0)


if __name__ == "__main__":
    unittest.main()
