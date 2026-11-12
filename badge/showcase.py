"""Theme-major on-device demonstration; no network, credentials or actions.

Only compact catalog metadata and one playback cursor are retained. Payloads
are generated when requested. All identities, dates and calls are synthetic.
"""

_BEFORE = (
    ("intro", "intro", "team", "day", "Theme preview", None),
    ("weather", "weather", "team", "day", "Day forecast", None),
    ("weather", "weather", "team", "night", "Night forecast", None),
    ("weather", "weather", "team", "rain", "Rain forecast", None),
    ("weather", "weather", "team", "storm", "Storm forecast", None),
    ("weather", "weather", "team", "snow", "Snow forecast", None),
    ("weather", "weather", "team", "fog", "Fog forecast", None),
    ("rain", "rain", "team", "rain", "Next hour / rain", "wet"),
    ("rain", "rain", "team", "day", "Next hour / dry", "dry"),
)
_AFTER = (
    ("moon", "moon", "team", "night", "Computed moon phase", None),
    ("meteors", "meteors", "team", "night", "Active meteor calendar", None),
    ("team", None, "team", "day", "Team status overview", None),
    ("team_detail", None, "team", "day", "Internal team call", "internal"),
    ("team_detail", None, "team", "day", "External team call", "external"),
    ("call", None, "ddi", "day", "Incoming direct call", None),
    ("call", None, "internal", "day", "Incoming internal call", None),
    ("call", None, "queue", "day", "Incoming queue call", None),
    ("call", None, "priority", "day", "High-priority call", None),
    ("call", None, "partner", "day", "Partner celebration", None),
    ("call", None, "connected", "day", "Connected own call", None),
    ("call", None, "outgoing", "day", "Outgoing call / dialling", None),
    ("call", None, "outgoing_connected", "day", "Outgoing call / connected timer", None),
    ("call", None, "partner_connected", "day", "Connected partner call", None),
    ("notification", None, "team", "day", "Information notification", "info"),
    ("notification", None, "team", "day", "Success notification", "success"),
    ("notification", None, "team", "day", "Warning notification", "warning"),
    ("notification", None, "team", "day", "Failure notification", "failure"),
    ("notification", None, "team", "day", "Progress / 25 percent", "progress25"),
    ("notification", None, "team", "day", "Progress / 75 percent", "progress75"),
    ("presence", None, "team", "day", "Own status / available", "available"),
    ("presence", None, "team", "day", "Own status / away", "away"),
    ("presence", None, "team", "day", "Own status / DND", "dnd"),
    ("settings", "settings", "team", "day", "Brightness and appearance settings", None),
    ("menu", None, "team", "day", "Main menu", None),
)
_DATES = {"easter": "2027-03-28", "anniversary": "2027-09-10",
          "birthday_self": "2027-02-03", "birthday_partner": "2027-06-07"}
_TEAMS = (("101", "Alex"), ("102", "Sam"), ("103", "Jo"), ("104", "Pat"))
_CALLER = "+441632960123"  # Reserved example range, not a real destination.
_PARTNER = "+441632960789"
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 9007199254740991


def _identifier(value):
    return (isinstance(value, str) and 1 <= len(value) <= 32
            and value[0] in "abcdefghijklmnopqrstuvwxyz"
            and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in value))


