"""Fail-closed adapter for Kristian Hentschel's Liteloop matrix hexpansion.

Only the exact CAFE:54E1 / Liteloop header is supported. Its monochrome LEDs
have a fixed colour: RGB colour is not available. No GPIO, port-power,
bootloader, firmware, EEPROM, or SD-card writes are performed here.

Protocol and grid: manufacturer companion app b7202429, board_liteloop.py;
firmware 873f484f, firmware/shared/core_registers.h.
https://github.com/kristianhentschel/tildagon-matrix-hexpansion-app
"""

import asyncio
from .matrix_text import caller_text, columns

# Physical grid derived from the manufacturer's MIT-licensed companion app.
# Copyright (c)2026 Kristian Hentschel.
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

VID, PID, NAME = 0xCAFE, 0x54E1, "Liteloop"
ADDRESS, DIRECT_REGISTER, LED_COUNT = 0x20, 0x50, 156
WIDTH, HEIGHT = 18, 9

# Physical LED numbers in display order, not wiring order. The manufacturer's
# top row is shorter; the right-hand six columns have their own wiring order.
GRID = (
    -1, -1, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, -1, -1, -1,
    12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 114, 115, 116, 117, 118, 119,
    24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 126, 127, 128, 129, 130, 131,
    36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 138, 139, 140, 141, 142, 143,
    48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 150, 151, 152, 153, 154, 155,
    60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 108, 109, 110, 111, 112, 113,
    72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 120, 121, 122, 123, 124, 125,
    84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 132, 133, 134, 135, 136, 137,
    96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 144, 145, 146, 147, 148, 149,
)

_GLYPHS = {
    "heart": ("01100110", "11111111", "11111111", "11111111", "01111110", "00111100", "00011000"),
    "heart_small": ("00000000", "00100100", "01111110", "01111110", "00111100", "00011000", "00000000"),
    "available": ("000000001", "000000011", "000000110", "110001100", "011011000", "001110000", "000100000"),
    "dnd": ("001111100", "011000110", "110000011", "111111111", "110000011", "011000110", "001111100"),
    "away": ("001111100", "011000110", "110010011", "100010001", "110011011", "011000110", "001111100"),
    "unknown": ("00111100", "01100110", "00000110", "00011100", "00011000", "00000000", "00011000"),
    "busy": ("11000011", "11100111", "01111110", "00111100", "01111110", "11100111", "11000011"),
    "ringing": ("10011001", "10111101", "01111110", "01111110", "11111111", "00011000", "00000000"),
    "internal": ("0011100", "0001000", "0001000", "0001000", "0001000", "0001000", "0011100"),
    "queue": ("00111100", "01100110", "11000011", "11000011", "11011011", "01101110", "00111101"),
    "ddi": ("11111000", "11001100", "11000110", "11000110", "11000110", "11001100", "11111000"),
    "external": ("11111110", "11000000", "11000000", "11111100", "11000000", "11000000", "11111110"),
    "sun": ("100010001", "010111010", "001111100", "111111111", "001111100", "010111010", "100010001"),
    "moon": ("00111100", "01111000", "11110000", "11100000", "11110000", "01111001", "00111110"),
    "cloud": ("000110000", "001111100", "011111110", "111111111", "111111111", "000000000", "000000000"),
    "rain": ("000110000", "001111100", "011111110", "111111111", "000000000", "010010010", "100100100"),
    "snow": ("1001001", "0101010", "0011100", "1111111", "0011100", "0101010", "1001001"),
    "storm": ("000110000", "001111100", "011111110", "111111111", "000110000", "001100000", "001000000"),
    "fog": ("000000000", "011111110", "000000000", "111111111", "000000000", "011111110", "000000000"),
    "dry": ("001111100", "011000110", "110010011", "100010001", "110000011", "011000110", "001111100"),
}


def _glyph_pixels(glyph):
    """Cache coordinates once, avoiding string/row allocations while drawing."""
    left, top = (WIDTH - len(glyph[0])) // 2, (HEIGHT - len(glyph)) // 2
    return tuple(GRID[(top + y) * WIDTH + left + x]
                 for y, row in enumerate(glyph) for x, cell in enumerate(row)
                 if cell == "1" and GRID[(top + y) * WIDTH + left + x] >= 0)


_PIXELS = {name: _glyph_pixels(glyph) for name, glyph in _GLYPHS.items()}
_ACTIVE = ("ringing", "dialing", "connected", "busy", "hold", "held")


