"""Actual idle UI/input integration against a fake badge; no network or PBX."""
import copy
from datetime import datetime, timezone
import math
import time as desktop_time
import unittest
from unittest.mock import patch

import test_badge as support


class AnimationCanvas(support.RecordingCanvas):
    def __init__(self):
        super().__init__()
        self.scales = []

    def scale(self, horizontal, vertical):
        self.scales.append((horizontal, vertical))
        return self


class NativeApiCanvas(AnimationCanvas):
    """Reject APIs/arities absent from firmware drivers/gc9a01/mp_uctx.c."""
    METHODS = {"rectangle": (4,), "round_rectangle": (5,), "fill": (0,), "stroke": (0,),
               "arc": (6,), "line_to": (2,), "curve_to": (6,), "rgba": (4,),
               "linear_gradient": (4,), "add_stop": (2, 3), "close_path": (0,),
               "begin_path": (0,), "clip": (0,), "translate": (2,), "rotate": (1,)}

    def __init__(self):
        super().__init__()
        self.arcs = []

    def __getattr__(self, name):
        if name not in self.METHODS:
            raise AttributeError("Unsupported native ctx API: " + name)
        def call(*args):
            if len(args) not in self.METHODS[name]:
                raise TypeError("Wrong native ctx argument count: " + name)
            if name == "arc":
                self.arcs.append(args)
            return self
        return call


