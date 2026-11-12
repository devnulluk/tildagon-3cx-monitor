import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingCanvas:
    """Exercise actual draw helpers while recording visible text and sizes."""
    CENTER = 0
    MIDDLE = 0
    def __init__(self):
        self.records = []
        self.font_size = 12
        self.text_align = self.CENTER
        self.text_baseline = self.MIDDLE
        self.colour = (1, 1, 1)
        self.position = (0, 0)
        self.stack = []
    def save(self):
        self.stack.append((self.font_size, self.text_align, self.text_baseline, self.colour, self.position))
        return self
    def restore(self):
        self.font_size, self.text_align, self.text_baseline, self.colour, self.position = self.stack.pop()
        return self
    def rgb(self, *colour):
        self.colour = colour
        return self
    def move_to(self, x, y):
        self.position = (x, y)
        return self
    def text_width(self, value):
        return len(str(value)) * self.font_size * 0.5
    def text(self, value):
        self.records.append({"text": str(value), "size": self.font_size,
                             "x": self.position[0], "y": self.position[1], "colour": self.colour})
        return self
    def __getattr__(self, name):
        return lambda *args, **kwargs: self


badge = load("badge_controller", "badge/controller.py")
demo = load("badge_demo", "badge/demo.py")
http_client = load("badge_http_client", "badge/http_client.py")


class BadgeTests(unittest.TestCase):
    def setUp(self):
        self.controller = badge.Controller(brightness=0.5, ring_brightness=1)
        self.payload = demo.snapshot("team")
        self.payload["demo"] = False
        self.controller.accept(self.payload, 1000)

    def test_team_idle_busy_and_ringing_leds(self):
        frame = self.controller.led_frame(1200)
        self.assertEqual(frame[9], (0, 145, 25))
        self.assertEqual(frame[9:12], [(0, 145, 25)] * 3)
        self.assertEqual(frame[:3], [(230, 10, 10)] * 3)
        self.assertEqual(frame[6:9], [(255, 155, 0)] * 3)
        self.assertEqual(self.controller.led_frame(1500)[6:9], [(0, 0, 0)] * 3)

    def test_failure_does_not_refresh_snapshot_and_stale_is_unknown(self):
        self.controller.failed()
        self.assertTrue(self.controller.live(5999))
        self.assertFalse(self.controller.live(6000))
        self.assertEqual(set(self.controller.led_frame(6000)), {(12, 12, 14)})
        self.assertIsNone(self.controller.alert(6000))

    def test_source_age_counts_towards_staleness(self):
        self.payload["age_seconds"] = 4
        self.controller.accept(self.payload, 1000)
        self.assertTrue(self.controller.live(1999))
        self.assertFalse(self.controller.live(2000))

    def test_disconnected_bridge_immediately_clears_live_colours(self):
        self.payload["connected"] = False
        self.payload["status"] = "PBX DOWN"
        self.controller.accept(self.payload, 1200)
        self.assertFalse(self.controller.live(1200))
        self.assertEqual(self.controller.status(1200), "PBX DOWN")
        self.assertEqual(set(self.controller.led_frame(1200)), {(12, 12, 14)})

    def test_disconnected_initial_snapshot_can_have_no_source_age(self):
        self.payload["connected"] = False
        self.payload["age_seconds"] = None
        self.payload["status"] = "CONNECTING"
        self.controller.accept(self.payload, 1000)
        self.assertFalse(self.controller.live(1000))
        self.assertEqual(self.controller.status(1000), "CONNECTING")
        self.payload["connected"] = True
        with self.assertRaises(ValueError):
            self.controller.accept(self.payload, 1100)

    def test_each_call_type_has_a_distinct_ring_colour(self):
        colours = []
        for scene in ("ddi", "internal", "queue", "priority"):
            self.controller.accept(demo.snapshot(scene), 0)
            colours.append(self.controller.led_frame(0)[0])
            self.assertEqual(len(set(self.controller.led_frame(0))), 1)
        self.assertEqual(len(set(colours)), 4)

    def test_priority_double_pulse_and_stale_alert(self):
        self.controller.accept(demo.snapshot("priority"), 0)
        self.assertNotEqual(self.controller.led_frame(50)[0], (0, 0, 0))
        self.assertEqual(self.controller.led_frame(200)[0], (0, 0, 0))
        self.assertNotEqual(self.controller.led_frame(300)[0], (0, 0, 0))
        self.assertEqual(self.controller.led_frame(500)[0], (0, 0, 0))
        self.assertIsNone(self.controller.alert(5000))

    def test_outbound_or_answered_call_does_not_flash_whole_ring(self):
        payload = demo.snapshot("ddi")
        payload["alert"]["direction"] = "outbound"
        self.controller.accept(payload, 0)
        self.assertIsNone(self.controller.alert(0))
        payload["alert"]["direction"] = "inbound"
        payload["alert"]["state"] = "busy"
        self.controller.accept(payload, 0)
        self.assertIsNone(self.controller.alert(0))

    def test_more_than_twelve_team_members_have_separate_led_pages(self):
        self.payload["team"] = [
            {"extension": str(300 + index), "name": "Member " + str(index), "state": "idle", "calls": []}
            for index in range(14)
        ]
        self.controller.accept(self.payload, 1000)
        self.controller.selected = 11
        self.controller.select(1)
        self.assertEqual(self.controller.page(), 1)
        self.assertEqual(self.controller.page_count(), 2)
        self.assertEqual(len(self.controller.page_team()), 2)
        self.assertEqual(self.controller.focused()["extension"], "312")
        self.assertEqual(self.controller.led_range(0), (1, 6))
        self.assertEqual(self.controller.led_range(1), (7, 12))
        self.controller.select(2)
        self.assertEqual(self.controller.selected, 0)

    def test_four_members_each_own_three_adjacent_leds(self):
        self.assertEqual([self.controller.led_range(index) for index in range(4)], [(10, 12), (1, 3), (7, 9), (4, 6)])
        self.assertEqual([member["extension"] for member in self.controller.team()], ["223", "268", "214", "277"])

    def test_selecting_member_opens_detail_and_exits_own_view(self):
        self.controller.own_view = True
        self.controller.select(1)
        self.assertFalse(self.controller.own_view)
        self.assertTrue(self.controller.detail_view)
        self.assertEqual(self.controller.focused()["extension"], "268")

    def test_malformed_snapshot_cannot_make_stale_data_fresh(self):
        invalid = dict(self.payload)
        invalid["version"] = 2
        with self.assertRaises(ValueError):
            self.controller.accept(invalid, 6000)
        self.assertFalse(self.controller.live(6000))

    def test_empty_team_and_brightness_limits(self):
        self.payload["team"] = []
        self.controller.accept(self.payload, 1000)
        self.controller.select(1)
        self.assertEqual(self.controller.page_count(), 1)
        self.assertEqual(self.controller.focused(), {})
        self.assertEqual(self.controller.led_frame(1000), [(0, 0, 0)] * 12)
        for _ in range(150):
            self.controller.adjust_brightness(-1)
        self.assertEqual(self.controller.brightness, 0.0)
        for _ in range(150):
            self.controller.adjust_brightness(1)
        self.assertEqual(self.controller.brightness, 1.0)


