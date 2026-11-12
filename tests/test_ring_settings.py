"""Adjustable ring lighting remains independent of EEH and live priority calls."""
import copy
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "badge/controller.py"
spec = importlib.util.spec_from_file_location("ring_settings_controller", PATH)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def snapshot():
    return {"version": 1, "connected": True, "age_seconds": 0, "alert": None,
            "team": [{"state": state, "calls": []} for state in ("idle", "busy", "ringing", "unknown")],
            "own": {"state": "idle", "calls": []}}


class RingSettingsTests(unittest.TestCase):
    def test_ring_defaults_to_fifteen_percent_separately_from_three_percent_eeh(self):
        value = controller.Controller()
        self.assertEqual(value.ring_brightness, 0.15)
        self.assertEqual(value.eeh_brightness, 0.03)
        value.accept(snapshot(), 0)
        self.assertEqual(value.led_frame(0), [(0, 21, 3)] * 3 + [(34, 1, 1)] * 3
                         + [(38, 23, 0)] * 3 + [(1, 1, 2)] * 3)

    def test_old_brightness_alias_still_only_changes_eeh(self):
        value = controller.Controller(brightness=0.25, ring_brightness=0.4)
        value.accept(snapshot(), 0)
        frame = value.led_frame(0)
        value.brightness = 0.9
        value.adjust_brightness(-1)
        self.assertEqual(value.eeh_brightness, 0.89)
        self.assertEqual(value.ring_brightness, 0.4)
        self.assertEqual(value.led_frame(0), frame)

    def test_ring_adjustment_has_one_percent_steps_and_never_changes_eeh(self):
        value = controller.Controller()
        self.assertEqual(value.adjust_ring_brightness(1), 0.16)
        self.assertEqual(value.adjust_ring_brightness(-1), 0.15)
        for _ in range(120):
            value.adjust_ring_brightness(-1)
        self.assertEqual(value.ring_brightness, 0)
        for _ in range(120):
            value.adjust_ring_brightness(1)
        self.assertEqual(value.ring_brightness, 1)
        self.assertEqual(value.eeh_brightness, 0.03)

    def test_ring_clamps_and_rejects_nan_as_a_saved_level(self):
        for supplied, expected in ((-0.5, 0), (3, 1), (float("nan"), 0.15)):
            self.assertEqual(controller.Controller(ring_brightness=supplied).ring_brightness, expected)

    def test_ring_off_and_full_settings_scale_palette_exactly_once(self):
        value = controller.Controller(ring_brightness=0)
        value.accept(snapshot(), 0)
        self.assertEqual(value.led_frame(0), [(0, 0, 0)] * 12)
        value.ring_brightness = 1
        full = value.led_frame(0)
        value.ring_brightness = 0.5
        self.assertEqual(value.led_frame(0), [tuple(int(c * 0.5) for c in colour) for colour in full])

    def test_normal_incoming_ring_uses_the_chosen_ring_level_and_keeps_its_off_phase(self):
        value = controller.Controller(ring_brightness=0.2)
        payload = snapshot()
        payload["alert"] = {"state": "ringing", "direction": "inbound", "kind": "queue", "priority": False}
        value.accept(payload, 0)
        self.assertEqual(value.led_frame(0), [(0, 46, 51)] * 12)
        self.assertEqual(value.led_frame(350), [(0, 0, 0)] * 12)

    def test_own_priority_incoming_call_uses_full_double_pulse_even_with_ring_off(self):
        payload = snapshot()
        call = {"state": "ringing", "direction": "inbound", "priority": True, "kind": "external"}
        payload["alert"] = call
        payload["own"]["calls"] = [call]
        value = controller.Controller(ring_brightness=0)
        value.accept(payload, 0)
        for now, colour in ((0, (255, 0, 200)), (200, (0, 0, 0)),
                            (300, (255, 0, 200)), (500, (0, 0, 0))):
            self.assertEqual(value.led_frame(now), [colour] * 12)
        self.assertEqual(value.ring_brightness, 0)

    def test_priority_override_lasts_for_active_call_then_restores_latest_setting(self):
        payload = snapshot()
        value = controller.Controller(ring_brightness=0.15)
        value.accept(payload, 0)
        normal = value.led_frame(0)
        for status in ("dialing", "connected", "hold", "held", "busy"):
            payload["own"]["calls"] = [{"state": status, "priority": True}]
            self.assertEqual(value.led_frame(0)[0], (0, 145, 25))
            self.assertEqual(value.ring_brightness, 0.15)
        value.ring_brightness = 0.25
        payload["own"]["calls"] = []
        self.assertEqual(value.led_frame(0)[0], (0, 36, 6))
        self.assertNotEqual(value.led_frame(0), normal)
        self.assertEqual(value.ring_brightness, 0.25)

    def test_stale_or_disconnected_priority_call_never_keeps_full_override(self):
        for connected, now in ((False, 0), (True, 5000)):
            value = controller.Controller(ring_brightness=0.15)
            payload = snapshot()
            payload["connected"] = connected
            payload["own"]["calls"] = [{"state": "connected", "priority": True}]
            value.accept(payload, 0)
            self.assertEqual(value.led_frame(now), [(1, 1, 2)] * 12)

    def test_teammate_priority_and_finished_own_calls_do_not_trigger_full_override(self):
        payload = snapshot()
        payload["team"][0]["calls"] = [{"state": "connected", "priority": True}]
        value = controller.Controller(ring_brightness=0.15)
        value.accept(payload, 0)
        for own_calls in ([], [{"state": "ended", "priority": True}], [{"state": "connected", "priority": False}]):
            payload["own"]["calls"] = own_calls
            self.assertEqual(value.led_frame(0)[0], (0, 21, 3))

    def test_ring_preference_can_be_reloaded_without_mutating_snapshot(self):
        payload = snapshot()
        before = copy.deepcopy(payload)
        value = controller.Controller(ring_brightness=0.32)
        value.accept(payload, 0)
        restarted = controller.Controller(ring_brightness=value.ring_brightness)
        restarted.accept(payload, 0)
        self.assertEqual(restarted.led_frame(0), value.led_frame(0))
        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
