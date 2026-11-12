"""Small theme catalog and local-calendar rules; no network or filesystem.

Auto priority: your birthday, partner birthday, anniversary, Christmas
(December1–26), then Easter (Good Friday through Easter Monday).
Personal dates belong in private config, never in public manifests. February29
occasions repeat on February28 in other years, or March1 with theme_leap_day.
"""

DATE_FIELDS = ("birthday_self", "birthday_partner", "anniversary")
THEMES = (
    ("original", "Original", "classic"),
    ("christmas", "Christmas", "seasonal"),
    ("easter", "Easter", "seasonal"),
    ("anniversary", "Anniversary", "personal"),
    ("birthday_self", "My birthday", "personal"),
    ("birthday_partner", "Partner birthday", "personal"),
    ("cyberpunk", "Cyberpunk", "style"),
    ("lcars", "LCARS", "style"),
    ("kitty", "Cute cat", "style"),
    ("photo", "Photo", "photo"),
    ("noir", "Noir", "style"),
    ("ocean", "Ocean", "style"),
    ("retro", "Retro", "style"),
)


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _valid_date(year, month, day):
    if (any(isinstance(value, bool) or not isinstance(value, int) for value in (year, month, day))
            or not 1583 <= year <= 4099 or not 1 <= month <= 12):
        return False
    lengths = (31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 1 <= day <= lengths[month - 1]


def parse_iso_date(value):
    """Return a valid private YYYY-MM-DD tuple, bounded to1900–2100."""
    if (not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-"
            or any(value[index] not in "0123456789" for index in (0, 1, 2, 3, 5, 6, 8, 9))):
        return None
    year, month, day = int(value[:4]), int(value[5:7]), int(value[8:])
    return (year, month, day) if 1900 <= year <= 2100 and _valid_date(year, month, day) else None


def _local_date(local):
    if not isinstance(local, (tuple, list)) or len(local) < 3:
        return None
    year, month, day = local[:3]
    return (year, month, day) if _valid_date(year, month, day) else None


def _ordinal(date):
    year, month, day = date
    previous = year - 1
    before = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    return previous * 365 + previous // 4 - previous // 100 + previous // 400 + before[month - 1] + day + (month > 2 and _leap(year))


def easter_date(year):
    """Gregorian Easter Sunday (Meeus/Jones/Butcher),1583–4099."""
    if isinstance(year, bool) or not isinstance(year, int) or not 1583 <= year <= 4099:
        return None
    a, b, c = year % 19, year // 100, year % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    value = h + l - 7 * m + 114
    return year, value // 31, value % 31 + 1


def _safe_id(value):
    return (isinstance(value, str) and 1 <= len(value) <= 32 and value[0] in "abcdefghijklmnopqrstuvwxyz"
            and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in value))


def _label(value, limit):
    return isinstance(value, str) and 1 <= len(value) <= limit and all(c >= " " and c != "\x7f" for c in value)