def app_runtime():
    """Load the actual app against the documented badge API surface."""
    modules = {}
    def module(name, **values):
        obj = types.ModuleType(name)
        obj.__dict__.update(values)
        modules[name] = obj
        return obj
    class FakeApp:
        def __init__(self):
            self.overlays = []
        def terminate(self, restore_pattern=False):
            self.terminated = restore_pattern
    class Buttons:
        def __init__(self, owner):
            self.values = set()
            self.latched = set()
        def get(self, key):
            if key.startswith("PHYSICAL_"):
                return key in self.values or key[9:] in self.values
            aliases = {"UP": "A", "RIGHT": "B", "CONFIRM": "C", "DOWN": "D", "LEFT": "E", "CANCEL": "F"}
            return key in self.values or aliases.get(key) in self.values
        def pressed(self, key):
            down = self.get(key)
            if down and key not in self.latched:
                self.latched.add(key)
                return True
            if not down:
                self.latched.discard(key)
            return False
        def clear(self):
            self.values.clear()
            self.latched.clear()
    class ExpansionManager:
        def __init__(self, owner, config):
            self.backend = types.SimpleNamespace()
            self.keyboard_present = False
            self.keyboard_slots = []
            self.eeh_ready = True
            self.eeh_status = "EEH READY"
            self.keys = []
            self.colours = []
            self.closed = False
        def refresh(self, now_ms):
            pass
        def pop_keys(self):
            keys, self.keys = self.keys, []
            return keys
        def write_own_status(self, colour, **kwargs):
            self.colours.append(colour)
        def close(self):
            self.closed = True
            self.colours.append((0, 0, 0))
            self.keyboard_present = False
    class LEDs(list):
        def write(self):
            pass
    leds = LEDs([(1, 2, 3)] * 19)
    hw = types.SimpleNamespace(leds=leds, set_led_power=lambda value: None)
    module("app", App=FakeApp)
    module("app_components", clear_background=lambda ctx: None)
    module("events")
    module("events.input", Buttons=Buttons, BUTTON_TYPES={key: key for key in ("CANCEL", "CONFIRM", "RIGHT", "LEFT", "UP", "DOWN")})
    module("frontboards")
    module("frontboards.common", FRONTBOARD_BUTTON_TYPES={key: "PHYSICAL_" + key for key in "ABCDEF"})
    module("system")
    module("system.eventbus", eventbus=types.SimpleNamespace(emit=lambda event: None))
    module("system.patterndisplay")
    module("system.patterndisplay.events", PatternDisable=type("PatternDisable", (), {}))
    module("tildagonos", tildagonos=hw)
    fake_time = module("time", now=1000, ticks_diff=lambda current, previous: current - previous)
    fake_time.ticks_ms = lambda: fake_time.now
    package = module("badge_runtime")
    package.__path__ = [str(ROOT / "badge")]
    modules["badge_runtime.controller"] = badge
    modules["badge_runtime.demo"] = demo
    modules["badge_runtime.http_client"] = http_client
    module("badge_runtime.expansions", ExpansionManager=ExpansionManager)
    spec = importlib.util.spec_from_file_location("badge_runtime.app", ROOT / "badge/app.py")
    app_module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(app_module)
    # The generic UI fixture has no RTC or NTP hardware. Clock policy has its
    # own tests; networking tests start from a synchronized clock.
    app_module.clock_valid = lambda: True
    app_module.sync_clock = lambda: True
    return app_module, hw


