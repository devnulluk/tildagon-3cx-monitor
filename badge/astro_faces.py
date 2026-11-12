"""Bounded native-vector Moon and meteor calendar faces for the round LCD.

Scientific values come only from astronomy.sky_snapshot. Meteor streaks and
stars are decorative: their number/speed never claims an observed meteor rate.
"""
import math
from .astronomy import sky_snapshot
from .clocks import draw_moon

TAU = math.pi * 2
_DEFAULT = ((.045, .055, .16), (.008, .015, .045), (.025, .045, .10),
            (.95, .97, 1), (.57, .68, .82), (.37, .83, 1), False)
_ROWS = tuple((-120 + index * 10, 10) for index in range(24))
_STARS = ((-85, -56, 1.2), (-61, -79, 1), (-28, -58, 1.5), (21, -91, 1),
          (61, -67, 1.4), (88, -38, 1), (-99, 4, 1.3), (95, 14, 1.4),
          (-76, 53, 1), (72, 58, 1.2), (-43, 83, 1), (41, 89, 1))
_TICKS = tuple((math.cos(index * TAU / 12), math.sin(index * TAU / 12)) for index in range(12))
_CRATERS = ((-.34, -.16, .10), (.24, -.27, .07), (.39, .20, .11), (-.23, .40, .07))
_TRAILS = ((-111, -65, 650, 2300), (-40, -77, 1100, 3100), (29, -48, 1700, 3700))
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_cached_palette = _cached_bands = None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) < 1e18


def _palette(value):
    if not isinstance(value, (tuple, list)) or len(value) < 6:
        return _DEFAULT
    for colour in value[:6]:
        if (not isinstance(colour, (tuple, list)) or len(colour) != 3
                or any(not _finite(c) or not 0 <= c <= 1 for c in colour)):
            return _DEFAULT
    if isinstance(value, tuple) and len(value) == 7 and all(isinstance(colour, tuple) for colour in value[:6]):
        return value
    return tuple(tuple(colour) for colour in value[:6]) + (value[6] is True if len(value) > 6 else False,)


def _mix(first, second, amount):
    return tuple(first[index] + (second[index] - first[index]) * amount for index in range(3))


def _text(ctx, value, y, size, width=204, colour=(1, 1, 1), minimum=14, x=0):
    value = "".join(c for c in str(value or "") if c >= " " and c != "\x7f")[:64]
    ctx.font_size = size
    while size > minimum and ctx.text_width(value) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(x, y).text(value)


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _ring(ctx, x, y, radius, colour, width=1, start=0, end=TAU):
    ctx.line_width = width
    ctx.rgb(*colour).arc(x, y, radius, start, end, False).stroke()


def _background(ctx, palette, now):
    global _cached_palette, _cached_bands
    if palette != _cached_palette:
        _cached_palette = palette
        _cached_bands = tuple(_mix(palette[0], palette[1], (index + .5) / 24) for index in range(24))
    for index, (y, height) in enumerate(_ROWS):
        ctx.rgb(*_cached_bands[index]).rectangle(-120, y, 240, height).fill()
    star_dim, star_bright = _mix(palette[4], palette[0], .3), _mix(palette[3], palette[5], .2)
    phase = int(now // 900) % 4
    for index, (x, y, radius) in enumerate(_STARS):
        _circle(ctx, x, y, radius, star_bright if (index + phase) % 4 == 0 else star_dim)
    _ring(ctx, 0, 0, 115, _mix(palette[0], palette[5], .35), 1)


def _chrome(ctx, page, own_rgb, palette, demo):
    if (not isinstance(own_rgb, (tuple, list)) or len(own_rgb) != 3
            or any(not _finite(c) or not 0 <= c <= 255 for c in own_rgb)):
        colour = palette[4]
    else:
        colour = tuple(c / 255 for c in own_rgb)
    _circle(ctx, -20, -103, 2.5, colour)
    _text(ctx, "MB", -103, 13, 38, colour, 13, x=0)
    if demo:
        _text(ctx, "DEMO", -103, 9, 38, palette[5], 9, x=43)
    _text(ctx, "MOON" if page == "moon" else "METEORS", -80, 21, 170, palette[3], 18)


def _moon_values(sky):
    moon = sky.get("moon")
    if sky.get("valid") is not True or not isinstance(moon, dict):
        return None, None, "Unknown"
    phase, illumination = moon.get("phase_fraction"), moon.get("illumination_percent")
    if (not _finite(phase) or not 0 <= phase < 1 or not _finite(illumination)
            or not 0 <= illumination <= 100):
        return None, None, "Unknown"
    return phase, illumination, moon.get("name") or "Moon phase"


def _lit(x, y, phase):
    if x * x + y * y >= 1:
        return False
    edge = math.sqrt(max(0, 1 - y * y)) * math.cos(phase * TAU)
    return x >= edge if phase <= .5 else x <= -edge


def _moon(ctx, sky, palette):
    phase, illumination, name = _moon_values(sky)
    # Physical illumination must remain bright-on-dark even in a pastel theme.
    light = _mix((.94, .96, 1), palette[5], .10)
    shadow = _mix(palette[2], (.035, .05, .09), .94)
    _ring(ctx, 0, -18, 52, _mix(palette[4], palette[0], .55), 1)
    ctx.line_width = 1
    ctx.rgb(*palette[5])
    for x, y in _TICKS:
        if y < -.95:
            continue
        ctx.move_to(x * 54, -18 + y * 54).line_to(x * 57, -18 + y * 57)
    ctx.stroke()
    draw_moon(ctx, 0, -18, 44, phase, light, shadow)
    if phase is not None:
        for x, y, radius in _CRATERS:
            if all(_lit(x + dx * radius, y + dy * radius, phase) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))):
                _circle(ctx, x * 44, -18 + y * 44, radius * 44, _mix(light, shadow, .22))
        angle = phase * TAU - math.pi / 2
        _circle(ctx, math.cos(angle) * 52, -18 + math.sin(angle) * 52, 2.6, palette[5])
    _text(ctx, name, 46, 21, 210, palette[3], 18)
    _text(ctx, "~%.0f%%" % illumination if illumination is not None else "--%", 76, 32, 185, palette[5], 28)
    _text(ctx, "Approx. illumination", 100, 11, 154, palette[4], 11)


