"""Station-clock motion follows supplied time, including minute boundaries."""
import importlib.util
import math
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/clock_rail.py"
SPEC = importlib.util.spec_from_file_location("rail_clock_fixture", PATH)
rail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rail)


class Canvas:
    ARITIES = {"rgb": 3, "arc": 6, "fill": 0, "stroke": 0, "move_to": 2,
               "line_to": 2, "close_path": 0, "text": 1}

    def __init__(self):
        self.operations = []
        self.words = []
        self.font_size = 14

    def text_width(self, value):
        return len(value) * self.font_size * .52

    def __getattr__(self, name):
        if name not in self.ARITIES:
            raise AttributeError(name)
        def draw(*values):
            if len(values) != self.ARITIES[name]:
                raise TypeError(name)
            self.operations.append((name, values))
            if name == "text":
                self.words.append((values[0], self.font_size))
            return self
        return draw


def value(hour=9, minute=41, second=0):
    return {"hour": hour, "minute": minute, "second": second, "clock": "%02d:%02d" % (hour, minute)}


class RailClockTests(unittest.TestCase):
    def test_swiss_second_hand_sweeps_in_58_seconds_then_waits_at_twelve(self):
        self.assertEqual(rail._mondaine_phase(value(second=0), 0), 0)
        self.assertEqual(rail._mondaine_phase(value(second=29), 0), .5)
        self.assertAlmostEqual(rail._mondaine_phase(value(second=57), 999), 57.999 / 58)
        for second, elapsed in ((58, 0), (58, 999), (59, 0), (59, 999)):
            self.assertEqual(rail._mondaine_phase(value(second=second), elapsed), 0)
        self.assertAlmostEqual(rail._mondaine_phase(value(minute=42, second=0), 250), .25 / 58)

    def test_swiss_minute_hand_waits_and_jumps_at_the_supplied_minute_boundary(self):
        before = rail._mondaine_hands(value(second=0))
        self.assertEqual(rail._mondaine_hands(value(second=58)), before)
        self.assertEqual(rail._mondaine_hands(value(second=59)), before)
        after = rail._mondaine_hands(value(minute=42, second=0))
        self.assertAlmostEqual(after[1] - before[1], 1 / 60)
        self.assertAlmostEqual(after[0] - before[0], 1 / 720)
        self.assertEqual(rail._mondaine_hands(value(hour=0, minute=0)), (0, 0))

    def test_british_arrows_meet_at_the_top_and_bottom_each_half_minute(self):
        self.assertEqual(rail._rail_phases(value(second=0), 0), (0, 0))
        self.assertEqual(rail._rail_phases(value(second=30), 0), (.5, .5))
        self.assertEqual(rail._rail_phases(value(second=15), 0), (.25, .75))
        self.assertEqual(rail._rail_phases(value(second=45), 0), (.75, .25))
        clockwise, counterclockwise = rail._rail_phases(value(second=0), 500)
        self.assertAlmostEqual(clockwise, .5 / 60)
        self.assertAlmostEqual(counterclockwise, 1 - .5 / 60)

    def test_seconds_fraction_comes_from_elapsed_not_animation_now(self):
        for draw in (rail.draw_mondaine, rail.draw_gbr):
            first, second, fractional = Canvas(), Canvas(), Canvas()
            draw(first, value(second=17), 250, 1, None, None)
            draw(second, value(second=17), 250, 50000000, None, None)
            draw(fractional, value(second=17), 750, 1, None, None)
            self.assertEqual(first.operations, second.operations)
            self.assertNotEqual(first.operations, fractional.operations)

    def test_unknown_time_has_an_explicit_placeholder_and_no_motion(self):
        invalid = (None, {}, "bad", value(hour=24), value(minute=-1), value(second=60),
                   value(hour=True), value(second=float("nan")))
        for bad in invalid:
            self.assertIsNone(rail._mondaine_phase(bad, 0))
            self.assertIsNone(rail._mondaine_hands(bad))
            self.assertIsNone(rail._rail_phases(bad, 0))
            for draw in (rail.draw_mondaine, rail.draw_gbr):
                canvas = Canvas()
                draw(canvas, bad, 0, 0, None, None)
                self.assertIn("--:--", [word for word, size in canvas.words])

    def test_invalid_elapsed_cannot_create_nonfinite_coordinates(self):
        for elapsed in (None, True, "bad", float("nan"), float("inf"), -1):
            self.assertEqual(rail._mondaine_phase(value(second=29), elapsed), .5)
            for draw in (rail.draw_mondaine, rail.draw_gbr):
                canvas = Canvas()
                draw(canvas, value(second=29), elapsed, None, None, None)
                for name, values in canvas.operations:
                    for number in values:
                        if isinstance(number, (int, float)):
                            self.assertTrue(math.isfinite(number))

    def test_british_digits_stay_24_hour_large_and_theme_independent(self):
        for local, expected in ((value(hour=0, minute=3), "00:03"),
                                (value(hour=23, minute=59), "23:59")):
            canvas = Canvas()
            rail.draw_gbr(canvas, local, 0, 0, [(1, 1, 1)] * 7, None)
            primary = [size for word, size in canvas.words if word == expected]
            self.assertEqual(len(primary), 1)
            self.assertGreaterEqual(primary[0], 53)
            self.assertIn(("rgb", rail._RAIL_RED), canvas.operations)
            self.assertIn(("rgb", rail._WHITE), canvas.operations)

    def test_rendering_stays_inside_dial_with_small_independent_paths(self):
        for draw in (rail.draw_mondaine, rail.draw_gbr):
            for second in range(60):
                canvas = Canvas()
                draw(canvas, value(second=second), 999, 0, None, None)
                primitives, edges = 0, 0
                for name, values in canvas.operations:
                    if name in ("move_to", "line_to"):
                        self.assertLessEqual(math.hypot(*values), 101)
                        edges += 1
                    if name in ("fill", "stroke", "text"):
                        primitives += 1
                        self.assertLess(edges, 255)
                        edges = 0
                self.assertLess(primitives, 25)


if __name__ == "__main__":
    unittest.main()
