"""Hardware-independent, one-press controls and confirmed own-status colour."""
import binascii
import os

from .controller import call_colour


def initials(name, number=""):
    name = str(name or "").strip()
    absent = ("", "UNKNOWN", "UNKNOWN CALLER", "WITHHELD", "ANONYMOUS", "PRIVATE", "UNAVAILABLE")
    if name.upper() in absent:
        number = str(number or "").strip()
        return number if number and number.upper() not in absent else "?"
    if 2 <= len(name) <= 3 and name.isalpha() and name == name.upper():
        return name
    words = name.replace("-", " ").split()
    letters = []
    for word in words:
        for letter in word:
            if letter.isalpha():
                letters.append(letter)
                break
        if len(letters) == 3:
            break
    result = "".join(letters).upper()
    return result or (str(number).strip() if number else "?")


class ControlButtons:
    """Require release after launch/mapping changes; ignore repeats and chords."""
    def __init__(self):
        self._mode = None
        self._down = set()
        self._armed = False
        self._last_edge = None

    def physical_edges(self, downset, keyboard_present, now_ms):
        down = set(button for button in downset if button in ("A", "B", "C", "D", "E", "F"))
        mode = bool(keyboard_present)
        if self._mode is None or mode != self._mode:
            self._mode = mode
            self._down = down
            self._armed = not down
            return []
        fresh = down - self._down
        self._down = down
        if not self._armed:
            if not down:
                self._armed = True
            return []
        if len(down) != 1 or len(fresh) != 1:
            return []
        if self._last_edge is not None and now_ms - self._last_edge < 300:
            return []
        self._last_edge = now_ms
        return list(fresh)


def _scale(colour, brightness):
    brightness = max(0.0, min(1.0, float(brightness)))
    return tuple(int(channel * brightness) for channel in colour)


def _fresh_presence(own):
    presence = own.get("presence") or {}
    if not isinstance(presence, dict) or presence.get("confirmed") is not True:
        return None
    age = presence.get("age_seconds")
    if isinstance(age, bool) or not isinstance(age, (int, float)) or age != age or age < 0 or age > 5:
        return None
    return presence if presence.get("state") in ("available", "dnd", "away") else None


