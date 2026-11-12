"""Tildagon / Spaceagon 3CX BLF and Caller ID display."""

import app
import asyncio
import json
import time

from app_components import clear_background
from events.input import Buttons, BUTTON_TYPES
from frontboards.common import FRONTBOARD_BUTTON_TYPES
from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable
from tildagonos import tildagonos

from .controller import Controller, call_colour, call_label
from .demo import SCENARIOS, snapshot
from .http_client import get_json, post_json, StateClient, ClockError, TLSError, HTTPError
from .controls import ControlButtons, ControlQueue, initials, own_colour
from .expansions import ExpansionManager
from .idle import IdlePages, data_fresh
from .idle_faces import draw_idle_face
from .visuals import backdrop, team_card, settings_row, notice_panel
from .themes import ThemeManager
from .theme_assets import ThemeAssetStore
from .theme_art import draw_theme_face
from .clocks import CLOCKS, get_clock_catalog, draw_clock_content
from .astronomy import sky_snapshot
from .astro_faces import draw_astro_face
from .matrix import MatrixDisplay
from .love import partner_call, partner_active, draw_love


DEFAULT_CONFIG = {
    "demo": True, "bridge_url": "", "token": "",
    "poll_seconds": 0.75, "eeh_brightness": 0.03, "ring_brightness": 0.15, "ca_file": "ca.der",
    "control_token": "", "demo_keyboard": False,
    "idle_seconds": 60, "rotate_seconds": 12,
    "theme": "original", "theme_auto": False, "clock_style": "original",
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
        self._demo_dnd = False
        self._demo_call = None
        self._demo_call_until = 0
        eventbus.emit(PatternDisable())
        tildagonos.set_led_power(True)
        if self.demo_mode:
            self._accept_demo()

    def _accept_demo(self):
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
        self.controller.accept(value, self.clock_ms)

    def _keyboard_present(self):
        return self.expansions.keyboard_present or (self.demo_mode and self.config.get("demo_keyboard") is True)

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
        if frame != self._last_leds:
            for index, colour in enumerate(frame):
                tildagonos.leds[index + 1] = colour
            tildagonos.leds.write()
            self._last_leds = frame
        payload, live = self._status_payload(), self.controller.live(self.clock_ms)
        partner = partner_active(payload, live, self.config, self.demo_mode)
        self.expansions.write_own_status(own_colour(payload, live, self.clock_ms,
            self.controller.eeh_brightness), now_ms=self.clock_ms, heartbeat=partner)
        weather, fresh, elapsed = self._weather(self.clock_ms)
        self.matrix.update(payload, live, self.clock_ms, page=self.idle_pages.page(self.clock_ms),
                           partner=partner, weather_fresh=fresh)

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
        if self._brightness_save_at is None:
            return
        try:
            import settings
            settings.set("threecx_monitor.eeh_brightness", self.controller.eeh_brightness)
            settings.set("threecx_monitor.ring_brightness", self.controller.ring_brightness)
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
        if key in ("S", "ESCAPE", "ENTER", "SPACE", "C", "F"):
            self.settings_open = False
            self._save_eeh_brightness()
            self._save_appearance()
            if self._appearance_preview:
                self.controller.detail_view = self.controller.own_view = False
                self.idle_pages.preview(self.clock_ms)
                self._appearance_preview = False
        elif key in ("UP", "A"):
            self.settings_selected = (self.settings_selected - 1) % 4
        elif key in ("DOWN", "D"):
            self.settings_selected = (self.settings_selected + 1) % 4
        elif key in ("LEFT", "E", "RIGHT", "B"):
            direction = 1 if key in ("RIGHT", "B") else -1
            if self.settings_selected == 0:
                self._adjust_ring_brightness(direction)
            elif self.settings_selected == 1:
                self._adjust_eeh_brightness(direction)
            else:
                self._adjust_appearance(direction)

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
        if self.demo_mode:
            while not self._stopping:
                self._now()
                self._accept_demo()
                await asyncio.sleep(0.5)
            return
        url = str(self.config.get("bridge_url") or "").rstrip("/")
        token = str(self.config.get("token") or "")
        control_token = str(self.config.get("control_token") or "")
        if not url.startswith(("http://", "https://")) or "?" in url or "#" in url or "@" in url:
            self.controller.failed("SET BRIDGE URL")
            return
        if not token or "\r" in token or "\n" in token:
            self.controller.failed("SET BRIDGE TOKEN")
            return
        import wifi
        import async_helpers
        ca_file = str(self.config.get("ca_file") or "ca.der")
        if not ca_file.startswith("/"):
            ca_file = __file__.replace("\\", "/").rsplit("/", 1)[0] + "/" + ca_file
        interval = max(0.5, min(5.0, float(self.config.get("poll_seconds", 0.75))))
        while not self._stopping:
            try:
                if not wifi.status():
                    self.controller.failed("CONNECTING WI-FI")
                    wifi.connect()
                    if not await wifi.async_wait(10):
                        self.controller.failed("WI-FI DISCONNECTED")
                        await asyncio.sleep(3)
                        continue
                intent = self.controls.take()
                if intent:
                    try:
                        result = await async_helpers.unblock(send_control, self._network_yield,
                                                            url, control_token, intent, ca_file)
                        self.controls.finish(result, self._now())
                    except Exception:
                        self.controls.fail_unknown(self._now())
                value = await async_helpers.unblock(fetch_snapshot, self._network_yield, url, token, ca_file, self.state_client)
                if not control_token or control_token == token:
                    value.setdefault("controls", {})["enabled"] = False
                self.controller.accept(value, self._now())
            except (ClockError, TLSError, HTTPError) as error:
                # These exception messages are fixed app text or HTTP status only.
                self.controller.failed(str(error))
            except Exception:
                # Do not log credentials, caller IDs, URLs, or raw response data.
                self.controller.failed("BRIDGE UNREACHABLE")
            await asyncio.sleep(interval)

    def _stop(self):
        self._stopping = True
        self.state_client.close()
        self._save_eeh_brightness()
        self._save_appearance()
        self.matrix.close()
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
        keyboard = self._keyboard_present()
        if keyboard != self._last_keyboard_mode:
            self._settings_hold_started = None
            self._last_keyboard_mode = keyboard
        down = {key for key, button in FRONTBOARD_BUTTON_TYPES.items() if self.buttons.get(button)}
        edges = self.control_buttons.physical_edges(down, keyboard, self.clock_ms)
        keys = self.expansions.pop_keys()
        self._observe_idle(self.clock_ms)
        was_idle = self.idle_pages.active(self.clock_ms)
        if edges or any(key not in ("LEFT", "RIGHT") or not was_idle for key in keys):
            self.idle_pages.touch(self.clock_ms)
        if self.settings_open:
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
                self.settings_selected = 2 if "T" in keys else 3 if "K" in keys else 0
                self._write_leds()
                return True
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
        peer = call.get("peer_initials") or initials(call.get("peer_name"), call.get("peer_number"))
        return peer if any(c.isalpha() for c in str(peer)) else ""

    def draw(self, ctx):
        now = self._now()
        self._observe_idle(now)
        ctx.save()
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        demo = self.demo_mode or bool(self.controller.payload and self.controller.payload.get("demo"))
        live = self.controller.live(now)
        own_rgb = own_colour(self._status_payload(), live, now, 1.0)
        alert = self.controller.alert(now)
        graphical_idle = (live and self.idle_pages.active(now) and not self.settings_open
                          and not alert and now >= self._brightness_notice_until
                          and now >= self.controls.message_until)
        if not graphical_idle:
            self._idle_draw_page = None
            decorated_call = dict(alert, _colour=call_colour(alert)) if alert else None
            backdrop(ctx, now, own_rgb, decorated_call, offline=not live)
            self._text(ctx, "MB", -98, 24, 90, tuple(v / 255 for v in own_rgb))
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
            elif self.idle_pages.active(now):
                self._draw_idle(ctx, now)
            else:
                self._draw_member(ctx)
        if demo and not graphical_idle:
            self._text(ctx, "DEMO", 104, 16, 70, (0.5, 0.65, 0.7))
        ctx.restore()

    def _observe_idle(self, now):
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
        if (self.settings_open or self._settings_hold_started is not None
                or now < self._brightness_notice_until or now < self.controls.message_until
                or self.controls.is_busy):
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
        clock_draw = None
        if self.clock_style != "original":
            def clock_draw(canvas, palette):
                return draw_clock_content(canvas, self.clock_style, weather, local, elapsed, now,
                                          palette=palette, sky=sky)
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
                draw_idle_face(ctx, page, weather, fresh, local, elapsed, now, own_rgb,
                               demo=demo, clock_draw=clock_draw)
        ctx.restore()

    def _draw_settings(self, ctx):
        self._text(ctx, "SETTINGS", -67, 25, 180)
        rows = (("RING", self.controller.ring_brightness), ("EEH", self.controller.eeh_brightness),
                ("THEME", "Auto" if self.themes.selection == "auto" else next(item["name"] for item in self.themes.catalog() if item["id"] == self.themes.selection)),
                ("CLOCK", next(item["name"] for item in get_clock_catalog() if item["id"] == self.clock_style)))
        start = max(0, self.settings_selected - 1)
        for index in range(start, min(4, start + 2)):
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
        self._text(ctx, "ENTER: DONE" if self._keyboard_present() else "C: DONE", 88, 18, 152, (0.6, 0.7, 0.7))

    def _draw_notice(self, ctx, message):
        notice_panel(ctx)
        words = str(message).split()
        middle = max(1, len(words) // 2)
        self._text(ctx, " ".join(words[:middle]), -17, 25)
        self._text(ctx, " ".join(words[middle:]), 19, 25)

    def _draw_call(self, ctx, call, incoming=False):
        colour = tuple(value / 255 for value in call_colour(call))
        label = call_label(call)
        beloved = partner_call(call, self.config, self.demo_mode)
        if beloved:
            draw_love(ctx, self.clock_ms)
        self._text(ctx, str(self.config.get("partner_name") or "Partner").upper() if beloved else "PRIORITY" if call.get("priority") else label,
                   -63, 24, 155 if beloved else 190, colour)
        peer = self._named_peer(call)
        if peer:
            self._text(ctx, peer, -20, 48, 210)
            number_lines = self._draw_number(ctx, call.get("peer_number"), y=39, size=26)
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
                self._text(ctx, peer, -20, 44, 210)
                number_lines = self._draw_number(ctx, call.get("peer_number"), y=36, size=26)
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
