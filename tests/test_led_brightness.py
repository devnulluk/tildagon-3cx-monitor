"""Keep the two independently adjustable LED groups and priority override separate."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest


BADGE = Path(__file__).resolve().parents[1] / "badge"
PACKAGE = "led_brightness_test_package"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(BADGE)]
sys.modules[PACKAGE] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, BADGE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE + "." + name] = module
    spec.loader.exec_module(module)
    return module


controller = load("controller")
controls = load("controls")


def snapshot():
    return {"version": 1, "connected": True, "age_seconds": 0, "alert": None,
            "team": [{"state": state, "calls": []} for state in ("idle", "busy", "ringing", "unknown")],
            "own": {"state": "idle", "calls": [],
                    "presence": {"state": "available", "confirmed": True, "age_seconds": 0}}}


class BrightnessTests(unittest.TestCase):
    def test_eeh_defaults_to_three_percent_and_supports_compatibility_alias(self):
        value = controller.Controller()
        self.assertEqual(value.eeh_brightness, 0.03)
        self.assertEqual(value.brightness, 0.03)
        value.brightness = 0.07
        self.assertEqual(value.eeh_brightness, 0.07)
        value.eeh_brightness = 0.11
        self.assertEqual(value.brightness, 0.11)

    def test_eeh_supports_off_and_full_brightness_with_one_percent_steps(self):
        value = controller.Controller()
        self.assertEqual(value.adjust_brightness(1), 0.04)
        self.assertEqual(value.adjust_brightness(-1), 0.03)
        for _ in range(120):
            value.adjust_brightness(-1)
        self.assertEqual(value.eeh_brightness, 0)
        for _ in range(120):
            value.adjust_brightness(1)
        self.assertEqual(value.eeh_brightness, 1)

    def test_eeh_configuration_can_be_reloaded_without_affecting_outer_leds(self):
        original = controller.Controller(eeh_brightness=0.03)
        original.accept(snapshot(), 0)
        before = original.led_frame(0)
        original.adjust_brightness(1)
        restarted = controller.Controller(eeh_brightness=original.eeh_brightness)
        restarted.accept(snapshot(), 0)
        self.assertEqual(restarted.eeh_brightness, 0.04)
        self.assertEqual(restarted.led_frame(0), before)

    def test_eeh_clamps_to_zero_through_one(self):
        self.assertEqual(controller.Controller(eeh_brightness=-0.5).eeh_brightness, 0)
        self.assertEqual(controller.Controller(eeh_brightness=3).eeh_brightness, 1)
        self.assertEqual(controller.Controller(eeh_brightness=float("nan")).eeh_brightness, 0.03)

    def test_eeh_level_does_not_affect_ring_when_ring_is_set_to_full(self):
        expected = [(0, 145, 25)] * 3 + [(230, 10, 10)] * 3 + [(255, 155, 0)] * 3 + [(12, 12, 14)] * 3
        for level in (0, 0.03, 0.5, 1):
            with self.subTest(level=level):
                value = controller.Controller(eeh_brightness=level, ring_brightness=1)
                value.accept(snapshot(), 0)
                self.assertEqual(value.led_frame(0), expected)
                self.assertEqual(value.led_frame(350)[6:9], [(0, 0, 0)] * 3)
                self.assertEqual(value.led_frame(5000), [(12, 12, 14)] * 12)

    def test_outer_incoming_calls_and_priority_are_never_dimmed(self):
        value = controller.Controller(eeh_brightness=0, ring_brightness=1)
        payload = snapshot()
        payload["alert"] = {"state": "ringing", "direction": "inbound", "kind": "queue"}
        value.accept(payload, 0)
        self.assertEqual(value.led_frame(0), [(0, 230, 255)] * 12)
        payload["alert"]["priority"] = True
        for now, colour in ((0, (255, 0, 200)), (200, (0, 0, 0)),
                            (300, (255, 0, 200)), (500, (0, 0, 0))):
            self.assertEqual(value.led_frame(now), [colour] * 12)

    def test_eeh_priority_pulse_ignores_normal_level_and_restores_it_after_call(self):
        value = controller.Controller(eeh_brightness=0.03)
        payload = snapshot()
        normal = controls.own_colour(payload, True, 0, value.eeh_brightness)
        self.assertEqual(normal, (0, 4, 0))
        payload["own"]["calls"] = [{"state": "ringing", "direction": "inbound", "priority": True}]
        for level in (0, 0.03, 0.5, 1):
            for now, colour in ((0, (255, 0, 200)), (200, (0, 0, 0)),
                                (300, (255, 0, 200)), (500, (0, 0, 0))):
                self.assertEqual(controls.own_colour(payload, True, now, level), colour)
        for state in ("dialing", "connected", "busy", "hold", "held"):
            payload["own"]["calls"] = [{"state": state, "direction": "inbound", "priority": True}]
            self.assertEqual(controls.own_colour(payload, True, 700, value.eeh_brightness), (230, 10, 10))
        payload["own"]["calls"] = []
        self.assertEqual(value.eeh_brightness, 0.03)
        self.assertEqual(controls.own_colour(payload, True, 1000, value.eeh_brightness), normal)

    def test_eeh_priority_override_requires_live_own_active_call(self):
        payload = snapshot()
        payload["alert"] = {"priority": True, "state": "ringing", "direction": "inbound"}
        payload["team"][0]["calls"] = [payload["alert"]]
        self.assertEqual(controls.own_colour(payload, True, 0), (0, 4, 0))
        for state, direction in (("ringing", "outbound"), ("connected", "inbound"), ("hold", "inbound")):
            payload["own"]["calls"] = [{"state": state, "direction": direction, "priority": True}]
            self.assertEqual(controls.own_colour(payload, True, 0), (230, 10, 10))
        payload["own"]["calls"] = [{"state": "connected", "direction": "inbound", "priority": False}]
        self.assertEqual(controls.own_colour(payload, True, 0), (6, 0, 0))
        payload["own"]["calls"] = [{"state": "ringing", "direction": "inbound", "priority": True}]
        self.assertEqual(controls.own_colour(payload, False, 0), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
