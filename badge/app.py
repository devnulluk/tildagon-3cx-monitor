"""Tildagon / Spaceagon 3CX BLF and Caller ID display."""

import app
import asyncio
import json
import time
import gc

from app_components import clear_background
from events.input import Buttons, BUTTON_TYPES
from frontboards.common import FRONTBOARD_BUTTON_TYPES
from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable
from tildagonos import tildagonos

from .controller import Controller, call_colour, call_label
from .demo import SCENARIOS, snapshot
from .http_client import get_json, post_json, StateClient, ClockError, TLSError, HTTPError
from .clock_sync import ClockSync, clock_valid, sync_clock
from .controls import ControlButtons, ControlQueue, initials, own_colour
from .expansions import ExpansionManager
from .idle import IdlePages, data_fresh
from .idle_faces import draw_idle_face
from .visuals import backdrop, team_card, settings_row, notice_panel
from .themes import ThemeManager
from .theme_assets import ThemeAssetStore
from .theme_art import draw_theme_face
from .clocks import CLOCKS, get_clock_catalog, draw_clock_content
from .clock_assets import ClockAssetStore
from .astronomy import sky_snapshot
from .astro_faces import draw_astro_face
from .matrix import MatrixDisplay
from .love import partner_call, partner_active, draw_love, draw_bunny
from .notifications import NotificationInbox, draw_notification, led_frame as notification_leds, urgent_eeh_colour
from .space_inputs import SpaceInputs
from .showcase import Showcase, snapshot as showcase_snapshot, demo_config as showcase_config


DEFAULT_CONFIG = {
    "demo": True, "bridge_url": "", "token": "",
    "poll_seconds": 0.75, "eeh_brightness": 0.03, "ring_brightness": 0.15, "ca_file": "ca.der",
    "control_token": "", "demo_keyboard": False,
    "idle_seconds": 60, "rotate_seconds": 12,
    "theme": "original", "theme_auto": False, "clock_style": "original",
    "space_joystick": True, "space_touch": True, "space_proximity": False, "space_tilt": False,
}


def load_config():
    config = DEFAULT_CONFIG.copy()
    try:
        folder = __file__.replace("\\", "/").rsplit("/", 1)[0]
        with open(folder + "/config.json", "r") as handle:
            values = json.load(handle)
        if isinstance(values, dict):
            config.update(values)
    except (OSError, ValueError):
        pass
    return config


def fetch_snapshot(url, token, ca_file="ca.der", client=None):
    # TLS handshake, body read, JSON parse and close all happen in the worker.
    endpoint = url.rstrip("/") + "/v1/state"
    if client is not None:
        return client.get(endpoint, token, ca_file=ca_file, timeout=5)
    return get_json(endpoint, token, ca_file=ca_file, timeout=5)


def send_control(url, token, intent, ca_file="ca.der"):
    action = intent.get("action")
    if action not in ("call", "dnd"):
        raise ValueError("Invalid control action")
    body = {key: value for key, value in intent.items() if key != "action"}
    return post_json(url.rstrip("/") + "/v1/control/" + action, token, body,
                     ca_file=ca_file, timeout=26)


