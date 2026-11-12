"""Offline primary-anchor/calendar checks; no API/network calls in tests."""
import calendar
from datetime import datetime, timezone
import importlib.util
import math
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/astronomy.py"
spec = importlib.util.spec_from_file_location("astronomy_under_test", PATH)
sky = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sky)


def epoch(year, month, day, hour=12, minute=0):
    return calendar.timegm((year, month, day, hour, minute, 0))


class AstronomyTests(unittest.TestCase):
    def test_usno_2026_primary_phase_times_have_correct_geometry_and_illumination(self):
        for moment, fraction, illumination, name in (
            ((2026, 11, 9, 7, 2), 0, 0, "New Moon"),
            ((2026, 11, 17, 11, 48), .25, 50, "First Quarter"),
            ((2026, 11, 24, 14, 53), .5, 100, "Full Moon"),
            ((2026, 12, 1, 6, 8), .75, 50, "Last Quarter")):
            with self.subTest(moment=moment):
                moon = sky.sky_snapshot(epoch(*moment))["moon"]
                self.assertAlmostEqual(moon["phase_fraction"], fraction)
                self.assertEqual(moon["illumination_percent"], illumination)
                self.assertEqual(moon["name"], name)
                self.assertEqual(moon["waxing"], fraction < .5)
                self.assertTrue(moon["reference_supported"])

    def test_usno_2027_phases_are_year_specific(self):
        for moment, phase in (((2027, 1, 7, 20, 24), 0), ((2027, 1, 15, 20, 34), .25),
                               ((2027, 3, 22, 10, 44), .5), ((2027, 11, 21, 0, 48), .75)):
            self.assertAlmostEqual(sky.sky_snapshot(epoch(*moment))["moon"]["phase_fraction"], phase)

    def test_every_embedded_anchor_is_exact_and_ordered_with_all_quarters(self):
        previous = None
        for stamp, code in sky.PHASE_ANCHORS:
            if previous:
                self.assertGreater(stamp, previous[0])
                self.assertEqual(code, (previous[1] + 1) % 4)
            self.assertAlmostEqual(sky.sky_snapshot(stamp)["moon"]["phase_fraction"], code / 4)
            previous = stamp, code

    def test_phase_interpolation_wraps_continuously_and_never_leaves_bounds(self):
        new_moon = epoch(2026, 11, 9, 7, 2)
        before = sky.sky_snapshot(new_moon - 1)["moon"]["phase_fraction"]
        after = sky.sky_snapshot(new_moon + 1)["moon"]["phase_fraction"]
        self.assertGreater(before, .999)
        self.assertLess(after, .001)
        for day in range(1, 29):
            moon = sky.sky_snapshot(epoch(2027, 2, day))["moon"]
            self.assertTrue(0 <= moon["phase_fraction"] < 1)
            self.assertTrue(0 <= moon["illumination_percent"] <= 100)
            self.assertTrue(moon["approximate"])

    def test_quadrantids_activity_crosses_new_year_without_duplicating_shower(self):
        result = sky.sky_snapshot(epoch(2026, 12, 29))
        values = [item for item in result["active_showers"] if item["id"] == "quadrantids"]
        self.assertEqual(len(values), 1)
        self.assertEqual((values[0]["start"], values[0]["end"], values[0]["peak"]),
                         ("2026-12-28", "2027-01-12", "2027-01-04"))
        self.assertEqual(result["next_shower"]["id"], "quadrantids")
        self.assertEqual(result["next_shower"]["peak_in_days"], 6)
        self.assertEqual(sky.sky_snapshot(epoch(2026, 1, 3))["next_shower"]["peak"], "2026-01-03")

    def test_imo_2026_and2027_peak_days_are_not_reused_blindly(self):
        examples = ((2026, 4, 22, "lyrids"), (2027, 4, 23, "lyrids"),
                    (2026, 10, 21, "orionids"), (2027, 10, 22, "orionids"),
                    (2026, 11, 17, "leonids"), (2027, 11, 18, "leonids"),
                    (2026, 12, 22, "ursids"), (2027, 12, 23, "ursids"))
        for year, month, day, ident in examples:
            result = sky.sky_snapshot(epoch(year, month, day))
            item = next(item for item in result["active_showers"] if item["id"] == ident)
            self.assertEqual(item["peak_in_days"], 0)
            self.assertEqual(item["basis"], "IMO " + str(year))

    def test_activity_boundaries_are_inclusive_but_not_extended_beyond_calendar(self):
        for day, expected in ((3, False), (4, True), (20, True), (21, False)):
            ids = [item["id"] for item in sky.sky_snapshot(epoch(2026, 12, day))["active_showers"]]
            self.assertEqual("geminids" in ids, expected)

    def test_overlapping_november_showers_are_retained_and_nearest_peak_first(self):
        result = sky.sky_snapshot(epoch(2026, 11, 12))
        self.assertEqual(result["active_showers"][0]["id"], "northern_taurids")
        self.assertTrue({"northern_taurids", "southern_taurids", "leonids"}
                        <= {item["id"] for item in result["active_showers"]})
        self.assertEqual(result["next_shower"]["peak_in_days"], 0)

    def test_out_of_supported_years_are_explicitly_typical_not_yearly_predictions(self):
        result = sky.sky_snapshot(epoch(2028, 8, 13))
        self.assertFalse(result["calendar_year_supported"])
        self.assertEqual(result["calendar_basis"], "Typical season")
        self.assertTrue(result["active_showers"])
        self.assertTrue(all(item["basis"] == "Typical season" for item in result["active_showers"]))
        self.assertEqual(result["moon"]["basis"], "Mean lunar cycle")
        crossyear = sky.sky_snapshot(epoch(2027, 12, 29))["next_shower"]
        self.assertEqual(crossyear["basis"], "Typical season")
        self.assertFalse(crossyear["calendar_year_supported"])

    def test_local_timezone_or_2000epoch_helpers_cannot_shift_utc_science(self):
        stamp = epoch(2027, 3, 28, 0, 30)
        result = sky.sky_snapshot(stamp)
        self.assertEqual(result, sky.sky_snapshot(stamp, local=(2027, 3, 28, 1, 30, 0)))
        self.assertEqual(sky._date(stamp // 86400), (2027, 3, 28))
        for value in ((2000, 2, 29), (2028, 2, 29), (2100, 3, 1), (2026, 12, 31)):
            days = epoch(*value, hour=0) // 86400
            self.assertEqual(sky._date(days), value)
            self.assertEqual(sky._day(*value), days)

    def test_returned_results_cannot_poison_the_daily_cache(self):
        stamp = epoch(2026, 11, 12)
        result = sky.sky_snapshot(stamp)
        result["active_showers"][0]["name"] = "mutated"
        result["next_shower"]["name"] = "also mutated"
        self.assertNotIn("mutated", repr(sky.sky_snapshot(stamp)))

    def test_unknown_clock_fails_safely_instead_of_making_up_activity(self):
        for value in (None, "2026", True, math.nan, math.inf, -math.inf, -1, 4133980800):
            result = sky.sky_snapshot(value)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["moon"]["phase_fraction"])
            self.assertIsNone(result["next_shower"])
            self.assertEqual(result["active_showers"], [])

    def test_snapshot_has_no_promised_visible_counts_or_observing_rates(self):
        result = sky.sky_snapshot(epoch(2026, 8, 13))
        self.assertEqual(len(sky.SHOWERS), 12)
        self.assertNotIn("zhr", repr(result).lower())
        self.assertNotIn("meteors_per_hour", repr(result))


if __name__ == "__main__":
    unittest.main()
