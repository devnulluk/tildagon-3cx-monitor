"""Bounded local notification inbox and native vector presentation.

IDs identify one lifetime: updates change content but never renew expiry or a
local dismissal. A sender must use a new ID for a genuinely new notification.
There are no image fetches, URLs, remote actions or hardware writes here.
"""
import math

TYPES = ("info", "success", "warning", "failure")
STYLES = ("card", "toast", "progress", "badge")
ICONS = ("info", "check", "warning", "error", "bell", "server", "download",
         "upload", "backup", "lock", "phone", "message", "heart", "cloud")
_DEFAULT_ICON = {"info": "info", "success": "check", "warning": "warning", "failure": "error"}
_ACCENTS = {"info": (.19, .76, 1.0), "success": (.23, .95, .61),
            "warning": (1.0, .69, .16), "failure": (1.0, .22, .34)}
_BACKGROUNDS = {"original": (.012, .025, .06), "cyberpunk": (.055, .012, .09),
                "lcars": (.045, .025, .055), "kitty": (.095, .045, .085),
                "christmas": (.012, .055, .038), "easter": (.055, .04, .085),
                "anniversary": (.065, .022, .05), "birthday_self": (.055, .025, .085),
                "birthday_partner": (.075, .035, .07), "ocean": (.006, .045, .07),
                "retro": (.008, .045, .025), "noir": (.025, .025, .03),
                "photo": (.018, .025, .035)}
_UNIT = tuple((math.cos(i * 2 * math.pi / 128), math.sin(i * 2 * math.pi / 128)) for i in range(128))
_FIELDS = ("id", "title", "body", "type", "priority", "style", "icon", "progress", "ttl_seconds")


def _number(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and low <= value <= high)


def _time(value):
    return int(value) if _number(value, 0, 9007199254740991) else 0


def _text_value(value, limit):
    if not isinstance(value, str):
        return ""
    # Keep ordinary Unicode text, but remove control/bidi escape characters.
    return " ".join("".join(c if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) <= 159
                           and not 0x202a <= ord(c) <= 0x202e and not 0x2066 <= ord(c) <= 0x2069)
                           else " " for c in value[:limit]).split())


def _notification(value):
    if not isinstance(value, dict):
        return None
    key = value.get("id")
    if (not isinstance(key, str) or not 1 <= len(key) <= 64
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for c in key)):
        return None
    ttl, age = value.get("ttl_seconds", 120), value.get("age_seconds")
    if not _number(ttl, 1, 86400) or not _number(age, 0, 86400) or age >= ttl:
        return None
    kind = value.get("type")
    kind = kind if kind in TYPES else "info"
    priority = value.get("priority", 3)
    priority = priority if type(priority) is int and 1 <= priority <= 5 else 3
    style, icon = value.get("style"), value.get("icon")
    progress = value.get("progress")
    return {"id": key, "title": _text_value(value.get("title"), 80) or "Notification",
            "body": _text_value(value.get("body"), 320), "type": kind, "priority": priority,
            "style": style if style in STYLES else "card",
            "icon": icon if icon in ICONS else _DEFAULT_ICON[kind],
            "progress": progress if _number(progress, 0, 100) else None,
            "ttl_seconds": ttl, "age_seconds": age}


