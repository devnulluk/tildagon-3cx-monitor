"""Exact private partner matching and lightweight call decoration."""
import math

ACTIVE = ("ringing", "dialing", "connected", "busy", "hold", "held")


def normalise(value):
    if not isinstance(value, str) or len(value) > 80:
        return None
    value = value.strip()
    if value.lower().startswith("tel:"):
        value = value[4:]
    if any(c not in "0123456789+ ()-." for c in value):
        return None
    value = "".join(c for c in value if c in "0123456789+")
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("0") and len(value) == 11:
        value = "+44" + value[1:]
    if "+" in value[1:] or not 7 <= len(value.lstrip("+")) <= 15:
        return None
    return value


def partner_call(call, config, demo=False):
    if not isinstance(call, dict) or str(call.get("state", "")).lower() not in ACTIVE:
        return False
    # Explicit synthetic initials work only inside the isolated demo.
    if demo and call.get("peer_initials") == "KZ":
        return True
    targets = config.get("partner_numbers") if isinstance(config, dict) else None
    number = normalise(call.get("peer_number"))
    return bool(number and isinstance(targets, (tuple, list))
                and any(number == normalise(value) for value in targets[:8]))


def partner_active(payload, live, config, demo=False):
    if not live or not isinstance(payload, dict):
        return False
    own = payload.get("own")
    if not isinstance(own, dict):
        return False
    calls = own.get("calls")
    if not isinstance(calls, (list, tuple)):
        return False
    return any(partner_call(call, config, demo) for call in calls[:16])


def draw_love(ctx, now_ms):
    """Two rose hearts frame the caller ID without covering its readout."""
    pulse = .8 + .2 * math.sin(now_ms / 280)
    for x, y, scale in ((-78, -48, 12 * pulse), (78, -48, 12 * pulse)):
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(scale, scale)
        ctx.rgb(.95, .16, .40).move_to(0, .85)
        ctx.curve_to(-1.5, -.15, -.75, -1.25, 0, -.55)
        ctx.curve_to(.75, -1.25, 1.5, -.15, 0, .85).fill()
        ctx.restore()