def _short_date(value):
    if (not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-"
            or any(value[index] not in "0123456789" for index in (0, 1, 2, 3, 5, 6, 8, 9))):
        return "Date unknown"
    month, day = int(value[5:7]), int(value[8:])
    return "%d %s" % (day, _MONTHS[month - 1]) if 1 <= month <= 12 and 1 <= day <= 31 else "Date unknown"


def _entry(value):
    return value if isinstance(value, dict) and isinstance(value.get("name"), str) else None


def _meteors(ctx, sky, palette, now):
    valid = sky.get("valid") is True
    supplied = sky.get("active_showers")
    active = [item for item in supplied[:12] if _entry(item)] if valid and isinstance(supplied, list) else []
    upcoming = _entry(sky.get("next_shower")) if valid else None
    # Three bounded decorative streaks; never a measured/predicted rate.
    if valid:
        for index, (x, y, delay, period) in enumerate(_TRAILS):
            progress = ((now + delay) % period) / period
            if progress > .52:
                continue
            x, y = x + progress * 175, y + progress * 82
            ctx.line_width = 1.4
            ctx.rgb(*_mix(palette[0], palette[5], .45)).move_to(x - 22, y - 10).line_to(x, y).stroke()
            ctx.line_width = 2
            ctx.rgb(*palette[3]).move_to(x - 6, y - 3).line_to(x, y).stroke()
    hero = active[0] if active else upcoming
    ctx.rgb(*palette[2]).round_rectangle(-104, -9, 208, 60, 14).fill()
    label = "ACTIVE SEASON" if active else "NEXT PEAK" if upcoming else "CALENDAR UNKNOWN" if not valid else "NO LISTED SHOWER"
    _text(ctx, label, -16, 12, 180, palette[5], 12)
    _text(ctx, hero["name"] if hero else "Unavailable" if not valid else "Quiet calendar", 10, 25, 198, palette[3], 17)
    _text(ctx, "Peak " + _short_date(hero.get("peak")) if hero else "No current UTC data", 37, 17, 192, palette[4], 15)
    following = next((item for item in active[1:] if _finite(item.get("peak_in_days")) and item["peak_in_days"] >= 0), None)
    if following is None and upcoming and (hero is None or upcoming.get("id") != hero.get("id")):
        following = upcoming
    if following:
        _text(ctx, "Next: " + following["name"], 68, 18, 196, palette[3], 14)
    elif active:
        count = len(active) - 1
        _text(ctx, "+%d other active" % count if count else "Within listed activity", 68, 17, 196, palette[4], 14)
    else:
        _text(ctx, "Calendar activity only", 68, 16, 194, palette[4], 14)
    basis = hero.get("basis") if hero else sky.get("calendar_basis")
    _text(ctx, basis or "Unavailable", 89, 12, 170, palette[5], 11)
    _text(ctx, "Decorative trails", 106, 9, 104, palette[4], 9)


def draw_astro_face(ctx, page, weather, fresh, local, elapsed_ms, now_ms, own_rgb, demo=False, sky=None, palette=None):
    """Draw a complete Moon/meteor face; other pages are untouched fallbacks."""
    if page not in ("moon", "meteors"):
        return False
    weather = weather if isinstance(weather, dict) else {}
    elapsed = max(0, elapsed_ms) if _finite(elapsed_ms) else 0
    now = max(0, now_ms) if _finite(now_ms) else 0
    if sky is None:
        stamp = weather.get("now_unix")
        sky = sky_snapshot(stamp + elapsed // 1000 if _finite(stamp) else None, local)
    sky = sky if isinstance(sky, dict) else {}
    palette = _palette(palette)
    ctx.save()
    try:
        ctx.text_align, ctx.text_baseline = ctx.CENTER, ctx.MIDDLE
        _background(ctx, palette, now)
        if page == "moon":
            _moon(ctx, sky, palette)
        else:
            _meteors(ctx, sky, palette, now)
        _chrome(ctx, page, own_rgb, palette, demo)
    finally:
        ctx.restore()
    return True