class NotificationInbox:
    """At most16 active items and64 bounded local dismissal/expiry tombstones."""
    def __init__(self):
        self._items = []
        self._dead = []
        self._current = None
        self._sequence = 0
        self._last_ms = 0
        self.entered_ms = None
        self.revision = 0

    @property
    def count(self):
        return len(self._items)

    def _now(self, value):
        self._last_ms = max(self._last_ms, _time(value))
        return self._last_ms

    def _remember(self, key):
        if key in self._dead:
            self._dead.remove(key)
        self._dead.append(key)
        if len(self._dead) > 64:
            self._dead.pop(0)

    def _age(self, item, now):
        return item["age_seconds"] + max(0, now - item["_at"]) / 1000

    def _select(self, key, now):
        if key != self._current:
            self._current, self.entered_ms = key, now if key else None

    def _prune(self, now):
        live = []
        for item in self._items:
            if self._age(item, now) >= item["ttl_seconds"]:
                self._remember(item["id"])
                self.revision += 1
            else:
                live.append(item)
        self._items = live
        if not any(item["id"] == self._current for item in live):
            self._select(live[0]["id"] if live else None, now)

    def observe(self, entries, now_ms):
        now = self._now(now_ms)
        before = self.revision
        self._prune(now)
        if not isinstance(entries, (list, tuple)):
            return self.revision != before
        values, seen = [], []
        for raw in entries[:16]:
            item = _notification(raw)
            key = raw.get("id") if isinstance(raw, dict) else None
            # Do not allow a still-present tombstone to age out of the bounded
            # cache when a sender repeatedly includes an expired cached entry.
            if key in self._dead:
                self._remember(key)
                continue
            if item is None:
                if (isinstance(key, str) and len(key) <= 64
                        and _number(raw.get("ttl_seconds"), 1, 86400)
                        and _number(raw.get("age_seconds"), 0, 9007199254740991)
                        and raw["age_seconds"] >= raw["ttl_seconds"]):
                    self._remember(key)
                continue
            if key not in seen:
                values.append(item)
                seen.append(key)
        old = {item["id"]: item for item in self._items}
        for key in old:
            if key not in seen:
                self._remember(key)
                self.revision += 1
        active, new = [], []
        # Source order is newest first. Sequence gives stable age order across
        # later snapshots that happen to reorder entries.
        for item in reversed(values):
            previous = old.get(item["id"])
            if previous:
                age = max(item["age_seconds"], self._age(previous, now))
                item["ttl_seconds"] = min(item["ttl_seconds"], previous["ttl_seconds"])
                if any(item.get(key) != previous.get(key) for key in _FIELDS):
                    self.revision += 1
                item["age_seconds"], item["_order"] = age, previous["_order"]
            else:
                self._sequence += 1
                item["_order"] = self._sequence
                new.append(item)
                self.revision += 1
            item["_at"] = now
            active.append(item)
        active.sort(key=lambda item: (-item["priority"], -item["_order"]))
        self._items = active
        self._prune(now)
        current = next((item for item in self._items if item["id"] == self._current), None)
        candidates = [item for item in new if self._age(item, now) < item["ttl_seconds"]]
        if candidates:
            candidate = max(candidates, key=lambda item: (item["priority"], item["_order"]))
            if current is None or candidate["priority"] >= current["priority"]:
                self._select(candidate["id"], now)
        return self.revision != before

    def current(self, now_ms):
        now = self._now(now_ms)
        self._prune(now)
        item = next((item for item in self._items if item["id"] == self._current), None)
        if item is None:
            return None
        result = {key: item[key] for key in _FIELDS}
        result["age_seconds"] = self._age(item, now)
        return result

    def dismiss(self, now_ms):
        now = self._now(now_ms)
        self._prune(now)
        if self._current is not None:
            self._remember(self._current)
            self._items = [item for item in self._items if item["id"] != self._current]
            self.revision += 1
            self._select(self._items[0]["id"] if self._items else None, now)
        return self.current(now)

    def next(self, direction, now_ms):
        now = self._now(now_ms)
        self._prune(now)
        if self._items:
            current = next((index for index, item in enumerate(self._items) if item["id"] == self._current), 0)
            step = 1 if isinstance(direction, (int, float)) and direction > 0 else -1 if isinstance(direction, (int, float)) and direction < 0 else 0
            self._select(self._items[(current + step) % len(self._items)]["id"], now)
        return self.current(now)


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, 2 * math.pi, False).fill()


def _line(ctx, points, colour, width=2):
    ctx.rgb(*colour)
    ctx.line_width = width
    for index, (x, y) in enumerate(points):
        if index:
            ctx.line_to(x, y)
        else:
            ctx.move_to(x, y)
    ctx.stroke()


