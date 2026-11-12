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


def draw_bunny(ctx, now_ms):
    """Small native-vector rabbit, waving without external image assets."""
    ctx.save()
    ctx.translate(0, 33 + math.sin(now_ms / 350) * 1.5)
    cream, pink, ink = (.98, .95, .91), (1, .53, .65), (.18, .12, .18)
    def disc(x, y, radius, colour):
        ctx.rgb(*colour).arc(x, y, radius, 0, math.pi * 2, False).fill()
    def oval(x, y, rx, ry, colour):
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(rx, ry)
        disc(0, 0, 1, colour)
        ctx.restore()
    oval(-15, -28, 10, 31, cream)
    oval(13, -30, 10, 32, cream)
    oval(-15, -29, 4, 21, pink)
    oval(13, -31, 4, 22, pink)
    oval(0, 33, 27, 30, cream)
    oval(0, 38, 18, 20, (1, .85, .84))
    oval(-18, 58, 15, 8, cream)
    oval(18, 58, 15, 8, cream)
    disc(-24, 32, 9, cream)
    ctx.save()
    ctx.translate(25, 24)
    ctx.rotate(-.6 + math.sin(now_ms / 150) * .45)
    oval(7, -13, 9, 20, cream)
    disc(9, -25, 10, cream)
    disc(9, -25, 4, pink)
    ctx.restore()
    oval(0, 0, 32, 27, cream)
    disc(-20, 9, 6, pink)
    disc(20, 9, 6, pink)
    blink = now_ms % 3600 > 3440
    for x in (-11, 11):
        if blink:
            ctx.line_width = 2
            ctx.rgb(*ink).move_to(x - 3, -3).line_to(x + 3, -3).stroke()
        else:
            oval(x, -3, 3, 4, ink)
            disc(x - .7, -4, .9, (1, 1, 1))
    disc(0, 6, 3, pink)
    ctx.line_width = 1.5
    ctx.rgb(*ink).move_to(0, 9).line_to(0, 13)
    ctx.move_to(-5, 12).curve_to(-3, 17, 3, 17, 5, 12).stroke()
    ctx.restore()
