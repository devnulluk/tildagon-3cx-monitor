"""Clock legibility, honest astronomy/unknown states and native ctx limits."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/clocks.py"
PACKAGE = types.ModuleType("clock_faces_fixture")
PACKAGE.__path__ = [str(PATH.parent)]
sys.modules[PACKAGE.__name__] = PACKAGE
SPEC = importlib.util.spec_from_file_location(PACKAGE.__name__ + ".clocks", PATH)
clocks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = clocks
SPEC.loader.exec_module(clocks)

LOCAL = (2026, 11, 12, 21, 7, 0, 3, 316)
SKY = {"valid": True, "moon": {"phase_fraction": .25, "illumination_percent": 50}}
EXPECTED_CLOCKS = ("original", "celestial", "tokyoflash", "radar", "flip", "analogue", "corpus",
                   "haute_celestial", "neon_orrery", "mondaine", "great_british_railways")


class Canvas:
    CENTER, MIDDLE = 1, 2
    ARITIES = {"save": 0, "restore": 0, "rgb": 3, "move_to": 2, "line_to": 2,
               "text": 1, "arc": 6, "fill": 0, "stroke": 0, "round_rectangle": 5, "close_path": 0,
               "translate": 2, "rotate": 1, "curve_to": 6, "image": 5}
    def __init__(self):
        self.operations = []
        self.words = []
        self.font_size = 14
        self.position = (0, 0)
        self.saved = 0
    def text_width(self, value):
        return len(value) * self.font_size * .52
    def __getattr__(self, name):
        if name not in self.ARITIES:
            raise AttributeError("Unsupported native ctx method:" + name)
        def draw(*values):
            if len(values) != self.ARITIES[name]:
                raise TypeError("Wrong native ctx arity:" + name)
            self.operations.append((name, values))
            if name == "move_to":
                self.position = values
            if name == "text":
                self.words.append((values[0], self.font_size, self.position))
            if name == "save":
                self.saved += 1
            if name == "restore":
                self.saved -= 1
            return self
        return draw


def render(style, local=LOCAL, sky=SKY, palette=None, elapsed=250, now=12345, artwork=None):
    canvas = Canvas()
    handled = clocks.draw_clock_content(canvas, style, {}, local, elapsed, now,
                                       palette=palette, sky=sky, artwork=artwork)
    return handled, canvas


class ClockTests(unittest.TestCase):
    def test_catalog_is_fixed_public_metadata_and_returns_copies(self):
        catalog = clocks.get_clock_catalog()
        self.assertEqual(clocks.CLOCKS, EXPECTED_CLOCKS)
        self.assertEqual(tuple(entry["id"] for entry in catalog), clocks.CLOCKS)
        self.assertEqual(len(catalog), 11)
        self.assertTrue(all(set(entry) == {"id", "name"} for entry in catalog))
        self.assertEqual(catalog[-2:], [{"id": "mondaine", "name": "Mondaine"},
                                        {"id": "great_british_railways", "name": "Great British Railways"}])
        catalog[0]["name"] = "modified"
        self.assertEqual(clocks.get_clock_catalog()[0]["name"], "Original")

    def test_original_and_unknown_are_exact_untouched_fallbacks(self):
        for style in ("original", "invalid", None, [], True):
            handled, canvas = render(style)
            self.assertFalse(handled)
            self.assertEqual(canvas.operations, [])

    def test_all_faces_use_supported_native_apis_and_restore_canvas(self):
        for style in clocks.CLOCKS[1:]:
            with self.subTest(style=style):
                handled, canvas = render(style)
                self.assertTrue(handled)
                self.assertEqual(canvas.saved, 0)
                primitives = sum(name in ("fill", "stroke", "text") for name, values in canvas.operations)
                self.assertLess(primitives, 100)
                self.assertFalse(any(name in ("texture", "linear_gradient") for name, values in canvas.operations))
                images = [values for name, values in canvas.operations if name == "image"]
                if style == "haute_celestial":
                    self.assertLessEqual(len(images), 1)
                else:
                    self.assertEqual(images, [])

    def test_primary_time_is_large_and_has_all_digits(self):
        for style in clocks.CLOCKS[1:]:
            handled, canvas = render(style)
            if style == "mondaine":
                # Its bold hands and baton indices carry the primary time;
                # an intrusive digital overlay would defeat the station dial.
                self.assertIn("MONDAINE", [word for word, size, position in canvas.words])
                self.assertNotIn("21:07", [word for word, size, position in canvas.words])
            elif style == "flip":
                digits = [(word, size) for word, size, position in canvas.words if word in ("21", "07")]
                self.assertEqual(len(digits), 2)
                self.assertTrue(all(size >= 52 for word, size in digits))
            else:
                primary = [(word, size) for word, size, position in canvas.words if word == "21:07"]
                self.assertEqual(len(primary), 1)
                self.assertGreaterEqual(primary[0][1], 45)

    def test_only_atelier_uses_verified_bitmap_callback_and_time_remains_native_text(self):
        for style in EXPECTED_CLOCKS:
            calls = []
            def artwork(canvas):
                calls.append(True)
                canvas.image("/synthetic/verified-atelier.png", -120, -120, 240, 240)
                return True
            handled, canvas = render(style, artwork=artwork)
            self.assertEqual(len(calls), 1 if style == "haute_celestial" else 0)
            images = [values for name, values in canvas.operations if name == "image"]
            self.assertEqual(len(images), len(calls))
            if style == "haute_celestial":
                self.assertTrue(handled)
                primary = [(word, size) for word, size, position in canvas.words if word == "21:07"]
                self.assertEqual(len(primary), 1)
                self.assertGreaterEqual(primary[0][1], 45)
                self.assertEqual(canvas.saved, 0)

    def test_atelier_missing_artwork_keeps_vector_face_and_legible_unknown_time(self):
        for artwork in (None, lambda canvas: False):
            for local, expected in ((LOCAL, "21:07"), (None, "--:--")):
                handled, canvas = render("haute_celestial", local=local, artwork=artwork)
                self.assertTrue(handled)
                self.assertEqual(canvas.saved, 0)
                self.assertFalse(any(name == "image" for name, values in canvas.operations))
                primary = [(word, size) for word, size, position in canvas.words if word == expected]
                self.assertEqual(len(primary), 1)
                self.assertGreaterEqual(primary[0][1], 45)
                self.assertGreater(sum(name == "fill" for name, values in canvas.operations), 1)

    def test_atelier_native_image_failure_falls_back_without_losing_clock_or_canvas_state(self):
        for failure in (OSError, ValueError, TypeError, AttributeError, MemoryError):
            with self.subTest(failure=failure):
                def artwork(canvas):
                    raise failure("Synthetic missing artwork")
                handled, canvas = render("haute_celestial", artwork=artwork)
                self.assertTrue(handled)
                self.assertEqual(canvas.saved, 0)
                self.assertIn("21:07", [word for word, size, position in canvas.words])

    def test_every_face_handles_unknown_and_malformed_local_clock_without_inventing_time(self):
        for style in clocks.CLOCKS[1:]:
            for local in (None, [], "bad", (2026, 11, 12, 25, 0, 0), (2026, 2, 30, 1, 2, 3),
                          (2026, 11, 12, True, 2, 3), (2026, 11, 12, float("nan"), 2, 3)):
                with self.subTest(style=style, local=local):
                    handled, canvas = render(style, local=local)
                    words = [word for word, size, position in canvas.words]
                    self.assertTrue(handled)
                    self.assertTrue("--:--" in words or words.count("--") >= 2)
                    self.assertNotIn("21:07", words)

    def test_supplied_palette_is_used_for_primary_time_in_light_and_dark_themes(self):
        for light in (True, False):
            palette = ((.8, .8, .8), (.7, .7, .7), (.9, .9, .9), (.1, .2, .3), (.3, .3, .3), (.8, .2, .4), light)
            handled, canvas = render("radar", palette=palette)
            index = next(i for i, operation in enumerate(canvas.operations) if operation == ("text", ("21:07",)))
            self.assertEqual(canvas.operations[index - 2], ("rgb", palette[3]))

    def test_missing_or_invalid_sky_moon_is_explicitly_unknown(self):
        for style in ("celestial", "haute_celestial", "neon_orrery"):
            for sky in (None, {}, {"valid": False, "moon": {"phase_fraction": .5}},
                        {"valid": True, "moon": "bad"}, {"valid": True, "moon": {"phase_fraction": float("nan")}}):
                with self.subTest(style=style, sky=sky):
                    handled, canvas = render(style, sky=sky)
                    words = [word for word, size, position in canvas.words]
                    self.assertIn("MOON UNKNOWN", words)
                    self.assertIn("?", words)
                    self.assertIn("21:07", words)

    def test_supplied_approximate_moon_illumination_is_labelled(self):
        handled, canvas = render("celestial")
        self.assertIn("MOON ~50%", [word for word, size, position in canvas.words])
        self.assertNotIn("?", [word for word, size, position in canvas.words])

    def test_moon_quarters_have_correct_waxing_and_waning_sides(self):
        for phase, direction in ((.25, 1), (.75, -1)):
            canvas = Canvas()
            self.assertTrue(clocks.draw_moon(canvas, 0, 0, 10, phase, (1, 1, 1), (0, 0, 0)))
            points = [values for name, values in canvas.operations if name == "line_to"]
            self.assertTrue(any(x * direction > 9 for x, y in points))
            self.assertTrue(all(x * direction >= -1e-6 for x, y in points))

    def test_atelier_moon_quarters_preserve_real_waxing_and_waning_orientation(self):
        haute = sys.modules[clocks._haute_celestial.__module__]
        for phase, direction in ((.25, 1), (.75, -1)):
            canvas = Canvas()
            haute._moon(canvas, phase)
            points = [values for name, values in canvas.operations if name == "line_to"]
            self.assertTrue(any(x * direction > 11 for x, y in points))
            self.assertTrue(all(x * direction >= -1e-6 for x, y in points))

    def test_unknown_seconds_do_not_draw_radar_sweep_or_analogue_hands(self):
        for style in ("radar", "analogue"):
            known = render(style)[1]
            unknown = render(style, local=None)[1]
            # The missing hands/sweep remove at least3 separate path strokes.
            count = lambda canvas: sum(name == "stroke" for name, values in canvas.operations)
            self.assertGreaterEqual(count(known) - count(unknown), 3)

    def test_tokyo_encoding_keeps_plain_time_and_explains_its_code(self):
        handled, canvas = render("tokyoflash")
        words = [word for word, size, position in canvas.words]
        self.assertIn("21:07", words)
        self.assertIn("HOURS / 10m / 1m", words)

    def test_uptime_beyond_sixteen_minutes_preserves_animation_and_invalid_numeric_inputs_are_safe(self):
        first = render("celestial", now=2000000)[1]
        second = render("celestial", now=2027000)[1]
        self.assertNotEqual(first.operations, second.operations)
        for value in (float("nan"), float("inf"), None, "unexpected"):
            handled, canvas = render("analogue", elapsed=value, now=value, palette=["bad"])
            self.assertTrue(handled)
            self.assertEqual(canvas.saved, 0)

    def test_corpus_decorative_dart_and_stall_never_change_digital_time(self):
        stalled = render("corpus", now=100)[1]
        darted = render("corpus", now=550)[1]
        self.assertNotEqual(stalled.operations, darted.operations)
        for canvas in (stalled, darted):
            words = [word for word, size, position in canvas.words]
            self.assertEqual(words.count("21:07"), 1)
            self.assertIn("H / M / S", words)
        self.assertEqual(clocks._dart(100), clocks._dart(300))
        self.assertNotEqual(clocks._dart(450), clocks._dart(550))

    def test_corpus_clock_unknown_has_no_three_blue_time_markers(self):
        known = render("corpus")[1]
        unknown = render("corpus", local=None)[1]
        blue = ("rgb", (.055, .48, .95))
        self.assertEqual(known.operations.count(blue), 3)
        self.assertEqual(unknown.operations.count(blue), 0)


if __name__ == "__main__":
    unittest.main()