def _icon(ctx, icon, x, y, r, colour, reveal=1):
    ctx.line_width = 2.3
    ctx.rgb(*colour)
    if icon == "check":
        points = ((x - r * .66, y), (x - r * .16, y + r * .48), (x + r * .72, y - r * .54))
        if reveal < .4:
            a, b, fraction = points[0], points[1], reveal / .4
            _line(ctx, (a, (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)), colour, 3.4)
        else:
            a, b = points[1], points[2]
            fraction = min(1, (reveal - .4) / .6)
            _line(ctx, (points[0], a, (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)), colour, 3.4)
    elif icon in ("warning", "error"):
        if icon == "warning":
            _line(ctx, ((x, y - r), (x + r, y + r * .75), (x - r, y + r * .75), (x, y - r)), colour)
            _line(ctx, ((x, y - r * .36), (x, y + r * .18)), colour, 2.8)
            _circle(ctx, x, y + r * .47, 1.5, colour)
        else:
            _line(ctx, ((x - r * .5, y - r * .5), (x + r * .5, y + r * .5)), colour, 3)
            _line(ctx, ((x + r * .5, y - r * .5), (x - r * .5, y + r * .5)), colour, 3)
    elif icon in ("download", "upload"):
        sign = 1 if icon == "download" else -1
        _line(ctx, ((x, y - r * .7 * sign), (x, y + r * .5 * sign)), colour)
        _line(ctx, ((x - r * .45, y + r * .05 * sign), (x, y + r * .5 * sign), (x + r * .45, y + r * .05 * sign)), colour)
        _line(ctx, ((x - r * .7, y + r * .65), (x - r * .7, y + r), (x + r * .7, y + r), (x + r * .7, y + r * .65)), colour)
    elif icon == "server":
        for offset in (-.65, 0, .65):
            ctx.rgb(*colour).rectangle(x - r * .8, y + r * offset - r * .22, r * 1.6, r * .44).stroke()
            _circle(ctx, x - r * .5, y + r * offset, 1.1, colour)
    elif icon == "lock":
        ctx.arc(x, y - r * .3, r * .5, math.pi, 2 * math.pi, False).stroke()
        ctx.rectangle(x - r * .7, y - r * .2, r * 1.4, r).stroke()
        _line(ctx, ((x, y + r * .17), (x, y + r * .5)), colour)
    elif icon == "message":
        _line(ctx, ((x - r, y - r * .65), (x + r, y - r * .65), (x + r, y + r * .5),
                    (x - r * .35, y + r * .5), (x - r * .8, y + r), (x - r * .8, y + r * .5),
                    (x - r, y + r * .5), (x - r, y - r * .65)), colour)
    elif icon == "heart":
        ctx.move_to(x, y + r * .8).curve_to(x - r * 1.5, y - r * .15, x - r * .75, y - r * 1.25, x, y - r * .55)
        ctx.curve_to(x + r * .75, y - r * 1.25, x + r * 1.5, y - r * .15, x, y + r * .8).fill()
    elif icon == "cloud":
        ctx.move_to(x - r, y + r * .4).curve_to(x - r * 1.4, y - r * .5, x - r * .3, y - r * .7, x - r * .1, y - r * .2)
        ctx.curve_to(x + r * .1, y - r * 1.2, x + r * 1.4, y - r * .5, x + r, y + r * .4)
        ctx.line_to(x - r, y + r * .4).stroke()
    elif icon == "bell":
        ctx.move_to(x - r * .75, y + r * .55).curve_to(x - r * .3, y + r * .1, x - r * .8, y - r * .75, x, y - r * .8)
        ctx.curve_to(x + r * .8, y - r * .75, x + r * .3, y + r * .1, x + r * .75, y + r * .55)
        ctx.line_to(x - r * .75, y + r * .55).stroke()
        _circle(ctx, x, y + r * .85, 2, colour)
    elif icon == "phone":
        _line(ctx, ((x - r * .65, y - r * .85), (x - r * .95, y - r * .45),
                    (x - r * .45, y + r * .45), (x + r * .45, y + r * .95),
                    (x + r * .85, y + r * .65), (x + r * .45, y + r * .2),
                    (x + r * .1, y + r * .4), (x - r * .4, y - r * .1),
                    (x - r * .2, y - r * .45), (x - r * .65, y - r * .85)), colour, 2.7)
    elif icon == "backup":
        ctx.arc(x, y, r * .8, -.4, 4.9, False).stroke()
        _line(ctx, ((x - r * .1, y - r), (x + r * .2, y - r * .65), (x + r * .48, y - r)), colour)
        _line(ctx, ((x, y - r * .3), (x, y + r * .4)), colour)
    else:
        _circle(ctx, x, y - r * .48, 2, colour)
        _line(ctx, ((x, y - r * .07), (x, y + r * .62)), colour, 2.8)


