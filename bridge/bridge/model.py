"""Convert read-only 3CX snapshots to the badge protocol. No PBX operations."""
import math
import re


def text(value, limit=100):
    # PBX names are external input; remove controls and bound display/payload size.
    return "".join(c for c in str(value or "") if c >= " " and c != "\x7f")[:limit]


def normalize_number(value, country_code="44"):
    value = str(value or "").strip()
    if value.lower().startswith("tel:"):
        value = value[4:]
    value = re.sub(r"[\s().-]", "", value)
    if not re.fullmatch(r"\+?\d+", value):
        return ""
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("0") and len(value) >= 9:
        value = "+" + country_code + value[1:]
    elif value.startswith(country_code) and len(value) >= 11:
        value = "+" + value
    return value


def _type(value):
    result = str(value or "").lower()
    return result[1:] if result.startswith("w") else result


def _call_key(participant):
    value = participant.get("callid")
    # Missing IDs must never merge unrelated calls/queues.
    if value is not None and str(value) not in ("", "0"):
        return str(value)
    return "leg:" + str(participant.get("dn", "")) + ":" + str(participant.get("id", id(participant)))


def _direction(participant):
    if participant.get("_direction") in ("inbound", "outbound"):
        return participant["_direction"]
    if participant.get("party_caller_id") == "MakeCall" or participant.get("party_dn") == "MakeCall":
        return "outbound"
    return {"Ringing": "inbound", "Dialing": "outbound"}.get(participant.get("status"), "unknown")


def _first_name(value, initials=(), actual_first_name=False):
    """Use a supplied person's name, never manufacture one from a DN/alias."""
    value = text(value).strip()
    if not value or value.casefold() in {str(alias).strip().casefold() for alias in initials if alias}:
        return ""
    words = value.split()
    while words and words[0].rstrip(".").casefold() in ("mr", "mrs", "ms", "miss", "dr", "prof"):
        words.pop(0)
    if not words:
        return ""
    first = words[0]
    if (not any(character.isalpha() for character in first)
            or any(character.isdigit() for character in first)
            or first.casefold() in ("unknown", "anonymous", "unavailable", "withheld", "private", "external", "internal", "makecall", "me")
            or (not actual_first_name and len(words) == 1
                and len(first.replace(".", "")) <= 3 and first.replace(".", "").isupper())):
        return ""
    return text(first, 32)


