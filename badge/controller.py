"""Hardware-independent display state for the Tildagon 3CX monitor.

Keep this module compatible with MicroPython. All timestamps here are elapsed
milliseconds supplied by the app, rather than wall-clock time.
"""

STALE_MS = 5000
PAGE_SIZE = 12
OFF = (0, 0, 0)
UNKNOWN = (12, 12, 14)
KINDS = {
    "internal": (255, 155, 0),
    "queue": (0, 230, 255),
    "ddi": (35, 80, 255),
    "external": (255, 255, 255),
    "unknown": (100, 100, 110),
}


def call_colour(call):
    if call.get("priority"):
        return (255, 0, 200)
    return KINDS.get(call.get("kind"), KINDS["unknown"])


def call_label(call):
    labels = {
        "internal": "INTERNAL", "queue": "QUEUE", "ddi": "DDI",
        "external": "EXTERNAL", "unknown": "UNKNOWN ROUTE",
    }
    kind = labels.get(call.get("kind"), "UNKNOWN ROUTE")
    return "PRIORITY / " + kind if call.get("priority") else kind


class Controller:
    def __init__(self, brightness=0.03, eeh_brightness=None, ring_brightness=0.15):
        self.payload = None
        self.received_ms = None
        self.source_age_ms = 0
        self.last_error = None
        self.selected = 0
        self.own_view = False
        self.detail_view = False
        self._connected_since = {}
        self.eeh_brightness = brightness if eeh_brightness is None else eeh_brightness
        self.ring_brightness = ring_brightness

    @property
    def eeh_brightness(self):
        return self._eeh_brightness

    @eeh_brightness.setter
    def eeh_brightness(self, value):
        value = float(value)
        if value != value:
            value = 0.03
        self._eeh_brightness = max(0.0, min(1.0, value))

    @property
    def brightness(self):
        """Compatibility alias: brightness controls only the EEH hexpansion."""
        return self.eeh_brightness

    @brightness.setter
    def brightness(self, value):
        self.eeh_brightness = value

    @property
    def ring_brightness(self):
        return self._ring_brightness

    @ring_brightness.setter
    def ring_brightness(self, value):
        value = float(value)
        if value != value:
            value = 0.15
        self._ring_brightness = max(0.0, min(1.0, value))

    def accept(self, payload, now_ms):
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported bridge data")
        if not isinstance(payload.get("team"), list):
            raise ValueError("Missing team data")
        if not isinstance(payload.get("own"), dict):
            raise ValueError("Missing own extension")
        if not isinstance(payload.get("connected"), bool):
            raise ValueError("Missing connection status")
        age = payload.get("age_seconds")
        if age is None and not payload["connected"]:
            age = STALE_MS / 1000
        if not isinstance(age, (int, float)) or age < 0 or age != age:
            raise ValueError("Invalid source age")
        if any(not isinstance(member, dict) for member in payload["team"]):
            raise ValueError("Invalid team data")
        alert = payload.get("alert")
        if alert is not None and not isinstance(alert, dict):
            raise ValueError("Invalid alert")
        self.payload = payload
        self.received_ms = now_ms
        self.source_age_ms = age * 1000
        self.last_error = None
        self.selected = min(self.selected, max(0, len(payload["team"]) - 1))
        calls = payload['own'].get('calls')
        calls = [call for call in calls[:16] if isinstance(call, dict)] if isinstance(calls, list) else []
        active = {str(call.get('id'))[:80] for call in calls
                  if call.get('id') and call.get('state') in ('connected','hold','held','busy')}
        self._connected_since = {key: value for key, value in self._connected_since.items() if key in active}
        if payload.get('connected') and self.source_age_ms < STALE_MS:
            for key in active:
                self._connected_since.setdefault(key, now_ms)

    def own_call(self, now_ms):
        if not self.live(now_ms):
            return None
        calls = self.payload.get('own', {}).get('calls')
        if not isinstance(calls, list):
            return None
        rank = {'connected':0,'hold':1,'held':1,'busy':1,'dialing':2,'ringing':3}
        active = [call for call in calls[:16] if isinstance(call, dict) and call.get('state') in rank]
        return min(active, key=lambda call: rank[call['state']]) if active else None

    def call_elapsed(self, call, now_ms):
        """Connected time observed by this badge; wall-clock/NTP independent."""
        if not self.live(now_ms) or call.get('state') not in ('connected','hold','held','busy'):
            return None
        since = self._connected_since.get(str(call.get('id'))[:80])
        return max(0, int(now_ms - since) // 1000) if since is not None else None

    def failed(self, message="BRIDGE UNREACHABLE"):
        # An unsuccessful fetch must never refresh the last successful timestamp.
        self.last_error = message

    def live(self, now_ms):
        return bool(
            self.payload is not None
            and self.payload.get("connected")
            and self.received_ms is not None
            and self.source_age_ms + max(0, now_ms - self.received_ms) < STALE_MS
        )

    def status(self, now_ms):
        if self.payload is None:
            return self.last_error or "CONNECTING"
        if not self.payload.get("connected"):
            return str(self.payload.get("status") or "PBX DISCONNECTED")
        if not self.live(now_ms):
            return "STALE / NO LIVE DATA"
        if self.last_error:
            return "RETRYING BRIDGE"
        return "DEMO" if self.payload.get("demo") else "LIVE"

    def team(self):
        return self.payload.get("team", []) if self.payload else []

    def page(self):
        return self.selected // PAGE_SIZE

    def page_count(self):
        return max(1, (len(self.team()) + PAGE_SIZE - 1) // PAGE_SIZE)

    def page_team(self):
        start = self.page() * PAGE_SIZE
        return self.team()[start:start + PAGE_SIZE]

    def led_range(self, page_index):
        """Inclusive one-based sector, matching the four-tile screen layout."""
        count = len(self.page_team())
        if not count or page_index < 0 or page_index >= count:
            return (0, 0)
        # Hardware starts at the top-right and runs clockwise. Screen order is
        # top-left, top-right, bottom-left, bottom-right.
        if count == 4:
            return ((10, 12), (1, 3), (7, 9), (4, 6))[page_index]
        return (page_index * PAGE_SIZE // count + 1, (page_index + 1) * PAGE_SIZE // count)

    def select(self, direction):
        if self.team():
            self.selected = (self.selected + direction) % len(self.team())
        self.own_view = False
        self.detail_view = True

    def focused(self):
        if self.own_view:
            return self.payload.get("own", {}) if self.payload else {}
        return self.team()[self.selected] if self.team() else {}

    def alert(self, now_ms):
        if not self.live(now_ms):
            return None
        alert = self.payload.get("alert")
        # Defend against malformed sources. Only incoming ringing calls can take
        # over all LEDs, including a call waiting alongside an established call.
        if alert and alert.get("state") == "ringing" and alert.get("direction") == "inbound":
            return alert
        return None

    def adjust_brightness(self, direction):
        self.eeh_brightness = round(self.eeh_brightness + direction * 0.01, 2)
        return self.eeh_brightness

    def adjust_ring_brightness(self, direction):
        self.ring_brightness = round(self.ring_brightness + direction * 0.01, 2)
        return self.ring_brightness

    def _priority_ring_override(self, now_ms):
        if not self.live(now_ms):
            return False
        own = self.payload.get("own") or {}
        calls = own.get("calls") if isinstance(own, dict) else None
        if not isinstance(calls, list):
            return False
        active_states = ("ringing", "dialing", "connected", "hold", "held", "busy")
        return any(isinstance(call, dict) and call.get("priority")
                   and call.get("state") in active_states for call in calls)

    def led_frame(self, now_ms):
        frame = [OFF] * PAGE_SIZE
        ringing_on = (now_ms // 300) % 2 == 0
        alert = self.alert(now_ms)
        if alert:
            # Priority calls use a distinctive double pulse each second.
            if alert.get("priority"):
                pulse = now_ms % 1000
                ringing_on = pulse < 140 or 260 <= pulse < 400
            frame = [call_colour(alert) if ringing_on else OFF] * PAGE_SIZE
        else:
            live = self.live(now_ms)
            for index, member in enumerate(self.page_team()):
                state = member.get("state") if live else "unknown"
                if state == "idle":
                    colour = (0, 145, 25)
                elif state == "busy":
                    colour = (230, 10, 10)
                elif state == "ringing":
                    colour = (255, 155, 0) if ringing_on else OFF
                else:
                    colour = UNKNOWN
                first, last = self.led_range(index)
                for led in range(first - 1, last):
                    frame[led] = colour
        # A live own priority call temporarily overrides the user's ring level,
        # including after it is answered. Never change the stored preference.
        level = 1.0 if self._priority_ring_override(now_ms) else self.ring_brightness
        return [tuple(int(channel * level) for channel in colour) for colour in frame]