class BadgeIdleTests(unittest.TestCase):
    def monitor(self, keyboard=True):
        module, monitor, hardware = support.BadgeAppTests.live_monitor(keyboard)
        module.time.gmtime = desktop_time.gmtime
        value = copy.deepcopy(monitor.controller.payload)
        value.update(alert=None, connected=True, age_seconds=0)
        value["own"].update(state="idle", calls=[])
        value["own"]["presence"] = {"state": "available", "confirmed": True, "age_seconds": 0}
        for member in value["team"]:
            member.update(state="idle", calls=[])
        value["weather"] = {
            "live": True, "available": True, "stale": False, "age_seconds": 0,
            "location": "Westmoor", "now_unix": 1794398820, "utc_offset_seconds": 0,
            "local_clock": "12:07", "local_date": "Wed 11 Nov",
            "current": {"temperature_c": 9.1, "apparent_temperature_c": 7, "condition": "Overcast"},
            "rain_next_hour": {"status": "rain_likely", "precipitation_mm": 0.6, "onset_minutes": [8, 23]},
        }
        monitor.controller.accept(value, monitor.clock_ms)
        monitor.update(0)
        return module, monitor, hardware

    @staticmethod
    def advance(module, monitor, milliseconds, refresh=True):
        module.time.now += milliseconds
        if refresh:
            # Simulate successful unchanged polls without aging call/presence data.
            monitor.controller.accept(copy.deepcopy(monitor.controller.payload), monitor.clock_ms + milliseconds)
        monitor.update(milliseconds)

    @staticmethod
    def draw(monitor):
        canvas = support.RecordingCanvas()
        monitor.draw(canvas)
        return canvas.records

    def enter_idle(self, module, monitor):
        self.advance(module, monitor, 60000)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
        self.assertEqual(monitor.idle_pages.page(monitor.clock_ms), "weather")

    def test_quiet_delay_rotates_weather_rain_clock_and_sky_while_polls_stay_fresh(self):
        module, monitor, unused = self.monitor()
        self.advance(module, monitor, 59999)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        self.advance(module, monitor, 1)
        local = monitor._local_weather_time(monitor.controller.payload["weather"], 0)
        expected = (("weather", "9 C", 40), ("rain", "Rain likely", 25),
                    ("clock", "%02d:%02d" % (local[3], local[4]), 45),
                    ("moon", "MOON", 28), ("meteors", "METEORS", 18))
        for index, (page, text, minimum_size) in enumerate(expected):
            if index:
                self.advance(module, monitor, 12000)
            self.assertEqual(monitor.idle_pages.page(monitor.clock_ms), page)
            records = self.draw(monitor)
            self.assertIn(text, [record["text"] for record in records])
            self.assertGreaterEqual(max(record["size"] for record in records), minimum_size)
        self.advance(module, monitor, 12000)
        self.assertEqual(monitor.idle_pages.page(monitor.clock_ms), "weather")

    def test_manual_left_right_browse_idle_without_selecting_team_or_dialing(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        selected = monitor.controller.selected
        with patch.object(module, "post_json") as post:
            for key, expected in (("RIGHT", "rain"), ("LEFT", "weather"), ("LEFT", "meteors"), ("RIGHT", "weather")):
                monitor.expansions.keys = [key]
                self.advance(module, monitor, 400)
                self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))
                self.assertEqual(monitor.idle_pages.page(monitor.clock_ms), expected)
                self.assertEqual(monitor.controller.selected, selected)
                self.assertFalse(monitor.controller.detail_view)
                self.assertFalse(monitor.controls.is_busy)
            post.assert_not_called()

    def test_page_animation_draws_one_destination_and_finishes_after_a_skipped_frame(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.draw(AnimationCanvas())
        monitor.expansions.keys = ["RIGHT"]
        self.advance(module, monitor, 400)
        first = AnimationCanvas()
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            monitor.draw(first)
            self.assertEqual(face.call_count, 1)
            self.assertEqual(face.call_args.args[1], "rain")
        self.assertEqual(len(first.scales), 1)
        self.assertGreaterEqual(first.scales[0][0], 0.9)
        self.assertLess(first.scales[0][0], 1)
        self.advance(module, monitor, 120, refresh=False)
        middle = AnimationCanvas()
        monitor.draw(middle)
        self.assertGreater(middle.scales[0][0], first.scales[0][0])
        self.assertLess(middle.scales[0][0], 1)
        self.advance(module, monitor, 130, refresh=False)
        finished = AnimationCanvas()
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            monitor.draw(finished)
            self.assertEqual(face.call_count, 1)
        self.assertEqual(finished.scales, [])
        # A later skipped frame must not replay any animation steps.
        self.advance(module, monitor, 1000, refresh=False)
        after_gap = AnimationCanvas()
        monitor.draw(after_gap)
        self.assertEqual(after_gap.scales, [])

    def test_forecast_scenes_use_supported_native_ctx_apis_for_every_condition_family(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        for code in (0, 1, 3, 45, 61, 65, 71, 95, None):
            for is_day in (True, False):
                with self.subTest(page="weather", code=code, is_day=is_day):
                    monitor.controller.payload["weather"]["current"].update(weather_code=code, is_day=is_day)
                    canvas = NativeApiCanvas()
                    monitor.draw(canvas)
                    self.assertIn("9 C", [record["text"] for record in canvas.records])
        monitor.idle_pages.next(1, monitor.clock_ms)
        for status in ("rain_likely", "dry_likely", "unknown"):
            with self.subTest(page="rain", status=status):
                monitor.controller.payload["weather"]["rain_next_hour"]["status"] = status
                monitor.draw(NativeApiCanvas())
        monitor.idle_pages.next(1, monitor.clock_ms)
        monitor.draw(NativeApiCanvas())
        monitor.controller.payload["weather"].update(now_unix=None, local_clock=None)
        monitor.draw(NativeApiCanvas())

    def test_clock_second_zero_is_at_twelve_and_unknown_time_has_no_position_marker(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.idle_pages.next(1, monitor.clock_ms)
        monitor.idle_pages.next(1, monitor.clock_ms)
        weather = monitor.controller.payload["weather"]
        weather.update(now_unix=int(datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc).timestamp()),
                       utc_offset_seconds=0)
        canvas = NativeApiCanvas()
        monitor.draw(canvas)
        markers = [arc for arc in canvas.arcs if math.hypot(arc[0], arc[1]) >= 100 and 3.5 < arc[2] < 8]
        self.assertEqual(len(markers), 1)
        self.assertAlmostEqual(markers[0][0], 0, delta=1)
        self.assertLess(markers[0][1], -100)
        weather.update(now_unix=None, local_clock=None, local_date=None)
        unknown = NativeApiCanvas()
        monitor.draw(unknown)
        markers = [arc for arc in unknown.arcs if math.hypot(arc[0], arc[1]) >= 100 and 3.5 < arc[2] < 8]
        self.assertEqual(markers, [])
        texts = [record["text"] for record in unknown.records]
        self.assertIn("--:--", texts)
        self.assertIn("--", texts)

    def test_unknown_weather_condition_keeps_valid_temperature_and_marks_missing_condition(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.controller.payload["weather"]["current"].update(weather_code=None, condition="Unknown")
        canvas = NativeApiCanvas()
        monitor.draw(canvas)
        texts = [record["text"] for record in canvas.records]
        self.assertIn("?", texts)
        self.assertIn("9 C", texts)
        self.assertIn("Unknown", texts)

    def test_incoming_call_cancels_mid_transition_in_same_draw_and_keeps_all_number_digits(self):
        class WideNumberCanvas(AnimationCanvas):
            def text_width(self, value):
                numeric = all(character in "+0123456789" for character in str(value))
                return len(str(value)) * self.font_size * (1.1 if numeric else 0.5)
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.draw(AnimationCanvas())
        monitor.expansions.keys = ["RIGHT"]
        self.advance(module, monitor, 400)
        monitor.draw(AnimationCanvas())
        number = "+441632960123"
        incoming = {"id": "interrupt", "state": "ringing", "direction": "inbound", "kind": "external",
                    "peer_name": "Unknown caller", "peer_initials": "", "peer_number": number, "priority": True}
        value = copy.deepcopy(monitor.controller.payload)
        value["alert"] = incoming
        value["own"].update(state="ringing", calls=[incoming])
        monitor.controller.accept(value, monitor.clock_ms)
        canvas = WideNumberCanvas()
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            monitor.draw(canvas)
            face.assert_not_called()
        self.assertEqual(canvas.scales, [])
        number_lines = [record for record in canvas.records if record["text"] and
                        all(character in "+0123456789" for character in record["text"])]
        self.assertEqual("".join(record["text"] for record in number_lines), number)
        self.assertTrue(all(record["size"] >= 22 for record in number_lines))
        self.assertIn("PRIORITY", [record["text"] for record in canvas.records])

    def test_settings_and_source_outage_cancel_active_page_animation_without_scaling_content(self):
        for interrupt, expected in (("settings", "SETTINGS"), ("offline", "OFFLINE")):
            with self.subTest(interrupt=interrupt):
                module, monitor, unused = self.monitor()
                self.enter_idle(module, monitor)
                initial = AnimationCanvas()
                monitor.draw(initial)
                self.assertTrue(initial.scales)
                if interrupt == "settings":
                    monitor.settings_open = True
                else:
                    monitor.controller.payload["connected"] = False
                canvas = AnimationCanvas()
                with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
                    monitor.draw(canvas)
                    face.assert_not_called()
                self.assertEqual(canvas.scales, [])
                self.assertIn(expected, [record["text"] for record in canvas.records])

    def test_space_wakes_to_overview_and_requires_another_quiet_minute(self):
        module, monitor, unused = self.monitor()
        monitor.controller.own_view = True
        monitor.controller.detail_view = True
        self.enter_idle(module, monitor)
        monitor.expansions.keys = ["SPACE"]
        self.advance(module, monitor, 400)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        self.assertFalse(monitor.controller.own_view)
        self.assertFalse(monitor.controller.detail_view)
        self.advance(module, monitor, 59999)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        self.advance(module, monitor, 1)
        self.assertTrue(monitor.idle_pages.active(monitor.clock_ms))

    def test_settings_wake_keeps_two_brightness_rows_and_pauses_idle_timer(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.expansions.keys = ["S"]
        self.advance(module, monitor, 400)
        self.assertTrue(monitor.settings_open)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        texts = [record["text"] for record in self.draw(monitor)]
        self.assertIn("RING", texts)
        self.assertIn("EEH", texts)
        self.assertNotIn("IDLE", texts)
        self.advance(module, monitor, 90000)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        monitor.expansions.keys = ["ENTER"]
        self.advance(module, monitor, 400)
        self.assertFalse(monitor.settings_open)
        self.advance(module, monitor, 59999)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))

    def test_legacy_idle_wake_uses_new_explicit_speed_dial_mappings(self):
        for key,target in (('F','tb'),('B','pd'),('E','jh'),('C','sm'),('D','kz')):
            with self.subTest(key=key):
                module,monitor,unused=self.monitor()
                self.enter_idle(module,monitor)
                with patch.object(module,'post_json') as post:
                    monitor.buttons.values.add(key);self.advance(module,monitor,400)
                    self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
                    self.assertEqual(monitor.controls.pending['target'],target)
                    post.assert_not_called()

    def test_up_down_wake_and_adjust_only_eeh_without_phone_intent(self):
        for key, direction in (("UP", 1), ("DOWN", -1)):
            with self.subTest(key=key):
                module, monitor, unused = self.monitor()
                self.enter_idle(module, monitor)
                old_eeh, old_ring = monitor.controller.eeh_brightness, monitor.controller.ring_brightness
                monitor.expansions.keys = [key]
                self.advance(module, monitor, 400)
                self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
                self.assertAlmostEqual(monitor.controller.eeh_brightness, old_eeh + direction * 0.01)
                self.assertEqual(monitor.controller.ring_brightness, old_ring)
                self.assertFalse(monitor.controls.is_busy)

    def test_stable_answered_teammate_can_idle_but_peer_change_immediately_wakes(self):
        module, monitor, hardware = self.monitor()
        teammate = monitor.controller.payload["team"][0]
        teammate.update(state="busy", calls=[{"id": "team1", "state": "connected", "kind": "internal",
                                              "peer_extension": "245", "peer_first_name": "Alice"}])
        monitor.update(0)
        self.enter_idle(module, monitor)
        self.assertEqual(hardware.leds[10:13], [(34, 1, 1)] * 3)
        teammate = monitor.controller.payload["team"][0]
        teammate["calls"][0].update(peer_extension="271", peer_first_name="Bob")
        self.advance(module, monitor, 100)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        self.assertIn("271", [record["text"] for record in self.draw(monitor)])

    def test_incoming_own_call_overrides_idle_and_brightness_notice_with_full_caller_id(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        incoming = {"id": "own-ring", "state": "ringing", "direction": "inbound", "kind": "external",
                    "peer_name": "Alice Smith", "peer_number": "+441632960123", "priority": False}
        value = monitor.controller.payload
        value["alert"] = incoming
        value["own"].update(state="ringing", calls=[incoming])
        monitor._brightness_notice_until = monitor.clock_ms + 2000
        self.advance(module, monitor, 100)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            texts = [record["text"] for record in self.draw(monitor)]
            face.assert_not_called()
        self.assertNotIn("+441632960123", texts)
        self.assertIn("Alice Smith", texts)
        self.assertNotIn("Overcast", texts)
        self.assertNotIn("EEH", texts)

    def test_new_team_ringing_call_interrupts_weather_and_own_answered_call_keeps_it_blocked(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        teammate = monitor.controller.payload["team"][0]
        teammate.update(state="ringing", calls=[{"id": "team-ring", "state": "ringing", "kind": "internal", "peer_extension": "245"}])
        self.advance(module, monitor, 100)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        teammate = monitor.controller.payload["team"][0]
        teammate.update(state="idle", calls=[])
        monitor.controller.payload["own"].update(state="busy", calls=[{"id": "own1", "state": "connected"}])
        self.advance(module, monitor, 60000)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))

    def test_stale_pbx_immediately_removes_weather_and_shows_offline(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        self.advance(module, monitor, 5000, refresh=False)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            texts = [record["text"] for record in self.draw(monitor)]
            face.assert_not_called()
        self.assertIn("OFFLINE", texts)
        self.assertNotIn("Overcast", texts)

    def test_stale_weather_never_reuses_dry_or_temperature_values_while_pbx_is_live(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        monitor.controller.payload["weather"].update(age_seconds=1801)
        monitor.controller.payload["weather"]["rain_next_hour"].update(status="dry_likely", precipitation_mm=0)
        records = self.draw(monitor)
        texts = [record["text"] for record in records]
        self.assertIn("-- C", texts)
        self.assertNotIn("9 C", texts)
        monitor.idle_pages.next(1, monitor.clock_ms)
        texts = [record["text"] for record in self.draw(monitor)]
        self.assertIn("Unavailable", texts)
        self.assertNotIn("Rain likely", texts)
        self.assertNotIn("Dry likely", texts)

    def test_malformed_weather_sections_show_unknown_instead_of_crashing_the_display(self):
        for malformed in ("unexpected", ["unexpected"]):
            with self.subTest(section="weather", value=malformed):
                module, monitor, unused = self.monitor()
                self.enter_idle(module, monitor)
                monitor.controller.payload["weather"] = malformed
                texts = [record["text"] for record in self.draw(monitor)]
                self.assertIn("-- C", texts)
                self.assertIn("Unavailable", texts)
            with self.subTest(section="current", value=malformed):
                module, monitor, unused = self.monitor()
                self.enter_idle(module, monitor)
                monitor.controller.payload["weather"]["current"] = malformed
                texts = [record["text"] for record in self.draw(monitor)]
                self.assertIn("-- C", texts)
                self.assertIn("Unavailable", texts)
            with self.subTest(section="rain_next_hour", value=malformed):
                module, monitor, unused = self.monitor()
                self.enter_idle(module, monitor)
                monitor.controller.payload["weather"]["rain_next_hour"] = malformed
                monitor.idle_pages.next(1, monitor.clock_ms)
                texts = [record["text"] for record in self.draw(monitor)]
                self.assertIn("Unavailable", texts)
                self.assertNotIn("Dry likely", texts)

    def test_weather_freshness_counts_local_elapsed_without_mutating_the_snapshot(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        raw_weather = monitor.controller.payload["weather"]
        raw_weather["age_seconds"] = 1799.9
        self.assertIn("9 C", [record["text"] for record in self.draw(monitor)])
        self.advance(module, monitor, 200, refresh=False)
        self.assertTrue(monitor.controller.live(monitor.clock_ms))
        self.assertIn("-- C", [record["text"] for record in self.draw(monitor)])
        self.assertEqual(raw_weather["age_seconds"], 1799.9)

    def test_background_snapshot_call_change_interrupts_idle_in_draw_before_update(self):
        module, monitor, unused = self.monitor()
        self.enter_idle(module, monitor)
        value = copy.deepcopy(monitor.controller.payload)
        value["team"][0].update(state="ringing", calls=[{"id": "new-ring", "state": "ringing", "kind": "internal", "peer_extension": "245"}])
        monitor.controller.accept(value, monitor.clock_ms)
        with patch.object(module, "draw_idle_face", wraps=module.draw_idle_face) as face:
            texts = [record["text"] for record in self.draw(monitor)]
            face.assert_not_called()
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        self.assertIn("245", texts)
        self.assertNotIn("Overcast", texts)

    def test_native_micropython_2000_epoch_and_desktop_1970_epoch_render_same_clock(self):
        module, monitor, unused = self.monitor()
        stamp = int(datetime(2026, 7, 1, 12, 7, tzinfo=timezone.utc).timestamp())
        weather = {"now_unix": stamp, "utc_offset_seconds": 3600}
        desktop = monitor._local_weather_time(weather, 61000)
        calls = []
        def native_gmtime(seconds):
            calls.append(seconds)
            return desktop_time.gmtime(seconds + 946684800)
        module.time.gmtime = native_gmtime
        native = monitor._local_weather_time(weather, 61000)
        self.assertEqual(native, desktop)
        self.assertEqual(native[:5], (2026, 7, 1, 13, 8))
        self.assertEqual(calls, [0, stamp + 3600 + 61 - 946684800])

    def test_invalid_clock_values_are_unknown_instead_of_raising_from_native_gmtime(self):
        module, monitor, unused = self.monitor()
        valid = {"now_unix": 1794398820, "utc_offset_seconds": 0}
        for key, values in (("now_unix", (None, True, "1794398820", math.nan, math.inf, -math.inf, 0, 999999999999)),
                            ("utc_offset_seconds", (None, True, "0", math.nan, math.inf, -math.inf, 86400, -86400))):
            for value in values:
                with self.subTest(key=key, value=value):
                    weather = dict(valid, **{key: value})
                    self.assertIsNone(monitor._local_weather_time(weather, 0))
        for value in (None, "unexpected", ["unexpected"]):
            self.assertIsNone(monitor._local_weather_time(value, 0))
        with patch.object(module.time, "gmtime", side_effect=[desktop_time.gmtime(0), OverflowError("unrepresentable native date")]):
            self.assertIsNone(monitor._local_weather_time(valid, 0))


if __name__ == "__main__":
    unittest.main()
