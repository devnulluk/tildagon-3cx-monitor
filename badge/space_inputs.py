"""Shared Spaceagon navigation and optional relative tilt; never phone actions.

Uses the running TwentyTwentySix frontboard's documented ButtonDown/Up events.
No GPIO, sensor configuration, frontboard detection or I2C scans are performed.
Canonical names avoid duplicating the physical A-F and generic System aliases.
Source: emfcamp/badge-2024-software modules/frontboards/twentysix.py and the
official emfcamp/badge-2026-apps-spaceagon-test example.
"""
import math
import time

_JOYSTICK = {"JOYUP": "up", "JOYDOWN": "down", "JOYLEFT": "left", "JOYRIGHT": "right", "JOYFIRE": "confirm"}
_PROXIMITY = {"LEFTPROX": "left", "RIGHTPROX": "right"}
_TOUCH_NAMES = tuple("TOUCH%02d" % pad for pad in range(1, 13))
_DEFAULTS = {"space_touch": True, "space_joystick": True, "space_proximity": False, "space_tilt": False}


def _clock_ms():
    ticks = getattr(time, "ticks_ms", None)
    return ticks() if callable(ticks) else int(time.monotonic() * 1000)


def _elapsed(now, then):
    if now >= then:
        return now - then
    difference = getattr(time, "ticks_diff", None)
    return difference(now, then) if callable(difference) else -1


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and value == value and abs(value) < 1000000


def _spaceagon(board):
    return (board.__class__.__name__ == "TwentyTwentySix"
            and board.__class__.__module__.split(".")[-1] == "twentysix"
            and getattr(board, "year", None) == 2026)


class FirmwareBackend:
    def frontboards(self):
        from system.scheduler import scheduler
        return [board for board in scheduler.apps if _spaceagon(board)]

    def acceleration(self):
        # Native imu.acc_read copies cached C measurements under a mutex.
        # It does not configure the sensor or initiate an I2C transaction.
        import imu
        return imu.acc_read()