class BadgeAppTests(unittest.TestCase):
    @staticmethod
    def live_monitor(keyboard=True, overview_on_demand=False):
        app_module, hw = app_runtime()
        config = dict(app_module.DEFAULT_CONFIG, demo=False, bridge_url="https://bridge.invalid",
                      token="read-token", control_token="different-control-token", overview_on_demand=overview_on_demand)
        with patch.object(app_module, "load_config", return_value=config):
            monitor = app_module.ThreeCXMonitor()
        payload = demo.snapshot("team")
        payload["demo"] = False
        payload["own"]["state"] = "idle"
        payload["own"]["presence"] = {"state": "available", "confirmed": True, "age_seconds": 0}
        payload["controls"] = {"enabled": True, "call": True, "dnd": True,
                               "session_id": "0123456789abcdef0123456789abcdef",
                               "targets": [{"id": key, "label": key.upper()}
                                           for key in ("tb", "pd", "jh", "sm", "kz")]}
        monitor.controller.accept(payload, 0)
        monitor.expansions.keyboard_present = keyboard
        monitor.update(0)
        return app_module, monitor, hw

    @staticmethod
    def press(app_module, monitor, key, elapsed=400):
        app_module.time.now += elapsed
        monitor.buttons.values.add(key)
        monitor.update(elapsed)

    @staticmethod
    def release(app_module, monitor, elapsed=50):
        app_module.time.now += elapsed
        monitor.buttons.values.clear()
        monitor.update(elapsed)

    def test_actual_app_defaults_to_explicit_demo_and_only_owns_outer_leds(self):
        app_module,hw=app_runtime()
        with patch('builtins.open',side_effect=OSError('No test configuration')):
            monitor=app_module.ThreeCXMonitor()
        self.assertTrue(monitor.demo_mode)
        monitor.update(50)
        self.assertEqual(hw.leds[0],(1,2,3))
        self.assertEqual(hw.leds[13:],[(1,2,3)]*6)
        monitor._open_menu();monitor.menu_selected=5;monitor._menu_key('ENTER')
        self.assertTrue(monitor.terminated)
        self.assertEqual(hw.leds[1:13],[(0,0,0)]*12)

    def test_menu_returns_to_overview_without_own_status_or_phone_action(self):
        module,monitor,unused=self.live_monitor(False)
        self.press(module,monitor,'A')
        self.assertTrue(monitor.menu_open)
        monitor.menu_selected=0;monitor._menu_key('ENTER')
        self.assertFalse(monitor.menu_open)
        self.assertFalse(monitor.controller.own_view)
        self.assertFalse(monitor.controller.detail_view)
        self.assertIsNone(monitor.controls.pending)

    def test_keyboard_mode_badge_buttons_map_to_team_and_keziah_without_network(self):
        for key, target in (("F", "tb"), ("B", "pd"), ("E", "jh"), ("C", "sm"), ("D", "kz")):
            with self.subTest(key=key):
                app_module, monitor, _ = self.live_monitor()
                with patch.object(app_module, "post_json") as post:
                    self.press(app_module, monitor, key)
                self.assertEqual(monitor.controls.pending["target"], target)
                self.assertEqual(monitor.controls.pending["action"], "call")
                self.assertFalse(monitor._stopping)
                self.assertEqual(monitor.controller.eeh_brightness, 0.03)
                post.assert_not_called()

    def test_keyboard_mode_f_queues_tb_and_does_not_exit(self):
        module,monitor,unused=self.live_monitor()
        self.press(module,monitor,'F')
        self.assertEqual(monitor.controls.pending['action'],'call')
        self.assertEqual(monitor.controls.pending['target'],'tb')
        self.assertFalse(monitor._stopping)

    def test_keyboard_arrows_navigate_without_dialling(self):
        app_module, monitor, _ = self.live_monitor()
        monitor.expansions.keys.append("RIGHT")
        monitor.update(0)
        self.assertEqual(monitor.controller.selected, 1)
        self.assertTrue(monitor.controller.detail_view)
        self.assertIsNone(monitor.controls.pending)
        self.assertFalse(monitor.controls.is_busy)

    def test_without_keyboard_badge_b_queues_pd(self):
        module,monitor,unused=self.live_monitor(False)
        self.press(module,monitor,'B')
        self.assertEqual(monitor.controls.pending['target'],'pd')
        self.assertFalse(monitor.controller.detail_view)

    def test_held_menu_button_cannot_dial_after_keyboard_hotplug(self):
        module,monitor,unused=self.live_monitor(False)
        self.press(module,monitor,'A')
        self.assertTrue(monitor.menu_open)
        monitor.expansions.keyboard_present=True
        module.time.now+=1000;monitor.update(1000)
        self.assertIsNone(monitor.controls.pending)
        self.release(module,monitor)
        self.press(module,monitor,'A')
        self.assertFalse(monitor.menu_open)
        self.release(module,monitor)
        self.press(module,monitor,'F')
        self.assertEqual(monitor.controls.pending['target'],'tb')

    def test_stop_clears_both_outer_leds_and_expansion_status(self):
        app_module, monitor, hw = self.live_monitor()
        monitor.expansions.keys.append("ESCAPE")
        monitor.update(0)
        self.assertTrue(monitor.expansions.closed)
        self.assertEqual(monitor.expansions.colours[-1], (0, 0, 0))
        self.assertEqual(hw.leds[1:13], [(0, 0, 0)] * 12)
        self.assertTrue(monitor.terminated)

    def test_demo_keyboard_override_cannot_enable_controls_in_live_mode(self):
        _, monitor, _ = self.live_monitor(keyboard=False)
        monitor.config["demo_keyboard"] = True
        self.assertFalse(monitor._keyboard_present())

    def test_presence_age_advances_locally_and_blocks_stale_dnd_without_mutating_snapshot(self):
        app_module, monitor, _ = self.live_monitor()
        original_presence = monitor.controller.payload["own"]["presence"]
        original_presence["age_seconds"] = 4.9
        app_module.time.now += 200
        monitor.update(200)
        # Call data is still recent; only the older presence evidence expired.
        self.assertTrue(monitor.controller.live(monitor.clock_ms))
        self.assertEqual(monitor.expansions.colours[-1], (0, 0, 0))
        effective = monitor._status_payload()["own"]["presence"]
        self.assertAlmostEqual(effective["age_seconds"], 5.1)
        self.assertFalse(effective["confirmed"])
        self.assertEqual(effective["state"], "unknown")
        self.assertTrue(original_presence["confirmed"])
        self.assertEqual(original_presence["state"], "available")
        self.assertEqual(original_presence["age_seconds"], 4.9)
        monitor._open_menu();monitor.menu_selected=1;monitor._menu_key('ENTER')
        self.assertIsNone(monitor.controls.pending)
        self.assertEqual(monitor.controls.message, "DND STATUS UNKNOWN")
        monitor.controller.own_view = True
        monitor._confirm()
        self.assertIsNone(monitor.controls.pending)
        self.assertEqual(monitor.controls.message, "DND STATUS UNKNOWN")

    def test_expired_presence_screen_header_agrees_with_unknown_expansion_colour(self):
        app_module, monitor, _ = self.live_monitor()
        monitor.controller.payload["own"]["presence"]["age_seconds"] = 4.9
        app_module.time.now += 200
        monitor.update(200)
        context = RecordingCanvas()
        monitor.draw(context)
        self.assertNotIn("MB", [record["text"] for record in context.records])
        self.assertEqual(monitor.expansions.colours[-1], (0, 0, 0))

    def test_idle_overview_uses_large_initials_in_two_by_two_grid_without_small_chrome(self):
        _, monitor, _ = self.live_monitor()
        for member in monitor.controller.payload["team"]:
            member.update(state="idle", calls=[])
        context = RecordingCanvas()
        monitor.draw(context)
        names = [record for record in context.records if record["text"] in ("TB", "PD", "JH", "SM")]
        self.assertEqual(len(names), 4)
        self.assertTrue(all(record["size"] >= 30 for record in names))
        self.assertEqual(len({record["x"] for record in names}), 4)
        self.assertEqual(len({record["y"] for record in names}), 2)
        self.assertTrue(all(record["colour"][1] > record["colour"][0] for record in names))
        texts = [record["text"] for record in context.records]
        for unwanted in ("BUSY", "IDLE", "RINGING", "223", "268", "214", "277", "3CX MONITOR"):
            self.assertNotIn(unwanted, texts)
        self.assertFalse(any("LED" in text or "A TB" in text or "LIGHT" in text for text in texts))
        self.assertNotIn("MB", [record["text"] for record in context.records])

    def test_internal_team_call_shows_large_extension_with_first_name_beneath(self):
        _, monitor, _ = self.live_monitor()
        call = {"peer_initials": "AS", "peer_number": "245", "peer_name": "Alice Smith",
                "peer_extension": "245", "peer_first_name": "Alice",
                "state": "connected", "kind": "internal", "priority": False}
        monitor.controller.payload["team"][1].update(state="busy", calls=[call])
        context = RecordingCanvas()
        monitor.draw(context)
        own = next(record for record in context.records if record["text"] == "PD")
        peer = next(record for record in context.records if record["text"] == "245")
        first_name = next(record for record in context.records if record["text"] == "Alice")
        self.assertGreaterEqual(own["size"], 18)
        self.assertLess(own["size"], 40)
        self.assertGreaterEqual(peer["size"], 20)
        self.assertGreaterEqual(first_name["size"], 10)
        self.assertLess(first_name["size"], peer["size"])
        self.assertGreater(first_name["y"], peer["y"])
        self.assertNotIn("AS", [record["text"] for record in context.records])
        self.assertTrue(own["colour"][0] > own["colour"][1])
        monitor.controller.selected = 1
        monitor.controller.detail_view = True
        selected = RecordingCanvas()
        monitor.draw(selected)
        extension = next(record for record in selected.records if record["text"] == "245")
        first_name = next(record for record in selected.records if record["text"] == "Alice")
        self.assertGreaterEqual(extension["size"], 42)
        self.assertGreater(first_name["y"], extension["y"])
        self.assertLess(first_name["size"], extension["size"])

    def test_long_internal_first_name_is_complete_by_shrinking_before_truncation(self):
        _, monitor, _ = self.live_monitor()
        call = {"peer_initials": "CS", "peer_number": "245", "peer_name": "Christopher Smith",
                "peer_extension": "245", "peer_first_name": "Christopher",
                "state": "connected", "kind": "internal", "priority": False}
        monitor.controller.payload["team"][1].update(state="busy", calls=[call])
        context = RecordingCanvas()
        monitor.draw(context)
        rendered = next(record for record in context.records if record["text"] == "Christopher")
        self.assertGreaterEqual(rendered["size"], 10)
        self.assertLess(rendered["size"], 20)
        monitor.controller.selected = 1
        monitor.controller.detail_view = True
        selected = RecordingCanvas()
        monitor.draw(selected)
        rendered = next(record for record in selected.records if record["text"] == "Christopher")
        self.assertGreaterEqual(rendered["size"], 18)

    def test_long_internal_first_name_shrinks_to_fit_without_losing_letters(self):
        _, monitor, _ = self.live_monitor()
        call = {"peer_number":"271", "peer_extension":"271", "peer_first_name":"Christopher",
                "kind":"internal", "state":"connected"}
        monitor.controller.payload["team"][1].update(state="busy", calls=[call])
        context = RecordingCanvas()
        monitor.draw(context)
        name = next(record for record in context.records if record["text"] == "Christopher")
        self.assertGreaterEqual(name["size"],10)
        self.assertLess(name["size"],20)

    def test_external_team_calls_show_only_external_without_customer_identity_or_number(self):
        for kind, name in (("external", ""), ("external", "Unknown caller"),
                           ("external", "Alice Smith"), ("ddi", "Alice Smith"), ("queue", "Alice Smith")):
            with self.subTest(kind=kind, name=name):
                _, monitor, _ = self.live_monitor()
                number = "+441632960123"
                call = {"peer_initials": "AS", "peer_name": name, "peer_number": number,
                        "peer_extension": "", "peer_first_name": "Alice",
                        "state": "connected", "kind": kind, "priority": False}
                monitor.controller.payload["team"][1].update(state="busy", calls=[call])
                context = RecordingCanvas()
                monitor.draw(context)
                external = next(record for record in context.records if record["text"] == "External")
                self.assertGreaterEqual(external["size"], 18)
                monitor.controller.selected = 1
                monitor.controller.detail_view = True
                selected = RecordingCanvas()
                monitor.draw(selected)
                self.assertIn("External", [record["text"] for record in selected.records])
                for rendered in (context, selected):
                    texts = [record["text"] for record in rendered.records]
                    for private in (number, "..60123", "AS", "Alice", "Alice Smith"):
                        self.assertNotIn(private, texts)
                    rendered_digits = ["".join(character for character in text if character.isdigit()) for text in texts]
                    self.assertFalse(any(len(digits) >= 5 and digits in number for digits in rendered_digits))

    def test_own_external_call_keeps_full_caller_id_while_team_external_calls_hide_it(self):
        class WideDigitsCanvas(RecordingCanvas):
            def text_width(self, value):
                factor = 1.1 if all(c in "+0123456789" for c in str(value)) else 0.5
                return len(str(value)) * self.font_size * factor
        _, monitor, _ = self.live_monitor()
        number = "+441632960123"
        call = {"peer_initials": "AS", "peer_name": "Alice Smith", "peer_number": number,
                "peer_extension": "", "peer_first_name": "Alice", "state": "connected",
                "kind": "external", "priority": False}
        monitor.controller.payload["own"].update(state="busy", calls=[call])
        monitor.controller.own_view = True
        own = WideDigitsCanvas()
        monitor.draw(own)
        lines = [record for record in own.records if record["text"] and record["x"] == 0
                 and all(character in "+0123456789" for character in record["text"])]
        self.assertEqual(lines, [])
        self.assertIn("Alice Smith", [record["text"] for record in own.records])

    def test_incoming_priority_call_stays_large_and_overrides_brightness_feedback(self):
        _, monitor, _ = self.live_monitor()
        call = {"peer_initials": "KZ", "peer_name": "Partner", "peer_number": "07700900123",
                "state": "ringing", "direction": "inbound", "kind": "external", "priority": True}
        monitor.controller.payload["own"].update(state="ringing", calls=[call])
        monitor.controller.payload["alert"] = call
        monitor._adjust_eeh_brightness(1)
        context = RecordingCanvas()
        monitor.draw(context)
        for text, minimum in (("Partner", 42), ("PRIORITY", 22), ("EXTERNAL", 18)):
            self.assertGreaterEqual(next(record["size"] for record in context.records if record["text"] == text), minimum)
        self.assertNotIn("EEH", [record["text"] for record in context.records])

    def test_arrow_brightness_changes_only_eeh_and_shows_a_large_percentage(self):
        app_module, monitor, hw = self.live_monitor()
        for member in monitor.controller.payload["team"]:
            member.update(state="idle", calls=[])
        monitor.update(0)
        outer = list(hw.leds[1:13])
        self.assertEqual(monitor.controller.eeh_brightness, 0.03)
        self.assertEqual(monitor.expansions.colours[-1], (0, 4, 0))
        app_module.time.now += 400
        monitor.expansions.keys.append("UP")
        monitor.update(400)
        self.assertEqual(monitor.controller.eeh_brightness, 0.04)
        self.assertEqual(hw.leds[1:13], outer)
        self.assertNotEqual(monitor.expansions.colours[-1], (0, 4, 0))
        context = RecordingCanvas()
        monitor.draw(context)
        self.assertGreaterEqual(next(record["size"] for record in context.records if record["text"] == "4%"), 48)
        app_module.time.now += 400
        monitor.expansions.keys.append("DOWN")
        monitor.update(400)
        self.assertEqual(monitor.controller.eeh_brightness, 0.03)
        self.assertEqual(hw.leds[1:13], outer)
        self.assertIsNone(monitor.controls.pending)

    def test_no_keyboard_brightness_buttons_leave_outer_blf_levels_unchanged(self):
        module,monitor,hw=self.live_monitor(False)
        for member in monitor.controller.payload['team']:member.update(state='idle',calls=[])
        monitor.update(0);before=list(hw.leds[1:13])
        monitor._open_menu();monitor.menu_selected=3;monitor._menu_key('ENTER')
        monitor.settings_selected=1
        monitor.update(0)
        self.press(module,monitor,'B')
        self.assertEqual(monitor.controller.eeh_brightness,.04)
        self.release(module,monitor);self.press(module,monitor,'E')
        self.assertEqual(monitor.controller.eeh_brightness,.03)
        self.assertEqual(hw.leds[1:13],before)
        self.assertIsNone(monitor.controls.pending)

    def test_offline_screen_and_outer_leds_do_not_keep_live_green_status(self):
        _, monitor, hw = self.live_monitor()
        monitor.controller.payload["connected"] = False
        monitor.update(0)
        self.assertEqual(hw.leds[1:13], [(1, 1, 2)] * 12)
        context = RecordingCanvas()
        monitor.draw(context)
        self.assertIn("OFFLINE", [record["text"] for record in context.records])
        self.assertNotIn("MB", [record["text"] for record in context.records])

    def test_control_result_notice_is_large_without_old_key_legends(self):
        _, monitor, _ = self.live_monitor()
        monitor.controls.message = "CALL REQUESTED"
        monitor.controls.message_until = 4000
        context = RecordingCanvas()
        monitor.draw(context)
        words = [record for record in context.records if record["text"] in ("CALL", "REQUESTED")]
        self.assertEqual(len(words), 2)
        self.assertTrue(all(record["size"] >= 22 for record in words))

    def test_live_eeh_setting_is_saved_after_debounce_and_restored_on_restart(self):
        stored = {}
        settings = types.ModuleType("settings")
        settings.get = lambda key, default=None: stored.get(key, default)
        settings.set = unittest.mock.Mock(side_effect=lambda key, value: stored.update({key: value}))
        settings.save = unittest.mock.Mock()
        with patch.dict(sys.modules, {"settings": settings}):
            app_module, monitor, _ = self.live_monitor()
            monitor.expansions.keys.append("UP")
            monitor.update(0)
            app_module.time.now += 300
            monitor.expansions.keys.append("UP")
            monitor.update(300)
            self.assertEqual(monitor.controller.eeh_brightness, 0.05)
            settings.save.assert_not_called()
            app_module.time.now += 900
            monitor.update(900)
            settings.save.assert_not_called()
            app_module.time.now += 101
            monitor.update(101)
            settings.save.assert_called_once()
            self.assertEqual(settings.set.call_args_list,
                             [unittest.mock.call("threecx_monitor.eeh_brightness", 0.05),
                              unittest.mock.call("threecx_monitor.ring_brightness", 0.15),
                      unittest.mock.call("threecx_monitor.matrix_call_brightness", 1.0)])
            _, restarted, _ = self.live_monitor()
            self.assertEqual(restarted.controller.eeh_brightness, 0.05)

    def test_stop_flushes_pending_eeh_setting_without_saving_credentials(self):
        settings = types.ModuleType("settings")
        settings.get = lambda key, default=None: default
        settings.set = unittest.mock.Mock()
        settings.save = unittest.mock.Mock()
        with patch.dict(sys.modules, {"settings": settings}):
            _, monitor, _ = self.live_monitor()
            monitor.expansions.keys.append("UP")
            monitor.update(0)
            monitor._stop()
        self.assertEqual(settings.set.call_args_list,
                         [unittest.mock.call("threecx_monitor.eeh_brightness", 0.04),
                          unittest.mock.call("threecx_monitor.ring_brightness", 0.15),
                      unittest.mock.call("threecx_monitor.matrix_call_brightness", 1.0)])
        settings.save.assert_called_once()

    def test_settings_keyboard_adjusts_ring_and_eeh_independently_without_phone_intents(self):
        app_module, monitor, _ = self.live_monitor()
        def key(name):
            app_module.time.now += 320
            monitor.expansions.keys.append(name)
            monitor.update(320)
        key("S")
        self.assertTrue(monitor.settings_open)
        self.assertEqual(monitor.settings_selected, 0)
        key("RIGHT")
        self.assertEqual(monitor.controller.ring_brightness, 0.16)
        self.assertEqual(monitor.controller.eeh_brightness, 0.03)
        key("DOWN")
        key("RIGHT")
        self.assertEqual(monitor.controller.eeh_brightness, 0.04)
        self.assertEqual(monitor.controller.ring_brightness, 0.16)
        key("LEFT")
        self.assertEqual(monitor.controller.eeh_brightness, 0.03)
        key("ESCAPE")
        self.assertFalse(monitor.settings_open)
        self.assertFalse(monitor._stopping)
        self.assertIsNone(monitor.controls.pending)

    def test_settings_capture_physical_dial_buttons_for_entire_opening_and_closing_frames(self):
        app_module, monitor, _ = self.live_monitor()
        app_module.time.now += 400
        monitor.buttons.values.add("A")
        monitor.expansions.keys.append("S")
        monitor.update(400)
        self.assertTrue(monitor.settings_open)
        self.assertIsNone(monitor.controls.pending)
        self.release(app_module, monitor)
        self.press(app_module, monitor, "B")
        self.assertEqual(monitor.controller.ring_brightness, 0.16)
        self.assertIsNone(monitor.controls.pending)
        self.release(app_module, monitor)
        self.press(app_module, monitor, "F")
        self.assertFalse(monitor.settings_open)
        self.assertFalse(monitor._stopping)
        self.assertIsNone(monitor.controls.pending)
        monitor.update(0)  # F remains held after closing; it must not become DND.
        self.assertIsNone(monitor.controls.pending)

    def test_without_keyboard_menu_opens_settings_and_held_close_never_calls(self):
        module,monitor,unused=self.live_monitor(False)
        self.press(module,monitor,'A');self.release(module,monitor)
        monitor.menu_selected=3
        self.press(module,monitor,'C');self.release(module,monitor)
        self.assertTrue(monitor.settings_open)
        self.assertIsNone(monitor.controls.pending)
        self.press(module,monitor,'F')
        self.assertFalse(monitor.settings_open)
        monitor.update(0)
        self.assertIsNone(monitor.controls.pending)

    def test_keyboard_hotplug_does_not_select_menu_with_held_button(self):
        module,monitor,unused=self.live_monitor(False)
        self.press(module,monitor,'A')
        monitor.expansions.keyboard_present=True
        module.time.now+=1100;monitor.update(1100)
        self.assertTrue(monitor.menu_open)
        self.assertFalse(monitor.settings_open)
        self.assertIsNone(monitor.controls.pending)

    def test_button_chord_does_not_call_until_released_and_pressed_again(self):
        module,monitor,unused=self.live_monitor(False)
        module.time.now+=400;monitor.buttons.values={'B','C'};monitor.update(400)
        self.assertIsNone(monitor.controls.pending)
        monitor.buttons.values={'B'};module.time.now+=400;monitor.update(400)
        self.assertIsNone(monitor.controls.pending)
        self.release(module,monitor)
        self.press(module,monitor,'C')
        self.assertEqual(monitor.controls.pending['target'],'sm')

    def test_settings_display_both_large_percentages_and_incoming_call_overrides_page(self):
        _, monitor, _ = self.live_monitor()
        monitor._open_settings()
        context = RecordingCanvas()
        monitor.draw(context)
        for text in ("RING", "EEH", "15%", "3%"):
            self.assertIn(text, [record["text"] for record in context.records])
        self.assertTrue(all(record["size"] >= 30 for record in context.records if record["text"] in ("15%", "3%")))
        call = {"state": "ringing", "direction": "inbound", "priority": True, "kind": "external",
                "peer_initials": "KZ", "peer_number": "07700900123"}
        monitor.controller.payload["own"]["calls"] = [call]
        monitor.controller.payload["alert"] = call
        incoming = RecordingCanvas()
        monitor.draw(incoming)
        self.assertIn("PRIORITY", [record["text"] for record in incoming.records])
        self.assertNotIn("SETTINGS", [record["text"] for record in incoming.records])

    def test_ring_setting_saves_and_restores_separately_from_eeh(self):
        stored = {}
        settings = types.ModuleType("settings")
        settings.get = lambda key, default=None: stored.get(key, default)
        settings.set = lambda key, value: stored.update({key: value})
        settings.save = unittest.mock.Mock()
        with patch.dict(sys.modules, {"settings": settings}):
            _, monitor, _ = self.live_monitor()
            monitor._open_settings()
            monitor._settings_key("RIGHT")
            monitor._settings_key("ENTER")
            self.assertEqual(stored, {"threecx_monitor.ring_brightness": 0.16,
                                      "threecx_monitor.eeh_brightness": 0.03,
                                  "threecx_monitor.matrix_call_brightness": 1.0})
            _, restarted, _ = self.live_monitor()
            self.assertEqual(restarted.controller.ring_brightness, 0.16)
            self.assertEqual(restarted.controller.eeh_brightness, 0.03)

    def test_complete_phone_number_wraps_under_wide_glyph_metrics_instead_of_truncating(self):
        class WideDigitsCanvas(RecordingCanvas):
            def text_width(self, value):
                factor = 1.1 if all(c in "+0123456789" for c in str(value)) else 0.5
                return len(str(value)) * self.font_size * factor
        _, monitor, _ = self.live_monitor()
        canonical = "+441632960123"
        formatted = "tel:+44 (1632) 960-123"
        context = WideDigitsCanvas()
        count = monitor._draw_number(context, formatted, size=34, width=206)
        self.assertEqual(count, 2)
        self.assertEqual("".join(record["text"] for record in context.records), canonical)
        self.assertTrue(all(record["size"] >= 22 for record in context.records))
        self.assertTrue(all(len(record["text"]) * record["size"] * 1.1 <= 206 for record in context.records))

    def test_unknown_incoming_number_keeps_all_digits_without_a_clipped_numeric_initials_row(self):
        _, monitor, _ = self.live_monitor()
        number = "+441632960123"
        call = {"state": "ringing", "direction": "inbound", "priority": False, "kind": "ddi",
                "peer_name": "Unknown caller", "peer_number": number, "ddi": "Example DDI"}
        monitor.controller.payload["alert"] = call
        monitor.controller.payload["own"]["calls"] = [call]
        context = RecordingCanvas()
        monitor.draw(context)
        lines = [record for record in context.records if record["text"] and record["x"] == 0
                 and all(c in "+0123456789" for c in record["text"])]
        self.assertEqual("".join(record["text"] for record in lines), number)
        self.assertTrue(all(record["size"] >= 26 for record in lines))

    def test_demo_does_not_read_or_overwrite_the_real_eeh_setting(self):
        settings = types.ModuleType("settings")
        settings.get = unittest.mock.Mock(return_value=0.99)
        settings.set = unittest.mock.Mock()
        settings.save = unittest.mock.Mock()
        with patch.dict(sys.modules, {"settings": settings}):
            app_module, _ = app_runtime()
            with patch.object(app_module, "load_config", return_value=dict(app_module.DEFAULT_CONFIG, demo=True)):
                monitor = app_module.ThreeCXMonitor()
            self.assertEqual(monitor.controller.eeh_brightness, 0.03)
            monitor.update(0)
            self.press(app_module, monitor, "A")
            monitor._stop()
        settings.get.assert_not_called()
        settings.set.assert_not_called()
        settings.save.assert_not_called()

    def test_send_control_selects_only_fixed_route_and_removes_action_from_json(self):
        app_module, _ = app_runtime()
        intent = {"action": "call", "target": "tb", "request_id": "0123456789abcdef-1",
                  "session_id": "0123456789abcdef0123456789abcdef"}
        with patch.object(app_module, "post_json", return_value={"status": "accepted"}) as post:
            self.assertEqual(app_module.send_control("https://bridge/", "control-token", intent, "ca.der"),
                             {"status": "accepted"})
        args, kwargs = post.call_args
        self.assertEqual(args[:2], ("https://bridge/v1/control/call", "control-token"))
        self.assertEqual(args[2], {key: value for key, value in intent.items() if key != "action"})
        self.assertEqual(kwargs["ca_file"], "ca.der")
        self.assertGreaterEqual(kwargs["timeout"], 8)
        self.assertLessEqual(kwargs["timeout"], 30)

    def test_fetch_delegates_to_verified_bounded_http_client(self):
        app_module, _ = app_runtime()
        with patch.object(app_module, "get_json", return_value={"ok": True}) as get:
            self.assertEqual(app_module.fetch_snapshot("https://bridge/", "secret-value", "test-root.der"), {"ok": True})
        get.assert_called_once_with("https://bridge/v1/state", "secret-value", ca_file="test-root.der", timeout=5)

    def test_verified_client_error_reaches_app_polling_handler(self):
        app_module, _ = app_runtime()
        with patch.object(app_module, "get_json", side_effect=http_client.TLSError("TLS / CLOCK / HOST ERROR")):
            with self.assertRaises(http_client.TLSError):
                app_module.fetch_snapshot("https://bridge", "bad-token")