def matches_header(header):
    return (getattr(header, "vid", None) == VID
            and getattr(header, "pid", None) == PID
            and getattr(header, "friendly_name", None) == NAME)


def _dict(value):
    return value if isinstance(value, dict) else {}


def _active_calls(own):
    calls = own.get("calls")
    if not isinstance(calls, (list, tuple)):
        return []
    return [call for call in calls if isinstance(call, dict) and call.get("state") in _ACTIVE]


def _scene(payload, live, page, partner, weather_fresh):
    """Choose semantic symbols from confirmed state, never from caller text."""
    if not live:
        return "unknown"
    payload = _dict(payload)
    own = _dict(payload.get("own"))
    calls = _active_calls(own)
    if calls:
        if partner:
            return "heart"
        ringing = [call for call in calls if call.get("state") == "ringing"]
        call = ringing[0] if ringing else calls[0]
        if call.get("state") == "ringing" and call.get("direction") != "outbound":
            return "caller"
        if call.get("state") in ("ringing", "dialing"):
            kind = call.get("kind")
            return kind if kind in ("internal", "queue", "ddi", "external") else "ringing"
        return "busy"
    if page in ("weather", "rain"):
        weather = _dict(payload.get("weather"))
        if (weather_fresh is not True or weather.get("live") is not True
                or weather.get("stale") is True):
            return "unknown"
        if page == "rain":
            rain = _dict(weather.get("rain_next_hour"))
            if rain.get("status") == "rain_likely":
                return "rain"
            if rain.get("status") == "dry_likely":
                return "dry"
            return "unknown"
        current = _dict(weather.get("current"))
        code = current.get("weather_code")
        if isinstance(code, bool) or not isinstance(code, int):
            return "unknown"
        if code == 0:
            return "sun" if current.get("is_day") in (True, 1) else "moon"
        if code in (1, 2, 3):
            return "cloud"
        if code in (45, 48):
            return "fog"
        if code in (71, 73, 75, 77, 85, 86):
            return "snow"
        if code in (95, 96, 99):
            return "storm"
        if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            return "rain"
        return "unknown"
    presence = _dict(own.get("presence"))
    age = presence.get("age_seconds", 0)
    if (presence.get("confirmed") is not True or isinstance(age, bool)
            or not isinstance(age, (int, float)) or not 0 <= age <= 5):
        return "unknown"
    state = presence.get("state")
    return state if state in ("available", "dnd", "away") else "unknown"