class SpaceInputs:
    """One bounded semantic navigation queue, owned by the focused app.

    Pass clock=lambda:self.clock_ms when the app maintains a monotonic clock;
    call update() each frame, then pop(). Config keys space_touch/joystick are
    enabled by default; space_proximity/tilt require explicit True. Touch taps
    produce select(pad1..12), two-pad rotary steps produce rotate(delta+/-1).
    Proximity requires a deliberate two-sensor sweep and emits focus only.
    Joystick confirm means display selection/pause, never call/DND consent.
    """

    def __init__(self, owner, config=None, backend=None, event_bus=None, event_types=None, clock=None):
        self.owner = owner
        self.config = config if isinstance(config, dict) else {}
        self.backend = backend if backend is not None else FirmwareBackend()
        self.clock = clock if callable(clock) else _clock_ms
        self.present = False
        self.tilt = (0.0, 0.0)
        self.motion_valid = False
        self.acceleration = None
        self.magnitude = None
        self.heading = None  # No calibration/tilt-compensated compass is assumed.
        self._baseline = None
        self._last_motion = None
        self._last_inventory = None
        self._boards = []
        self._queue = []
        self._held = set()
        self._suppressed = set()
        self._last_release = {}
        self._touch = None
        self._touch_pads = set()
        self._prox_first = None
        self._prox_wave = None
        self._prox_last = None
        self._closed = False
        self._focused = bool(getattr(owner, "_focused", True))
        self._bus = event_bus
        self._bindings = []
        self._bind(event_types)
        self.update()

    def _enabled(self, name):
        return self.config.get(name, _DEFAULTS[name]) is True

    def _bind(self, event_types):
        try:
            if self._bus is None:
                from system.eventbus import eventbus
                self._bus = eventbus
            if event_types is None:
                from events.input import ButtonDownEvent, ButtonUpEvent
                event_types = (ButtonDownEvent, ButtonUpEvent)
            for kind, callback in ((event_types[0], self._down), (event_types[1], self._up)):
                self._bus.on(kind, callback, self.owner)
                self._bindings.append((kind, callback))
        except ImportError:
            pass

    def _enqueue(self, kind, action, **values):
        if (not self._closed and self.present and self._focused
                and getattr(self.owner, "_focused", True) and len(self._queue) < 16):
            self._queue.append(dict(values, kind=kind, action=action))

    def _clear_gestures(self):
        self._touch = None
        self._touch_pads.clear()
        self._prox_first = self._prox_wave = None

    def _physical_held(self):
        result = set()
        for board in self._boards:
            for key, state in getattr(board, "joystick_states", {}).items():
                if isinstance(state, (list, tuple)) and state and state[0]:
                    result.add("JOY" + key)
            for key, state in getattr(board, "touch_states", {}).items():
                if isinstance(state, (list, tuple)) and state and state[0]:
                    result.add(key)
        return result

    def _name(self, event):
        button = getattr(event, "button", None)
        if getattr(button, "group", None) != "TwentyTwentySix":
            return None
        name = getattr(button, "name", None)
        return name if isinstance(name, str) and (name in _JOYSTICK or name in _PROXIMITY or name in _TOUCH_NAMES) else None

    def _down(self, event):
        if self._closed or not self.present or not self._focused or not getattr(self.owner, "_focused", True):
            return
        name = self._name(event)
        if not name or name in self._held or name in self._suppressed:
            return
        now = self.clock()
        self._held.add(name)
        last = self._last_release.get(name)
        if last is not None and 0 <= _elapsed(now, last) < 45:
            return
        if name in _JOYSTICK and self._enabled("space_joystick"):
            self._enqueue("joystick", _JOYSTICK[name])
        elif name.startswith("TOUCH") and self._enabled("space_touch"):
            try:
                pad = int(name[5:])
            except ValueError:
                return
            if 1 <= pad <= 12 and name == "TOUCH%02d" % pad:
                self._touch_down(pad, now)
        elif name in _PROXIMITY and self._enabled("space_proximity"):
            self._prox_down(name, now)

    def _up(self, event):
        if self._closed:
            return
        name = self._name(event)
        if not name:
            return
        now = self.clock()
        self._held.discard(name)
        self._suppressed.discard(name)
        self._last_release[name] = now
        if name.startswith("TOUCH"):
            try:
                self._touch_pads.discard(int(name[5:]))
            except ValueError:
                return
            if self._touch is not None and not self._touch_pads:
                self._touch["released"] = now
        elif name in _PROXIMITY and not any(key in self._held for key in _PROXIMITY):
            if self._prox_wave is not None and self._enabled("space_proximity"):
                if self._prox_last is None or _elapsed(now, self._prox_last) >= 1200:
                    self._enqueue("proximity", "focus", side=self._prox_wave)
                    self._prox_last = now
                self._prox_first = self._prox_wave = None

    def _touch_down(self, pad, now):
        touch = self._touch
        self._touch_pads.add(pad)
        if touch is None or _elapsed(now, touch["last"]) > 350:
            self._touch = {"pad": pad, "first": now, "last": now, "last_pad": pad,
                           "released": None, "moved": False, "invalid": len(self._touch_pads) > 1, "distance": 0}
            return
        touch["released"] = None
        delta = (pad - touch["last_pad"] + 6) % 12 - 6
        if delta:
            touch["moved"] = True
            if abs(delta) > 2 or _elapsed(now, touch["last"]) < 45:
                touch["invalid"] = True
            elif not touch["invalid"]:
                touch["distance"] += delta
                if abs(touch["distance"]) >= 2:
                    direction = 1 if touch["distance"] > 0 else -1
                    self._enqueue("touch", "rotate", delta=direction, pad=pad)
                    touch["distance"] -= direction * 2
        touch["last"], touch["last_pad"] = now, pad

    def _prox_down(self, name, now):
        if self._prox_first is None or _elapsed(now, self._prox_first[1]) > 900:
            self._prox_first = (name, now)
            self._prox_wave = None
        elif name != self._prox_first[0] and 80 <= _elapsed(now, self._prox_first[1]) <= 900:
            self._prox_wave = _PROXIMITY[name]

    def _motion(self, now):
        if not self._enabled("space_tilt") or not self._focused:
            self.tilt, self.motion_valid = (0.0, 0.0), False
            self.acceleration = self.magnitude = None
            return
        if self._last_motion is not None and 0 <= _elapsed(now, self._last_motion) < 50:
            return
        self._last_motion = now
        try:
            sample = self.backend.acceleration()
            if (not isinstance(sample, (tuple, list)) or len(sample) != 3
                    or any(not _finite(value) or abs(value) > 20 for value in sample)):
                raise ValueError()
            magnitude = math.sqrt(sum(value * value for value in sample))
            # Reject native absent-IMU(1,1,1), free fall and large impulses.
            if not 6.5 <= magnitude <= 13.1:
                raise ValueError()
            self.acceleration, self.magnitude = tuple(sample), magnitude
            if self._baseline is None:
                self._baseline = tuple(sample)
            x = max(-1, min(1, (sample[0] - self._baseline[0]) / 9.81))
            y = max(-1, min(1, (sample[1] - self._baseline[1]) / 9.81))
            self.tilt = (self.tilt[0] + (x - self.tilt[0]) * .24,
                         self.tilt[1] + (y - self.tilt[1]) * .24)
            self.motion_valid = True
        except Exception:
            self.motion_valid = False
            self.acceleration = self.magnitude = None
            self.tilt = (self.tilt[0] * .75, self.tilt[1] * .75)

    def recenter(self):
        """Use the next valid gravity sample as relative centre; no sensor write."""
        self._baseline = None
        self._last_motion = None
        self.tilt, self.motion_valid = (0.0, 0.0), False

    def update(self):
        if self._closed:
            return
        now = self.clock()
        if self._last_inventory is None or _elapsed(now, self._last_inventory) >= 1000:
            self._last_inventory = now
            try:
                self._boards = [board for board in self.backend.frontboards() if _spaceagon(board)]
            except Exception:
                self._boards = []
            present = bool(self._boards)
            if present != self.present:
                self._queue = []
                self._suppressed.update(self._held)
                self._held.clear()
                self._clear_gestures()
                if present:
                    physical = self._physical_held()
                    self._suppressed = {name for name in self._suppressed if name in physical or name in _PROXIMITY}
                    self._suppressed.update(physical)
            self.present = present
        focused = bool(getattr(self.owner, "_focused", True))
        if focused != self._focused:
            self._queue = []
            self._suppressed.update(self._held)
            self._held.clear()
            self._clear_gestures()
            if focused:
                physical = self._physical_held()
                self._suppressed = {name for name in self._suppressed if name in physical or name in _PROXIMITY}
                self._suppressed.update(physical)
            self._focused = focused
        touch = self._touch
        if touch is not None and touch["released"] is not None and _elapsed(now, touch["released"]) >= 220:
            duration = _elapsed(touch["released"], touch["first"])
            if (self._enabled("space_touch") and not touch["moved"] and not touch["invalid"]
                    and 35 <= duration <= 500):
                self._enqueue("touch", "select", pad=touch["pad"])
            self._touch = None
        if not self._enabled("space_proximity"):
            self._prox_first = self._prox_wave = None
        elif self._prox_first is not None and _elapsed(now, self._prox_first[1]) > 900:
            self._prox_first = self._prox_wave = None
        self._motion(now)

    def pop(self):
        queue, self._queue = self._queue, []
        return queue

    def close(self):
        if self._closed:
            return
        for kind, callback in self._bindings:
            self._bus.remove(kind, callback, self.owner)
        self._bindings = []
        self._queue = []
        self._held.clear()
        self._suppressed.clear()
        self._clear_gestures()
        self._closed = True
        self.present, self.motion_valid = False, False
        self.tilt = (0.0, 0.0)