class ThreeCXMonitor(app.App):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.buttons = Buttons(self)
        self.demo_mode = self.config.get("demo") is True
        self.showcase = None
        self._showcase_saved = None
        self._showcase_stage = None
        self._showcase_signature = None
        self._showcase_received = None
        self._network_generation = 0
        level = self.config.get("eeh_brightness", 0.03)
        ring_level = self.config.get("ring_brightness", 0.15)
        if not self.demo_mode:
            try:
                import settings
                level = settings.get("threecx_monitor.eeh_brightness", level)
                ring_level = settings.get("threecx_monitor.ring_brightness", ring_level)
            except (ImportError, OSError, ValueError):
                pass
        self.controller = Controller(float(level), ring_brightness=float(ring_level))
        self.assets = ThemeAssetStore(self.config)
        self.clock_art = ClockAssetStore()
        self.themes = ThemeManager(self.config, self.assets.catalog_entries())
        self.clock_style = self.config.get("clock_style", "original")
        if not self.demo_mode:
            try:
                import settings
                self.themes.select(settings.get("threecx_monitor.theme", self.themes.selection))
                self.clock_style = settings.get("threecx_monitor.clock_style", self.clock_style)
            except (ImportError, OSError, ValueError):
                pass
        if self.clock_style not in CLOCKS:
            self.clock_style = "original"
        self._appearance_save_at = None
        self._appearance_preview = False
        self._sky_key, self._sky_value = None, None
        self._brightness_notice_until = 0
        self._brightness_notice_kind = "EEH"
        self._brightness_save_at = None
        self.settings_open = False
        self.settings_selected = 0
        self._settings_hold_started = None
        self._last_keyboard_mode = None
        self._idle_draw_page = None
        self._idle_entered_ms = 0
        self.idle_pages = IdlePages(idle_after_ms=max(0, min(86400, float(self.config.get("idle_seconds", 60)))) * 1000,
                                    rotate_ms=max(1, min(3600, float(self.config.get("rotate_seconds", 12)))) * 1000)
        self.demo_scene = 0
        self.clock_ms = 0
        self._ticks = time.ticks_ms()
        self._stopping = False
        self._last_leds = None
        self.controls = ControlQueue()
        self.state_client = StateClient()
        self.control_buttons = ControlButtons()
        self.expansions = ExpansionManager(self, self.config)
        self.matrix = MatrixDisplay(self.config, backend=getattr(self.expansions, "backend", None))
        if not self.demo_mode:
            try:
                import settings
                matrix_level = settings.get('threecx_monitor.matrix_call_brightness', self.matrix.call_brightness)
                if isinstance(matrix_level, (int, float)) and not isinstance(matrix_level, bool) and 0 <= matrix_level <= 1:
                    self.matrix.call_brightness = matrix_level
            except (ImportError, OSError, ValueError):
                pass
        self.space_inputs = SpaceInputs(self, self.config, clock=lambda: self.clock_ms)
        self.notifications = NotificationInbox()
        self.notifications_open = False
        self._notification_snapshot = None
        self._notification_received = None
        self._notification_pending = None
        self._notification_until = 0
        self._notification_entered = 0
        self._notification_presented = []
        self._notification_input_mode = False
        self._demo_dnd = False
        self._demo_call = None
        self._demo_call_until = 0
        eventbus.emit(PatternDisable())
        tildagonos.set_led_power(True)
        if self.demo_mode:
            self._accept_demo()

    def _accept_demo(self):
        if self.showcase is not None:
            self._tick_showcase()
            return
        value = snapshot(SCENARIOS[self.demo_scene])
        own = value["own"]
        own["state"] = "ringing" if own["calls"] else "idle"
        own["presence"] = {"state": "dnd" if self._demo_dnd else "available",
                           "profile": "Out of office" if self._demo_dnd else "Available",
                           "confirmed": True, "age_seconds": 0}
        if self._demo_call and self.clock_ms < self._demo_call_until and not own["calls"]:
            own["calls"] = [self._demo_call]
            own["state"] = "busy"
        value["controls"] = {"enabled": True, "call": True, "dnd": True,
                             "session_id": "d" * 32,
                             "targets": [{"id": key, "label": label} for key, label in
                                         (("tb", "TB"), ("pd", "PD"), ("jh", "JH"),
                                          ("sm", "SM"), ("kz", "KZ"))]}
        if isinstance(self.config.get("demo_notifications"), list):
            value["notifications"] = self.config["demo_notifications"]
        self.controller.accept(value, self.clock_ms)

    def _keyboard_present(self):
        return self.expansions.keyboard_present or (self.demo_mode and self.config.get("demo_keyboard") is True)

    def _network_current(self, generation, controller):
        return self.showcase is None and generation == self._network_generation and controller is self.controller

    def _showcase_reset_inputs(self):
        self.buttons.clear()
        self.control_buttons = ControlButtons()
        self.expansions.pop_keys()
        self.space_inputs.close()
        self.space_inputs = SpaceInputs(self, self.config, clock=lambda: self.clock_ms)
        self._last_leds = None

    def _start_showcase(self):
        if self.showcase is not None:
            return False
        if self.controls._in_flight is not None:
            self.controls._message("FINISH CURRENT ACTION", self.clock_ms)
            return False
        # An unsent intent must never reappear when this demonstration ends.
        self.controls.pending = None
        fields = ("config", "controller", "themes", "demo_mode", "clock_style", "idle_pages",
                  "notifications", "controls", "settings_open", "settings_selected",
                  "_appearance_save_at", "_brightness_save_at", "_appearance_preview",
                  "_brightness_notice_until", "_brightness_notice_kind", "_settings_hold_started",
                  "_notification_snapshot", "_notification_received", "_notification_pending",
                  "_notification_until", "_notification_entered", "_notification_presented",
                  "_notification_input_mode", "notifications_open", "_idle_draw_page", "_idle_entered_ms",
                  "_sky_key", "_sky_value")
        catalog = self.themes.catalog()
        for item in catalog:
            if item.get("requires_asset"):
                item["available"] = self.assets.photo_available(item["id"])
        self._showcase_saved = {name: getattr(self, name) for name in fields}
        # Discard a C press begun in the previous input mode; its eventual
        # release must not become phone consent after leaving the tour.
        self._showcase_saved["_settings_hold_started"] = None
        # Drop the idle transport while showing sample data. An active worker
        # owns its old client until it finishes; close defers its TLS cleanup.
        self.state_client.close()
        self.state_client = StateClient()
        self._network_generation += 1
        self.showcase = Showcase(catalog, get_clock_catalog())
        keyboard = self._keyboard_present()
        self.config = showcase_config()
        self.config["demo_keyboard"] = keyboard
        self.controller = Controller(self._showcase_saved["controller"].eeh_brightness,
                                     ring_brightness=self._showcase_saved["controller"].ring_brightness)
        self.themes = ThemeManager(self.config, self.assets.catalog_entries())
        self.demo_mode = True
        self.controls = ControlQueue()
        self.idle_pages = IdlePages(idle_after_ms=0, rotate_ms=3600000)
        self._brightness_save_at = self._appearance_save_at = None
        self._appearance_preview = False
        self._brightness_notice_until = 0
        self._settings_hold_started = None
        self.settings_open = False
        self._showcase_stage = self._showcase_signature = self._showcase_received = None
        self._showcase_reset_inputs()
        self._tick_showcase()
        return True

    def _end_showcase(self):
        if self.showcase is None:
            return False
        self._network_generation += 1
        saved = self._showcase_saved
        self.showcase = None
        for name, value in saved.items():
            setattr(self, name, value)
        self._showcase_saved = None
        self._showcase_stage = self._showcase_signature = self._showcase_received = None
        self._showcase_reset_inputs()
        gc.collect()
        return True

    def _showcase_step(self, direction=1):
        if self.showcase is not None:
            self.showcase.advance(direction, self.clock_ms)
            self._tick_showcase(force=True)

    def _showcase_theme(self, direction=1):
        if self.showcase is not None:
            self.showcase.next_theme(direction, self.clock_ms)
            self._tick_showcase(force=True)

    def _showcase_seek(self, index):
        if self.showcase is not None:
            self.showcase.seek(index, self.clock_ms)
            self._tick_showcase(force=True)
            return True
        return False

    def _tick_showcase(self, force=False):
        if self.showcase is None:
            return
        stage = self.showcase.current(self.clock_ms)
        signature = (stage["index"], stage["loop"], stage["id"])
        if signature != self._showcase_signature:
            self._showcase_signature = signature
            self._showcase_received = None
            self.themes.select(stage["theme"])
            self.clock_style = stage.get("clock") or "original"
            self._sky_key, self._sky_value = None, None
            self._idle_draw_page = None
            self.notifications = NotificationInbox()
            self.notifications_open = False
            self._notification_snapshot = self._notification_received = None
            self._notification_pending = None
            self._notification_until = self._notification_entered = 0
            self._notification_presented = []
            self._notification_input_mode = False
            self.settings_open = stage.get("page") == "settings"
            self.settings_selected = 0
            self.controller.selected = stage.get("team_index", 0)
            self.controller.detail_view = bool(stage.get("detail"))
            self.controller.own_view = bool(stage.get("own_view"))
        self._showcase_stage = stage
        if stage.get("feature") == "settings":
            self.settings_selected = min(5, stage["elapsed_ms"] * 6 // self.showcase.step_ms)
        if force or self._showcase_received is None or self.clock_ms - self._showcase_received >= 400:
            self.controller.accept(showcase_snapshot(stage, self.clock_ms), self.clock_ms)
            self._showcase_received = self.clock_ms

    def _showcase_input(self, keys, edges, events):
        if any(key in keys for key in ("ESCAPE", "D")) or "F" in edges:
            self._end_showcase()
            return
        commands = list(keys) + list(edges)
        for event in events:
            action, kind = event.get("action"), event.get("kind")
            if kind == "joystick":
                commands.append({"left": "LEFT", "right": "RIGHT", "up": "UP", "down": "DOWN", "confirm": "ENTER"}.get(action))
            elif kind == "touch" and action == "rotate":
                commands.append("RIGHT" if event.get("delta", 0) > 0 else "LEFT")
        if any(key in commands for key in ("C", "SPACE", "ENTER")):
            self.showcase.toggle_pause(self.clock_ms)
        elif any(key in commands for key in ("B", "RIGHT")):
            self._showcase_step(1)
        elif any(key in commands for key in ("E", "LEFT")):
            self._showcase_step(-1)
        elif any(key in commands for key in ("A", "UP")):
            self._showcase_theme(1)
        elif any(key in commands for key in ("D", "DOWN")):
            self._showcase_theme(-1)
        self._tick_showcase()

    def _showcase_entry(self, keys, down):
        if "D" in keys:
            self._start_showcase()
            return True
        return False

    def _status_payload(self):
        value = self.controller.payload
        if not value:
            return value
        value = dict(value)
        own = dict(value.get("own") or {})
        presence = dict(own.get("presence") or {})
        age = presence.get("age_seconds")
        if isinstance(age, (int, float)) and not isinstance(age, bool):
            age += max(0, self.clock_ms - (self.controller.received_ms or 0)) / 1000
            presence["age_seconds"] = age
            if age > 5:
                presence.update(state="unknown", confirmed=False)
        own["presence"] = presence
        value["own"] = own
        return value

    def _now(self):
        ticks = time.ticks_ms()
        self.clock_ms += max(0, time.ticks_diff(ticks, self._ticks))
        self._ticks = ticks
        return self.clock_ms

    def _write_leds(self):
        frame = self.controller.led_frame(self._now())
        notification = self._visible_notification(self.clock_ms)
        urgent = notification is not None and notification.get("priority") == 5
        if urgent:
            frame = [(255, 0, 0)] * 12
        elif notification and self.clock_ms - self._notification_entered < 2500:
            frame = notification_leds(notification, self.clock_ms, self.controller.ring_brightness)
        if self.showcase is not None:
            ceiling = int(255 * self.controller.ring_brightness)
            frame = [tuple(min(channel, ceiling) for channel in colour) for colour in frame]
        if frame != self._last_leds:
            for index, colour in enumerate(frame):
                tildagonos.leds[index + 1] = colour
            tildagonos.leds.write()
            self._last_leds = frame
        payload, live = self._status_payload(), self.controller.live(self.clock_ms)
        partner = partner_active(payload, live, self.config, self.demo_mode)
        own_rgb = own_colour(payload, live, self.clock_ms, self.controller.eeh_brightness)
        if urgent:
            own_rgb = urgent_eeh_colour(self.clock_ms - self._notification_entered)
            partner = False
        if self.showcase is not None:
            ceiling = int(255 * self.controller.eeh_brightness)
            own_rgb = tuple(min(channel, ceiling) for channel in own_rgb)
        self.expansions.write_own_status(own_rgb, now_ms=self.clock_ms, heartbeat=partner)
        weather, fresh, elapsed = self._weather(self.clock_ms)
        matrix_partner = partner
        own = payload.get('own') if isinstance(payload, dict) else None
        calls = own.get('calls') if isinstance(own, dict) else None
        if isinstance(calls, (list, tuple)):
            ringing = next((call for call in calls if isinstance(call, dict)
                            and call.get('state') == 'ringing'), None)
            if ringing is not None:
                matrix_partner = live and partner_call(ringing, self.config, self.demo_mode)
        if live and isinstance(calls, list) and any(isinstance(call, dict) and call.get('state') in ('connected','hold','held','busy') for call in calls):
            payload=dict(payload)
            own=dict(own)
            own['calls']=[dict(call,elapsed_seconds=self.controller.call_elapsed(call,self.clock_ms))
                          if isinstance(call,dict) else call for call in calls]
            payload['own']=own
        self.matrix.update(payload, live, self.clock_ms, page=self.idle_pages.page(self.clock_ms),
                           partner=matrix_partner, weather_fresh=fresh)

    def _adjust_eeh_brightness(self, direction):
        self.config["eeh_brightness"] = self.controller.adjust_brightness(direction)
        self._brightness_notice_kind = "EEH"
        self._brightness_notice_until = self.clock_ms + 1100
        if not self.demo_mode:
            self._brightness_save_at = self.clock_ms + 1000

    def _adjust_ring_brightness(self, direction):
        self.config["ring_brightness"] = self.controller.adjust_ring_brightness(direction)
        self._brightness_notice_kind = "RING"
        self._brightness_notice_until = self.clock_ms + 1100
        if not self.demo_mode:
            self._brightness_save_at = self.clock_ms + 1000

    def _save_eeh_brightness(self):
        if self.showcase is not None:
            return
        if self._brightness_save_at is None:
            return
        try:
            import settings
            settings.set("threecx_monitor.eeh_brightness", self.controller.eeh_brightness)
            settings.set("threecx_monitor.ring_brightness", self.controller.ring_brightness)
            settings.set('threecx_monitor.matrix_call_brightness', self.matrix.call_brightness)
            settings.save()
        except (ImportError, OSError, ValueError):
            pass
        self._brightness_save_at = None

    def _open_settings(self):
        self.idle_pages.touch(self.clock_ms)
        self.settings_open = True
        self.settings_selected = 0
        self._brightness_notice_until = 0

    def _save_appearance(self):
        if self.showcase is not None:
            return
        if self._appearance_save_at is None:
            return
        try:
            import settings
            settings.set("threecx_monitor.theme", self.themes.selection)
            settings.set("threecx_monitor.clock_style", self.clock_style)
            settings.save()
        except (ImportError, OSError, ValueError):
            pass
        self._appearance_save_at = None

    def _adjust_appearance(self, direction):
        if self.settings_selected == 2:
            choices = ["auto"] + [item["id"] for item in self.themes.catalog()]
            current = self.themes.selection
            self.themes.select(choices[(choices.index(current) + direction) % len(choices)])
        else:
            self.clock_style = CLOCKS[(CLOCKS.index(self.clock_style) + direction) % len(CLOCKS)]
            self.config["clock_style"] = self.clock_style
        self._appearance_preview = True
        self._idle_draw_page = None
        if not self.demo_mode:
            self._appearance_save_at = self.clock_ms + 1000

    def _settings_key(self, key):
        if self.settings_selected == 5 and key in ("ENTER", "C"):
            self._start_showcase()
        elif key in ("S", "ESCAPE", "ENTER", "SPACE", "C", "F"):
            self.settings_open = False
            self._save_eeh_brightness()
            self._save_appearance()
            if self._appearance_preview:
                self.controller.detail_view = self.controller.own_view = False
                self.idle_pages.preview(self.clock_ms)
                self._appearance_preview = False
        elif key in ("UP", "A"):
            self.settings_selected = (self.settings_selected - 1) % 6
        elif key in ("DOWN", "D"):
            self.settings_selected = (self.settings_selected + 1) % 6
        elif key in ("LEFT", "E", "RIGHT", "B"):
            direction = 1 if key in ("RIGHT", "B") else -1
            if self.settings_selected == 0:
                self._adjust_ring_brightness(direction)
            elif self.settings_selected == 1:
                self._adjust_eeh_brightness(direction)
            elif self.settings_selected < 4:
                self._adjust_appearance(direction)
            elif self.settings_selected == 4 and self.showcase is None:
                self.matrix.call_brightness = max(0, min(1, round(self.matrix.call_brightness + direction * .05, 2)))
                if not self.demo_mode:
                    self._brightness_save_at = self.clock_ms + 1000

    async def _network_yield(self):
        # The separate foreground loop keeps rendering and animating the LEDs.
        await asyncio.sleep(0)

    async def background_task(self):
        matrix_task = asyncio.create_task(self._matrix_worker())
        try:
            await self._background_task()
        finally:
            # Firmware cancellation/crash paths bypass the user's _stop hook.
            # StateClient defers native TLS disposal if its worker is active.
            self.state_client.close()
            self.matrix.close()
            self.space_inputs.close()
            matrix_task.cancel()
            try:
                await matrix_task
            except asyncio.CancelledError:
                pass

    async def _matrix_worker(self):
        while not self._stopping:
            await self.matrix.flush()
            await asyncio.sleep(.05)

    async def _background_task(self):
        base_config = self._showcase_saved["config"] if self.showcase is not None else self.config
        base_demo = self._showcase_saved["demo_mode"] if self.showcase is not None else self.demo_mode
        base_controller = self._showcase_saved["controller"] if self.showcase is not None else self.controller
        if base_demo:
            while not self._stopping:
                self._now()
                self._accept_demo()
                await asyncio.sleep(0.5)
            return
        url = str(base_config.get("bridge_url") or "").rstrip("/")
        token = str(base_config.get("token") or "")
        control_token = str(base_config.get("control_token") or "")
        if not url.startswith(("http://", "https://")) or "?" in url or "#" in url or "@" in url:
            base_controller.failed("SET BRIDGE URL")
            return
        if not token or "\r" in token or "\n" in token:
            base_controller.failed("SET BRIDGE TOKEN")
            return
        import wifi
        import async_helpers
        clock_sync = ClockSync()
        ca_file = str(base_config.get("ca_file") or "ca.der")
        if not ca_file.startswith("/"):
            ca_file = __file__.replace("\\", "/").rsplit("/", 1)[0] + "/" + ca_file
        interval = max(0.5, min(5.0, float(base_config.get("poll_seconds", 0.75))))
        while not self._stopping:
            if self.showcase is not None:
                await asyncio.sleep(.1)
                continue
            generation, target, queue = self._network_generation, self.controller, self.controls
            try:
                if not wifi.status():
                    clock_sync.disconnected()
                    target.failed("CONNECTING WI-FI")
                    wifi.connect()
                    if not await wifi.async_wait(10):
                        if self._network_current(generation, target):
                            target.failed("WI-FI DISCONNECTED")
                        await asyncio.sleep(3)
                        continue
                if not self._network_current(generation, target):
                    continue
                if clock_sync.due(self._now()):
                    if not clock_valid():
                        target.failed("SYNCING CLOCK")
                    synced = await async_helpers.unblock(sync_clock, self._network_yield)
                    clock_sync.attempted(self._now(), synced)
                    if not self._network_current(generation, target):
                        continue
                if not clock_valid():
                    target.failed("CLOCK SYNC FAILED")
                    await asyncio.sleep(3)
                    continue
                intent = queue.take()
                if intent:
                    try:
                        result = await async_helpers.unblock(send_control, self._network_yield,
                                                            url, control_token, intent, ca_file)
                        if self._network_current(generation, target):
                            queue.finish(result, self._now())
                    except Exception:
                        if self._network_current(generation, target):
                            queue.fail_unknown(self._now())
                if not self._network_current(generation, target):
                    continue
                value = await async_helpers.unblock(fetch_snapshot, self._network_yield, url, token, ca_file, self.state_client)
                if not control_token or control_token == token:
                    value.setdefault("controls", {})["enabled"] = False
                if self._network_current(generation, target):
                    target.accept(value, self._now())
            except (ClockError, TLSError, HTTPError) as error:
                # These exception messages are fixed app text or HTTP status only.
                if self._network_current(generation, target):
                    target.failed(str(error))
            except Exception:
                # Do not log credentials, caller IDs, URLs, or raw response data.
                if self._network_current(generation, target):
                    target.failed("BRIDGE UNREACHABLE")
            await asyncio.sleep(interval)

    def _stop(self):
        if self.showcase is not None:
            self._end_showcase()
        self._stopping = True
        self.state_client.close()
        self._save_eeh_brightness()
        self._save_appearance()
        self.matrix.close()
        self.space_inputs.close()
        self.expansions.close()
        for index in range(1, 13):
            tildagonos.leds[index] = (0, 0, 0)
        tildagonos.leds.write()
        self.terminate(restore_pattern=True)

    def _confirm(self):
        if self.demo_mode:
            self.demo_scene = (self.demo_scene + 1) % len(SCENARIOS)
            self.controller.detail_view = False
            self.controller.own_view = False
            self._accept_demo()
        elif self.controller.own_view:
            self.controls.queue_dnd(self._status_payload(), self.controller.live(self.clock_ms), self.clock_ms)
        elif self.controller.detail_view:
            self.controller.detail_view = False
        else:
            self.controller.own_view = True

    def _physical_control(self, key):
        payload, live = self._status_payload(), self.controller.live(self.clock_ms)
        if key == "F":
            self.controls.queue_dnd(payload, live, self.clock_ms)
        else:
            target = {"A": "tb", "B": "pd", "C": "jh", "D": "sm", "E": "kz"}.get(key)
            if target:
                self.controls.queue_call(payload, live, target, self.clock_ms)

    def _phone_attention(self, now):
        """Notifications and new sensors never obscure uncertain/active calls."""
        if not self.controller.live(now) or self.controller.alert(now):
            return True
        payload = self.controller.payload or {}
        own = payload.get("own") or {}
        if own.get("state") != "idle":
            return True
        calls = own.get("calls")
        if calls and (not isinstance(calls, list) or any(not isinstance(call, dict)
                or call.get("state") not in ("ended", "completed", "disconnected", "failed", "rejected",
                                             "cancelled", "canceled", "terminated") for call in calls)):
            return True
        for member in payload.get("team") or []:
            if member.get("state") in ("ringing", "dialing"):
                return True
            calls = member.get("calls")
            if calls and (not isinstance(calls, list) or any(not isinstance(call, dict)
                    or call.get("state") in (None, "unknown", "ringing", "dialing") for call in calls)):
                return True
        return False

    def _observe_notifications(self, now):
        payload = self.controller.payload
        if (payload is not self._notification_snapshot
                or self.controller.received_ms != self._notification_received):
            self._notification_snapshot = payload
            self._notification_received = self.controller.received_ms
            if isinstance(payload, dict) and "notifications" in payload:
                entries = payload["notifications"]
                if isinstance(entries, list):
                    elapsed = max(0, now - (self.controller.received_ms or 0)) / 1000
                    entries = [dict(item, age_seconds=item["age_seconds"] + elapsed)
                               if isinstance(item, dict) and isinstance(item.get("age_seconds"), (int, float))
                               and not isinstance(item["age_seconds"], bool) else item for item in entries[:16]]
                self.notifications.observe(entries, now)
            current = self.notifications.current(now)
            if current and current["id"] not in self._notification_presented:
                self._notification_pending = current["id"]
        self.notifications.current(now)

    def _visible_notification(self, now):
        self._observe_notifications(now)
        current = self.notifications.current(now)
        urgent = current is not None and current.get("priority") == 5
        priority_call = self.controller._priority_ring_override(now)
        alert = self.controller.alert(now)
        priority_call = priority_call or bool(alert and alert.get("priority"))
        if ((priority_call if urgent else self._phone_attention(now)) or self.settings_open or self.controls.is_busy
                or now < self.controls.message_until or now < self._brightness_notice_until):
            return None
        if current and self._notification_pending == current["id"]:
            self._notification_until = now + 10000
            self._notification_entered = now
            self._notification_presented.append(current["id"])
            self._notification_presented = self._notification_presented[-64:]
            self._notification_pending = None
        if urgent or self.notifications_open or now < self._notification_until:
            return current
        return None

    def _open_notifications(self):
        self._observe_notifications(self.clock_ms)
        self.notifications_open = True
        self._notification_entered = self.clock_ms
        self._settings_hold_started = None
        self.idle_pages.touch(self.clock_ms)

    def _notification_key(self, key):
        """Modal display navigation: never invoke phone confirmation here."""
        visible = self._visible_notification(self.clock_ms)
        urgent = visible is not None and visible.get("priority") == 5
        if key in ("ESCAPE", "SPACE", "F", "CANCEL"):
            self.notifications_open = False
            self._notification_until = 0
            self._notification_pending = None
        elif urgent or not self._phone_attention(self.clock_ms):
            if urgent and key not in ("ENTER", "CONFIRM", "C"):
                return
            if key in ("RIGHT", "DOWN", "B"):
                self.notifications.next(1, self.clock_ms)
                self._notification_entered = self.clock_ms
            elif key in ("LEFT", "UP", "E"):
                self.notifications.next(-1, self.clock_ms)
                self._notification_entered = self.clock_ms
            elif key in ("ENTER", "CONFIRM", "C"):
                self.notifications.dismiss(self.clock_ms)
                self._notification_entered = self.clock_ms
                self._notification_until = self.clock_ms + 10000 if self.notifications.count else 0
        self.idle_pages.touch(self.clock_ms)

    def _space_navigation(self, events, was_idle):
        """Canonical Spaceagon sensors only navigate; they are never consent."""
        for event in events:
            kind, action = event.get("kind"), event.get("action")
            if self.settings_open:
                if kind == "joystick":
                    key = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
                           "confirm": "ENTER"}.get(action)
                    if key:
                        self._settings_key(key)
                self.idle_pages.touch(self.clock_ms)
                continue
            visible = self._visible_notification(self.clock_ms)
            if self.notifications_open or visible:
                key = {"left": "LEFT", "up": "UP", "right": "RIGHT", "down": "DOWN",
                       "confirm": "CONFIRM", "cancel": "CANCEL"}.get(action)
                if kind == "touch" and action == "rotate":
                    key = "RIGHT" if event.get("delta", 0) > 0 else "LEFT"
                if key:
                    self._notification_key(key)
                continue
            if self._phone_attention(self.clock_ms):
                self.idle_pages.touch(self.clock_ms)
                continue
            direction = 0
            if kind == "joystick":
                direction = 1 if action in ("right", "down") else -1 if action in ("left", "up") else 0
                if action == "confirm":
                    self.controller.own_view = False
                    self.controller.detail_view = False if was_idle else not self.controller.detail_view
            elif kind == "touch" and action == "rotate":
                direction = 1 if event.get("delta", 0) > 0 else -1
            elif kind == "touch" and action == "select":
                pad = event.get("pad")
                team = self.controller.page_team()
                if type(pad) is int and 1 <= pad <= 12 and team:
                    target = self.controller.page() * 12 + min(len(team) - 1, (pad - 1) * len(team) // 12)
                    self.controller.select(target - self.controller.selected)
            elif kind == "proximity" and action == "focus":
                direction = 1 if event.get("side") == "right" else -1
            if direction and was_idle:
                self.idle_pages.next(direction, self.clock_ms)
            else:
                if direction:
                    self.controller.select(direction)
                self.idle_pages.touch(self.clock_ms)

    def _run_demo_control(self):
        intent = self.controls.take()
        if not intent:
            return
        if intent["action"] == "dnd":
            self._demo_dnd = intent["enabled"]
        else:
            target = intent["target"].upper()
            self._demo_call = {"id": "demo-dial", "state": "ringing", "direction": "outbound",
                               "peer_name": target, "peer_initials": target,
                               "peer_number": "DEMO", "kind": "external" if target == "KZ" else "internal", "priority": target == "KZ"}
            self._demo_call_until = self.clock_ms + 3500
            self.controller.own_view = True
        self.controls.finish({"status": "demo"}, self.clock_ms)
        self._accept_demo()

    def update(self, delta):
        if self._stopping:
            return False
        self._now()
        if self._brightness_save_at is not None and self.clock_ms >= self._brightness_save_at:
            self._save_eeh_brightness()
        if self._appearance_save_at is not None and self.clock_ms >= self._appearance_save_at:
            self._save_appearance()
        self.expansions.refresh(self.clock_ms)
        self.space_inputs.update()
        space_events = self.space_inputs.pop()
        keyboard = self._keyboard_present()
        if self.showcase is not None:
            down = {key for key, button in FRONTBOARD_BUTTON_TYPES.items() if self.buttons.get(button)}
            edges = self.control_buttons.physical_edges(down, keyboard, self.clock_ms)
            self._showcase_input(self.expansions.pop_keys(), edges, space_events)
            self._write_leds()
            return True
        notification_mode = bool(self.notifications_open or self._visible_notification(self.clock_ms))
        if notification_mode != self._notification_input_mode:
            # A button held across a popup boundary must be released before
            # its meaning can change back to a telephone control.
            self.control_buttons = ControlButtons()
            self._notification_input_mode = notification_mode
        if keyboard != self._last_keyboard_mode:
            self._settings_hold_started = None
            self._last_keyboard_mode = keyboard
        down = {key for key, button in FRONTBOARD_BUTTON_TYPES.items() if self.buttons.get(button)}
        edges = self.control_buttons.physical_edges(down, keyboard, self.clock_ms)
        keys = self.expansions.pop_keys()
        if self._showcase_entry(keys, down):
            self._write_leds()
            return True
        self._observe_idle(self.clock_ms)
        was_idle = self.idle_pages.active(self.clock_ms)
        if edges or any(key not in ("LEFT", "RIGHT") or not was_idle for key in keys):
            self.idle_pages.touch(self.clock_ms)
        if self.settings_open:
            self._space_navigation(space_events, was_idle)
            for key in edges + keys:
                self._settings_key(key)
            self._settings_hold_started = None
            self._write_leds()
            return True
        if keyboard:
            # Open settings before processing any other keys in the same frame.
            # Physical speed-dials are suppressed for this whole frame.
            if any(key in keys for key in ("S", "T", "K")):
                self._open_settings()
                self.notifications_open = False
                self._notification_until = 0
                self.settings_selected = 2 if "T" in keys else 3 if "K" in keys else 0
                self._write_leds()
                return True
            if "N" in keys:
                self._open_notifications()
                self._write_leds()
                return True
        notification = self._visible_notification(self.clock_ms)
        if self.notifications_open or notification:
            self._settings_hold_started = None
            self._space_navigation(space_events, was_idle)
            for key in keys + edges:
                self._notification_key(key)
            self._write_leds()
            return True
        if space_events:
            self._space_navigation(space_events, was_idle)
            self._write_leds()
            return True
        if keyboard:
            for key in keys:
                if key == "ESCAPE":
                    self._stop()
                    return False
                if key == "RIGHT":
                    if was_idle:
                        self.idle_pages.next(1, self.clock_ms)
                    else:
                        self.controller.select(1)
                elif key == "LEFT":
                    if was_idle:
                        self.idle_pages.next(-1, self.clock_ms)
                    else:
                        self.controller.select(-1)
                elif key == "UP":
                    self._adjust_eeh_brightness(1)
                elif key == "DOWN":
                    self._adjust_eeh_brightness(-1)
                elif key == "SPACE":
                    self.controller.own_view = False if was_idle else not self.controller.own_view
                    self.controller.detail_view = False
                elif key == "ENTER" and self.demo_mode:
                    self._confirm()
            for key in edges:
                self._physical_control(key)
            if self.demo_mode:
                self._run_demo_control()
            self._write_leds()
            return True
        key = edges[0] if edges else None
        # Without the keyboard, hold C for settings. Its short action happens
        # on release so holding it cannot accidentally toggle DND first.
        if key == "C":
            self._settings_hold_started = self.clock_ms
            key = None
        if self._settings_hold_started is not None:
            if down - {"C"}:
                self._settings_hold_started = None
            elif "C" in down:
                if self.clock_ms - self._settings_hold_started >= 900:
                    self._open_settings()
                    self._settings_hold_started = None
            else:
                self._settings_hold_started = None
                self._confirm()
        if key == "F":
            self.buttons.clear()
            self._stop()
            return False
        if key == "B":
            self.controller.select(1)
        elif key == "E":
            self.controller.select(-1)
        elif key == "A":
            self._adjust_eeh_brightness(1)
        elif key == "D":
            self._adjust_eeh_brightness(-1)
        elif key == "C":
            self._confirm()
        self._write_leds()
        return True

    def _text(self, ctx, text, y, size=22, width=210, colour=(1, 1, 1), x=0, minimum_size=None):
        text = str(text or "")
        ctx.font_size = size
        while minimum_size is not None and size > minimum_size and ctx.text_width(text) > width:
            size -= 1
            ctx.font_size = size
        while text and ctx.text_width(text) > width:
            text = text[:-1]
        ctx.rgb(*colour).move_to(x, y).text(text)

    def _draw_number(self, ctx, number, y=35, size=28, width=206, max_lines=2):
        value = str(number or "Withheld").strip()
        if value.lower().startswith("tel:"):
            value = value[4:]
        if value and all(c in "+0123456789 ()-./" for c in value):
            value = ("+" if value.startswith("+") else "") + "".join(c for c in value if c.isdigit())
        # Numbers are never sent through _text's label truncation. Balance
        # complete chunks across lines and shrink only if the full value needs it.
        chosen, lines = size, [value]
        for candidate in range(size, 17, -1):
            ctx.font_size = candidate
            for count in range(1, max_lines + 1):
                span = (len(value) + count - 1) // count
                chunks = [value[start:start + span] for start in range(0, len(value), span)] if span else [""]
                if all(ctx.text_width(chunk) <= width for chunk in chunks):
                    chosen, lines = candidate, chunks
                    break
            else:
                continue
            break
        else:
            # The bridge bounds a number at40 characters. At18px this can need
            # additional lines; retaining every digit takes priority over labels.
            chosen, lines, chunk = 18, [], ""
            ctx.font_size = chosen
            for character in value:
                if chunk and ctx.text_width(chunk + character) > width:
                    lines.append(chunk)
                    chunk = ""
                chunk += character
            lines.append(chunk)
        step = chosen + 3
        first_y = y - (len(lines) - 1) * step / 2
        ctx.font_size = chosen
        for index, line in enumerate(lines):
            ctx.rgb(1, 1, 1).move_to(0, first_y + index * step).text(line)
        return len(lines)

    @staticmethod
    def _named_peer(call):
        peer = str(call.get("peer_name") or "").strip()
        if peer.lower() in ("unknown", "unknown caller", "anonymous", "withheld", "private", "private number", "unavailable", "external", "incoming call", "outgoing call"):
            return ""
        return peer if any(c.isalpha() for c in str(peer)) else ""

    def draw(self, ctx):
        now = self._now()
        self._tick_showcase()
        self._observe_idle(now)
        ctx.save()
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        if self.showcase is not None and self._showcase_stage.get("page") == "intro":
            self._draw_showcase_intro(ctx, now)
            self._draw_showcase_footer(ctx)
            ctx.restore()
            return
        demo = self.demo_mode or bool(self.controller.payload and self.controller.payload.get("demo"))
        live = self.controller.live(now)
        own_rgb = own_colour(self._status_payload(), live, now, 1.0)
        alert = self.controller.alert(now)
        notification = self._visible_notification(now)
        own_call = self.controller.own_call(now)
        empty_inbox = (self.notifications_open and not self._phone_attention(now)
                       and not self.settings_open and not self.controls.is_busy
                       and now >= self.controls.message_until and now >= self._brightness_notice_until)
        if notification or empty_inbox:
            self._idle_draw_page = None
            if notification:
                weather, fresh, elapsed = self._weather(now)
                local = self._local_weather_time(weather, elapsed)
                theme = self.themes.resolve(local, photo_available=self.assets.photo_available())
                draw_notification(ctx, notification, now, self._notification_entered, theme["id"])
            else:
                backdrop(ctx, now, own_rgb)
                self._text(ctx, "INBOX", -20, 32)
                self._text(ctx, "No notifications", 20, 24)
                self._text(ctx, "F: BACK", 68, 18)
            if demo and self.showcase is None:
                self._text(ctx, "DEMO", -111, 9, 40, (.55, .70, .75))
            self._draw_showcase_footer(ctx)
            ctx.restore()
            return
        graphical_idle = (live and self.idle_pages.active(now) and not self.settings_open
                          and not alert and not own_call and now >= self._brightness_notice_until
                          and now >= self.controls.message_until)
        if not graphical_idle:
            self._idle_draw_page = None
            decorated_call = dict(alert, _colour=call_colour(alert)) if alert else None
            backdrop(ctx, now, own_rgb, decorated_call, offline=not live)
        if self.settings_open and not alert:
            self._draw_settings(ctx)
        elif not self.controller.live(now):
            self._text(ctx, "OFFLINE", -20, 32)
            self._text(ctx, "No live data", 18, 24)
            self._text(ctx, "Check Wi-Fi", 53, 22)
        else:
            if alert:
                self._draw_call(ctx, alert, True)
            elif now < self._brightness_notice_until:
                level = self.controller.eeh_brightness if self._brightness_notice_kind == "EEH" else self.controller.ring_brightness
                self._text(ctx, self._brightness_notice_kind, -22, 30)
                self._text(ctx, "%d%%" % round(level * 100), 27, 52)
            elif now < self.controls.message_until:
                self._draw_notice(ctx, self.controls.message)
            elif own_call:
                self._draw_call(ctx, own_call)
            elif self.idle_pages.active(now):
                self._draw_idle(ctx, now)
            else:
                self._draw_member(ctx)
        if demo and not graphical_idle and self.showcase is None:
            self._text(ctx, "DEMO", 104, 16, 70, (0.5, 0.65, 0.7))
        self._draw_showcase_footer(ctx)
        ctx.restore()

    def _observe_idle(self, now):
        self._observe_notifications(now)
        self.idle_pages.observe(self._status_payload(), self.controller.live(now), now)
        weather, fresh, elapsed = self._weather(now)
        local = self._local_weather_time(weather, elapsed)
        theme = self.themes.resolve(local, photo_available=self.assets.photo_available())
        sky = self._sky(weather, elapsed, local)
        pages = ["weather", "rain", "clock", "moon"]
        upcoming = sky.get("next_shower") or {}
        if sky.get("active_showers") or 0 <= upcoming.get("peak_in_days", 999) <= 7:
            pages.append("meteors")
        if theme.get("advent"):
            pages.append("advent")
        self.idle_pages.set_pages(pages, now)
        if self.showcase is not None:
            page = (self._showcase_stage or {}).get("page")
            if page in ("weather", "rain", "clock", "moon", "meteors", "advent"):
                self.idle_pages.set_pages([page], now)
                self.idle_pages.preview(now)
            else:
                # Zero quiet delay belongs to the curated idle scenes only.
                # Detail/status cues must stay on their actual phone view.
                self.idle_pages.set_pages([], now)
            return
        if (self.settings_open or self._settings_hold_started is not None
                or now < self._brightness_notice_until or now < self.controls.message_until
                or self.controls.is_busy or self.notifications_open
                or self._visible_notification(now)):
            self.idle_pages.touch(now)

    def _weather(self, now):
        weather = (self.controller.payload or {}).get("weather")
        weather = weather if isinstance(weather, dict) else {}
        elapsed = max(0, now - (self.controller.received_ms or 0))
        fresh = (weather.get("live") is True and weather.get("stale") is not True
                 and data_fresh(weather, elapsed, max_age_seconds=1800))
        return weather, fresh, elapsed

    @staticmethod
    def _local_weather_time(weather, elapsed):
        if not isinstance(weather, dict):
            return None
        stamp = weather.get("now_unix")
        offset = weather.get("utc_offset_seconds")
        if (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and isinstance(offset, (int, float)) and not isinstance(offset, bool)
                and 1577836800 <= stamp <= 4102444800 and -86400 < offset < 86400):
            # ESP32 MicroPython uses a2000 epoch; desktop Python uses1970.
            epoch = 946684800 if time.gmtime(0)[0] == 2000 else 0
            try:
                return time.gmtime(int(stamp + offset + elapsed // 1000 - epoch))
            except (ValueError, OverflowError):
                return None
        return None

    def _sky(self, weather, elapsed, local):
        stamp = weather.get("now_unix")
        stamp = (int(stamp + elapsed // 1000) if isinstance(stamp, (int, float))
                 and not isinstance(stamp, bool) and 946684800 <= stamp < 4133980800 else None)
        if stamp != self._sky_key or self._sky_value is None:
            self._sky_key, self._sky_value = stamp, sky_snapshot(stamp, local)
        return self._sky_value

    def _draw_idle(self, ctx, now):
        page = self.idle_pages.page(now)
        weather, fresh, elapsed = self._weather(now)
        local = self._local_weather_time(weather, elapsed)
        sky = self._sky(weather, elapsed, local)
        theme = self.themes.resolve(local, photo_available=self.assets.photo_available())
        asset_id = theme["id"]
        def photo_draw(canvas, tick):
            return self.assets.draw_photo(canvas, tick, theme_id=asset_id)
        theme["photo_draw"] = photo_draw
        render_theme = "photo" if self.assets.photo_available(asset_id) else theme["id"]
        # Independent dials own their full-screen background; skip outer
        # theme navigation chrome which would overlap the expanded face.
        if page == "clock" and self.clock_style in ("haute_celestial", "neon_orrery", "mondaine", "great_british_railways"):
            render_theme = "original"
        clock_draw = None
        if self.clock_style != "original":
            def clock_draw(canvas, palette):
                return draw_clock_content(canvas, self.clock_style, weather, local, elapsed, now,
                                          palette=palette, sky=sky, artwork=self.clock_art.draw)
            theme["clock_draw"] = clock_draw
        own_rgb = own_colour(self._status_payload(), self.controller.live(now), now, 1.0)
        if page != self._idle_draw_page:
            self._idle_draw_page = page
            self._idle_entered_ms = now
        progress = max(0, min(1, (now - self._idle_entered_ms) / 240))
        ctx.save()
        if progress < 1:
            ctx.rgb(0.015, 0.025, 0.05).rectangle(-120, -120, 240, 240).fill()
            scale = 0.91 + 0.09 * (1 - (1 - progress) ** 3)
            ctx.scale(scale, scale)
        demo = self.demo_mode or bool((self.controller.payload or {}).get("demo"))
        if not draw_astro_face(ctx, page, weather, fresh, local, elapsed, now, own_rgb, demo=demo, sky=sky):
            if not draw_theme_face(ctx, page, render_theme, weather, fresh, local, elapsed, now,
                                   own_rgb, demo=demo, context=theme):
                parallax = (self.config.get("space_tilt") is True and self.space_inputs.motion_valid
                            and render_theme == "original" and page in ("weather", "rain", "clock"))
                if parallax:
                    ctx.rgb(.015, .025, .05).rectangle(-120, -120, 240, 240).fill()
                    ctx.save()
                    ctx.translate(max(-1, min(1, self.space_inputs.tilt[0])) * 4,
                                  max(-1, min(1, self.space_inputs.tilt[1])) * 4)
                try:
                    draw_idle_face(ctx, page, weather, fresh, local, elapsed, now, own_rgb,
                                   demo=demo, clock_draw=clock_draw)
                finally:
                    if parallax:
                        ctx.restore()
        ctx.restore()

    def _draw_settings(self, ctx):
        self._text(ctx, "SETTINGS", -67, 25, 180)
        rows = (("RING", self.controller.ring_brightness), ("EEH", self.controller.eeh_brightness),
                ("THEME", "Auto" if self.themes.selection == "auto" else next(item["name"] for item in self.themes.catalog() if item["id"] == self.themes.selection)),
                ("CLOCK", next(item["name"] for item in get_clock_catalog() if item["id"] == self.clock_style)),
                ("MATRIX CALL", "%d%%" % round(self.matrix.call_brightness * 100)),
                ("DEMO", "Play all themes"))
        start = max(0, self.settings_selected - 1)
        for index in range(start, min(6, start + 2)):
            label, level = rows[index]
            row = index - start
            settings_row(ctx, row, level if index < 2 else 0, self.settings_selected == index)
            y = -18 + row * 57
            colour = (0.25, 1, 0.85) if self.settings_selected == index else (0.6, 0.65, 0.7)
            if index < 2:
                self._text(ctx, label, y - 11, 20, 84, colour, x=-49)
                self._text(ctx, "%d%%" % round(level * 100), y, 34, 103, colour, x=48)
            else:
                self._text(ctx, label, y - 16, 12, 120, colour)
                self._text(ctx, level, y + 5, 25, 192, colour, minimum_size=16)
        finish = "PLAY" if self.settings_selected == 5 else "DONE"
        self._text(ctx, ("ENTER: " if self._keyboard_present() else "C: ") + finish, 88, 18, 152, (0.6, 0.7, 0.7))

    def _draw_showcase_intro(self, ctx, now):
        stage = self._showcase_stage
        backdrop(ctx, now, (0, 145, 25))
        self._text(ctx, "DEMO TOUR", -70, 19, 150, (.31, .90, 1))
        self._text(ctx, "THEME %d / %d" % (stage["theme_index"] + 1, stage["theme_count"]), -39, 16)
        self._text(ctx, stage["theme_name"], 2, 34, 202, minimum_size=22)
        caption = "%d FEATURES" % stage["step_count"] if stage.get("available", True) else "ART UNAVAILABLE"
        self._text(ctx, caption, 42, 17, 175, (.65, .75, .85))
        self._text(ctx, "C PAUSE / F EXIT", 73, 13, 174, (.65, .75, .85))

    def _draw_showcase_footer(self, ctx):
        if self.showcase is None:
            return
        stage = self._showcase_stage
        notification = stage.get("feature") == "notification"
        y = -109 if notification else 106
        ctx.rgb(.012, .026, .055).round_rectangle(-58, y - 8, 116, 16, 6).fill()
        prefix = "DEMO PAUSE" if self.showcase.paused else "DEMO"
        self._text(ctx, "%s %d/%d %d/%d" % (prefix, stage["theme_index"] + 1, stage["theme_count"],
                   stage["step_index"] + 1, stage["step_count"]), y, 9, 112, (1, .79, .36), minimum_size=8)

    def _draw_notice(self, ctx, message):
        notice_panel(ctx)
        words = str(message).split()
        middle = max(1, len(words) // 2)
        self._text(ctx, " ".join(words[:middle]), -17, 25)
        self._text(ctx, " ".join(words[middle:]), 19, 25)

    def _draw_call(self, ctx, call, incoming=False):
        colour = tuple(value / 255 for value in call_colour(call))
        label = call_label(call)
        state = call.get('state')
        elapsed = self.controller.call_elapsed(call, self.clock_ms)
        timer = ('%d:%02d:%02d' % (elapsed // 3600, elapsed // 60 % 60, elapsed % 60)
                 if elapsed is not None and elapsed >= 3600 else
                 '%02d:%02d' % (elapsed // 60, elapsed % 60) if elapsed is not None else '')
        beloved = partner_call(call, self.config, self.demo_mode)
        if beloved:
            self._text(ctx, str(self.config.get("partner_name") or "Partner"), -76, 38, 182)
            self._text(ctx, str(self.config.get("partner_surname") or ""), -40, 24, 194)
            if timer:
                ctx.save()
                ctx.translate(0, -6)
                ctx.scale(.84, .84)
                draw_bunny(ctx, self.clock_ms)
                ctx.restore()
            else:
                draw_bunny(ctx, self.clock_ms)
            if timer:
                self._text(ctx, timer, 106, 17, 140, colour)
            return
        if not incoming:
            self._text(ctx, 'ON HOLD' if state in ('hold','held') else 'ON CALL' if state in ('connected','busy') else 'CALLING',
                       -76, 22, 190, colour)
            peer = self._named_peer(call)
            if peer:
                self._text(ctx, peer, -28, 44, 210, minimum_size=18)
            else:
                self._draw_number(ctx, call.get('peer_number') or call.get('peer_extension'), y=-22, size=32)
            if timer:
                self._text(ctx, timer, 40, 39, 194, minimum_size=27)
            else:
                self._text(ctx, 'DIALLING' if state == 'dialing' else 'RINGING', 38, 24, 190, colour)
            direction = 'OUTGOING' if call.get('direction') == 'outbound' else 'INCOMING' if call.get('direction') == 'inbound' else 'CALL'
            self._text(ctx, direction + ' / ' + label.replace('PRIORITY / ', ''), 84, 14, 194, colour, minimum_size=10)
            return
        self._text(ctx, str(self.config.get("partner_name") or "Partner").upper() if beloved else "PRIORITY" if call.get("priority") else label,
                   -63, 24, 155 if beloved else 190, colour)
        peer = self._named_peer(call)
        if peer:
            self._text(ctx, peer, -20, 48, 210, minimum_size=18)
            number_lines = 0
        else:
            number_lines = self._draw_number(ctx, call.get("peer_number"), y=5, size=34)
        route = call.get("queue_name") or call.get("queue_number") or call.get("ddi") or ""
        detail = label.replace("PRIORITY / ", "") if call.get("priority") else route
        self._text(ctx, detail, 84 if peer and number_lines > 1 else 72,
                   18 if peer and number_lines > 1 else 20, 178,
                   colour if call.get("priority") else (0.7, 0.75, 0.8))

    def _draw_member(self, ctx):
        if not self.controller.own_view and not self.controller.detail_view and 0 < len(self.controller.page_team()) <= 4:
            self._draw_team_overview(ctx)
            return
        member = self.controller.focused()
        if not member:
            self._text(ctx, "No team", 0, 28)
            return
        name = "ME" if self.controller.own_view else initials(member.get("name"), member.get("extension"))
        colour = self._member_colour(member)
        calls = member.get("calls") or []
        if calls:
            self._text(ctx, name, -63, 30, 180, colour)
            call = calls[0]
            if not self.controller.own_view:
                if call.get("kind") == "internal":
                    self._draw_number(ctx, call.get("peer_extension") or call.get("peer_number"), y=-9, size=44)
                    self._text(ctx, call.get("peer_first_name") or "", 38, 28, 205, minimum_size=18)
                else:
                    self._text(ctx, "External", 4, 38, 210)
                if len(calls) > 1:
                    self._text(ctx, "+%d" % (len(calls) - 1), -63, 18, 48, x=76)
                return
            peer = self._named_peer(call)
            if peer:
                self._text(ctx, peer, -20, 44, 210, minimum_size=18)
                number_lines = 0
            else:
                number_lines = self._draw_number(ctx, call.get("peer_number"), y=4, size=34)
            self._text(ctx, call_label(call), 82 if peer and number_lines > 1 else 70,
                       18 if peer and number_lines > 1 else 20, 180,
                       tuple(value / 255 for value in call_colour(call)))
            if len(calls) > 1:
                self._text(ctx, "+%d" % (len(calls) - 1), -63, 18, 48, x=76)
        else:
            self._text(ctx, name, -2, 72, 200, colour)

    def _member_colour(self, member):
        colours = {"idle": (0.15, 1, 0.25), "busy": (1, 0.2, 0.2),
                   "ringing": (1, 0.65, 0.05), "unknown": (0.45, 0.45, 0.5)}
        if self.controller.own_view:
            return tuple(v / 255 for v in own_colour(self._status_payload(), self.controller.live(self.clock_ms), self.clock_ms, 1.0))
        return colours.get(member.get("state"), colours["unknown"])

    def _draw_team_overview(self, ctx):
        team = self.controller.page_team()
        for index, member in enumerate(team):
            x, y = (-52 if index % 2 == 0 else 52), (-30 if index < 2 else 47)
            name = initials(member.get("name"), member.get("extension"))
            colour = self._member_colour(member)
            team_card(ctx, x, y, colour, member.get("state") == "ringing", self.clock_ms)
            calls = member.get("calls") or []
            if calls:
                call = calls[0]
                self._text(ctx, name, y - 22, 26, 76, colour, x=x)
                if call.get("kind") == "internal":
                    extension = call.get("peer_extension") or call.get("peer_number") or "?"
                    self._text(ctx, extension, y + 4, 30, 90, x=x)
                    self._text(ctx, call.get("peer_first_name") or "", y + 28, 20, 92,
                               (0.7, 0.75, 0.8), x=x, minimum_size=14)
                else:
                    self._text(ctx, "External", y + 8, 22, 102, x=x)
            else:
                self._text(ctx, name, y, 52, 94, colour, x=x)


__app_export__ = ThreeCXMonitor
