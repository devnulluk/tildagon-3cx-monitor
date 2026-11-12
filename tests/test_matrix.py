"""Known-board protocol, hotplug and freshness checks; no badge or PBX writes."""
import importlib.util
import asyncio
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("monitor_matrix", ROOT / "badge/matrix.py")
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


def header(**changes):
    value = dict(vid=0xCAFE, pid=0x54E1, friendly_name="Liteloop")
    value.update(changes)
    return types.SimpleNamespace(**value)


def payload(state="available", calls=None, confirmed=True, age=0, weather=None):
    return {"own": {"calls": calls or [], "presence": {
        "state": state, "confirmed": confirmed, "age_seconds": age}},
        "weather": weather or {}}


class Bus:
    def __init__(self):
        self.frames = []
        self.registers = bytearray(256)
        self.error = False
        self.short_write = False

    def writeto_mem(self, address, register, data):
        if self.error:
            raise OSError("test I2C unavailable")
        self.frames.append((address, register, bytes(data)))
        self.registers[register:register + len(data)] = data
        return 0 if self.short_write else None


class Backend:
    def __init__(self):
        self.attached = {2}
        self.drivers = {}
        self.running = []
        self.known = {2: header()}
        self.created = []
        self.bus = Bus()

    def snapshot(self):
        return self.drivers, self.attached, self.running

    def headers(self):
        return self.known

    def matrix_i2c(self, slot):
        self.created.append(slot)
        return self.bus


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()

    def display(self, **setting):
        return matrix.MatrixDisplay({"matrix": setting}, self.backend)

    def drain(self, display):
        async def drain():
            for _ in range(20):
                if not display.pending:
                    return
                await display.flush()
            self.fail("bounded fake transfer never completed")
        asyncio.run(drain())

    def image(self):
        return bytes(self.backend.bus.registers[0x51:0x51 + 156])

    def test_only_exact_known_header_is_initialized(self):
        for change in ({"vid": 0x1234}, {"pid": 0xFFFF}, {"friendly_name": "Different"}):
            self.backend.known = {2: header(**change)}
            display = self.display(slot=2)
            self.assertFalse(display.update(payload(), True, 0))
        self.assertEqual(self.backend.created, [])
        self.assertEqual(self.backend.bus.frames, [])

    def test_explicit_slot_never_uses_other_known_board(self):
        display = self.display(slot=3)
        self.assertFalse(display.ready)
        self.assertEqual(self.backend.created, [])

    def test_auto_discovery_requires_unique_exact_header(self):
        self.backend.attached.add(3)
        self.backend.known[3] = header()
        display = self.display()
        self.assertEqual(display.status, "MATRIX CHOOSE SLOT")
        self.assertEqual(self.backend.created, [])
        selected = self.display(slot=2)
        self.assertTrue(selected.ready)
        self.assertEqual(selected.slot, 2)

    def test_invalid_configuration_never_initializes_a_bus(self):
        for value in ({"slot": True}, {"slot": 0}, {"slot": 7}, {"type": "Guessed"},
                      {"brightness": float("nan")}, {"brightness": 2}, {"brightness": True}):
            self.assertFalse(self.display(**value).ready)
        self.assertEqual(self.backend.created, [])

    def test_disabled_and_unattached_board_are_not_driven(self):
        display = self.display(enabled=False)
        self.assertFalse(display.update(payload(), True, 0))
        self.backend.attached.clear()
        self.assertFalse(self.display(slot=2).ready)
        self.assertEqual(self.backend.created, [])

    def test_any_active_slot_driver_blocks_direct_control(self):
        self.backend.drivers = {2: object()}
        display = self.display(slot=2)
        self.assertEqual(display.status, "MATRIX SLOT IN USE")
        self.assertEqual(self.backend.created, [])

    def test_manufacturer_companion_app_blocks_direct_control(self):
        self.backend.running = [type("MatrixHexpansionApp", (), {})()]
        display = self.display(slot=2)
        self.assertEqual(display.status, "CLOSE MATRIX APP")
        self.assertEqual(self.backend.created, [])

    def test_native_pwm_packet_uses_exact_register_and_physical_mapping(self):
        display = self.display(slot=2, brightness=0.03)
        self.assertTrue(display.update(payload(), True, 0))
        self.assertEqual(self.backend.bus.frames, [], "update must not touch I2C")
        self.drain(display)
        self.assertTrue(all(address == 0x20 and 0x50 <= register <= 0xEC and len(data) == 1
                            for address, register, data in self.backend.bus.frames))
        self.assertEqual(self.backend.bus.registers[0x50], 3)
        actual = {index for index, value in enumerate(self.image()) if value}
        self.assertEqual(actual, set(matrix._PIXELS["available"]))
        self.assertEqual(max(self.image()), 7)
        self.assertEqual(sorted(index for index in matrix.GRID if index >= 0), list(range(156)))

    def test_identical_static_state_is_not_written_each_frame(self):
        display = self.display()
        for tick in range(0, 1000, 20):
            self.assertTrue(display.update(payload(), True, tick))
            self.drain(display)
        self.assertEqual(display.frames_written, 1)

    def test_only_active_explicit_partner_call_gets_heart(self):
        display = self.display()
        own = payload(calls=[{"state": "connected", "peer_name": "Partner"}])
        display.update(own, True, 150, partner=False)
        self.assertEqual(display.last_mode, "busy")
        display.update(own, True, 160, partner=True)
        self.assertEqual(display.last_mode, "heart")
        display.update(payload(), True, 170, partner=True)
        self.assertEqual(display.last_mode, "available")
        display.update(own, False, 180, partner=True)
        self.assertEqual(display.last_mode, "unknown")

    def test_heart_animates_without_raising_configured_brightness(self):
        display = self.display(brightness=0.03)
        own = payload(calls=[{"state": "ringing"}])
        frames = []
        for tick in range(0, 2400, 125):
            display.update(own, True, tick, partner=True)
            self.drain(display)
            frames.append(self.image())
        self.assertGreater(len(set(frames)), 1)
        self.assertTrue(all(max(data) <= 7 for data in frames))
        self.assertLessEqual(display.frames_written, 20)

    def test_route_glyph_and_busy_are_distinct(self):
        display = self.display()
        for index, kind in enumerate(("internal", "queue", "ddi", "external")):
            display.update(payload(calls=[{"state": "ringing", "kind": kind}]), True, index * 200)
            self.assertEqual(display.last_mode, kind)
        display.update(payload(calls=[{"state": "held", "kind": "queue"}]), True, 900)
        self.assertEqual(display.last_mode, "busy")

    def test_stale_presence_never_shows_available(self):
        display = self.display()
        for value in (payload(confirmed=False), payload(age=6), payload(age=float("nan")), payload(age=True)):
            display.update(value, True, 0)
            self.assertEqual(display.last_mode, "unknown")

    def test_stale_weather_never_shows_dry(self):
        display = self.display()
        weather = {"live": True, "rain_next_hour": {"status": "dry_likely"}}
        value = payload(weather=weather)
        display.update(value, True, 0, page="rain", weather_fresh=True)
        self.assertEqual(display.last_mode, "dry")
        weather["stale"] = True
        display.update(value, True, 1, page="rain", weather_fresh=True)
        self.assertEqual(display.last_mode, "unknown")
        weather.pop("stale")
        display.update(value, True, 2, page="rain", weather_fresh=False)
        self.assertEqual(display.last_mode, "unknown")

    def test_weather_symbols_follow_codes_and_malformed_data_is_unknown(self):
        display = self.display()
        for index, (code, symbol) in enumerate(((0, "sun"), (3, "cloud"), (45, "fog"), (61, "rain"),
                                                (75, "snow"), (95, "storm"), (123, "unknown"), (True, "unknown"))):
            display.update(payload(weather={"live": True, "current": {"weather_code": code, "is_day": True}}),
                           True, index * 150, page="weather", weather_fresh=True)
            self.assertEqual(display.last_mode, symbol)
        for malformed in (None, [], "unexpected"):
            display.update(payload(weather={"live": True, "current": malformed}),
                           True, 2000, page="weather", weather_fresh=True)
            self.assertEqual(display.last_mode, "unknown")

    def test_call_overrides_weather_and_offline_overrides_everything(self):
        display = self.display()
        own = payload(calls=[{"state": "ringing", "kind": "queue"}],
                      weather={"live": True, "current": {"weather_code": 0, "is_day": True}})
        display.update(own, True, 0, page="weather", weather_fresh=True)
        self.assertEqual(display.last_mode, "queue")
        display.update(own, False, 1, page="weather", partner=True, weather_fresh=True)
        self.assertEqual(display.last_mode, "unknown")

    def test_unplug_or_header_change_blocks_all_further_writes(self):
        display = self.display()
        display.update(payload(), True, 0)
        self.drain(display)
        count = len(self.backend.bus.frames)
        self.backend.known[2] = header(pid=0x1234)
        self.assertFalse(display.update(payload(state="dnd"), True, 10))
        self.drain(display)
        self.assertEqual(len(self.backend.bus.frames), count)
        self.backend.known[2] = header()
        self.backend.attached.clear()
        self.assertFalse(display.update(payload(), True, 20))
        self.assertEqual(len(self.backend.bus.frames), count)

    def test_replug_initializes_and_rewrites_same_glyph(self):
        display = self.display()
        display.update(payload(), True, 0)
        self.drain(display)
        self.backend.attached.clear()
        display.update(payload(), True, 10)
        self.backend.attached.add(2)
        self.backend.known[2] = header()
        display.update(payload(), True, 20)
        self.drain(display)
        self.assertEqual(self.backend.created, [2, 2])
        self.assertEqual(display.frames_written, 2)

    def test_i2c_error_backs_off_without_reset_or_automatic_immediate_retry(self):
        display = self.display()
        self.backend.bus.error = True
        self.assertTrue(display.update(payload(), True, 0))
        self.drain(display)
        self.assertEqual(display.status, "MATRIX I2C ERROR")
        self.backend.bus.error = False
        self.assertFalse(display.update(payload(), True, 1999))
        self.assertTrue(display.update(payload(), True, 2000))
        self.drain(display)
        self.assertEqual(self.backend.created, [2, 2])

    def test_short_write_is_an_error_not_a_successful_frame(self):
        display = self.display()
        self.backend.bus.short_write = True
        self.assertTrue(display.update(payload(), True, 0))
        self.drain(display)
        self.assertEqual(display.frames_written, 0)

    def test_close_is_idempotent_and_never_clears_replacement_hardware(self):
        display = self.display()
        display.update(payload(), True, 0)
        self.drain(display)
        count = len(self.backend.bus.frames)
        display.close()
        self.assertEqual(len(self.backend.bus.frames), count)
        display.close()
        display.update(payload(), True, 1000)
        self.assertEqual(len(self.backend.bus.frames), count)
        second = self.display()
        self.backend.known[2] = header(pid=0)
        second.close()
        self.assertEqual(len(self.backend.bus.frames), count)

    def test_flush_is_bounded_and_initial_load_never_flashes_unscaled_values(self):
        display = self.display(brightness=0.03)
        display.update(payload(), True, 0)
        writes = asyncio.run(display.flush())
        self.assertEqual(writes, 24)
        self.assertTrue(display.pending)
        self.assertEqual(self.backend.bus.frames[:2], [(0x20, 0x51, b"\x00"), (0x20, 0x50, b"\x01")])
        self.assertEqual(self.backend.bus.registers[0x51], 0)
        self.drain(display)
        self.assertTrue(all(data[0] <= 7 for address, register, data in self.backend.bus.frames if register != 0x50))

    def test_new_goal_coalesces_during_yield_without_an_unbounded_queue(self):
        display = self.display()
        display.update(payload(), True, 0)
        asyncio.run(display.flush())
        display.update(payload(state="dnd"), True, 200)
        self.drain(display)
        self.assertEqual(display.displayed_mode, "dnd")
        self.assertEqual({i for i, value in enumerate(self.image()) if value}, set(matrix._PIXELS["dnd"]))
        self.assertEqual(display.frames_written, 1)

    def test_close_during_flush_yield_prevents_all_remaining_writes(self):
        display = self.display()
        display.update(payload(), True, 0)
        async def run():
            worker = asyncio.create_task(display.flush())
            await asyncio.sleep(0)
            count = len(self.backend.bus.frames)
            self.assertEqual(count, 8)
            display.close()
            await worker
            self.assertEqual(len(self.backend.bus.frames), count)
            self.assertFalse(display.pending)
        asyncio.run(run())

    def test_animation_goal_stays_stable_during_slow_native_drain_until_commit(self):
        display = self.display()
        own = payload(calls=[{"state": "ringing"}])
        display.update(own, True, 0, partner=True)
        initial = bytes(display._packet)
        for tick in range(150, 1200, 150):
            display.update(own, True, tick, partner=True)
            self.assertEqual(bytes(display._packet), initial)
            asyncio.run(display.flush())
        self.assertFalse(display.pending)
        self.assertEqual(display.displayed_mode, "heart")
        self.assertEqual(display.frames_written, 1)
        display.update(own, True, 1350, partner=True)
        self.assertNotEqual(bytes(display._packet), initial)

    def test_pending_animation_yields_to_offline_and_brightness_changes_immediately(self):
        display = self.display()
        own = payload(calls=[{"state": "ringing"}])
        display.update(own, True, 150, partner=True)
        asyncio.run(display.flush())
        display.update(own, False, 200, partner=True)
        self.assertEqual(display.last_mode, "unknown")
        self.drain(display)
        self.assertEqual(display.displayed_mode, "unknown")
        display.update(own, True, 300, partner=True)
        previous = bytes(display._packet)
        display.setting["brightness"] = .03
        display.update(own, True, 301, partner=True)
        self.assertNotEqual(bytes(display._packet), previous)
        self.assertLessEqual(max(display._packet[1:]), 7)

    def test_second_flush_cannot_run_concurrently_and_cancel_releases_owner(self):
        display = self.display()
        display.update(payload(), True, 0)
        async def run():
            worker = asyncio.create_task(display.flush())
            await asyncio.sleep(0)
            self.assertEqual(await display.flush(), 0)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
            self.assertFalse(display._flushing)
            self.assertGreater(await display.flush(), 0)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