def build_state(config, dns, connected, age_seconds, demo=False, status=""):
    country = str(config.get("country_code", "44"))
    norm = lambda value: normalize_number(value, country)
    age = float(age_seconds)
    if math.isfinite(age):
        age = max(0.0, age)
    live = bool(connected and math.isfinite(age) and age <= config.get("stale_after_seconds", 5))
    dns = [dn for dn in dns if isinstance(dn, dict)]
    directory = {str(dn.get("dn", "")): dn for dn in dns}
    team = config.get("team", [])
    internal_names = {str(k): str(v) for k, v in config.get("internal_extensions", {}).items()}
    known_internal = {str(x["extension"]): str(x.get("name", x["extension"])) for x in team}
    known_internal.update({str(k): str(v) for k, v in config.get("internal_extensions", {}).items()})
    known_internal[str(config["own_extension"])] = str(config.get("own_name", "Me"))
    queue_names = {str(k): str(v) for k, v in config.get("queues", {}).items()}
    for number, dn in directory.items():
        if _type(dn.get("type")) == "queue":
            queue_names.setdefault(number, number)
    ddi_names = {norm(k): str(v) for k, v in config.get("ddis", {}).items() if norm(k)}
    priority_ddis = {norm(x) for x in config.get("priority_ddis", []) if norm(x)}
    known_ddis = set(ddi_names) | priority_ddis
    priority_callers = {norm(x) for x in config.get("priority_callers", []) if norm(x)}
    priority_extensions = set(config.get("priority_extensions", []))
    contacts = {norm(k): str(v) for k, v in config.get("contacts", {}).items() if norm(k)}
    phonebook = {norm(k): str(v) for k, v in config.get("phonebook_contacts", {}).items() if norm(k)}
    aliases = {norm(k): text(v, 12) for k, v in config.get("initials", {}).items() if norm(k)}
    for entry in team:
        aliases.setdefault(norm(entry["extension"]), text(entry.get("name"), 12))
    legs_by_call = {}
    for dn in dns:
        for original in dn.get("participants", []):
            if isinstance(original, dict):
                participant = dict(original)
                participant.setdefault("dn", str(dn.get("dn", "")))
                legs_by_call.setdefault(_call_key(participant), []).append(participant)

    def describe(group):
        # A connected device and its still-ringing sibling are one answered call.
        rank = {"Undefined": 0, "Dialing": 1, "Ringing": 2, "Held": 3, "Hold": 4, "Connected": 5}
        chosen = max(group, key=lambda p: rank.get(p.get("status"), 0))
        related = legs_by_call.get(_call_key(chosen), group)
        peer_dn = str(chosen.get("party_dn", ""))
        if not peer_dn and _type(chosen.get("party_dn_type")) == "extension":
            peer_dn = str(chosen.get("party_caller_id", ""))
        peer_number = text(chosen.get("party_caller_id") or peer_dn, 40)
        peer_name = (contacts.get(norm(peer_number)) or phonebook.get(norm(peer_number))
                     or known_internal.get(peer_dn) or text(chosen.get("party_caller_name")))
        if peer_number == "MakeCall" or peer_dn == "MakeCall":
            peer_name, peer_number = "Outgoing call", ""
        routing = [str(p.get(field, "")) for p in related for field in ("referred_by_dn", "on_behalf_of_dn", "originated_by_dn")]
        queue = next((number for number in routing if number in queue_names), "")
        if not queue:
            queue = next((str(p.get("dn", "")) for p in related if str(p.get("dn", "")) in queue_names), "")
        # A known dialled number is required: an arbitrary external caller isn't a DDI.
        ddi = next((norm(p.get("party_did")) for p in group if norm(p.get("party_did")) in known_ddis), "")
        if not ddi:
            ddi = next((norm(p.get("party_did")) for p in related
                        if str(p.get("dn", "")) in config.get("trunk_dns", [])
                        and norm(p.get("party_did")) in known_ddis), "")
        internal = peer_dn in known_internal or _type(chosen.get("party_dn_type")) == "extension"
        peer_extension = text(peer_dn, 32) if internal and re.fullmatch(r"[0-9]{1,32}", peer_dn) else ""
        peer_first_name = ""
        if peer_extension:
            peer_aliases = [config.get("initials", {}).get(peer_extension, "")]
            candidates = [internal_names.get(peer_extension), config.get("directory_names", {}).get(peer_extension),
                          chosen.get("party_caller_name")]
            if peer_extension == str(config["own_extension"]):
                candidates.append(config.get("own_name"))
            candidates.extend(entry.get("name") for entry in team if str(entry["extension"]) == peer_extension)
            peer_first_name = next((name for index, candidate in enumerate(candidates)
                                    if (name := _first_name(candidate, peer_aliases, actual_first_name=index == 1))), "")
        kind = "queue" if queue else "internal" if internal else "ddi" if ddi else "external" if peer_number else "unknown"
        priority = (norm(peer_number) in priority_callers if norm(peer_number) else False) or peer_dn in priority_extensions or (bool(ddi) and ddi in priority_ddis)
        directions = {_direction(p) for p in group}
        direction = "outbound" if "outbound" in directions else "inbound" if "inbound" in directions else "unknown"
        raw_state = str(chosen.get("status", "Undefined"))
        return {
            "id": text(_call_key(chosen), 64), "state": raw_state.lower(), "direction": direction,
            "peer_name": text(peer_name), "peer_number": peer_number,
            "peer_extension": peer_extension, "peer_first_name": peer_first_name,
            "peer_initials": aliases.get(norm(peer_number)) or aliases.get(norm(peer_dn)) or "",
            "kind": kind, "priority": bool(priority), "ddi": ddi,
            "ddi_name": text(ddi_names.get(ddi, "")),
            "queue_number": queue, "queue_name": text(queue_names.get(queue, "")),
        }

    def member(number, name, slot=None):
        dn = directory.get(number)
        groups = {}
        if live and dn:
            for p in dn.get("participants", []):
                if isinstance(p, dict):
                    p = dict(p)
                    p.setdefault("dn", number)
                    groups.setdefault(_call_key(p), []).append(p)
        calls = [describe(group) for group in groups.values()]
        calls.sort(key=lambda c: (not (c["state"] == "ringing" and c["direction"] == "inbound"), not c["priority"], c["id"]))
        if not live or dn is None:
            state = "unknown"
        elif any(c["state"] == "ringing" for c in calls):
            state = "ringing"
        elif any(c["state"] in ("connected", "hold", "held", "dialing") for c in calls):
            state = "busy"
        elif calls or not dn.get("devices"):
            state = "unknown"
        else:
            state = "idle"
        result = {"extension": number, "name": text(name, 80), "state": state, "calls": calls}
        if slot is not None:
            result["led"] = slot % 12 + 1
        return result

    own = member(str(config["own_extension"]), config.get("own_name", "Me"))
    alerts = [c for c in own["calls"] if c["state"] == "ringing" and c["direction"] == "inbound"]
    alerts.sort(key=lambda c: (not c["priority"], c["id"]))
    return {
        "version": 1, "demo": bool(demo), "connected": live,
        "status": text(status or ("live" if live else "offline"), 80),
        "age_seconds": round(age, 2) if math.isfinite(age) else None,
        "team": [member(str(m["extension"]), m.get("name", m["extension"]), index) for index, m in enumerate(team)],
        "own": own, "alert": alerts[0] if alerts else None,
    }