def _direction(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not -1e15 < value < 1e15:
        return 0
    return 1 if value > 0 else -1 if value < 0 else 0


def _catalog(values, limit):
    result, seen = [], []
    if isinstance(values, (list, tuple)):
        for raw in values[:limit]:
            item = {"id": raw, "name": raw} if isinstance(raw, str) else raw
            if not isinstance(item, dict) or not _identifier(item.get("id")) or item["id"] in seen:
                continue
            name = item.get("name")
            name = "".join(c for c in name[:40] if 32 <= ord(c) != 127) if isinstance(name, str) else item["id"]
            result.append((item["id"], name or item["id"], item.get("available", True) is True))
            seen.append(item["id"])
    return tuple(result) or (("original", "Original", True),)


def demo_config():
    """Fresh synthetic occasion/partner metadata; deliberately no connection keys."""
    return {"demo": True, "theme": "original", "theme_auto": False, "clock_style": "original",
            "personal_dates": {"birthday_self": "1990-02-03", "birthday_partner": "1991-06-07",
                               "anniversary": "2020-09-10"},
            "partner_name": "Partner", "partner_surname": "Example", "partner_numbers": [_PARTNER]}


class Showcase:
    def __init__(self, theme_catalog, clock_catalog, step_ms=5000):
        if not _finite(step_ms) or not 250 <= step_ms <= 60000:
            raise ValueError("Showcase steps must be250..60000 milliseconds")
        self.themes = _catalog(theme_catalog, 29)
        self.clocks = _catalog(clock_catalog, 16)
        self.step_ms = int(step_ms)
        self.paused = False
        self._position = 0
        self._wall = None
        self._slot = 0
        self._visit = 0
        starts, total = [], 0
        for key, name, available in self.themes:
            starts.append(total)
            total += len(_BEFORE) + len(self.clocks) + len(_AFTER) + (key == "christmas")
        self._starts, self.count = tuple(starts), total

    def _sync(self, now_ms):
        now = int(now_ms) if _finite(now_ms) else (self._wall or 0)
        now = max(self._wall or 0, now)
        if self._wall is not None and not self.paused:
            self._position += now - self._wall
        self._wall = now
        slot = self._position // self.step_ms
        if slot != self._slot:
            self._visit = (self._visit + abs(slot - self._slot)) & 0xffffffff
            self._slot = slot

    def _describe(self, index, elapsed=0, loop=0):
        index %= self.count
        theme_index = 0
        for candidate in range(len(self._starts) - 1, -1, -1):
            if index >= self._starts[candidate]:
                theme_index = candidate
                break
        theme, theme_name, available = self.themes[theme_index]
        local = index - self._starts[theme_index]
        steps = len(_BEFORE) + len(self.clocks) + len(_AFTER) + (theme == "christmas")
        clock = self.clocks[0][0]
        if local < len(_BEFORE):
            spec = _BEFORE[local]
        elif local < len(_BEFORE) + len(self.clocks):
            clock, clock_name, clock_available = self.clocks[local - len(_BEFORE)]
            spec = ("clock", "clock", "team", "night", "Clock / " + clock_name, None)
        else:
            at = local - len(_BEFORE) - len(self.clocks)
            spec = _AFTER[at] if at < len(_AFTER) else ("advent", "advent", "team", "night", "December Advent", None)
        feature, page, scene, weather, label, variant = spec
        date = "2027-12-14" if feature in ("meteors", "advent") else _DATES.get(theme, "2027-12-14")
        stage = {"id": "showcase-%08x-%03x" % (self._visit, index),
                 "theme": theme, "theme_name": theme_name, "available": available,
                 "render_theme": theme if available else "original", "feature": feature,
                 "label": label, "page": page, "clock": clock, "scene": scene,
                 "date": date, "weather_kind": weather, "presence": "available", "detail": None,
                 "partner": scene in ("partner", "partner_connected"), "notification": None,
                 "own_view": scene in ("connected", "partner_connected"), "team_index": 0,
                 "index": index, "theme_index": theme_index, "theme_count": len(self.themes),
                 "step_index": local, "step_count": steps, "loop": loop, "paused": self.paused,
                 "elapsed_ms": elapsed, "remaining_ms": self.step_ms - elapsed}
        if feature == "team_detail":
            stage["detail"] = variant
            stage["team_index"] = 0 if variant == "internal" else 1
        elif feature == "notification":
            stage["notification"] = variant
            stage["progress"] = 25 if variant == "progress25" else 75 if variant == "progress75" else None
        elif feature == "presence":
            stage["presence"], stage["own_view"] = variant, True
        elif feature == "settings":
            stage["settings_selected"] = 0
        return stage

    def stage(self, index):
        """Side-effect-free zero-based lookup for labelled representative captures."""
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Showcase stage index must be an integer")
        return self._describe(index)

    def current(self, now_ms):
        self._sync(now_ms)
        slot, elapsed = divmod(self._position, self.step_ms)
        loop, index = divmod(slot, self.count)
        return self._describe(index, elapsed, loop)

    def progress(self, now_ms):
        stage = self.current(now_ms)
        return {key: stage[key] for key in ("index", "theme_index", "theme_count", "step_index",
                                            "step_count", "loop", "paused", "elapsed_ms", "remaining_ms")}

    def seek(self, index, now_ms):
        self._sync(now_ms)
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Showcase stage index must be an integer")
        loop = self._position // (self.count * self.step_ms)
        self._position = (loop * self.count + index % self.count) * self.step_ms
        self._slot = self._position // self.step_ms
        self._visit = (self._visit + 1) & 0xffffffff
        return self.current(now_ms)

    def advance(self, direction, now_ms):
        self._sync(now_ms)
        direction = _direction(direction)
        if direction:
            target = self._position // self.step_ms + direction
            self._position = target * self.step_ms if target >= 0 else (self.count - 1) * self.step_ms
            self._slot = self._position // self.step_ms
            self._visit = (self._visit + 1) & 0xffffffff
        return self.current(now_ms)

    def next_theme(self, direction, now_ms):
        stage = self.current(now_ms)
        step = _direction(direction)
        if not step:
            return stage
        return self.seek(self._starts[(stage["theme_index"] + step) % len(self.themes)], now_ms)

    def toggle_pause(self, now_ms):
        self._sync(now_ms)
        self.paused = not self.paused
        return self.paused


def _ordinal(year, month, day):
    before = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    previous = year - 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return previous * 365 + previous // 4 - previous // 100 + previous // 400 + before[month - 1] + day + (month > 2 and leap)


def _weather(stage, now_ms):
    # Dates are pinned synthetic calendar days. Seconds keep advancing while
    # the operator pauses a stage; no real clock or personal date is read.
    date = stage.get("date", "2027-12-14")
    try:
        year, month, day = (int(value) for value in date.split("-"))
        if not 2020 <= year <= 2100 or not 1 <= month <= 12 or not 1 <= day <= 28:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        year, month, day = 2027, 12, 14
    kind = stage.get("weather_kind", "day")
    night = kind == "night"
    second_of_day = ((21 if night else 12) * 3600 + 7 * 60 + (int(now_ms) // 1000 if _finite(now_ms) else 0)) % 86400
    hour, remaining = divmod(second_of_day, 3600)
    minute, second = divmod(remaining, 60)
    march_sunday = 31 - ((_ordinal(year, 3, 31) - 1) % 7 - 6) % 7
    october_sunday = 31 - ((_ordinal(year, 10, 31) - 1) % 7 - 6) % 7
    ordinal = _ordinal(year, month, day)
    offset = 3600 if _ordinal(year, 3, march_sunday) <= ordinal < _ordinal(year, 10, october_sunday) else 0
    unix = (ordinal - _ordinal(1970, 1, 1)) * 86400 + second_of_day - offset
    current = {"temperature_c": 8.1 if night else 18.4, "apparent_temperature_c": 5.5 if night else 17.0,
               "condition": "Clear", "weather_code": 0, "is_day": not night, "wind_kmh": 8.2,
               "forecast_at": unix}
    rain = {"status": "dry_likely", "precipitation_mm": 0.0, "onset_minutes": None,
            "window_start": unix, "window_end": unix + 3600, "resolution_minutes": 15,
            "interpolated": True, "basis": "model_forecast", "peak_overlapping_hourly_probability_percent": 5}
    conditions = {"rain": (10.4, 8.5, "Light rain", 61, 12.0, .8),
                  "storm": (13.0, 10.0, "Thunderstorm", 95, 38.0, 3.1),
                  "snow": (-1.4, -4.2, "Snow", 73, 16.0, .6),
                  "fog": (5.0, 2.0, "Fog", 45, 4.0, 0.0)}
    if kind in conditions:
        temperature, feels, condition, code, wind, amount = conditions[kind]
        current.update(temperature_c=temperature, apparent_temperature_c=feels, condition=condition,
                       weather_code=code, wind_kmh=wind)
        if amount:
            rain.update(status="rain_likely", precipitation_mm=amount,
                        onset_minutes=[15, 30] if kind == "rain" else [0, 15],
                        peak_overlapping_hourly_probability_percent=95 if kind == "storm" else 80 if kind == "snow" else 60)
    weekday = (ordinal - 1) % 7
    return {"status": "live", "live": True, "available": True, "stale": False, "demo": True,
            "source": "DEMO", "attribution": "Synthetic demonstration data", "location": "Westmoor",
            "now_unix": unix, "local_clock": "%02d:%02d" % (hour, minute),
            "local_date": "%s %02d %s" % (_DAYS[weekday], day, _MONTHS[month - 1]),
            "local_date_iso": "%04d-%02d-%02d" % (year, month, day), "utc_offset_seconds": offset,
            "fetched_at": unix, "age_seconds": 0, "current": current, "rain_next_hour": rain}


def _call(scene, key):
    internal = scene == "internal"
    partner = scene in ("partner", "partner_connected")
    connected = scene in ("connected", "partner_connected", "outgoing_connected")
    return {"id": key, "state": "connected" if connected else "dialing" if scene == 'outgoing' else "ringing",
            "direction": "outbound" if scene.startswith('outgoing') else "inbound",
            "kind": "internal" if internal else "queue" if scene == "queue" else "ddi",
            "priority": scene == "priority" or partner,
            "peer_name": "Taylor Example" if internal else "Partner" if partner else "Example caller",
            "peer_initials": "TE" if internal else "KZ" if partner else "EC",
            "peer_number": "105" if internal else _PARTNER if partner else _CALLER,
            "peer_extension": "105" if internal else None, "peer_first_name": "Taylor" if internal else None,
            "ddi": "01632960100" if not internal else "",
            "queue_name": "Example support" if scene == "queue" else "",
            "queue_number": "800" if scene == "queue" else ""}


def _notification(stage):
    variant = stage.get("notification")
    progress = 25 if variant == "progress25" else 75 if variant == "progress75" else None
    kind = variant if variant in ("info", "success", "warning", "failure") else "info"
    title, body = {"info": ("System update", "Synthetic status from an example server."),
                   "success": ("Build completed", "Example checks finished successfully."),
                   "warning": ("Storage warning", "An example volume is nearing capacity."),
                   "failure": ("Backup failed", "Synthetic alert for this demonstration.")}[kind]
    if progress is not None:
        title, body = "Download progress", "An example transfer is running."
    identity = stage.get("id")
    identity = identity if isinstance(identity, str) and len(identity) <= 48 else "showcase-preview"
    return {"id": identity + "-notice", "title": title, "body": body, "type": kind,
            "priority": 4 if kind in ("warning", "failure") else 3,
            "style": "progress" if progress is not None else "toast" if kind == "warning" else "badge" if kind == "success" else "card",
            "icon": "download" if progress is not None else {"info": "server", "success": "check", "warning": "warning", "failure": "error"}[kind],
            "progress": progress, "ttl_seconds": 86400, "age_seconds": 0}


def snapshot(stage, now_ms=0):
    """Build one fresh Controller-compatible synthetic snapshot, without I/O."""
    stage = stage if isinstance(stage, dict) else {}
    team = [{"extension": number, "name": name, "led": index + 1, "state": "idle",
             "registered": True, "calls": []} for index, (number, name) in enumerate(_TEAMS)]
    presence = stage.get("presence")
    presence = presence if presence in ("available", "away", "dnd") else "available"
    own = {"extension": "100", "name": "Demo user", "registered": True, "state": "idle", "calls": [],
           "presence": {"state": presence, "confirmed": True, "age_seconds": 0,
                        "profile": {"available": "Available", "away": "Away", "dnd": "Out of office"}[presence]}}
    alert, feature = None, stage.get("feature")
    key = stage.get("id") if isinstance(stage.get("id"), str) else "showcase-preview"
    if feature == "call":
        call = _call(stage.get("scene"), key + "-call")
        own.update(state="ringing" if call["state"] == "ringing" else "busy", calls=[call])
        alert = call if call["state"] == "ringing" else None
    elif feature in ("team", "team_detail"):
        internal = {"id": key + "-internal", "state": "connected", "direction": "outbound",
                    "peer_name": "Alex Example", "peer_first_name": "Alex", "peer_extension": "245",
                    "peer_number": "245", "peer_initials": "AE", "kind": "internal", "priority": False}
        external = {"id": key + "-external", "state": "connected", "direction": "outbound",
                    "peer_name": "Example customer", "peer_number": "+441632960456", "peer_initials": "EC",
                    "peer_extension": None, "peer_first_name": None, "kind": "external", "priority": False}
        if feature == "team":
            team[1].update(state="busy", calls=[internal])
            team[2].update(state="ringing", calls=[dict(external, state="ringing", direction="inbound")])
            team[3].update(state="unknown", registered=False)
        elif stage.get("detail") == "internal":
            team[0].update(state="busy", calls=[internal])
        else:
            team[1].update(state="busy", calls=[external])
    return {"version": 1, "demo": True, "connected": True, "status": "DEMO SHOWCASE",
            "age_seconds": 0, "team": team, "own": own, "alert": alert,
            "weather": _weather(stage, now_ms),
            "notifications": [_notification(stage)] if feature == "notification" else [],
            "controls": {"enabled": False, "call": False, "dnd": False,
                         "session_id": "showcase-display-only", "targets": []}}
