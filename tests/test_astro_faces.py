"""Native-vector astronomy faces; synthetic fixtures, no hardware or network."""
import calendar
import copy
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import test_clocks as support

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("astro_face_package")
package.__path__ = [str(ROOT / "badge")]
spec = importlib.util.spec_from_file_location("astro_face_package.astro_faces", ROOT / "badge/astro_faces.py")
faces = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"astro_face_package": package}):
    spec.loader.exec_module(faces)


class Canvas(support.Canvas):
    ARITIES = dict(support.Canvas.ARITIES, rectangle=4)


def moon_sky(phase=.25, illumination=50, name="First Quarter"):
    return {"valid": True, "moon": {"phase_fraction": phase, "illumination_percent": illumination, "name": name},
            "active_showers": [], "next_shower": None, "calendar_basis": "IMO 2026"}


def render(page, sky=None, weather=None, **values):
    ctx = Canvas()
    handled = faces.draw_astro_face(ctx, page, weather or {}, False, None, 0, 12345, (0, 145, 25), sky=sky, **values)
    return handled, ctx


class AstroFaceTests(unittest.TestCase):
    def test_unsupported_pages_are_untouched_fallbacks(self):
        for page in ("clock", "weather", "advent", None, [], True):
            handled, ctx = render(page)
            self.assertFalse(handled)
            self.assertEqual(ctx.operations, [])

    def test_both_faces_use_supported_bounded_native_operations_and_restore_state(self):
        stamp = calendar.timegm((2026, 11, 12, 12, 0, 0))
        for page in ("moon", "meteors"):
            for now in (0, 100, 3000, 1234567890):
                ctx = Canvas()
                self.assertTrue(faces.draw_astro_face(ctx, page, {"now_unix": stamp}, False, None, 0, now, (0, 145, 25)))
                self.assertEqual(ctx.saved, 0)
                primitives = sum(name in ("fill", "stroke", "text") for name, values in ctx.operations)
                self.assertLess(primitives, 100)
                self.assertFalse(any(name in ("image", "texture", "linear_gradient") for name, values in ctx.operations))

    def test_moon_quarters_light_the_correct_northern_hemisphere_side(self):
        for phase, side, name in ((.25, 1, "First Quarter"), (.75, -1, "Last Quarter")):
            handled, ctx = render("moon", sky=moon_sky(phase, 50, name))
            closing = next(index for index, operation in enumerate(ctx.operations) if operation[0] == "close_path")
            opening = max(index for index, operation in enumerate(ctx.operations[:closing]) if operation[0] == "move_to")
            points = [values for method, values in ctx.operations[opening:closing] if method == "line_to"]
            self.assertTrue(points)
            self.assertTrue(all(x * side >= -1e-8 for x, y in points))
            self.assertTrue(any(x * side > 40 for x, y in points))
            self.assertIn(name, [word for word, size, position in ctx.words])

    def test_primary_phase_percentage_is_readable_and_explicitly_approximate(self):
        for phase, illumination, name in ((0, 0, "New Moon"), (.25, 50, "First Quarter"), (.5, 100, "Full Moon")):
            handled, ctx = render("moon", sky=moon_sky(phase, illumination, name))
            percentage = [(word, size) for word, size, position in ctx.words if word == "~%d%%" % illumination]
            self.assertEqual(len(percentage), 1)
            self.assertGreaterEqual(percentage[0][1], 28)
            self.assertIn("Approx. illumination", [word for word, size, position in ctx.words])

    def test_light_theme_cannot_invert_the_moons_illuminated_and_shadow_sides(self):
        pastel = ((.8, .8, .8), (.7, .7, .7), (.9, .9, .9), (.1, .2, .3), (.3, .3, .3), (.8, .2, .4), True)
        for palette in (None, pastel):
            handled, ctx = render("moon", sky=moon_sky(), palette=palette)
            disc = next(index for index, (method, values) in enumerate(ctx.operations) if method == "arc" and values[2] == 44)
            shadow = ctx.operations[disc - 1][1]
            closing = next(index for index, operation in enumerate(ctx.operations) if operation[0] == "close_path")
            opening = max(index for index, operation in enumerate(ctx.operations[:closing]) if operation[0] == "move_to")
            light = ctx.operations[opening - 1][1]
            self.assertGreater(sum(light), sum(shadow) * 3)

    def test_invalid_sky_or_phase_is_unknown_without_fabricating_full_or_new_moon(self):
        for sky in ({}, {"valid": False, "moon": moon_sky()["moon"]}, moon_sky(math.nan), moon_sky(True),
                    moon_sky(.5, math.inf), {"valid": True, "moon": "bad"}):
            handled, ctx = render("moon", sky=sky)
            words = [word for word, size, position in ctx.words]
            self.assertIn("?", words)
            self.assertIn("--%", words)
            self.assertNotIn("~0%", words)
            self.assertNotIn("~100%", words)

    def test_current_calendar_activity_and_another_upcoming_peak_are_separate(self):
        stamp = calendar.timegm((2026, 11, 12, 12, 0, 0))
        sky = faces.sky_snapshot(stamp)
        handled, ctx = render("meteors", sky=sky)
        words = [word for word, size, position in ctx.words]
        self.assertIn("ACTIVE SEASON", words)
        self.assertIn("N. Taurids", words)
        self.assertIn("Peak 12 Nov", words)
        self.assertIn("Next: Leonids", words)
        self.assertIn("IMO 2026", words)
        self.assertIn("Decorative trails", words)
        self.assertFalse(any("per hour" in word or "observed" in word.lower() for word in words))

    def test_upcoming_showers_and_unsupported_years_never_claim_to_be_observed(self):
        stamp = calendar.timegm((2028, 2, 12, 12, 0, 0))
        handled, ctx = render("meteors", sky=faces.sky_snapshot(stamp))
        words = [word for word, size, position in ctx.words]
        self.assertIn("NEXT PEAK", words)
        self.assertIn("Lyrids", words)
        self.assertIn("Typical season", words)
        self.assertNotIn("ACTIVE SEASON", words)

    def test_missing_clock_has_no_calendar_activity_or_decorative_streaks(self):
        handled, unknown = render("meteors", sky={"valid": False, "active_showers": [{"name": "Fake"}]})
        words = [word for word, size, position in unknown.words]
        self.assertIn("CALENDAR UNKNOWN", words)
        self.assertIn("Unavailable", words)
        self.assertNotIn("Fake", words)
        lines = [values for name, values in unknown.operations if name == "line_to"]
        self.assertEqual(lines, [])

    def test_stale_weather_does_not_invalidate_independent_known_utc_astronomy(self):
        stamp = calendar.timegm((2026, 11, 24, 14, 53, 0))
        handled, ctx = render("moon", weather={"now_unix": stamp, "live": False, "stale": True})
        words = [word for word, size, position in ctx.words]
        self.assertIn("Full Moon", words)
        self.assertIn("~100%", words)

    def test_supplied_theme_palette_and_own_status_are_used_without_mutating_inputs(self):
        palette = ((.8, .8, .8), (.7, .7, .7), (.9, .9, .9), (.1, .2, .3), (.3, .3, .3), (.8, .2, .4), True)
        sky = moon_sky()
        before = copy.deepcopy(sky)
        handled, ctx = render("moon", sky=sky, palette=palette, demo=True)
        self.assertEqual(sky, before)
        index = next(index for index, operation in enumerate(ctx.operations) if operation == ("text", ("First Quarter",)))
        self.assertEqual(ctx.operations[index - 2], ("rgb", palette[3]))
        self.assertIn("DEMO", [word for word, size, position in ctx.words])

    def test_malformed_weather_palette_and_clock_values_do_not_crash(self):
        for page in ("moon", "meteors"):
            ctx = Canvas()
            self.assertTrue(faces.draw_astro_face(ctx, page, "bad", False, None, math.nan, math.inf,
                                                 (math.nan, 0, 0), sky="bad", palette=[True]))
            self.assertEqual(ctx.saved, 0)


if __name__ == "__main__":
    unittest.main()