def own_colour(payload, live, now_ms, brightness=0.03):
    unknown = (12, 12, 14)
    if not live or not isinstance(payload, dict):
        return _scale(unknown, brightness)
    own = payload.get("own") or {}
    if not isinstance(own, dict):
        return _scale(unknown, brightness)
    supplied_calls = own.get("calls")
    calls = [call for call in supplied_calls if isinstance(call, dict)] if isinstance(supplied_calls, list) else []
    if any(call.get("priority") and call.get("state") in
           ("ringing", "dialing", "connected", "busy", "hold", "held") for call in calls):
        # Keep an active priority call visible for its whole lifetime. This is
        # a temporary scale override; the saved normal EEH level is unchanged.
        brightness = 1.0
    ringing = [call for call in calls if call.get("state") == "ringing" and call.get("direction") == "inbound"]
    if ringing:
        ringing.sort(key=lambda call: not call.get("priority"))
        call = ringing[0]
        if call.get("priority"):
            pulse = now_ms % 1000
            on = pulse < 140 or 260 <= pulse < 400
        else:
            on = (now_ms // 300) % 2 == 0
        return _scale(call_colour(call) if on else (0, 0, 0), brightness)
    if own.get("state") == "busy" or any(call.get("state") in ("connected", "hold", "held", "dialing", "ringing", "busy") for call in calls):
        return _scale((230, 10, 10), brightness)
    presence = _fresh_presence(own)
    if not presence:
        return _scale(unknown, brightness)
    return _scale({"available": (0, 145, 25), "dnd": (145, 0, 220), "away": (255, 155, 0)}[presence["state"]], brightness)


class ControlQueue:
    """One user intent at a time; uncertain writes are never requeued."""
    def __init__(self, boot_id=None):
        if boot_id is None:
            boot_id = binascii.hexlify(os.urandom(8)).decode()
        if not isinstance(boot_id, str) or len(boot_id) != 16 or any(character not in "0123456789abcdefABCDEF" for character in boot_id):
            raise ValueError("boot_id must contain 16 hexadecimal characters")
        self.boot_id = boot_id.lower()
        self._counter = 0
        self.pending = None
        self._in_flight = None
        self.message = ""
        self.message_until = 0

    @property
    def is_busy(self):
        return self.pending is not None or self._in_flight is not None

    def _message(self, message, now, duration=4000):
        self.message = message
        self.message_until = now + duration

    def _ready(self, payload, live, operation, now):
        if self.is_busy:
            self._message("CONTROL BUSY", now)
            return None
        if not live or not isinstance(payload, dict):
            self._message("NO LIVE DATA", now)
            return None
        controls = payload.get("controls") or {}
        if not isinstance(controls, dict) or controls.get("enabled") is not True or controls.get(operation) is not True:
            self._message("CALL CONTROL OFF" if operation == "call" else "DND CONTROL OFF", now)
            return None
        session = controls.get("session_id")
        if not isinstance(session, str) or not session:
            self._message("REFRESH CONTROL STATE", now)
            return None
        return controls

    def _queue(self, action, controls, now, **fields):
        self._counter += 1
        self.pending = {"action": action, "request_id": self.boot_id + "-" + str(self._counter),
                        "session_id": controls["session_id"]}
        self.pending.update(fields)
        self._message("CALL QUEUED" if action == "call" else "DND CHANGE QUEUED", now)
        return True

    def queue_call(self, payload, live, target, now):
        controls = self._ready(payload, live, "call", now)
        if controls is None:
            return False
        targets = controls.get("targets") or []
        if not isinstance(targets, list) or not isinstance(target, str) or not any(isinstance(item, dict) and item.get("id") == target for item in targets):
            self._message("SPEED DIAL UNAVAILABLE", now)
            return False
        own = payload.get("own") or {}
        if not isinstance(own, dict) or own.get("state") != "idle" or not isinstance(own.get("calls"), list) or own.get("calls"):
            self._message("YOUR PHONE IS BUSY" if isinstance(own, dict) and own.get("calls") else "PHONE STATUS UNKNOWN", now)
            return False
        return self._queue("call", controls, now, target=target)

    def queue_dnd(self, payload, live, now):
        controls = self._ready(payload, live, "dnd", now)
        if controls is None:
            return False
        own = payload.get("own") or {}
        presence = _fresh_presence(own) if isinstance(own, dict) else None
        if not presence:
            self._message("DND STATUS UNKNOWN", now)
            return False
        return self._queue("dnd", controls, now, enabled=presence["state"] != "dnd")

    def take(self):
        if self._in_flight is not None or self.pending is None:
            return None
        self._in_flight, self.pending = self.pending, None
        return dict(self._in_flight)

    def fail_unknown(self, now):
        intent = self._in_flight or self.pending or {}
        action = intent.get("action")
        self.pending = None
        self._in_flight = None
        self._message("DND STATUS UNKNOWN" if action == "dnd" else "CALL STATUS UNKNOWN", now, 8000)

    def finish(self, result, now):
        intent = self._in_flight or self.pending or {}
        if not isinstance(result, dict) or result.get("status") == "unknown":
            self.fail_unknown(now)
            return
        self.pending = None
        self._in_flight = None
        error = result.get("error")
        if error:
            messages = {
                "unauthorized": "CONTROL NOT AUTHORISED", "stale_session": "REFRESH CONTROL STATE",
                "own_busy": "YOUR PHONE IS BUSY", "own_unavailable": "PHONE STATUS UNKNOWN",
                "cooldown": "CONTROL BUSY", "action_in_progress": "CONTROL BUSY",
                "bridge_offline": "NO LIVE DATA", "stale_state": "NO LIVE DATA",
                "dnd_unavailable": "DND CONTROL OFF", "invalid_target": "SPEED DIAL UNAVAILABLE",
            }
            self._message(messages.get(error, "CONTROL REQUEST FAILED"), now)
            return
        action = intent.get("action")
        state = result.get("status")
        if state == "pending":
            message = "DND PENDING" if action == "dnd" else "CALL PENDING"
        elif state == "demo":
            message = "DEMO DND" if action == "dnd" else "DEMO CALL"
        elif action == "dnd" and state in ("confirmed", "unchanged"):
            message = "DND ON" if intent.get("enabled") else "DND OFF"
        elif action == "call" and state == "accepted":
            message = "CALL REQUESTED"
        else:
            message = "CONTROL REQUEST FAILED"
        self._message(message, now)
