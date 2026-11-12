"""Small, explicit configuration; credentials are environment variables only."""
import json
import math
import unicodedata


def validate_weather_config(raw):
    """Fixed, explicitly enabled weather location; keys/secrets stay private."""
    allowed = {"enabled", "latitude", "longitude", "location", "timezone"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError("weather must be an object with supported fields")
    weather = dict(raw)
    enabled = weather.setdefault("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("weather.enabled must be a boolean")
    for field, lower, upper in (("latitude", -90, 90), ("longitude", -180, 180)):
        if field not in weather and not enabled:
            continue
        value = weather.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError("weather." + field + " must be a finite valid coordinate")
        weather[field] = float(value)
    location = weather.setdefault("location", "")
    if (not isinstance(location, str) or len(location) > 80
            or any(unicodedata.category(character) == "Cc" for character in location)):
        raise ValueError("weather.location must be a short label without controls")
    if weather.setdefault("timezone", "Europe/London") != "Europe/London":
        raise ValueError("weather.timezone must be Europe/London")
    return weather


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("Configuration must be a JSON object")
    config = dict(raw)
    own = str(config.get("own_extension", "")).strip()
    if not own or len(own) > 32 or not own.isalnum():
        raise ValueError("own_extension must be a DN identifier")
    config["own_extension"] = own
    config.setdefault("own_name", "Me")
    team = config.get("team", [])
    if not isinstance(team, list) or not team or len(team) > 120:
        raise ValueError("team must contain between 1 and 120 extensions")
    seen = set()
    for member in team:
        if not isinstance(member, dict):
            raise ValueError("Each team member needs extension and name")
        dn = str(member.get("extension", "")).strip()
        if not dn or len(dn) > 32 or not dn.isalnum() or dn in seen:
            raise ValueError("Team extensions must be unique DN identifiers")
        member["extension"] = dn
        member["name"] = str(member.get("name", dn))[:80]
        seen.add(dn)
    for field in ("queues", "ddis", "contacts", "internal_extensions", "initials"):
        config.setdefault(field, {})
        if not isinstance(config[field], dict):
            raise ValueError(field + " must be an object mapping numbers to names")
    for field in ("priority_callers", "priority_ddis", "priority_extensions", "trunk_dns"):
        config.setdefault(field, [])
        if not isinstance(config[field], list) or any(not isinstance(x, str) for x in config[field]):
            raise ValueError(field + " must be a list of strings")
    for field, default, low, high in (
        ("stale_after_seconds", 5, 2, 30),
        ("refresh_interval_seconds", 2, 0.25, 10),
    ):
        value = config.setdefault(field, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(field + " is outside the supported range")
    if config["refresh_interval_seconds"] >= config["stale_after_seconds"]:
        raise ValueError("refresh_interval_seconds must be shorter than stale_after_seconds")
    config.setdefault("country_code", "44")
    country = str(config["country_code"])
    if not country.isdigit() or not 1 <= len(country) <= 3:
        raise ValueError("country_code must contain 1 to 3 digits")
    config["country_code"] = country
    if not isinstance(config.setdefault("phonebook_lookup", False), bool):
        raise ValueError("phonebook_lookup must be a boolean")
    config["weather"] = validate_weather_config(config.get("weather", {"enabled": False}))
    speed_dials = config.setdefault("speed_dials", [])
    if not isinstance(speed_dials, list) or len(speed_dials) > 24:
        raise ValueError("speed_dials must be a list of at most 24 targets")
    target_ids = set()
    for target in speed_dials:
        if not isinstance(target, dict) or set(target) - {"id", "label", "number"}:
            raise ValueError("Invalid speed dial target")
        key, number = target.get("id"), target.get("number")
        if (not isinstance(key, str) or not key or len(key) > 24
                or not all(c.isascii() and (c.isalnum() or c in "_-") for c in key)
                or key in target_ids):
            raise ValueError("Speed dial IDs must be unique simple identifiers")
        if (not isinstance(number, str) or not 2 <= len(number.lstrip("+")) <= 16
                or not number.isascii() or not number.lstrip("+").isdigit() or number.count("+") > 1
                or ("+" in number and not number.startswith("+"))
                or number == own):
            raise ValueError("Speed dial destinations must be phone numbers other than your own extension")
        target["label"] = str(target.get("label", key))[:12]
        target_ids.add(key)
    return config


def load_config(path):
    with open(path, encoding="utf-8-sig") as handle:
        return validate_config(json.load(handle))
