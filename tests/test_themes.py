"""Pure local-calendar/theme rules; all personal dates here are synthetic."""
from datetime import date
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/themes.py"
spec = importlib.util.spec_from_file_location("themes_under_test", PATH)
themes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(themes)


def local(year, month, day):
    return year, month, day, 12, 0, 0, date(year, month, day).weekday(), 0


class ThemeCalendarTests(unittest.TestCase):
    def automatic(self, dates=None, **values):
        return themes.ThemeManager(dict(theme_auto=True, personal_dates=dates or {}, **values))

    def test_original_preserves_existing_default_and_manual_selection_disables_auto(self):
        config = {}
        manager = themes.ThemeManager(config)
        self.assertEqual(manager.resolve(local(2027, 12, 25))["id"], "original")
        manager.select("auto")
        self.assertEqual(manager.resolve(local(2027, 12, 25))["id"], "christmas")
        self.assertTrue(manager.select("cyberpunk"))
        self.assertFalse(config["theme_auto"])
        self.assertEqual(manager.resolve(local(2027, 12, 25))["id"], "cyberpunk")
        self.assertFalse(manager.select("missing"))
        self.assertEqual(manager.selection, "cyberpunk")

    def test_gregorian_easter_known_dates_including_requested_2027_2028(self):
        for year, month, day in ((2000, 4, 23), (2024, 3, 31), (2025, 4, 20),
                                 (2026, 4, 5), (2027, 3, 28), (2028, 4, 16)):
            self.assertEqual(themes.easter_date(year), (year, month, day))
        for value in (True, "2027", 1582, 4100):
            self.assertIsNone(themes.easter_date(value))

    def test_easter_weekend_uses_real_calendar_across_march_and_april(self):
        manager = self.automatic()
        for day, selected, offset in ((25, "original", None), (26, "easter", -2),
                                       (27, "easter", -1), (28, "easter", 0),
                                       (29, "easter", 1), (30, "original", None)):
            result = manager.resolve(local(2027, 3, day))
            self.assertEqual(result["id"], selected)
            self.assertEqual(result["easter_offset"], offset)
        self.assertEqual(manager.resolve(local(2028, 4, 16))["id"], "easter")
        self.assertEqual(manager.resolve(local(2028, 3, 28))["id"], "original")

    def test_christmas_window_and_advent_calendar_have_distinct_boundaries(self):
        manager = self.automatic()
        for month, day, selected in ((11, 30, "original"), (12, 1, "christmas"),
                                     (12, 24, "christmas"), (12, 25, "christmas"),
                                     (12, 26, "christmas"), (12, 27, "original")):
            with self.subTest(month=month, day=day):
                result = manager.resolve(local(2027, month, day))
                self.assertEqual(result["id"], selected)
                self.assertEqual(result["advent"], month == 12 and day <= 24)
                self.assertEqual(result["advent_day"], day if result["advent"] else None)
        self.assertEqual(manager.resolve(local(2027, 12, 1))["days_until_christmas"], 24)
        self.assertEqual(manager.resolve(local(2027, 12, 25))["days_until_christmas"], 0)

    def test_manual_christmas_outside_advent_and_disabled_calendar_do_not_add_a_page(self):
        manager = themes.ThemeManager({"theme": "christmas"})
        self.assertEqual(manager.resolve(local(2027, 7, 1))["id"], "christmas")
        self.assertFalse(manager.resolve(local(2027, 7, 1))["advent"])
        manager.config["theme_advent_enabled"] = False
        self.assertFalse(manager.resolve(local(2027, 12, 12))["advent"])

    def test_personal_priority_birthdays_then_anniversary_then_season(self):
        dates = {"birthday_self": "2000-12-25", "birthday_partner": "2001-12-25", "anniversary": "2010-12-25"}
        manager = self.automatic(dates)
        result = manager.resolve(local(2027, 12, 25))
        self.assertEqual((result["id"], result["age"], result["years"]), ("birthday_self", 27, None))
        self.assertFalse(result["advent"])
        manager.set_personal_date("birthday_self", None)
        self.assertEqual(manager.resolve(local(2027, 12, 25))["id"], "birthday_partner")
        manager.set_personal_date("birthday_partner", None)
        result = manager.resolve(local(2027, 12, 25))
        self.assertEqual((result["id"], result["years"]), ("anniversary", 17))
        manager.set_personal_date("anniversary", None)
        self.assertEqual(manager.resolve(local(2027, 12, 25))["id"], "christmas")

    def test_anniversary_overrides_easter_and_repeats_yearly(self):
        manager = self.automatic({"anniversary": "2010-03-28"})
        self.assertEqual(manager.resolve(local(2027, 3, 28))["id"], "anniversary")
        result = manager.resolve(local(2028, 3, 28))
        self.assertEqual((result["id"], result["years"]), ("anniversary", 18))

    def test_future_and_initial_year_dates_never_produce_negative_or_zero_age_counts(self):
        manager = self.automatic({"birthday_self": "2030-05-06", "anniversary": "2027-06-07"})
        self.assertEqual(manager.resolve(local(2027, 5, 6))["id"], "original")
        self.assertIsNone(manager.resolve(local(2030, 5, 6))["age"])
        self.assertIsNone(manager.resolve(local(2027, 6, 7))["years"])
        self.assertEqual(manager.resolve(local(2028, 6, 7))["years"], 1)

    def test_manual_personal_style_does_not_claim_an_age_on_an_unrelated_day(self):
        manager = themes.ThemeManager({"theme": "birthday_self", "personal_dates": {"birthday_self": "2000-05-06"}})
        result = manager.resolve(local(2027, 1, 1))
        self.assertEqual(result["caption"], "Happy birthday")
        self.assertIsNone(result["age"])
        self.assertIsNone(result["event"])

    def test_february29_repeats_annually_with_explicit_observance_policy(self):
        manager = self.automatic({"birthday_self": "2000-02-29"})
        self.assertEqual(manager.resolve(local(2027, 2, 28))["age"], 27)
        self.assertEqual(manager.resolve(local(2027, 3, 1))["id"], "original")
        self.assertEqual(manager.resolve(local(2028, 2, 28))["id"], "original")
        self.assertEqual(manager.resolve(local(2028, 2, 29))["age"], 28)
        manager.config["theme_leap_day"] = "mar1"
        self.assertEqual(manager.resolve(local(2027, 2, 28))["id"], "original")
        self.assertEqual(manager.resolve(local(2027, 3, 1))["age"], 27)

    def test_iso_validation_handles_century_leaps_and_rejects_noncanonical_or_unbounded_dates(self):
        self.assertEqual(themes.parse_iso_date("2000-02-29"), (2000, 2, 29))
        for value in (None, [], 20270506, "1900-02-29", "2100-02-29", "2027-02-29", "2027-04-31",
                      "1899-12-31", "2101-01-01", "2027-00-01", "2027-12-00", "2027-5-6",
                      "2027/05/06", "2027-05-06\n", "２０２７-05-06"):
            with self.subTest(value=value):
                self.assertIsNone(themes.parse_iso_date(value))

    def test_invalid_private_fields_are_ignored_and_invalid_edit_preserves_valid_date(self):
        config = {"theme_auto": True, "personal_dates": {"birthday_self": "bad", "anniversary": [1]}}
        manager = themes.ThemeManager(config)
        self.assertEqual(manager.resolve(local(2027, 5, 6))["id"], "original")
        self.assertTrue(manager.set_personal_date("birthday_self", "2000-05-06"))
        self.assertFalse(manager.set_personal_date("birthday_self", "2000-02-30"))
        self.assertEqual(manager.personal_date("birthday_self"), "2000-05-06")
        self.assertFalse(manager.set_personal_date("unsupported", "2000-01-01"))

    def test_unknown_or_malformed_local_date_never_invents_an_automatic_occasion(self):
        manager = self.automatic({"birthday_self": "2000-12-25"})
        for value in (None, [], (2027, 2, 30), (True, 12, 25), ("2027", 12, 25), (99999, 12, 25)):
            self.assertEqual(manager.resolve(value)["id"], "original")
        manager.select("lcars")
        self.assertEqual(manager.resolve(None)["id"], "lcars")

    def test_renderer_context_and_catalog_never_expose_private_iso_dates(self):
        values = {"birthday_self": "1970-05-06", "birthday_partner": "1975-07-08", "anniversary": "2001-09-10"}
        manager = self.automatic(values)
        result = manager.resolve(local(2027, 5, 6))
        self.assertEqual(result["age"], 57)
        for value in values.values():
            self.assertNotIn(value, repr(result))
            self.assertNotIn(value, repr(manager.catalog()))
        self.assertNotIn("personal_dates", result)

    def test_public_calendar_weekday_matches_the_local_date(self):
        manager = self.automatic()
        for value in ((2027, 1, 4), (2028, 2, 29), (2029, 12, 24)):
            self.assertEqual(manager.resolve(local(*value))["weekday"], date(*value).weekday())


