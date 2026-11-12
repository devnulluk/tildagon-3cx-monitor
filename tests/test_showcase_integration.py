"""The actual app's showcase is isolated from PBX state, writes and preferences."""

import asyncio
import copy
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_badge as support
import test_theme_integration as theme_fixture


class SemanticCanvas(support.RecordingCanvas):
    def __init__(self):
        super().__init__()
        self.operations = []

    def __getattr__(self, name):
        def draw(*args, **kwargs):
            self.operations.append((name, args))
            return self
        return draw


class ShowcaseFixtures:
    def monitor(self, **config):
        values = {"theme": "ocean", "clock_style": "radar", "ring_brightness": .37,
                  "overview_on_demand": False,
                  "eeh_brightness": .12, "partner_name": "PRIVATE PARTNER FIXTURE",
                  "personal_dates": {"birthday_self": "1980-02-03", "anniversary": "2000-06-07"}}
        values.update(config)
        return theme_fixture.ThemeIntegrationTests().monitor(config=values)

    @staticmethod
    def key(module, monitor, key):
        monitor.expansions.keys.append(key)
        return monitor.update(0)

    @staticmethod
    def physical(module, monitor, key):
        module.time.now += 400
        monitor.buttons.values.add(key)
        result = monitor.update(0)
        monitor.buttons.values.clear()
        module.time.now += 400
        monitor.update(0)
        return result

    @staticmethod
    def draw(monitor):
        canvas = support.RecordingCanvas()
        monitor.draw(canvas)
        return canvas.records