def _wrap(ctx, text, width, size, limit):
    ctx.font_size = size
    lines, current = [], ""
    for word in text.split():
        candidate = current + " " + word if current else word
        if ctx.text_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while word and ctx.text_width(word) > width:
            cut = len(word) - 1
            while cut > 1 and ctx.text_width(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
            if len(lines) >= limit:
                break
        current = word
        if len(lines) >= limit:
            break
    if current:
        lines.append(current)
    if len(lines) > limit:
        lines = lines[:limit]
        while lines[-1] and ctx.text_width(lines[-1] + "...") > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    return lines


def _label(ctx, text, y, size, colour):
    ctx.font_size = size
    ctx.rgb(*colour).move_to(0, y).text(text)


def draw_notification(ctx, item, now_ms, entered_ms, theme_id="original"):
    item = _notification(item)
    if item is None:
        return False
    now, entered = _time(now_ms), _time(entered_ms)
    age = max(0, now - entered)
    accent = _ACCENTS[item["type"]]
    background = _BACKGROUNDS.get(theme_id, _BACKGROUNDS["original"]) if isinstance(theme_id, str) else _BACKGROUNDS["original"]
    ctx.save()
    try:
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        ctx.rgb(*background).rectangle(-120, -120, 240, 240).fill()
        arrival = 1 - min(1, age / 360)
        ctx.translate(0, 11 * arrival * arrival * arrival)
        if item["style"] != "badge":
            ctx.rgb(*(min(1, c + .025) for c in background)).round_rectangle(-104, -78, 208, 174, 20).fill()
        angle = (now // 24) & 127
        ctx.line_width = 1.2
        ctx.rgb(*(c * .25 for c in accent)).arc(0, 0, 110, 0, 2 * math.pi, False).stroke()
        ctx.rgb(*accent).arc(0, 0, 110, angle * math.pi / 64, (angle + 17) * math.pi / 64, False).stroke()
        ctx.rgb(*accent)
        for index in range(8):
            c, s = _UNIT[(angle + index * 16) & 127]
            ctx.rectangle(c * 102 - 1, s * 102 - 1, 2, 2)
        ctx.fill()
        _label(ctx, "URGENT" if item["priority"] == 5 else item["type"].upper(), -94, 13, accent)
        title = _wrap(ctx, item["title"], 176, 26, 2)
        for index, line in enumerate(title):
            _label(ctx, line, -66 + index * 25, 26, (.96, .98, 1))
        # Animation stays behind the large semantic/source icon.
        if item["type"] == "warning":
            ctx.rgb(*(c * .44 for c in accent)).arc(0, 1, 30, 0, 2 * math.pi, False).stroke()
            c, s = _UNIT[(now // 12) & 127]
            _line(ctx, ((0, 1), (c * 29, 1 + s * 29)), (.43, .31, .10), 1)
        elif item["type"] == "failure":
            ctx.rgb(*(c * (.36 + .14 * _UNIT[(now // 18) & 127][1]) for c in accent))
            ctx.line_width = 2
            for index in range(8):
                c, s = _UNIT[index * 16]
                ctx.move_to(c * 26, 1 + s * 26).line_to(c * 31, 1 + s * 31)
            ctx.stroke()
        else:
            ctx.rgb(*(c * .38 for c in accent)).arc(0, 1, 29, 0, 2 * math.pi, False).stroke()
            for offset in (0, 43, 85):
                c, s = _UNIT[(angle + offset) & 127]
                _circle(ctx, c * 29, 1 + s * 29, 2.2, accent)
        _icon(ctx, item["icon"], 0, 1, 19, accent, min(1, age / 650))
        progress = item["progress"]
        # The third line sits near the circular screen's lower edge, where a
        # rectangular full-width paragraph would lose its end characters.
        body = _wrap(ctx, item["body"], 176 if progress is not None else 156, 18, 2 if progress is not None else 3)
        for index, line in enumerate(body):
            _label(ctx, line, 39 + index * 21, 18, (.73, .80, .88))
        if progress is not None:
            ctx.rgb(.10, .15, .22).round_rectangle(-66, 76, 132, 7, 3).fill()
            if progress > 0:
                ctx.rgb(*accent).round_rectangle(-66, 76, 132 * progress / 100, 7, min(3, 66 * progress / 100)).fill()
            _label(ctx, "%d%%" % round(progress), 98, 20, accent)
    finally:
        ctx.restore()
    return True


def urgent_eeh_colour(elapsed_ms):
    """Slow 4s red breathing cycle, 25%-100%; never an on/off strobe.

    This limits the programmed modulation, not a medical safety certification
    or a measurement of the LEDs' underlying PWM frequency.
    """
    phase = (_time(elapsed_ms) % 4000) * (2 * math.pi / 4000)
    return (round(159.5 - 95.5 * math.cos(phase)), 0, 0)


def led_frame(item, now_ms, brightness):
    """Twelve RGB indicators, capped at25% and never above user brightness."""
    item = _notification(item)
    level = max(0, min(.25, brightness)) if _number(brightness, 0, 1) else 0
    if item is None or level == 0:
        return [(0, 0, 0)] * 12
    now = _time(now_ms)
    colour, result = _ACCENTS[item["type"]], []
    head = now // 115 % 12
    wave = .56 + .30 * _UNIT[(now // 20) & 127][1]
    for index in range(12):
        distance = (head - index) % 12
        if item["progress"] is not None:
            gain = .8 if index < item["progress"] * 12 / 100 else .09
        elif item["type"] == "failure":
            gain = wave
        elif item["type"] == "success":
            gain = .18 + (.70 if distance < 3 else 0)
        else:
            gain = .08 + (.80 if distance == 0 else .35 if distance == 1 else .12 if distance == 2 else 0)
        result.append(tuple(int(c * level * gain * 255) for c in colour))
    return result
