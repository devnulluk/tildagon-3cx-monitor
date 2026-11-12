"""Pure scheduling checks; no clock, network, account or badge dependency."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/idle.py"
spec = importlib.util.spec_from_file_location("idle_pages_under_test", PATH)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


def snapshot():
    return {"connected": True, "age_seconds": 0, "alert": None,
            "own": {"extension": "200", "state": "idle", "calls": [],
                    "presence": {"state": "available", "profile": "Available", "confirmed": True, "age_seconds": 0}},
            "team": [{"extension": number, "state": "idle", "calls": []} for number in ("223", "268", "214", "277")]}


class IdlePagesTests(unittest.TestCase):
    def setUp(self):
        self.value = idle.IdlePages()
        self.payload = snapshot()
        self.value.observe(self.payload, True, 0)

    def test_default_delay_and_twelve_second_rotation(self):
        self.assertFalse(self.value.active(59999))
        self.assertIsNone(self.value.page(59999))
        self.assertEqual(tuple(idle.DEFAULT_PAGES), ("weather", "rain", "clock", "moon"))
        for index, page in enumerate(("weather", "rain", "clock", "moon")):
            self.assertEqual(self.value.page(60000 + index * 12000), page)
        self.assertEqual(self.value.page(108000), "weather")

    def test_user_input_restarts_quiet_period_and_initial_page(self):
        self.assertTrue(self.value.active(60000))
        self.value.touch(65000)
        self.value.observe(self.payload, True, 65000)
        self.assertIsNone(self.value.page(124999))
        self.assertEqual(self.value.page(125000), "weather")

    def test_manual_navigation_stays_idle_and_restarts_page_dwell(self):
        self.assertEqual(self.value.page(71000), "weather")
        self.assertEqual(self.value.next(1, 71000), "rain")
        self.assertTrue(self.value.active(71000))
        self.assertEqual(self.value.page(82999), "rain")
        self.assertEqual(self.value.page(83000), "clock")
        self.assertEqual(self.value.next(-1, 84000), "rain")

    def test_manual_navigation_before_idle_cannot_activate_it(self):
        self.assertIsNone(self.value.next(1, 1000))
        self.assertFalse(self.value.active(1000))

    def test_pages_can_be_reordered_filtered_or_disabled(self):
        value = idle.IdlePages(pages=["clock", "bad", "clock", "rain"], idle_after_ms=0)
        value.observe(self.payload, True, 0)
        self.assertEqual(value.pages, ["clock", "rain"])
        self.assertEqual(value.page(0), "clock")
        self.assertEqual(value.page(12000), "rain")
        disabled = idle.IdlePages(pages=[], idle_after_ms=0)
        disabled.observe(self.payload, True, 0)
        self.assertFalse(disabled.active(100000))

    def test_removed_pages_cannot_be_reenabled_by_saved_configuration(self):
        value = idle.IdlePages(pages=["daylight", "clock", "teamsummary", "weather", "rain"], idle_after_ms=0)
        value.observe(self.payload, True, 0)
        self.assertEqual(value.pages, ["clock", "weather", "rain"])
        disabled = idle.IdlePages(pages=["daylight", "teamsummary"], idle_after_ms=0)
        disabled.observe(self.payload, True, 0)
        self.assertIsNone(disabled.page(100000))

    def test_manual_navigation_wraps_the_four_retained_pages(self):
        self.assertEqual(self.value.page(60000), "weather")
        self.assertEqual(self.value.next(-1, 61000), "moon")
        self.assertEqual(self.value.next(1, 62000), "weather")
        self.assertEqual(self.value.next(1, 63000), "rain")
        self.assertEqual(self.value.next(1, 64000), "clock")
        self.assertEqual(self.value.next(1, 65000), "moon")

    def test_any_own_active_call_blocks_idle_until_sixty_seconds_after_end(self):
        for status in idle.ACTIVE_CALLS:
            with self.subTest(status=status):
                value = idle.IdlePages()
                payload = snapshot()
                value.observe(payload, True, 0)
                payload["own"].update(state="busy", calls=[{"id": "own-call", "state": status}])
                value.observe(payload, True, 60000)
                self.assertFalse(value.active(160000))
                payload["own"].update(state="idle", calls=[])
                value.observe(payload, True, 160000)
                self.assertFalse(value.active(219999))
                self.assertTrue(value.active(220000))

    def test_own_incoming_alert_interrupts_even_without_duplicate_call_leg(self):
        self.payload["alert"] = {"id": "incoming", "state": "ringing", "direction": "inbound"}
        self.value.observe(self.payload, True, 60000)
        self.assertFalse(self.value.active(120000))

    def test_stable_team_answered_or_held_calls_can_idle_after_quiet_minute(self):
        for status in ("connected", "busy", "hold", "held"):
            with self.subTest(status=status):
                value = idle.IdlePages()
                payload = snapshot()
                payload["team"][0].update(state="busy", calls=[{"id": "team-call", "state": status, "peer_extension": "245"}])
                value.observe(payload, True, 0)
                value.observe(payload, True, 59999)
                self.assertFalse(value.active(59999))
                self.assertTrue(value.active(60000))

    def test_team_ringing_and_dialing_keep_overview_visible(self):
        for status in ("ringing", "dialing"):
            value = idle.IdlePages()
            payload = snapshot()
            payload["team"][0].update(state="busy", calls=[{"id": "team-call", "state": status}])
            value.observe(payload, True, 0)
            self.assertFalse(value.active(600000))

    def test_team_call_or_peer_change_immediately_wakes_and_restarts_timer(self):
        self.assertTrue(self.value.active(60000))
        self.payload["team"][0].update(state="busy", calls=[{"id": "call", "state": "connected", "peer_extension": "245"}])
        self.value.observe(self.payload, True, 61000)
        self.assertFalse(self.value.active(61000))
        self.assertTrue(self.value.active(121000))
        self.payload["team"][0]["calls"][0]["peer_extension"] = "271"
        self.value.observe(self.payload, True, 122000)
        self.assertFalse(self.value.active(122000))
        self.assertTrue(self.value.active(182000))

    def test_team_call_end_wakes_even_if_member_state_was_already_busy(self):
        self.payload["team"][0].update(state="busy", calls=[{"id": "call", "state": "connected"}])
        self.value.observe(self.payload, True, 0)
        self.assertTrue(self.value.active(60000))
        self.payload["team"][0].update(state="idle", calls=[])
        self.value.observe(self.payload, True, 61000)
        self.assertFalse(self.value.active(61000))

    def test_unknown_offline_teammates_without_calls_remain_gray_but_do_not_block_idle(self):
        for status in ("unknown", "offline", "unregistered"):
            self.payload["team"][0]["state"] = status
            self.value.observe(self.payload, True, 0)
            self.assertTrue(self.value.active(60000))

    def test_unknown_own_status_and_malformed_nonempty_calls_block_idle(self):
        for member, changes in (("own", {"state": "unknown"}), ("own", {"calls": [{}]}),
                                ("team", {"calls": [None]}), ("team", {"calls": [{"state": "Undefined"}]})):
            value = idle.IdlePages()
            payload = snapshot()
            target = payload["own"] if member == "own" else payload["team"][0]
            target.update(changes)
            value.observe(payload, True, 0)
            self.assertFalse(value.active(60000))

    def test_stale_disconnected_and_recovered_source_keep_errors_visible(self):
        for live, connected in ((False, True), (True, False)):
            self.payload["connected"] = connected
            self.value.observe(self.payload, live, 60000)
            self.assertFalse(self.value.active(60000))
        self.payload["connected"] = True
        self.value.observe(self.payload, True, 61000)
        self.assertFalse(self.value.active(120999))
        self.assertTrue(self.value.active(121000))

    def test_presence_changes_wake_but_age_and_weather_refreshes_do_not(self):
        self.payload["age_seconds"] = 1
        self.payload["generated_at"] = "new timestamp"
        self.payload["own"]["presence"]["age_seconds"] = 4
        self.payload["weather"] = {"age_seconds": 12, "temperature": 15}
        self.value.observe(self.payload, True, 60000)
        self.assertTrue(self.value.active(60000))
        self.payload["own"]["presence"].update(state="dnd", profile="Out of office")
        self.value.observe(self.payload, True, 61000)
        self.assertFalse(self.value.active(61000))

    def test_call_order_changes_do_not_look_like_new_activity(self):
        calls = [{"id": "a", "state": "connected"}, {"id": "b", "state": "hold"}]
        self.payload["team"][0].update(state="busy", calls=calls)
        self.value.observe(self.payload, True, 0)
        self.payload["team"][0]["calls"] = list(reversed(calls))
        self.value.observe(self.payload, True, 60000)
        self.assertTrue(self.value.active(60000))

    def test_observation_does_not_mutate_snapshot(self):
        before = copy.deepcopy(self.payload)
        self.value.observe(self.payload, True, 60000)
        self.assertEqual(self.payload, before)

    def test_bad_configuration_is_rejected(self):
        for kwargs in ({"idle_after_ms": math.nan}, {"idle_after_ms": -1}, {"rotate_ms": 0},
                       {"rotate_ms": math.inf}, {"pages": "weather"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                idle.IdlePages(**kwargs)


class ExternalDataFreshnessTests(unittest.TestCase):
    def test_weather_age_is_independent_and_counts_local_elapsed_time(self):
        self.assertTrue(idle.data_fresh({"age_seconds": 899}, 500))
        self.assertFalse(idle.data_fresh({"age_seconds": 899}, 2000))
        for age in (None, math.nan, math.inf, -1, True):
            self.assertFalse(idle.data_fresh({"age_seconds": age}))


if __name__ == "__main__":
    unittest.main()
