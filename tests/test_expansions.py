import importlib.util
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("monitor_expansions", ROOT / "badge/expansions.py")
expansions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expansions)


class Bus:
    def __init__(self):
        self.handlers = []
    def on(self, kind, callback, owner):
        self.handlers.append((kind, callback, owner))
    def remove(self, kind, callback, owner):
        self.handlers.remove((kind, callback, owner))


class Pixels:
    def __init__(self, count):
        self.n = count
        self.frames = []
    def fill(self, colour):
        self.colour = colour
    def write(self):
        self.frames.append(self.colour)


class Backend:
    def __init__(self):
        self.drivers = {}
        self.attached = set()
        self.running = []
        self.saved = None
        self.created = []
    def snapshot(self):
        return self.drivers, self.attached, self.running
    def saved_eeh(self):
        return self.saved
    def pixels(self, slot, count):
        pixels = Pixels(count)
        self.created.append((slot, count, pixels))
        return pixels


def keyboard(slot):
    return types.SimpleNamespace(hexpansion_config=types.SimpleNamespace(port=slot), ADDR=0x34, handle_keyboard_key=lambda key, pressed: None)


def key(name, group="Keyboard"):
    return types.SimpleNamespace(button=types.SimpleNamespace(name=name, group=group))


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.bus = Bus()
        self.event_types = tuple(type(name, (), {}) for name in ("Down", "Up", "Inserted", "Removed", "Mounted", "Unmounted"))
    def manager(self, config=None):
        return expansions.ExpansionManager(object(), config, self.backend, self.bus, self.event_types)

    def test_nothing_is_driven_without_explicit_type_and_slot(self):
        self.backend.attached = {1, 2, 3}
        manager = self.manager()
        self.assertFalse(manager.eeh_ready)
        self.assertEqual(self.backend.created, [])

    def test_manufacturer_logo_count_and_slot_are_used_exactly(self):
        self.backend.attached = {4}
        manager = self.manager({"eeh": {"slot": 4, "type": "EEH Logo"}})
        self.assertTrue(manager.eeh_ready)
        self.assertEqual(self.backend.created[0][:2], (4, 14))
        self.assertTrue(manager.write_own_status((0, 30, 0)))
        self.assertEqual(self.backend.created[0][2].frames, [(0, 30, 0)])

    def test_unique_existing_manufacturer_setting_can_be_reused(self):
        self.backend.saved = {"slot": 2, "type": "TARDIS"}
        self.backend.attached = {2}
        manager = self.manager()
        self.assertTrue(manager.eeh_ready)
        self.assertEqual(self.backend.created[0][:2], (2, 5))

    def test_invalid_configuration_and_unknown_type_never_touch_gpio(self):
        self.backend.attached = set(range(1, 7))
        for slot, kind in ((0, "EEH Logo"), (7, "EEH Logo"), (True, "EEH Logo"), (1, "Guessed board")):
            with self.subTest(slot=slot, kind=kind):
                manager = self.manager({"eeh": {"slot": slot, "type": kind}})
                self.assertFalse(manager.eeh_ready)
                self.assertEqual(manager.eeh_status, "EEH CONFIG INVALID")
        self.assertEqual(self.backend.created, [])

    def test_unattached_board_is_not_initialized(self):
        manager = self.manager({"eeh": {"slot": 1, "type": "EEH Logo"}})
        self.assertEqual(manager.eeh_status, "EEH NOT CONNECTED")
        self.assertEqual(self.backend.created, [])

    def test_keyboard_never_gets_overwritten_by_saved_eeh_configuration(self):
        self.backend.drivers = {1: keyboard(1)}
        self.backend.attached = {1}
        manager = self.manager({"eeh": {"slot": 1, "type": "EEH Logo"}})
        self.assertTrue(manager.keyboard_present)
        self.assertEqual(manager.keyboard_slots, [1])
        self.assertEqual(manager.eeh_status, "EEH SLOT IN USE")
        self.assertEqual(self.backend.created, [])

    def test_other_running_slot_driver_is_not_overwritten(self):
        self.backend.drivers = {2: object()}
        self.backend.attached = {2}
        manager = self.manager({"eeh": {"slot": 2, "type": "Dalek"}})
        self.assertFalse(manager.eeh_ready)
        self.assertFalse(manager.keyboard_present)
        self.assertEqual(self.backend.created, [])

    def test_competing_manufacturer_app_is_not_driven_concurrently(self):
        self.backend.attached = {1}
        self.backend.running = [type("EEHNeoPixelHexpansions", (), {})()]
        manager = self.manager({"eeh": {"slot": 1, "type": "EEH Logo"}})
        self.assertEqual(manager.eeh_status, "CLOSE EEH LED APP")
        self.assertEqual(self.backend.created, [])

    def test_keyboard_presence_tracks_hotplug_without_scanning_i2c(self):
        manager = self.manager()
        self.backend.drivers = {5: keyboard(5)}
        self.backend.attached = {5}
        manager._changed(types.SimpleNamespace(port=5))
        manager.refresh(10)
        self.assertTrue(manager.keyboard_present)
        self.backend.attached = set()
        manager.refresh(1010)
        self.assertFalse(manager.keyboard_present)

    def test_only_keyboard_events_are_queued_once_per_press(self):
        self.backend.drivers = {3: keyboard(3)}
        self.backend.attached = {3}
        manager = self.manager()
        manager._key_down(key("A", "TwentyTwentyFour"))
        manager._key_down(key("K"))
        manager._key_down(key("K"))
        self.assertEqual(manager.pop_keys(), ["K"])
        manager._key_up(key("K"))
        manager._key_down(key("K"))
        self.assertEqual(manager.pop_keys(), ["K"])

    def test_keyboard_unplug_clears_queued_actions_and_latches(self):
        self.backend.drivers = {3: keyboard(3)}
        self.backend.attached = {3}
        manager = self.manager()
        manager._key_down(key("ENTER"))
        self.backend.attached = set()
        manager.refresh(1000)
        self.assertEqual(manager.pop_keys(), [])
        self.assertFalse(manager.keyboard_present)

    def test_eeh_unplug_stops_writes_and_replug_reinitializes(self):
        self.backend.attached = {2}
        manager = self.manager({"eeh": {"slot": 2, "type": "Dalek"}})
        manager.write_own_status((10, 0, 0))
        self.backend.attached = set()
        manager._changed(types.SimpleNamespace(port=2))
        manager.refresh(10)
        self.assertFalse(manager.write_own_status((0, 10, 0)))
        self.assertEqual(len(self.backend.created), 1)
        self.backend.attached = {2}
        manager._changed(types.SimpleNamespace(port=2))
        manager.refresh(20)
        self.assertTrue(manager.write_own_status((0, 10, 0)))
        self.assertEqual(len(self.backend.created), 2)

    def test_close_clears_leds_and_removes_event_handlers(self):
        self.backend.attached = {1}
        manager = self.manager({"eeh": {"slot": 1, "type": "EEH Logo"}})
        manager.write_own_status((30, 0, 0))
        self.assertEqual(len(self.bus.handlers), 6)
        manager.close()
        manager.close()
        self.assertEqual(self.bus.handlers, [])
        self.assertEqual(self.backend.created[0][2].frames[-1], (0, 0, 0))
        self.assertFalse(manager.write_own_status((0, 30, 0)))

    def test_partner_heartbeat_is_red_and_respects_existing_effective_brightness(self):
        self.backend.attached = {6}
        manager = self.manager({"eeh": {"slot": 6, "type": "EEH Logo"}})
        for tick in range(0, 2400, 30):
            manager.write_own_status((7, 0, 6), tick, heartbeat=True)
        frames = self.backend.created[0][2].frames
        self.assertGreater(len(set(frames)), 2)
        self.assertTrue(all(green == blue == 0 and 0 <= red <= 7 for red, green, blue in frames))
        self.assertEqual(max(red for red, green, blue in frames), 7)

    def test_heartbeat_never_modifies_normal_status_or_doubles_priority_scale(self):
        self.backend.attached = {6}
        manager = self.manager({"eeh": {"slot": 6, "type": "EEH Logo"}})
        manager.write_own_status((255, 0, 200), 150, heartbeat=True)
        self.assertEqual(self.backend.created[0][2].frames[-1], (255, 0, 0))
        manager.write_own_status((0, 4, 0), 160, heartbeat=False)
        self.assertEqual(self.backend.created[0][2].frames[-1], (0, 4, 0))


if __name__ == "__main__":
    unittest.main()
