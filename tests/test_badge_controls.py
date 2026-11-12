"""Input and user-intent checks without badge hardware or PBX access."""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import types
import unittest

BADGE = Path(__file__).resolve().parents[1] / "badge"
package_name = "badge_controls_test_package"
package = types.ModuleType(package_name)
package.__path__ = [str(BADGE)]
sys.modules[package_name] = package
spec = importlib.util.spec_from_file_location(package_name + ".controls", BADGE / "controls.py")
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


def state(presence="available"):
    return {"controls": {"enabled": True, "call": True, "dnd": True,
                         "session_id": "0123456789abcdef0123456789abcdef",
                         "targets": [{"id": target, "label": target} for target in ("TB", "PD", "JH", "SM", "KZ")]},
            "own": {"extension": "200", "state": "idle", "calls": [],
                    "presence": {"state": presence, "profile": presence,
                                 "confirmed": True, "age_seconds": 0.1}}}


class InitialsTests(unittest.TestCase):
    def test_existing_compact_initials_are_preserved(self):
        for name in ("TB", "PD", "JH", "SM", "KZ", "ABC"):
            self.assertEqual(controls.initials(name), name)

    def test_names_become_compact_initials(self):
        for name, expected in (("Sarah B", "SB"), ("Mark H", "MH"), ("Tim Brown", "TB"),
                               ("Partner", "P"), ("one two three four", "OTT"),
                               ("Anne-Marie Smith", "AMS")):
            self.assertEqual(controls.initials(name), expected)

    def test_missing_names_use_real_number_or_unknown_marker(self):
        self.assertEqual(controls.initials("", "223"), "223")
        self.assertEqual(controls.initials(None, "+441632960000"), "+441632960000")
        for name in (None, "", "WITHHELD", "Unknown caller", "anonymous"):
            self.assertEqual(controls.initials(name), "?")
        self.assertEqual(controls.initials("", "WITHHELD"), "?")


class PhysicalButtonTests(unittest.TestCase):
    def test_start_with_held_key_requires_release_and_new_press(self):
        buttons = controls.ControlButtons()
        self.assertEqual(buttons.physical_edges({"A"}, False, 0), [])
        self.assertEqual(buttons.physical_edges({"A"}, False, 1000), [])
        self.assertEqual(buttons.physical_edges(set(), False, 1100), [])
        self.assertEqual(buttons.physical_edges({"A"}, False, 1200), ["A"])

    def test_hold_and_bounce_never_repeat_action(self):
        buttons = controls.ControlButtons()
        buttons.physical_edges(set(), True, 0)
        self.assertEqual(buttons.physical_edges({"B"}, True, 100), ["B"])
        self.assertEqual(buttons.physical_edges({"B"}, True, 1000), [])
        buttons.physical_edges(set(), True, 1050)
        self.assertEqual(buttons.physical_edges({"B"}, True, 1100), ["B"])
        buttons.physical_edges(set(), True, 1150)
        self.assertEqual(buttons.physical_edges({"B"}, True, 1200), [])
        self.assertEqual(buttons.physical_edges({"B"}, True, 1800), [])
        buttons.physical_edges(set(), True, 1900)
        self.assertEqual(buttons.physical_edges({"B"}, True, 2000), ["B"])

    def test_simultaneous_chord_does_not_become_a_call_on_partial_release(self):
        buttons = controls.ControlButtons()
        buttons.physical_edges(set(), True, 0)
        self.assertEqual(buttons.physical_edges({"A", "B"}, True, 500), [])
        self.assertEqual(buttons.physical_edges({"B"}, True, 1000), [])
        buttons.physical_edges(set(), True, 1500)
        self.assertEqual(buttons.physical_edges({"B"}, True, 2000), ["B"])

    def test_keyboard_hotplug_releases_before_new_mapping_can_act(self):
        buttons = controls.ControlButtons()
        buttons.physical_edges(set(), False, 0)
        self.assertEqual(buttons.physical_edges({"C"}, False, 500), ["C"])
        self.assertEqual(buttons.physical_edges({"C"}, True, 1000), [])
        self.assertEqual(buttons.physical_edges({"C"}, True, 2000), [])
        buttons.physical_edges(set(), True, 2100)
        self.assertEqual(buttons.physical_edges({"C"}, True, 2200), ["C"])
        self.assertEqual(buttons.physical_edges({"C"}, False, 3000), [])

    def test_non_badge_button_names_never_trigger_physical_controls(self):
        buttons = controls.ControlButtons()
        buttons.physical_edges(set(), True, 0)
        self.assertEqual(buttons.physical_edges({"ENTER", "G", "LEFT"}, True, 1000), [])