class ShowcaseIntegrationTests(ShowcaseFixtures, unittest.TestCase):
    def assert_stage_content(self, monitor, stage, canvas):
        words = [item["text"] for item in canvas.records]
        feature, payload = stage["feature"], monitor.controller.payload
        current = payload["weather"]["current"]
        if feature == "intro":
            self.assertIn("DEMO TOUR", words)
            self.assertIn(stage["theme_name"], words)
        elif feature == "weather":
            self.assertIn(current["condition"], words)
            self.assertIn("%.0f C" % current["temperature_c"], words)
        elif feature == "rain":
            state = payload["weather"]["rain_next_hour"]["status"]
            self.assertIn("Rain likely" if state == "rain_likely" else "Dry likely", words)
        elif feature == "clock":
            local = monitor._local_weather_time(payload["weather"], 0)
            clock = "%02d:%02d" % (local[3], local[4])
            if stage["clock"] == "mondaine":
                self.assertIn("MONDAINE", words)
                self.assertGreaterEqual(sum(name == "line_to" for name, args in canvas.operations), 60)
            elif stage["clock"] == "original" and stage["theme"] == "retro":
                months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
                self.assertIn("%02d %s %04d" % (local[2], months[local[1] - 1], local[0]), words)
                self.assertGreaterEqual(sum(name == "rectangle" for name, args in canvas.operations), 8)
            elif stage["clock"] == "flip" or (stage["clock"] == "original" and stage["theme"] == "noir"):
                for part in clock.split(":"):
                    self.assertIn(part, words)
            else:
                self.assertIn(clock, words)
        elif feature == "moon":
            self.assertIn("MOON", words)
            self.assertIn("Approx. illumination", words)
        elif feature == "meteors":
            self.assertIn("METEORS", words)
            self.assertTrue(any(word.startswith("Peak ") for word in words))
        elif feature == "advent":
            self.assertIn("ADVENT", words)
            self.assertIn("14", words)
        elif feature == "team":
            self.assertTrue({"A", "S", "J", "P", "245", "Alex", "External"} <= set(words))
        elif feature == "team_detail":
            if stage["detail"] == "internal":
                self.assertIn("245", words)
                self.assertIn("Alex", words)
            else:
                self.assertIn("External", words)
                self.assertNotIn("+441632960456", words)
        elif feature == "presence":
            me = [item for item in canvas.records if item["text"] == "ME"]
            self.assertEqual(len(me), 1)
            self.assertGreaterEqual(me[0]["size"], 60)
            colour = {"available": (0, 145, 25), "away": (255, 155, 0), "dnd": (145, 0, 220)}[stage["presence"]]
            self.assertEqual(me[0]["colour"], tuple(value / 255 for value in colour))
        elif feature == "settings":
            self.assertTrue({"SETTINGS", "RING", "EEH"} <= set(words), words)
            self.assertIn("%d%%" % round(monitor.controller.ring_brightness * 100), words)
            self.assertIn("%d%%" % round(monitor.controller.eeh_brightness * 100), words)
        elif feature == "notification":
            item = payload["notifications"][0]
            text = " ".join(words)
            self.assertIn(item["title"], text)
            self.assertIn(item["body"], text)
            self.assertIn(item["type"].upper(), words)
            if item["progress"] is not None:
                self.assertIn("%d%%" % item["progress"], words)
        elif feature == "call":
            call = payload["own"]["calls"][0]
            self.assertIn(monitor.config["partner_name"] if stage["partner"] and call["state"] != "connected" else call["peer_name"], words)
            self.assertNotIn(call["peer_number"], words)
            if call["state"] == "connected":
                self.assertIn("00:00", words)
                if not stage['partner']:self.assertIn('ON CALL',words)
            elif call['state'] == 'dialing':
                self.assertIn('CALLING',words)
            else:
                label = "Partner" if stage["partner"] else "PRIORITY" if call["priority"] else call["kind"].upper()
                self.assertIn(label, words)
        else:
            self.fail("Unverified showcase feature: " + feature)
        if feature not in ("weather", "rain"):
            self.assertNotIn("%.0f C" % current["temperature_c"], words)

    def test_every_theme_and_feature_renders_with_demo_label_and_no_private_fixture_data(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        themes, features, clocks = set(), set(), {}
        for index in range(monitor.showcase.count):
            self.assertTrue(monitor._showcase_seek(index))
            stage = monitor.showcase.current(monitor.clock_ms)
            with self.subTest(index=index, theme=stage["theme"], feature=stage["feature"]):
                canvas = SemanticCanvas()
                monitor.draw(canvas)
                records = canvas.records
                words = [item["text"] for item in records]
                self.assertTrue(records)
                self.assertIn("DEMO", records[-1]["text"])
                self.assertNotIn("PRIVATE PARTNER FIXTURE", " ".join(words))
                self.assertNotIn("MB", words)
                self.assertNotIn("1980-02-03", str(monitor.config))
                self.assertTrue(monitor.controller.payload["demo"])
                self.assertFalse(monitor.controller.payload["controls"]["enabled"])
                self.assertFalse(monitor.controls.is_busy)
                self.assert_stage_content(monitor, stage, canvas)
                themes.add(stage["theme"])
                features.add(stage["feature"])
                if stage["feature"] == "clock":
                    clocks.setdefault(stage["theme"], set()).add(stage["clock"])
        self.assertEqual(themes, {"original", "christmas", "easter", "anniversary", "birthday_self",
                                  "birthday_partner", "cyberpunk", "lcars", "kitty", "photo", "noir", "ocean", "retro"})
        self.assertEqual(features, {"intro", "weather", "rain", "clock", "moon", "meteors", "advent",
                                    "team", "team_detail", "call", "notification", "presence", "settings"})
        for theme in themes:
            self.assertEqual(clocks[theme], set(module.CLOCKS))

    def phone_view_after_weather(self, feature, variant):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        self.draw(monitor)
        index = next(index for index in range(monitor.showcase.count)
                     if monitor.showcase.stage(index)["feature"] == feature
                     and (monitor.showcase.stage(index).get("detail") == variant if feature == "team_detail"
                          else monitor.showcase.stage(index).get("presence") == variant))
        monitor._showcase_seek(index)
        canvas = SemanticCanvas()
        monitor.draw(canvas)
        self.assert_stage_content(monitor, monitor.showcase.current(monitor.clock_ms), canvas)
        self.assertFalse(monitor.idle_pages.active(monitor.clock_ms))
        return canvas.records

    def test_internal_detail_after_idle_weather_displays_extension_and_first_name(self):
        records = self.phone_view_after_weather("team_detail", "internal")
        self.assertTrue({"245", "Alex"} <= {item["text"] for item in records})

    def test_external_detail_after_idle_weather_displays_external_without_number(self):
        records = self.phone_view_after_weather("team_detail", "external")
        self.assertIn("External", [item["text"] for item in records])

    def test_all_three_own_presence_views_after_idle_weather_display_me(self):
        for presence in ("available", "away", "dnd"):
            with self.subTest(presence=presence):
                records = self.phone_view_after_weather("presence", presence)
                self.assertIn("ME", [item["text"] for item in records])

    def test_paused_clock_retains_explicit_demo_label_above_the_underlying_face(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        clock = next(index for index in range(monitor.showcase.count)
                     if monitor.showcase.stage(index)["feature"] == "clock")
        monitor._showcase_seek(clock)
        monitor.showcase.toggle_pause(monitor.clock_ms)
        footer = self.draw(monitor)[-1]["text"]
        self.assertIn("DEMO", footer)
        self.assertIn("PAUSE", footer)

    def test_progress_percentage_is_not_covered_by_the_final_showcase_footer_plate(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        for variant, text in (("progress25", "25%"), ("progress75", "75%")):
            index = next(index for index in range(monitor.showcase.count)
                         if monitor.showcase.stage(index).get("notification") == variant)
            monitor._showcase_seek(index)
            canvas = SemanticCanvas()
            monitor.draw(canvas)
            percent = next(item for item in canvas.records if item["text"] == text)
            plate = next(args for name, args in reversed(canvas.operations) if name == "round_rectangle")
            top, bottom = percent["y"] - percent["size"] / 2, percent["y"] + percent["size"] / 2
            self.assertTrue(plate[1] + plate[3] <= top or plate[1] >= bottom, (text, percent, plate))
            self.assertIn("DEMO", canvas.records[-1]["text"])

    def test_settings_scene_automatically_shows_all_six_rows_without_saving(self):
        module, monitor, hardware, settings = self.monitor()
        with patch.dict(sys.modules, {"settings": settings}):
            self.assertTrue(monitor._start_showcase())
            index = next(index for index in range(monitor.showcase.count)
                         if monitor.showcase.stage(index)["feature"] == "settings")
            monitor._showcase_seek(index)
            visible = set()
            for selected in range(6):
                if selected:
                    module.time.now += (monitor.showcase.step_ms + 5) // 6
                monitor.update(0)
                visible.update(item["text"] for item in self.draw(monitor))
                self.assertEqual(monitor.settings_selected, selected)
                self.assertIsNone(monitor._appearance_save_at)
                self.assertIsNone(monitor._brightness_save_at)
        self.assertTrue({"SETTINGS", "RING", "EEH", "THEME", "CLOCK", "DEMO", "Play all themes", "MATRIX CALL"} <= visible)
        self.assertEqual(settings.writes, [])
        self.assertEqual(settings.saves, 0)

    def test_entry_closes_the_old_state_transport_and_keeps_a_fresh_client_for_exit(self):
        module, monitor, hardware, settings = self.monitor()
        original = monitor.state_client
        with patch.object(original, "close", wraps=original.close) as close:
            self.assertTrue(monitor._start_showcase())
        close.assert_called_once()
        self.assertTrue(original._closed)
        replacement = monitor.state_client
        self.assertIsNot(replacement, original)
        self.assertFalse(replacement._closed)
        self.assertTrue(monitor._end_showcase())
        self.assertIs(monitor.state_client, replacement)
        self.assertFalse(replacement._closed)

    def test_ordinary_caller_types_do_not_render_partner_celebrations(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        cases = {}
        for index in range(monitor.showcase.count):
            stage = monitor.showcase.stage(index)
            if stage["theme"] != "original" or stage["feature"] != "call":
                continue
            if stage["scene"] in ("connected", "partner_connected"):
                continue
            monitor._showcase_seek(index)
            words = [item["text"] for item in self.draw(monitor)]
            cases[stage["scene"]] = words
            self.assertEqual("Partner" in words, stage["scene"] == "partner", stage["scene"])
        self.assertTrue({"ddi", "internal", "queue", "priority", "partner"} <= set(cases))
        self.assertIn("DDI", cases["ddi"])
        self.assertIn("INTERNAL", cases["internal"])
        self.assertIn("QUEUE", cases["queue"])
        self.assertIn("PRIORITY", cases["priority"])

    def test_entry_and_exit_restore_original_objects_private_dates_and_saved_brightness(self):
        module, monitor, hardware, settings = self.monitor()
        names = ("config", "controller", "themes", "idle_pages", "notifications", "controls")
        originals = {name: getattr(monitor, name) for name in names}
        configuration = copy.deepcopy(monitor.config)
        dates = monitor.config["personal_dates"]
        source = monitor.controller.payload
        received = monitor.controller.received_ms
        self.assertTrue(monitor._start_showcase())
        for name in names:
            self.assertIsNot(getattr(monitor, name), originals[name], name)
        self.assertTrue(monitor.controller.payload["demo"])
        self.assertNotIn("PRIVATE PARTNER FIXTURE", str(monitor.config))
        self.assertNotIn("1980-02-03", str(monitor.config))
        self.assertNotIn("2000-06-07", str(monitor.config))
        self.assertIsNot(monitor.config.get("personal_dates"), dates)
        module.time.now += 6000
        monitor.update(0)
        self.assertTrue(monitor._end_showcase())
        self.assertIsNone(monitor.showcase)
        for name in names:
            self.assertIs(getattr(monitor, name), originals[name], name)
        self.assertEqual(monitor.config, configuration)
        self.assertIs(monitor.config["personal_dates"], dates)
        self.assertEqual(monitor.clock_style, "radar")
        self.assertEqual(monitor.themes.selection, "ocean")
        self.assertEqual(monitor.controller.ring_brightness, .37)
        self.assertEqual(monitor.controller.eeh_brightness, .12)
        self.assertIs(monitor.controller.payload, source)
        self.assertEqual(monitor.controller.received_ms, received)
        self.assertFalse(monitor.controller.live(monitor.clock_ms))

    def test_unsent_phone_intent_is_cancelled_and_never_restored(self):
        module, monitor, hardware, settings = self.monitor()
        controls = monitor.controls
        self.assertTrue(controls.queue_call(monitor._status_payload(), True, "tb", monitor.clock_ms))
        self.assertIsNotNone(controls.pending)
        self.assertTrue(monitor._start_showcase())
        self.assertIsNone(controls.pending)
        self.assertIsNone(monitor.controls.pending)
        monitor._end_showcase()
        self.assertIs(monitor.controls, controls)
        self.assertFalse(monitor.controls.is_busy)
        self.assertIsNone(monitor.controls.take())

    def test_entry_is_refused_while_a_real_phone_request_is_already_in_flight(self):
        module, monitor, hardware, settings = self.monitor()
        controls, controller, config = monitor.controls, monitor.controller, monitor.config
        self.assertTrue(controls.queue_dnd(monitor._status_payload(), True, monitor.clock_ms))
        intent = controls.take()
        self.assertIsNotNone(intent)
        self.assertFalse(monitor._start_showcase())
        self.assertIsNone(monitor.showcase)
        self.assertIs(monitor.controller, controller)
        self.assertIs(monitor.controls, controls)
        self.assertIs(monitor.config, config)
        self.assertEqual(controls._in_flight, intent)

    def test_network_generation_changes_on_both_boundaries_and_repeated_exit_is_safe(self):
        module, monitor, hardware, settings = self.monitor()
        before = monitor._network_generation
        self.assertTrue(monitor._start_showcase())
        self.assertGreater(monitor._network_generation, before)
        active = monitor._network_generation
        self.assertTrue(monitor._end_showcase())
        self.assertGreater(monitor._network_generation, active)
        self.assertFalse(monitor._end_showcase())
        self.assertIsNone(monitor.showcase)

    def test_entry_shortcut_wins_over_a_simultaneous_physical_speed_dial(self):
        module, monitor, hardware, settings = self.monitor()
        module.time.now += 400
        monitor.buttons.values.add("A")
        monitor.expansions.keys.append("D")
        with patch.object(module, "send_control") as send, patch.object(module, "post_json") as post:
            monitor.update(0)
        self.assertIsNotNone(monitor.showcase)
        self.assertIsNone(monitor.controls.pending)
        send.assert_not_called()
        post.assert_not_called()

    def test_demo_settings_row_starts_with_confirm_with_or_without_keyboard(self):
        for keyboard in (False, True):
            with self.subTest(keyboard=keyboard):
                module, monitor, hardware, settings = self.monitor()
                monitor.expansions.keyboard_present = keyboard
                monitor.update(0)
                if keyboard:
                    self.key(module, monitor, "S")
                    self.key(module, monitor, "UP")
                    self.assertEqual(monitor.settings_selected, 5)
                    self.key(module, monitor, "ENTER")
                else:
                    monitor.buttons.values.add("C")
                    monitor.update(0)
                    module.time.now += 901
                    monitor.update(0)
                    self.assertTrue(monitor.settings_open)
                    monitor.buttons.values.clear()
                    monitor.update(0)
                    self.physical(module, monitor, "A")
                    self.assertEqual(monitor.settings_selected, 5)
                    self.physical(module, monitor, "C")
                self.assertIsNotNone(monitor.showcase)
                self.assertFalse(monitor.settings_open)
                self.assertIsNone(monitor.controls.pending)

    def test_normal_b_e_and_d_speed_dials_keep_their_existing_meaning(self):
        for key, target in (("B", "pd"), ("E", "kz"), ("D", "sm")):
            with self.subTest(key=key):
                module, monitor, hardware, settings = self.monitor()
                self.physical(module, monitor, key)
                self.assertIsNone(monitor.showcase)
                self.assertEqual(monitor.controls.pending["target"], target)

    def test_manual_buttons_step_scenes_and_themes_and_pause_without_changing_mode(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        monitor.update(0)
        with patch.object(monitor, "_showcase_step") as step, patch.object(monitor, "_showcase_theme") as theme:
            self.physical(module, monitor, "B")
            step.assert_called_with(1)
            self.physical(module, monitor, "E")
            step.assert_called_with(-1)
            self.physical(module, monitor, "A")
            theme.assert_called_with(1)
            self.physical(module, monitor, "D")
            theme.assert_called_with(-1)
        self.assertIsNotNone(monitor.showcase)
        self.assertFalse(monitor.showcase.paused)
        self.physical(module, monitor, "C")
        self.assertTrue(monitor.showcase.paused)
        self.key(module, monitor, "SPACE")
        self.assertFalse(monitor.showcase.paused)
        self.key(module, monitor, "ENTER")
        self.assertTrue(monitor.showcase.paused)
        self.assertIsNone(monitor.controls.pending)

    def test_showcase_physical_and_keyboard_navigation_cannot_queue_call_or_dnd(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        monitor.update(0)
        with patch.object(module, "send_control") as send, patch.object(module, "post_json") as post:
            for key in ("A", "B", "C", "D", "E"):
                self.physical(module, monitor, key)
                self.assertIsNotNone(monitor.showcase)
                self.assertFalse(monitor.controls.is_busy)
            for key in ("UP", "DOWN", "LEFT", "RIGHT", "ENTER", "SPACE", "S", "T", "K", "N"):
                self.key(module, monitor, key)
                self.assertIsNotNone(monitor.showcase)
                self.assertFalse(monitor.controls.is_busy)
        send.assert_not_called()
        post.assert_not_called()

    def test_escape_d_and_physical_f_return_to_monitor_without_terminating_app(self):
        for key in ("ESCAPE", "D", "F"):
            with self.subTest(key=key):
                module, monitor, hardware, settings = self.monitor()
                self.assertTrue(monitor._start_showcase())
                monitor.update(0)
                if key == "F":
                    self.physical(module, monitor, key)
                else:
                    self.key(module, monitor, key)
                self.assertIsNone(monitor.showcase)
                self.assertFalse(monitor._stopping)
                self.assertFalse(getattr(monitor, "terminated", False))
                self.assertIsNone(monitor.controls.pending)

    def test_physical_button_held_across_exit_must_be_released_before_call_mapping_rearms(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        monitor.update(0)
        monitor.buttons.values.add("A")
        module.time.now += 400
        monitor.update(0)
        self.key(module, monitor, "ESCAPE")
        self.assertIsNone(monitor.showcase)
        for _ in range(3):
            module.time.now += 400
            monitor.update(0)
            self.assertIsNone(monitor.controls.pending)
        monitor.buttons.values.clear()
        monitor.update(0)
        module.time.now += 400
        monitor.buttons.values.add("A")
        monitor.update(0)
        self.assertIsNotNone(monitor.controls.pending)
        self.assertEqual(monitor.controls.pending["target"], "tb")

    def test_old_c_hold_cannot_confirm_dnd_after_shortcut_entry_and_f_exit(self):
        module, monitor, hardware, settings = self.monitor()
        monitor.expansions.keyboard_present = False
        monitor.update(0)
        monitor.controller.own_view = True
        monitor.buttons.values.add("C")
        monitor.update(0)
        self.assertIsNotNone(monitor._settings_hold_started)
        # A newly delivered keyboard shortcut can arrive while the existing
        # physical hold still belongs to the no-keyboard input mapping.
        self.key(module, monitor, "D")
        self.assertIsNotNone(monitor.showcase)
        monitor.update(0)
        self.physical(module, monitor, "F")
        monitor.update(0)
        self.assertIsNone(monitor.showcase)
        self.assertIsNone(monitor._settings_hold_started)
        self.assertTrue(monitor.controller.own_view)
        self.assertIsNone(monitor.controls.pending)
        self.assertFalse(monitor.controls.is_busy)

    def test_showcase_never_saves_synthetic_preferences_and_stop_restores_before_cleanup(self):
        module, monitor, hardware, settings = self.monitor()
        original = monitor.config
        with patch.dict(sys.modules, {"settings": settings}):
            self.assertTrue(monitor._start_showcase())
            monitor._appearance_save_at = monitor.clock_ms
            monitor._brightness_save_at = monitor.clock_ms
            monitor._save_appearance()
            monitor._save_eeh_brightness()
            monitor.update(0)
            self.assertEqual(settings.writes, [])
            monitor._stop()
        self.assertIs(monitor.config, original)
        self.assertEqual(settings.writes, [])
        self.assertEqual(settings.saves, 0)
        self.assertTrue(monitor._stopping)
        self.assertIsNone(monitor.showcase)


class ShowcaseNetworkIsolationTests(ShowcaseFixtures, unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def modules(unblock):
        wifi = types.SimpleNamespace(status=Mock(return_value=True), connect=Mock(), async_wait=AsyncMock(return_value=True))
        return {"wifi": wifi, "async_helpers": types.SimpleNamespace(unblock=unblock)}, wifi

    @staticmethod
    def runtime(sleep):
        return types.SimpleNamespace(sleep=sleep, create_task=asyncio.create_task, CancelledError=asyncio.CancelledError)

    async def test_active_before_background_start_performs_no_wifi_fetch_or_control_work(self):
        module, monitor, hardware, settings = self.monitor()
        self.assertTrue(monitor._start_showcase())
        unblock = AsyncMock(side_effect=AssertionError("Network must stay paused"))
        modules, wifi = self.modules(unblock)
        sleeps = 0
        async def sleep(delay):
            nonlocal sleeps
            sleeps += 1
            if sleeps >= 3:
                monitor._stopping = True
        with patch.dict(sys.modules, modules), patch.object(module, "asyncio", self.runtime(sleep)), \
                patch.object(module, "fetch_snapshot") as fetch, patch.object(module, "send_control") as send:
            await asyncio.wait_for(monitor._background_task(), timeout=2)
        self.assertGreater(sleeps, 0)
        unblock.assert_not_called()
        wifi.status.assert_not_called()
        wifi.connect.assert_not_called()
        fetch.assert_not_called()
        send.assert_not_called()
        self.assertTrue(monitor.controller.payload["demo"])

    async def interrupted_fetch(self, exit_before_result, failure=False):
        module, monitor, hardware, settings = self.monitor()
        original_controller = monitor.controller
        original_payload = original_controller.payload
        original_received = original_controller.received_ms
        late = copy.deepcopy(original_payload)
        late["own"]["name"] = "LATE PRIVATE LIVE RESULT"
        started, release = asyncio.Event(), asyncio.Event()
        reads = 0
        async def unblock(function, periodic, *args):
            nonlocal reads
            reads += 1
            if reads > 1:
                raise asyncio.CancelledError()
            started.set()
            await release.wait()
            if failure:
                raise OSError("Late private network error")
            return late
        modules, wifi = self.modules(unblock)
        async def sleep(delay):
            monitor._stopping = True
        with patch.dict(sys.modules, modules), patch.object(module, "asyncio", self.runtime(sleep)), \
                patch.object(module, "send_control") as send:
            task = asyncio.create_task(monitor._background_task())
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                self.assertTrue(monitor._start_showcase())
                if exit_before_result:
                    self.assertTrue(monitor._end_showcase())
                expected_error = monitor.controller.last_error
                release.set()
                try:
                    await asyncio.wait_for(task, timeout=2)
                except asyncio.CancelledError:
                    pass
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        send.assert_not_called()
        if exit_before_result:
            self.assertIs(monitor.controller, original_controller)
            self.assertIs(monitor.controller.payload, original_payload)
            self.assertEqual(monitor.controller.received_ms, original_received)
            self.assertEqual(monitor.controller.last_error, expected_error)
        else:
            self.assertTrue(monitor.controller.payload["demo"])
            self.assertNotIn("LATE PRIVATE LIVE RESULT", str(monitor.controller.payload))
            self.assertIsNone(monitor.controller.last_error)
            self.assertEqual(reads, 1)

    async def test_live_fetch_finishing_during_showcase_is_not_accepted(self):
        await self.interrupted_fetch(False)

    async def test_live_fetch_finishing_after_entry_and_exit_is_not_mistaken_for_fresh_data(self):
        await self.interrupted_fetch(True)

    async def test_late_network_error_does_not_overwrite_synthetic_state(self):
        await self.interrupted_fetch(False, failure=True)

    async def test_late_network_error_after_exit_does_not_mutate_restored_live_state(self):
        await self.interrupted_fetch(True, failure=True)


if __name__ == "__main__":
    unittest.main()
