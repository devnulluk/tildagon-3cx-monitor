"""Spaceagon gestures produce navigation only; no GPIO, PBX or live sensors."""
import importlib.util
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "space_inputs.py"
if not PATH.is_file():
    PATH = ROOT / "badge/space_inputs.py"
SPEC = importlib.util.spec_from_file_location("space_inputs_under_test", PATH)
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


def board():
    cls = type("TwentyTwentySix", (), {"__module__": "frontboards.twentysix", "year": 2026})
    value = cls()
    value.joystick_states = {key: [False, 0] for key in ("UP", "DOWN", "LEFT", "RIGHT", "FIRE")}
    value.touch_states = {"TOUCH%02d" % pad: [False, 0] for pad in range(1, 13)}
    return value


class Backend:
    def __init__(self):
        self.boards = [board()]
        self.sample = (0, 0, 9.81)
        self.reads = 0
    def frontboards(self):
        return self.boards
    def acceleration(self):
        self.reads += 1
        return self.sample


class Bus:
    def __init__(self):
        self.handlers = []
    def on(self, *values):
        self.handlers.append(values)
    def remove(self, *values):
        self.handlers.remove(values)


class InputTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.owner = types.SimpleNamespace(_focused=True)
        self.backend, self.bus = Backend(), Bus()
        self.events = (type("Down", (), {}), type("Up", (), {}))
    def helper(self, **config):
        return inputs.SpaceInputs(self.owner, config, self.backend, self.bus, self.events, lambda: self.now)
    def event(self, name, group="TwentyTwentySix"):
        return types.SimpleNamespace(button=types.SimpleNamespace(name=name, group=group))
    def down(self, helper, name, at=None, group="TwentyTwentySix"):
        if at is not None:
            self.now = at
        helper._down(self.event(name, group))
    def up(self, helper, name, at=None):
        if at is not None:
            self.now = at
        helper._up(self.event(name))
    def finish(self, helper, at):
        self.now = at
        helper.update()
        return helper.pop()

    def test_presence_comes_from_active_exact_frontboard_inventory_only(self):
        self.backend.boards = [types.SimpleNamespace(year=2026)]
        helper = self.helper()
        self.assertFalse(helper.present)
        self.down(helper, "JOYUP")
        self.assertEqual(helper.pop(), [])
        self.backend.boards = [board()]
        self.now = 1000
        helper.update()
        self.assertTrue(helper.present)

    def test_canonical_joystick_maps_to_navigation_once_per_physical_press(self):
        helper = self.helper()
        for name, action in (("JOYUP", "up"), ("JOYDOWN", "down"), ("JOYLEFT", "left"),
                             ("JOYRIGHT", "right"), ("JOYFIRE", "confirm")):
            self.down(helper, name)
            self.now += 250
            self.down(helper, name)
            self.assertEqual(helper.pop(), [{"kind": "joystick", "action": action}])
            self.up(helper, name)
            self.now += 100
        self.assertEqual(self.backend.reads, 0)

    def test_physical_system_keyboard_and_malformed_aliases_are_ignored(self):
        helper = self.helper()
        for name, group in [(key, "TwentyTwentySix") for key in "ABCDEF"] + [
                ("UP", "System"), ("CONFIRM", "System"), ("UP", "Joystick"), ("JOYUP", "Keyboard"),
                (None, "TwentyTwentySix"), ([], "TwentyTwentySix"), ("TOUCH99", "TwentyTwentySix")]:
            self.down(helper, name, group=group)
        self.assertEqual(helper.pop(), [])
        self.assertEqual(helper._held, set())

    def test_queue_never_exceeds_sixteen_and_never_emits_a_phone_action(self):
        helper = self.helper()
        for index in range(40):
            self.down(helper, "JOYFIRE", index * 100)
            self.up(helper, "JOYFIRE", index * 100 + 50)
        events = helper.pop()
        self.assertEqual(len(events), 16)
        self.assertTrue(all(item == {"kind": "joystick", "action": "confirm"} for item in events))

    def test_joystick_contact_bounce_is_not_a_second_press(self):
        helper = self.helper()
        self.down(helper, "JOYUP", 0)
        self.up(helper, "JOYUP", 100)
        self.down(helper, "JOYUP", 110)
        self.assertEqual(len(helper.pop()), 1)

    def test_touch_tap_selects_a_pad_after_release_grace_only(self):
        helper = self.helper()
        self.down(helper, "TOUCH12", 0)
        self.up(helper, "TOUCH12", 100)
        self.assertEqual(self.finish(helper, 319), [])
        self.assertEqual(self.finish(helper, 320), [{"kind": "touch", "action": "select", "pad": 12}])
        self.assertEqual(self.finish(helper, 500), [])

    def test_short_noise_and_long_hold_never_select(self):
        for duration in (20, 900):
            helper = self.helper()
            self.down(helper, "TOUCH01", 0)
            self.up(helper, "TOUCH01", duration)
            self.assertEqual(self.finish(helper, duration + 250), [])

    def test_touch_ring_rotation_wraps_both_directions_and_does_not_tap(self):
        for pads, delta in (((11, 12, 1), 1), ((2, 1, 12), -1)):
            helper = self.helper()
            for index, pad in enumerate(pads):
                name = "TOUCH%02d" % pad
                self.down(helper, name, index * 150)
                self.up(helper, name, index * 150 + 80)
            events = self.finish(helper, 700)
            self.assertEqual(events, [{"kind": "touch", "action": "rotate", "delta": delta, "pad": pads[-1]}])

    def test_touch_back_and_forth_jitter_and_large_jumps_do_nothing(self):
        for pads in ((1, 2, 1), (1, 7, 8)):
            helper = self.helper()
            for index, pad in enumerate(pads):
                name = "TOUCH%02d" % pad
                self.down(helper, name, index * 150)
                self.up(helper, name, index * 150 + 80)
            self.assertEqual(self.finish(helper, 700), [])

    def test_simultaneous_touch_chord_is_rejected(self):
        helper = self.helper()
        self.down(helper, "TOUCH01", 0)
        self.down(helper, "TOUCH02", 0)
        self.up(helper, "TOUCH01", 100)
        self.up(helper, "TOUCH02", 100)
        self.assertEqual(self.finish(helper, 400), [])

    def test_proximity_is_off_by_default(self):
        helper = self.helper()
        self.down(helper, "LEFTPROX", 0)
        self.up(helper, "LEFTPROX", 120)
        self.down(helper, "RIGHTPROX", 240)
        self.up(helper, "RIGHTPROX", 360)
        self.assertEqual(helper.pop(), [])

    def test_opted_in_deliberate_proximity_wave_only_focuses(self):
        helper = self.helper(space_proximity=True)
        self.down(helper, "LEFTPROX", 0)
        self.up(helper, "LEFTPROX", 120)
        self.down(helper, "RIGHTPROX", 240)
        self.up(helper, "RIGHTPROX", 360)
        self.assertEqual(helper.pop(), [{"kind": "proximity", "action": "focus", "side": "right"}])
        self.down(helper, "LEFTPROX", 400)
        self.up(helper, "LEFTPROX", 520)
        self.down(helper, "RIGHTPROX", 640)
        self.up(helper, "RIGHTPROX", 760)
        self.assertEqual(helper.pop(), [])

    def test_simultaneous_proximity_or_single_hover_never_focuses(self):
        helper = self.helper(space_proximity=True)
        self.down(helper, "LEFTPROX", 0)
        self.down(helper, "RIGHTPROX", 10)
        self.up(helper, "LEFTPROX", 100)
        self.up(helper, "RIGHTPROX", 110)
        self.assertEqual(helper.pop(), [])
        self.finish(helper, 1200)
        self.down(helper, "LEFTPROX", 1300)
        self.up(helper, "LEFTPROX", 1400)
        self.assertEqual(self.finish(helper, 2400), [])

    def test_focus_loss_clears_queue_and_held_joystick_needs_release(self):
        helper = self.helper()
        self.down(helper, "JOYUP", 0)
        self.owner._focused = False
        helper.update()
        self.assertEqual(helper.pop(), [])
        self.backend.boards[0].joystick_states["UP"][0] = True
        self.owner._focused = True
        helper.update()
        self.down(helper, "JOYUP", 200)
        self.assertEqual(helper.pop(), [])
        self.backend.boards[0].joystick_states["UP"][0] = False
        self.up(helper, "JOYUP", 300)
        self.down(helper, "JOYUP", 400)
        self.assertEqual(helper.pop(), [{"kind": "joystick", "action": "up"}])

    def test_opted_in_tilt_uses_first_gravity_sample_as_neutral_and_smooths(self):
        helper = self.helper(space_tilt=True)
        self.assertTrue(helper.motion_valid)
        self.assertEqual(helper.tilt, (0, 0))
        self.backend.sample = (4.905, 0, 8.5)
        self.finish(helper, 50)
        self.assertAlmostEqual(helper.tilt[0], .12)
        self.assertEqual(helper.tilt[1], 0)
        self.finish(helper, 100)
        self.assertTrue(.12 < helper.tilt[0] < .5)
        self.assertIsNone(helper.heading)
        self.assertEqual(helper.pop(), [])

    def test_absent_imu_nonfinite_freefall_and_large_impulse_are_invalid(self):
        for sample in ((1, 1, 1), (0, 0, 0), (0, 0, 30), (float("nan"), 0, 9.81), "unexpected"):
            self.backend.sample = sample
            helper = self.helper(space_tilt=True)
            self.assertFalse(helper.motion_valid)
            self.assertEqual(helper.tilt, (0, 0))
            self.assertIsNone(helper.heading)

    def test_tilt_sampling_is_limited_and_recenter_has_no_sensor_write(self):
        helper = self.helper(space_tilt=True)
        self.assertEqual(self.backend.reads, 1)
        self.finish(helper, 20)
        self.assertEqual(self.backend.reads, 1)
        self.backend.sample = (3, 0, 9)
        self.finish(helper, 50)
        self.assertGreater(helper.tilt[0], 0)
        helper.recenter()
        helper.update()
        self.assertEqual(helper.tilt, (0, 0))

    def test_close_removes_handlers_and_stops_inputs_without_hardware_operations(self):
        helper = self.helper()
        self.assertEqual(len(self.bus.handlers), 2)
        helper.close()
        helper.close()
        self.down(helper, "JOYUP", 200)
        self.up(helper, "JOYUP", 300)
        helper.update()
        self.assertEqual(helper.pop(), [])
        self.assertEqual(self.bus.handlers, [])


if __name__ == "__main__":
    unittest.main()