class BadgeControlPollingTests(unittest.IsolatedAsyncioTestCase):
    async def poll_once(self, outcome):
        app_module, monitor, _ = BadgeAppTests.live_monitor()
        monitor._physical_control("F")
        value = monitor.controller.payload
        wifi = types.ModuleType("wifi")
        wifi.status = lambda: True
        helper = types.ModuleType("async_helpers")
        async def unblock(function, periodic, *args):
            return function(*args)
        helper.unblock = unblock
        async def no_sleep(delay):
            return None
        def read_snapshot(*args):
            monitor._stopping = True
            return value
        side_effect = outcome if isinstance(outcome, Exception) else None
        return_value = None if side_effect else outcome
        with patch.dict(sys.modules, {"wifi": wifi, "async_helpers": helper}), \
                patch.object(app_module, "asyncio", types.SimpleNamespace(sleep=no_sleep, create_task=__import__("asyncio").create_task, CancelledError=__import__("asyncio").CancelledError)), \
                patch.object(app_module, "send_control", side_effect=side_effect, return_value=return_value) as send, \
                patch.object(app_module, "fetch_snapshot", side_effect=read_snapshot):
            await monitor.background_task()
        return monitor, send

    async def test_deliberate_call_intent_is_sent_once_before_next_snapshot(self):
        monitor, send = await self.poll_once({"status": "accepted"})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[2]["target"], "tb")
        self.assertEqual(send.call_args.args[1], "different-control-token")
        self.assertEqual(monitor.controls.message, "CALL REQUESTED")
        self.assertFalse(monitor.controls.is_busy)

    async def test_lost_control_response_is_unknown_and_never_automatically_requeued(self):
        monitor, send = await self.poll_once(OSError("simulated lost response"))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(monitor.controls.message, "CALL STATUS UNKNOWN")
        self.assertFalse(monitor.controls.is_busy)
        self.assertIsNone(monitor.controls.take())


if __name__ == "__main__":
    unittest.main()