class ThemeCatalogTests(unittest.TestCase):
    def test_catalog_contains_requested_styles_and_metadata_copies_cannot_mutate_manager(self):
        manager = themes.ThemeManager()
        catalog = manager.catalog()
        ids = {entry["id"] for entry in catalog}
        self.assertTrue({"original", "christmas", "easter", "anniversary", "birthday_self", "birthday_partner",
                         "cyberpunk", "lcars", "kitty", "photo", "noir", "ocean", "retro"} <= ids)
        catalog[0]["name"] = "changed"
        self.assertEqual(manager.catalog()[0]["name"], "Original")

    def test_missing_photo_falls_back_safely_without_forgetting_selection(self):
        manager = themes.ThemeManager({"theme": "photo"})
        result = manager.resolve(local(2027, 1, 1))
        self.assertEqual((result["id"], result["requested_id"], result["fallback_reason"]), ("original", "photo", "photo_missing"))
        self.assertEqual(manager.selection, "photo")
        self.assertEqual(manager.resolve(None, photo_available=True)["id"], "photo")

    def test_external_metadata_is_bounded_cannot_override_builtins_and_requires_available_asset(self):
        manager = themes.ThemeManager(extra_themes=[{"id": "original", "name": "Bad override", "available": True},
            {"id": "../escape", "name": "Bad path", "available": True}, {"id": "auto", "name": "Reserved"},
            {"id": "garden", "name": "Garden", "available": False, "secret": "must-not-export"},
            {"id": "space", "name": "Space", "available": True}, {"id": "badlabel", "name": "Bad\nlabel"}])
        self.assertTrue(manager.select("garden"))
        self.assertEqual(manager.resolve(None)["id"], "original")
        self.assertTrue(manager.select("space"))
        self.assertEqual(manager.resolve(None)["id"], "space")
        self.assertEqual(manager.catalog()[0]["name"], "Original")
        self.assertNotIn("must-not-export", repr(manager.catalog()))
        self.assertFalse(manager.select("../escape"))
        many = themes.ThemeManager(extra_themes=[{"id": "item" + str(index), "name": "Item", "available": True} for index in range(30)])
        self.assertEqual(len(many.catalog()), len(themes.THEMES) + 16)

    def test_invalid_config_types_default_safely_and_auto_requires_real_boolean(self):
        manager = themes.ThemeManager({"theme": ["lcars"], "theme_auto": "true", "personal_dates": []})
        self.assertEqual(manager.resolve(None)["id"], "original")
        self.assertFalse(manager.set_auto(1))
        self.assertTrue(manager.set_auto(True))
        self.assertEqual(manager.selection, "auto")


if __name__ == "__main__":
    unittest.main()
