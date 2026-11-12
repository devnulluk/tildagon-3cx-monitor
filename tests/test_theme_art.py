"""Theme invariants: exact Original fallback and truthful idle-state data."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/theme_art.py"
SPEC = importlib.util.spec_from_file_location("theme_art_under_test", PATH)
art = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(art)


class Context:
    CENTER = 1
    MIDDLE = 2
    def __init__(self):
        self.operations = []
        self.words = []
        self.font_size = 14
    def text_width(self, value):
        return len(value) * self.font_size * .5
    def __getattr__(self, name):
        def draw(*values):
            self.operations.append((name, values))
            if name == "text":
                self.words.append(values[0])
            return self
        return draw


WEATHER = {"location": "Example place", "local_clock": "12:34", "local_date": "Example date",
           "current": {"temperature_c": 18, "condition": "Clear", "apparent_temperature_c": 17},
           "rain_next_hour": {"status": "rain_likely", "precipitation_mm": .8, "onset_minutes": [15, 30]}}
LOCAL = (2026, 12, 12, 12, 34, 56, 5, 346)


def draw(theme, page="weather", fresh=True, weather=None, context=None):
    canvas = Context()
    result = art.draw_theme_face(canvas, page, theme, WEATHER if weather is None else weather,
                                 fresh, LOCAL, 200, 1234, (30, 255, 60), demo=True, context=context)
    return result, canvas


class ThemeArtTests(unittest.TestCase):
    def test_original_and_unknown_leave_the_context_completely_untouched(self):
        for theme in ("original", "missing_style", None):
            result, canvas = draw(theme)
            self.assertIs(result, False)
            self.assertEqual(canvas.operations, [])

    def test_every_theme_keeps_stale_weather_unknown_instead_of_reusing_values(self):
        for theme in art._PALETTES:
            with self.subTest(theme=theme):
                result, canvas = draw(theme, fresh=False)
                self.assertTrue(result)
                self.assertIn("-- C", canvas.words)
                self.assertIn("Unavailable", canvas.words)
                self.assertNotIn("18 C", canvas.words)
                self.assertNotIn("Clear", canvas.words)

    def test_rain_onset_never_reports_invalid_or_reversed_minutes(self):
        for pair in ([60, 90], [-1, 30], [30, 15], [float("nan"), 30], [True, 20]):
            payload = dict(WEATHER, rain_next_hour={"status": "rain_likely", "precipitation_mm": .8, "onset_minutes": pair})
            result, canvas = draw("lcars", page="rain", weather=payload)
            self.assertTrue(result)
            self.assertIn("Model forecast", canvas.words)
            self.assertFalse(any(str(word).startswith("In ") for word in canvas.words))
        result, canvas = draw("lcars", page="rain")
        self.assertIn("In 15-30 min", canvas.words)

    def test_clock_does_not_depend_on_weather_forecast_freshness(self):
        for theme in art._PALETTES:
            result, canvas = draw(theme, page="clock", fresh=False)
            self.assertTrue(result)
            if theme != "retro":  # Retro uses native seven-segment geometry.
                self.assertTrue("12:34" in canvas.words or ("12" in canvas.words and "34" in canvas.words))
            self.assertIn("12 DEC 2026", canvas.words)

    def test_selected_clock_replaces_content_and_failure_keeps_readable_time(self):
        calls = []
        def selected(canvas, palette):
            calls.append(palette)
            canvas.text("Selected clock")
            return True
        result, canvas = draw("kitty", page="clock", context={"clock_draw": selected})
        self.assertTrue(result)
        self.assertEqual(calls, [art._PALETTES["kitty"]])
        self.assertIn("Selected clock", canvas.words)
        self.assertNotIn("12:34", canvas.words)
        self.assertIn("DEMO", canvas.words)
        def unavailable(canvas, palette):
            raise OSError("asset removed")
        result, canvas = draw("kitty", page="clock", context={"clock_draw": unavailable})
        self.assertIn("12:34", canvas.words)
        before = len(calls)
        result, canvas = draw("original", page="clock", context={"clock_draw": selected})
        self.assertFalse(result)
        self.assertEqual(len(calls), before)
        self.assertEqual(canvas.operations, [])

    def test_missing_photo_is_explicit_and_successful_callback_is_used(self):
        result, canvas = draw("photo")
        self.assertTrue(result)
        self.assertIn("Photo unavailable", canvas.words)
        calls = []
        def photo(canvas, now):
            calls.append(now)
            return True
        result, canvas = draw("photo", context={"photo_draw": photo})
        self.assertTrue(result)
        self.assertEqual(calls, [1234])
        self.assertNotIn("Photo unavailable", canvas.words)
        self.assertIn("18 C", canvas.words)

    def test_advent_uses_only_explicit_valid_calendar_context(self):
        result, canvas = draw("christmas", page="advent")
        self.assertTrue(result)
        self.assertIn("DEC", canvas.words)
        self.assertIn("Starts in December", canvas.words)
        result, canvas = draw("christmas", page="advent", context={"advent": True, "advent_day": 12, "days_until_christmas": 13})
        self.assertIn("13 days to Christmas", canvas.words)


if __name__ == "__main__":
    unittest.main()
