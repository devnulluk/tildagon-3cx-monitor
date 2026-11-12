"""Hotplug adapters for the official keyboard and East Essex NeoPixels.

EEH pin/count definitions come from the manufacturer's config.py:
https://github.com/eehackspace/tildagon-app-eehneopixelhexpansions
All supported boards use HS0; the firmware resolves the physical slot pin.
Nothing is driven until an explicit board type/slot and attachment are known.
"""

EEH_TYPES = {"EEH Logo": 14, "Dalek": 3, "K9": 1, "Sonic Screwdriver": 1, "TARDIS": 5}


def heartbeat_colour(colour, now_ms):
    """Two red beats, bounded by the caller's already-scaled RGB peak.

    The Logo's documented LEDs form an H, not a pixel matrix. Pulsing the
    complete logo is intentional; no unverified spatial LED map is assumed.
    Existing priority-call brightness is decided by own_colour upstream.
    """
    peak = max(max(0, min(255, int(channel))) for channel in colour)
    phase = int(now_ms) % 1200
    if phase < 150:
        envelope = 40 + (215 * phase // 150)
    elif phase < 300:
        envelope = 255 - (215 * (phase - 150) // 150)
    elif phase < 420:
        envelope = 40 + (160 * (phase - 300) // 120)
    elif phase < 600:
        envelope = 200 - (160 * (phase - 420) // 180)
    else:
        envelope = 20
    return (peak * envelope // 255, 0, 0)


def keyboard_slots(drivers):
    """Identify initialized official KeebDeck driver APIs, not generic RGB apps."""
    result = []
    for slot, driver in drivers.items():
        config = getattr(driver, "hexpansion_config", None)
        if (
            isinstance(slot, int) and 1 <= slot <= 6
            and getattr(config, "port", None) == slot
            and getattr(driver, "ADDR", None) == 0x34
            and callable(getattr(driver, "handle_keyboard_key", None))
        ):
            result.append(slot)
    return sorted(result)


def keyboard_name(event):
    button = getattr(event, "button", None)
    if getattr(button, "group", None) != "Keyboard":
        find = getattr(button, "find_parent_in_group", None)
        button = find("Keyboard") if callable(find) else None
    name = getattr(button, "name", None)
    return name if isinstance(name, str) and 0 < len(name) <= 24 else None


class FirmwareBackend:
    def headers(self):
        from system.hexpansion import app as hexpansion_app
        manager = hexpansion_app._hexpansion_manager
        return dict(manager.hexpansion_headers) if manager is not None else {}

    def matrix_i2c(self, slot):
        # The firmware routes each logical slot to its native I2C bus. Do not
        # copy GPIO numbers or the manufacturer's power-cycling error wrapper.
        from machine import I2C
        return I2C(slot)

    def snapshot(self):
        from system.hexpansion import app as hexpansion_app
        from system.scheduler import scheduler
        manager = hexpansion_app._hexpansion_manager
        if manager is None:
            return {}, set(), []
        attached = set(index + 1 for index, pin in enumerate(manager.hexpansion_pins) if not pin.value())
        return dict(manager.hexpansion_apps), attached, list(scheduler.apps)

    def pixels(self, slot, count):
        import neopixel
        from system.hexpansion.config import HexpansionConfig
        return neopixel.NeoPixel(HexpansionConfig(slot).pin[0], count)

    def saved_eeh(self):
        import settings
        candidates = []
        for slot in range(1, 7):
            kind = settings.get("eehneopixel.slot." + str(slot), None)
            if kind in EEH_TYPES:
                candidates.append({"slot": slot, "type": kind})
        # Multiple configured boards need an explicit choice for this monitor.
        return candidates[0] if len(candidates) == 1 else None


class ExpansionManager:
    def __init__(self, owner, config=None, backend=None, event_bus=None, event_types=None):
        self.owner = owner
        self.backend = backend if backend is not None else FirmwareBackend()
        self.keyboard_slots = []
        self.keyboard_present = False
        self.eeh_ready = False
        self.eeh_status = "EEH NOT CONFIGURED"
        self._pixels = None
        self._colour = None
        self._slot = None
        self._count = 0
        self._keys = []
        self._held = set()
        self._bindings = []
        self._bus = event_bus
        self._dirty = True
        self._last_refresh = None
        self._closed = False
        values = config or {}
        self._eeh = values.get("eeh")
        if self._eeh is None:
            try:
                self._eeh = self.backend.saved_eeh()
            except Exception:
                self._eeh = None
        self._bind_events(event_types)
        self.refresh(0)

    def _bind_events(self, event_types):
        try:
            if self._bus is None:
                from system.eventbus import eventbus
                self._bus = eventbus
            if event_types is None:
                from events.input import ButtonDownEvent, ButtonUpEvent
                from system.hexpansion.events import HexpansionInsertionEvent, HexpansionRemovalEvent, HexpansionMountedEvent, HexpansionUnmountedEvent
                event_types = (ButtonDownEvent, ButtonUpEvent, HexpansionInsertionEvent, HexpansionRemovalEvent, HexpansionMountedEvent, HexpansionUnmountedEvent)
            for kind, callback in ((event_types[0], self._key_down), (event_types[1], self._key_up)):
                self._bus.on(kind, callback, self.owner)
                self._bindings.append((kind, callback))
            for kind in event_types[2:]:
                self._bus.on(kind, self._changed, self.owner)
                self._bindings.append((kind, self._changed))
        except ImportError:
            # Older/simulated firmware can still use periodic discovery.
            pass

    def _key_down(self, event):
        name = keyboard_name(event)
        if not self._closed and self.keyboard_present and name and name not in self._held:
            self._held.add(name)
            if len(self._keys) < 16:
                self._keys.append(name)

    def _key_up(self, event):
        self._held.discard(keyboard_name(event))

    def _changed(self, event):
        self._dirty = True
        self._keys = []
        self._held.clear()
        # The native manager releases pins during removal. Drop our reference
        # without writing into a slot that may now contain another device.
        if getattr(event, "port", None) == self._slot:
            self._pixels = None
            self._colour = None
            self.eeh_ready = False

    def pop_keys(self):
        keys, self._keys = self._keys, []
        return keys

    def refresh(self, now_ms):
        if self._closed:
            return
        if not self._dirty and self._last_refresh is not None and 0 <= now_ms - self._last_refresh < 1000:
            return
        self._dirty = False
        self._last_refresh = now_ms
        try:
            drivers, attached, running = self.backend.snapshot()
        except Exception:
            self.keyboard_slots = []
            self.keyboard_present = False
            self._keys = []
            self._held.clear()
            self._pixels = None
            self.eeh_ready = False
            self.eeh_status = "EXPANSIONS UNAVAILABLE"
            return
        slots = [slot for slot in keyboard_slots(drivers) if slot in attached]
        if slots != self.keyboard_slots:
            self._keys = []
            self._held.clear()
        self.keyboard_slots = slots
        self.keyboard_present = bool(slots)
        setting = self._eeh
        if not isinstance(setting, dict):
            self._drop_pixels("EEH NOT CONFIGURED")
            return
        slot, kind = setting.get("slot"), setting.get("type")
        if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= 6 or kind not in EEH_TYPES:
            self._drop_pixels("EEH CONFIG INVALID")
            return
        if slot not in attached:
            self._drop_pixels("EEH NOT CONNECTED")
            return
        if slot in drivers:
            self._drop_pixels("EEH SLOT IN USE")
            return
        if any(app.__class__.__name__ == "EEHNeoPixelHexpansions" for app in running):
            self._drop_pixels("CLOSE EEH LED APP")
            return
        count = EEH_TYPES[kind]
        if self._pixels is None or self._slot != slot or self._count != count:
            try:
                self._pixels = self.backend.pixels(slot, count)
                self._slot, self._count = slot, count
                self._colour = None
            except Exception:
                self._drop_pixels("EEH DRIVER ERROR")
                return
        self.eeh_ready = True
        self.eeh_status = "EEH READY"

    def _drop_pixels(self, status):
        self._pixels = None
        self._colour = None
        self.eeh_ready = False
        self.eeh_status = status

    def write_own_status(self, colour, now_ms=0, heartbeat=False):
        if self._closed or not self.eeh_ready or self._pixels is None:
            return False
        rgb = tuple(max(0, min(255, int(channel))) for channel in colour)
        if len(rgb) != 3:
            raise ValueError("RGB colour must have three channels")
        if heartbeat:
            rgb = heartbeat_colour(rgb, now_ms)
        if rgb != self._colour:
            try:
                self._pixels.fill(rgb)
                self._pixels.write()
                self._colour = rgb
            except Exception:
                self._drop_pixels("EEH DISCONNECTED")
                self._dirty = True
                return False
        return True

    def close(self):
        if self._closed:
            return
        try:
            drivers, attached, running = self.backend.snapshot()
            if self._pixels is not None and self._slot in attached and self._slot not in drivers:
                self._pixels.fill((0, 0, 0))
                self._pixels.write()
        except Exception:
            pass
        for kind, callback in self._bindings:
            self._bus.remove(kind, callback, self.owner)
        self._bindings = []
        self._closed = True
        self._keys = []
        self._held.clear()
        self.keyboard_present = False
        self.keyboard_slots = []
        self._drop_pixels("EEH OFF")