class OwnColourTests(unittest.TestCase):
    def test_confirmed_presence_colours_scale_once(self):
        self.assertEqual(controls.own_colour(state("available"), True, 0), (0, 4, 0))
        self.assertEqual(controls.own_colour(state("dnd"), True, 0), (4, 0, 6))
        self.assertEqual(controls.own_colour(state("away"), True, 0), (7, 4, 0))
        self.assertEqual(controls.own_colour(state("available"), True, 0, brightness=1), (0, 145, 25))

    def test_stale_live_or_presence_state_cannot_show_available(self):
        unknown = controls.own_colour({}, False, 0)
        self.assertEqual(controls.own_colour(state(), False, 0), unknown)
        for age in (None, 5.01, math.inf, math.nan, -1, True):
            payload = state()
            payload["own"]["presence"]["age_seconds"] = age
            self.assertEqual(controls.own_colour(payload, True, 0), unknown)
        payload = state()
        payload["own"]["presence"]["confirmed"] = False
        self.assertEqual(controls.own_colour(payload, True, 0), unknown)

    def test_busy_call_overrides_dnd_presence(self):
        payload = state("dnd")
        payload["own"]["state"] = "busy"
        payload["own"]["calls"] = [{"state": "connected"}]
        self.assertEqual(controls.own_colour(payload, True, 0), (6, 0, 0))

    def test_incoming_kind_colour_and_priority_double_pulse(self):
        payload = state()
        call = {"state": "ringing", "direction": "inbound", "kind": "ddi", "priority": False}
        payload["own"]["calls"] = [call]
        self.assertEqual(controls.own_colour(payload, True, 0, 1), (35, 80, 255))
        self.assertEqual(controls.own_colour(payload, True, 350, 1), (0, 0, 0))
        call["priority"] = True
        for now, expected in ((0, (255, 0, 200)), (200, (0, 0, 0)), (300, (255, 0, 200)), (500, (0, 0, 0))):
            self.assertEqual(controls.own_colour(payload, True, now, 1), expected)

    def test_outgoing_ringback_is_busy_and_never_flashes_incoming_colour(self):
        payload = state()
        payload["own"]["calls"] = [{"state": "ringing", "direction": "outbound", "kind": "internal"}]
        self.assertEqual(controls.own_colour(payload, True, 0, 1), (230, 10, 10))
        self.assertEqual(controls.own_colour(payload, True, 350, 1), (230, 10, 10))


class ControlQueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = controls.ControlQueue("0123456789abcdef")
        self.payload = state()

    def test_only_allowlisted_id_is_queued_with_server_session_and_unique_intent(self):
        before = copy.deepcopy(self.payload)
        self.assertTrue(self.queue.queue_call(self.payload, True, "TB", 0))
        first = self.queue.take()
        self.assertEqual(first, {"action": "call", "target": "TB", "request_id": "0123456789abcdef-1",
                                 "session_id": self.payload["controls"]["session_id"]})
        self.queue.finish({"status": "accepted"}, 100)
        self.assertTrue(self.queue.queue_call(self.payload, True, "KZ", 4000))
        self.assertNotEqual(self.queue.take()["request_id"], first["request_id"])
        self.assertEqual(self.payload, before)

    def test_pending_and_inflight_intents_block_other_button_actions(self):
        self.assertTrue(self.queue.queue_call(self.payload, True, "TB", 0))
        self.assertTrue(self.queue.is_busy)
        self.assertFalse(self.queue.queue_call(self.payload, True, "PD", 100))
        self.queue.take()
        self.assertTrue(self.queue.is_busy)
        self.assertIsNone(self.queue.take())
        self.assertFalse(self.queue.queue_dnd(self.payload, True, 200))
        self.queue.finish({"status": "accepted"}, 300)
        self.assertFalse(self.queue.is_busy)

    def test_stale_disabled_and_unlisted_targets_cannot_queue_a_call(self):
        self.assertFalse(self.queue.queue_call(self.payload, False, "TB", 0))
        self.payload["controls"]["call"] = False
        self.assertFalse(self.queue.queue_call(self.payload, True, "TB", 1000))
        self.payload["controls"]["call"] = True
        for target in ("07700900123", "223", "ZZ", None):
            self.assertFalse(self.queue.queue_call(self.payload, True, target, 2000))
        self.assertIsNone(self.queue.take())

    def test_busy_unknown_or_ringing_own_extension_cannot_queue_a_call(self):
        for own_state, calls in (("busy", []), ("unknown", []), ("ringing", [{"state": "ringing"}]),
                                 ("idle", [{"state": "connected"}])):
            self.payload["own"]["state"] = own_state
            self.payload["own"]["calls"] = calls
            self.assertFalse(self.queue.queue_call(self.payload, True, "TB", 0))
        self.assertIsNone(self.queue.take())

    def test_dnd_sends_explicit_desired_state_only_from_confirmed_fresh_presence(self):
        self.assertTrue(self.queue.queue_dnd(self.payload, True, 0))
        intent = self.queue.take()
        self.assertIs(intent["enabled"], True)
        self.assertEqual(intent["action"], "dnd")
        self.queue.finish({"status": "confirmed"}, 100)
        self.payload["own"]["presence"]["state"] = "dnd"
        self.assertTrue(self.queue.queue_dnd(self.payload, True, 1000))
        self.assertIs(self.queue.take()["enabled"], False)

    def test_unknown_or_stale_dnd_presence_never_becomes_a_toggle(self):
        for confirmed, age, status in ((False, 0, "dnd"), (True, 6, "dnd"), (True, None, "available"),
                                       (True, 0, "unknown")):
            self.payload["own"]["presence"] = {"confirmed": confirmed, "age_seconds": age, "state": status}
            self.assertFalse(self.queue.queue_dnd(self.payload, True, 0))
            self.assertEqual(self.queue.message, "DND STATUS UNKNOWN")
        self.assertIsNone(self.queue.take())

    def test_failed_call_or_dnd_outcome_is_not_automatically_requeued(self):
        for action in ("call", "dnd"):
            queue = controls.ControlQueue("0123456789abcdef")
            if action == "call":
                queue.queue_call(self.payload, True, "TB", 0)
            else:
                queue.queue_dnd(self.payload, True, 0)
            queue.take()
            queue.fail_unknown(5000)
            self.assertFalse(queue.is_busy)
            self.assertIsNone(queue.take())
            self.assertEqual(queue.message, action.upper() + " STATUS UNKNOWN")
            self.assertEqual(queue.message_until, 13000)

    def test_dnd_result_does_not_optimistically_change_confirmed_payload(self):
        before = copy.deepcopy(self.payload)
        self.queue.queue_dnd(self.payload, True, 0)
        self.queue.take()
        self.queue.finish({"status": "confirmed"}, 100)
        self.assertEqual(self.queue.message, "DND ON")
        self.assertEqual(self.payload, before)
        self.assertEqual(controls.own_colour(self.payload, True, 100), (0, 4, 0))

    def test_server_error_text_is_not_used_as_untrusted_display_content(self):
        self.queue.queue_call(self.payload, True, "TB", 0)
        self.queue.take()
        self.queue.finish({"error": "unauthorized", "message": "raw private response"}, 100)
        self.assertEqual(self.queue.message, "CONTROL NOT AUTHORISED")
        self.assertFalse(self.queue.is_busy)
        self.assertIsNone(self.queue.take())

    def test_queued_intent_keeps_old_epoch_instead_of_replaying_after_restart(self):
        original_session = self.payload["controls"]["session_id"]
        self.queue.queue_call(self.payload, True, "TB", 0)
        self.payload["controls"]["session_id"] = "new-server-session"
        self.assertEqual(self.queue.take()["session_id"], original_session)
        self.queue.finish({"error": "stale_session"}, 100)
        self.assertEqual(self.queue.message, "REFRESH CONTROL STATE")
        self.assertIsNone(self.queue.take())


if __name__ == "__main__":
    unittest.main()