class MatrixDisplay:
    """One known Liteloop, hotplug safe, coalesced eight-FPS target frames.

    config['matrix'] may contain type='Liteloop', slot=1..6, enabled=False,
    brightness=0..1. Omitted slot auto-selects only a unique exact header.
    Callers supply the same live/weather_fresh flags as the LCD. partner=True
    is an explicit, upstream exact-number match, not a substring of a name.

    update() only queues a goal. A single background coroutine must await
    flush() periodically; it sends at most24 one-byte PWM register writes,
    yielding after each group of8 successful bytes. The pinned native I2C driver holds the GIL and has
    a length-dependent timeout: limiting each transaction bounds a fault to
    about500ms instead of16seconds for a bulk frame. No automatic retries
    happen within flush(). close() is immediate and performs no I/O; the
    co-processor retains its last frame until powered off or taken over.
    """

    def __init__(self, config=None, backend=None):
        if backend is None:
            from .expansions import FirmwareBackend
            backend = FirmwareBackend()
        self.backend = backend
        config = _dict(config)
        self.setting = config.get("matrix", {})
        call_level = _dict(self.setting).get('call_brightness', 1.0)
        self.call_brightness = (call_level if isinstance(call_level, (int, float))
                                and not isinstance(call_level, bool) and 0 <= call_level <= 1 else 1.0)
        self.ready = False
        self.status = "MATRIX NOT CONNECTED"
        self.slot = None
        self.last_mode = None
        self.frames_written = 0
        self.displayed_mode = None
        self._bus = None
        self._header = None
        self._last_frame = None
        self._last_write_ms = None
        self._retry_at = 0
        self._closed = False
        self._flushing = False
        self._goal_pending = False
        self._goal_peak = None
        self._clock_ms = 0
        self._actual = bytearray(LED_COUNT)
        self._known = bytearray(LED_COUNT)
        self._cursor = 1
        self._phase = 0
        self._byte = bytearray(1)
        self._packet = bytearray(LED_COUNT + 1)
        self._packet[0] = 3
        self._zero = bytes(LED_COUNT)
        self._peak = 38
        self._scroll_key = None
        self._scroll_columns = ()
        self._scroll_position = 0
        self._scroll_next = 0
        self.refresh(0)

    def _drop(self, status):
        self.ready = False
        self.status = status
        self._bus = None
        self._header = None
        self.slot = None
        self._last_frame = None
        self.last_mode = None
        self.displayed_mode = None
        self._goal_pending = False

        self._scroll_key = None

    def refresh(self, now_ms):
        if self._closed:
            return False
        setting = self.setting
        if setting is False or (isinstance(setting, dict) and setting.get("enabled") is False):
            self._drop("MATRIX OFF")
            return False
        if not isinstance(setting, dict):
            self._drop("MATRIX CONFIG INVALID")
            return False
        slot = setting.get("slot")
        level = setting.get("brightness", 0.15)
        if (setting.get("type", NAME) != NAME
                or (slot is not None and (isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 6))
                or isinstance(level, bool) or not isinstance(level, (int, float)) or not 0 <= level <= 1):
            self._drop("MATRIX CONFIG INVALID")
            return False
        self._peak = int(level * 255)
        try:
            drivers, attached, running = self.backend.snapshot()
            headers = self.backend.headers()
            candidates = [number for number in attached
                          if isinstance(number, int) and not isinstance(number, bool)
                          and 1 <= number <= 6 and (slot is None or number == slot)
                          and matches_header(headers.get(number))]
        except Exception:
            self._drop("MATRIX UNAVAILABLE")
            return False
        if len(candidates) != 1:
            self._drop("MATRIX CHOOSE SLOT" if len(candidates) > 1 else "MATRIX NOT CONNECTED")
            return False
        slot = candidates[0]
        if slot in drivers:
            self._drop("MATRIX SLOT IN USE")
            return False
        if any(app.__class__.__name__ == "MatrixHexpansionApp" for app in running):
            self._drop("CLOSE MATRIX APP")
            return False
        header = headers[slot]
        if self._bus is not None and self.slot == slot and self._header is header:
            return True
        if now_ms < self._retry_at:
            return False
        try:
            self._bus = self.backend.matrix_i2c(slot)
        except Exception:
            self._drop("MATRIX DRIVER ERROR")
            self._retry_at = now_ms + 2000
            return False
        self._header = header
        self.slot = slot
        self.ready = True
        self.status = "MATRIX READY"
        self._last_frame = None
        self._last_write_ms = None
        self._actual[:] = self._zero
        self._known[:] = self._zero
        self._cursor = 1
        self._phase = 0
        self._scroll_key = None
        return True

    def update(self, payload, live, now_ms, page=None, partner=False, weather_fresh=False):
        # Recheck cached header, physical attachment and ownership before each
        # possible write. There is no I2C scan or EEPROM access in this check.
        if not self.refresh(now_ms):
            return False
        self._clock_ms = now_ms
        if live and _active_calls(_dict(_dict(payload).get('own'))):
            self._peak = int(self.call_brightness * 255)
        mode = _scene(payload, live, page, partner, weather_fresh)
        scroll_changed = False
        if mode == "caller":
            ringing = [call for call in _active_calls(_dict(_dict(payload).get("own")))
                       if call.get("state") == "ringing"]
            call = ringing[0]
            text = caller_text(call.get("peer_name"))
            key = (str(call.get("id") or '')[:80], text)
            if key != self._scroll_key:
                self._scroll_key = key
                self._scroll_columns = columns(text)
                self._scroll_position = 0
                self._scroll_next = now_ms + 1000
                scroll_changed = True
        else:
            self._scroll_key = None
        # A native LCD frame can run at every async yield. Keep one animation
        # goal stable until it commits, otherwise a breathing frame can change
        # faster than the bytewise transfer ever finishes. Source/scene and
        # configured-brightness changes still supersede the old goal at once.
        if self._goal_pending and mode == self.last_mode and self._peak == self._goal_peak and not scroll_changed:
            return True
        frame = None
        peak = self._peak
        if mode == "caller":
            if now_ms >= self._scroll_next and not scroll_changed:
                self._scroll_position = (self._scroll_position + 1) % len(self._scroll_columns)
                self._scroll_next = now_ms + (1000 if self._scroll_position == 0 else 180)
            frame = ('text', peak, self._scroll_key, self._scroll_position)
        elif mode == "heart":
            phase = int(now_ms) % 1200
            large = 120 <= phase < 320 or 440 <= phase < 610
            glyph = "heart" if large else "heart_small"
            peak = peak if large else peak * 3 // 7
            frame = (glyph, peak)
        elif mode in ("ringing", "internal", "queue", "ddi", "external"):
            frame = (mode, peak if int(now_ms) % 800 < 550 else peak // 5)
        elif mode == "rain":
            frame = (mode, peak, int(now_ms) // 250 % 2)
        else:
            frame = (mode, peak)
        if frame == self._last_frame:
            return True
        # Semantic changes (including stale/live) are immediate. Animation
        # frames are capped to protect the shared firmware event loop.
        if (not scroll_changed and self.last_mode == mode and self._peak == self._goal_peak and self._last_write_ms is not None
                and 0 <= now_ms - self._last_write_ms < 125):
            return True
        self._packet[1:] = self._zero
        glyph, level = frame[:2]
        if mode == 'caller':
            for x in range(WIDTH):
                bits = self._scroll_columns[(x + self._scroll_position) % len(self._scroll_columns)]
                for y in range(7):
                    index = GRID[(y + 1) * WIDTH + x]
                    if bits & (1 << y) and index >= 0:
                        self._packet[index + 1] = level
        else:
            for index in _PIXELS[glyph]:
                self._packet[index + 1] = level
        if mode == "rain" and frame[2]:
            # Alternate only the bottom rain strokes, preserving the cloud.
            for x in (3, 6, 9, 12, 15):
                self._packet[GRID[7 * WIDTH + x] + 1] = level
        self._last_frame = frame
        self.last_mode = mode
        self._last_write_ms = now_ms
        self._goal_pending = True
        self._goal_peak = self._peak
        return True

    @property
    def pending(self):
        return self._goal_pending and not self._closed

    def _write_byte(self, register, value):
        self._byte[0] = value
        result = self._bus.writeto_mem(ADDRESS, register, self._byte)
        if result is not None and result != 1:
            raise OSError("Incomplete matrix register write")

    async def flush(self):
        """Drain at most24 changes, coalescing semantic goals at every yield.

        No task is created here. A unique owner task serializes calls. Failed
        writes abort the pass immediately and block reinitialization for2s.
        Initial loading holds constant-zero mode until the entire PWM buffer
        is known. LED0 remains zero until PWM mode is enabled, avoiding a
        full-matrix flash from the shared constant-brightness/data0 register.
        """
        if self._closed or self._flushing or not self._goal_pending:
            return 0
        self._flushing = True
        writes = 0
        try:
            while writes < 24 and self._goal_pending and not self._closed:
                if not self.refresh(self._clock_ms):
                    break
                try:
                    if self._phase == 0:
                        self._write_byte(DIRECT_REGISTER + 1, 0)
                        self._actual[0], self._known[0] = 0, 1
                        self._phase = 1
                    elif self._phase == 1:
                        self._write_byte(DIRECT_REGISTER, 1)
                        self._phase = 2
                    else:
                        index = None
                        # During initial loading data0 must remain zero while
                        # it controls constant mode. Other bytes can load.
                        start, count = (1, LED_COUNT - 1) if self._phase == 2 else (0, LED_COUNT)
                        for offset in range(count):
                            candidate = start + (self._cursor - start + offset) % count
                            if (not self._known[candidate]
                                    or self._actual[candidate] != self._packet[candidate + 1]):
                                index = candidate
                                break
                        if index is None:
                            if self._phase == 2:
                                self._write_byte(DIRECT_REGISTER, 3)
                                self._phase = 3
                                self._cursor = 0
                            else:
                                self._goal_pending = False
                                self.frames_written += 1
                                self.displayed_mode = self.last_mode
                                if self.last_mode == 'caller':
                                    self._scroll_next = self._clock_ms + (1000 if self._scroll_position == 0 else 180)
                                break
                        else:
                            value = self._packet[index + 1]
                            self._write_byte(DIRECT_REGISTER + 1 + index, value)
                            self._actual[index], self._known[index] = value, 1
                            self._cursor = index + 1
                except Exception:
                    self._drop("MATRIX I2C ERROR")
                    self._retry_at = self._clock_ms + 2000
                    break
                writes += 1
                # Yield in small groups: one LCD draw between every byte can
                # starve a156-byte image for many seconds. A failed write still
                # aborts immediately, so a fault never waits for the group.
                if writes % 8 == 0:
                    await asyncio.sleep(0)
        finally:
            self._flushing = False
        return writes

    def close(self):
        if self._closed:
            return
        # Never block scheduler shutdown or touch hardware after ownership
        # changes. The external processor keeps its last complete/partial
        # frame, just as it does when the manufacturer's app is stopped.
        self._closed = True
        self._drop("MATRIX OFF")