class ThemeManager:
    def __init__(self, config=None, extra_themes=None):
        self.config = config if isinstance(config, dict) else {}
        self._catalog = [{"id": key, "name": name, "kind": kind, "available": True,
                          "requires_asset": kind == "photo"} for key, name, kind in THEMES]
        known = {item["id"] for item in self._catalog}
        if isinstance(extra_themes, (list, tuple)):
            for item in extra_themes[:16]:
                if (not isinstance(item, dict) or not _safe_id(item.get("id")) or item["id"] in known
                        or item["id"] == "auto" or not _label(item.get("name"), 40)):
                    continue
                self._catalog.append({"id": item["id"], "name": item["name"], "kind": "external",
                                      "available": item.get("available") is True, "requires_asset": True})
                known.add(item["id"])
        self._by_id = {item["id"]: item for item in self._catalog}

    def catalog(self):
        """Return only bounded public metadata; never personal configuration."""
        return [dict(item) for item in self._catalog]

    @property
    def selection(self):
        if self.config.get("theme_auto") is True:
            return "auto"
        value = self.config.get("theme", "original")
        return value if isinstance(value, str) and value in self._by_id else "original"

    def select(self, theme_id):
        if theme_id == "auto":
            self.config["theme_auto"] = True
            return True
        if not isinstance(theme_id, str) or theme_id not in self._by_id:
            return False
        self.config.update(theme=theme_id, theme_auto=False)
        return True

    def set_auto(self, enabled):
        if not isinstance(enabled, bool):
            return False
        self.config["theme_auto"] = enabled
        return True

    def personal_date(self, key):
        values = self.config.get("personal_dates")
        value = values.get(key) if isinstance(values, dict) and key in DATE_FIELDS else None
        return value if parse_iso_date(value) else None

    def set_personal_date(self, key, value):
        if key not in DATE_FIELDS or (value is not None and parse_iso_date(value) is None):
            return False
        dates = self.config.get("personal_dates")
        dates = dict(dates) if isinstance(dates, dict) else {}
        if value is None:
            dates.pop(key, None)
        else:
            dates[key] = value
        self.config["personal_dates"] = dates
        return True

    def _occasion(self, key, today):
        value = parse_iso_date(self.personal_date(key))
        if value is None or today is None or value > today:
            return False, None
        month, day = value[1:]
        if month == 2 and day == 29 and not _leap(today[0]):
            month, day = (3, 1) if self.config.get("theme_leap_day") == "mar1" else (2, 28)
        if (month, day) != today[1:]:
            return False, None
        count = today[0] - value[0]
        limit = 130 if key.startswith("birthday") else 200
        return True, count if 1 <= count <= limit else None

    def resolve(self, local, photo_available=False):
        """Resolve using London local calendar values supplied by the app.

        Result is safe to pass to a renderer: no raw private ISO date is returned.
        Missing calendar data never guesses a seasonal/personal occasion.
        """
        today = _local_date(local)
        automatic = self.config.get("theme_auto") is True
        requested = self.selection
        theme_id = "original" if automatic else requested
        easter = easter_date(today[0]) if today else None
        offset = _ordinal(today) - _ordinal(easter) if today else None
        if automatic and today:
            theme_id = next((key for key in DATE_FIELDS if self._occasion(key, today)[0]), None)
            if theme_id is None:
                theme_id = "christmas" if today[1] == 12 and 1 <= today[2] <= 26 else "easter" if -2 <= offset <= 1 else "original"
        requested_id = theme_id
        metadata = self._by_id.get(theme_id, self._by_id["original"])
        fallback = None
        if theme_id == "photo" and photo_available is not True:
            fallback = "photo_missing"
        elif metadata["kind"] == "external" and not metadata["available"]:
            fallback = "asset_missing"
        if fallback:
            theme_id, metadata = "original", self._by_id["original"]
        match, count = self._occasion(theme_id, today) if theme_id in DATE_FIELDS else (False, None)
        event = theme_id if match or (today and theme_id == "christmas" and today[1] == 12 and 1 <= today[2] <= 26) or (today and theme_id == "easter" and -2 <= offset <= 1) else None
        advent = bool(today and theme_id == "christmas" and today[1] == 12 and 1 <= today[2] <= 24
                      and self.config.get("theme_advent_enabled", True) is True)
        result = {"id": theme_id, "name": metadata["name"], "requested_id": requested_id,
                  "auto": automatic, "event": event, "age": count if match and theme_id.startswith("birthday") else None,
                  "years": count if match and theme_id == "anniversary" else None,
                  "caption": "Happy birthday" if theme_id.startswith("birthday") else "Happy anniversary" if theme_id == "anniversary" else "Happy Easter" if theme_id == "easter" else "Merry Christmas" if theme_id == "christmas" else metadata["name"],
                  "event_name": {"birthday_self": "Your birthday", "birthday_partner": "Partner birthday", "anniversary": "Anniversary"}.get(theme_id, metadata["name"]),
                  "advent": advent, "advent_day": today[2] if advent else None,
                  "days_until_christmas": max(0, 25 - today[2]) if today and theme_id == "christmas" and today[1] == 12 and today[2] <= 26 else None,
                  "easter_offset": offset if today and -2 <= offset <= 1 else None,
                  "year": today[0] if today else None, "month": today[1] if today else None,
                  "day": today[2] if today else None, "weekday": (_ordinal(today) - 1) % 7 if today else None,
                  "fallback_reason": fallback}
        return result
