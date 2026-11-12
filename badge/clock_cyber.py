"""Neon Orrery: an original native-vector celestial complication clock.

Orbital planets and their angles are decorative, driven by animation time.
Moon illumination uses supplied astronomy; the seconds indicator uses supplied
local time. A private dark dial keeps the face readable inside every theme.
No clock imports, image assets, framebuffer access or hardware writes.
"""
import math

TAU = 2 * math.pi
_UNIT = tuple((math.cos(index * TAU / 256), math.sin(index * TAU / 256)) for index in range(256))
_MOON_EDGE = tuple((math.cos(-math.pi / 2 + index * math.pi / 16),
                    math.sin(-math.pi / 2 + index * math.pi / 16)) for index in range(17))
_DARK = (.005, .012, .032)
_PANEL = (.008, .024, .053)
_WHITE = (.93, .98, 1.0)
_CYAN = (.18, .88, 1.0)
_MAGENTA = (.98, .22, .68)
_AMBER = (1.0, .69, .29)
_MUTED = (.40, .63, .75)
_BLUE = (.035, .17, .27)
_GRID = ((-79, 37, 79, 37), (-73, 49, 73, 49), (-64, 65, 64, 65),
         (-45, 83, 45, 83), (-43, 36, -62, 75), (-22, 36, -31, 88),
         (0, 36, 0, 90), (22, 36, 31, 88), (43, 36, 62, 75))
_STARS = ((-90, -24), (90, -25), (-91, 9), (91, 12), (-29, -76), (37, -75))


def _orbit(rx, ry, rotation):
    c, s = math.cos(rotation), math.sin(rotation)
    return tuple((rx * x * c - ry * y * s, -54 + rx * x * s + ry * y * c)
                 for index in range(48) for x, y in (_UNIT[index * 256 // 48],))


_ORBITS = (_orbit(65, 16, -.22), _orbit(47, 21, .32), _orbit(31, 14, -.45))
_ORBIT_HALVES = tuple((points[24:] + (points[0],), points[:25]) for points in _ORBITS)
_ORBIT_COLOURS = (_CYAN, _MAGENTA, _AMBER)
_ORBIT_BACK = tuple(tuple(channel * .25 for channel in colour) for colour in _ORBIT_COLOURS)
_NODE_FILL = tuple(tuple(channel * .21 for channel in colour) for colour in _ORBIT_COLOURS)
_MINOR = tuple((c * 96.3, s * 96.3, c * 98, s * 98)
               for index in range(60) if index % 5 for c, s in (_UNIT[index * 256 // 60],))
_MAJOR = tuple((c * 94, s * 94, c * 99, s * 99)
               for index in range(12) for c, s in (_UNIT[index * 256 // 12],))


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and -1e15 < value < 1e15)


def _clock(value):
    if not isinstance(value, dict):
        value = {}
    hour, minute, second = (value.get(key) for key in ("hour", "minute", "second"))
    valid = type(hour) is int and 0 <= hour < 24 and type(minute) is int and 0 <= minute < 60
    known_second = second if valid and type(second) is int and 0 <= second < 60 else None
    return value, "%02d:%02d" % (hour, minute) if valid else "--:--", known_second


def _text(ctx, value, x, y, size, width, colour, minimum=None):
    value = str(value)
    ctx.font_size = size
    minimum = size if minimum is None else minimum
    while size > minimum and ctx.text_width(value) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(x, y).text(value)


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _ring(ctx, x, y, radius, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).stroke()


def _segments(ctx, geometry, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour)
    for x0, y0, x1, y1 in geometry:
        ctx.move_to(x0, y0).line_to(x1, y1)
    ctx.stroke()


def _path(ctx, points, colour, width=1, closed=False):
    ctx.line_width = width
    ctx.rgb(*colour)
    for index, (x, y) in enumerate(points):
        if index:
            ctx.line_to(x, y)
        else:
            ctx.move_to(x, y)
    if closed:
        ctx.close_path()
    ctx.stroke()


def _wire_planet(ctx, x, y, radius, angle, colour):
    """Small rotating wire sphere; geometry has no ephemeris meaning."""
    _ring(ctx, x, y, radius, colour, .8)
    ctx.rgb(*colour)
    ctx.line_width = .6
    for offset in (0, 43, 85):
        width = _UNIT[(angle + offset) & 255][0] * radius
        for index in range(25):
            c, s = _UNIT[index * 256 // 24 & 255]
            if index:
                ctx.line_to(x + c * width, y + s * radius)
            else:
                ctx.move_to(x + c * width, y + s * radius)
    ctx.stroke()
    ctx.rgb(*colour)
    for index in range(25):
        c, s = _UNIT[index * 256 // 24 & 255]
        if index:
            ctx.line_to(x + c * radius, y + s * radius * .27)
        else:
            ctx.move_to(x + c * radius, y + s * radius * .27)
    ctx.stroke()


def _orrery(ctx, now):
    # Back halves are restrained; front halves glow more brightly. Each
    # cached half-path has only24 vertices, even at the highest visual detail.
    for index, (back, front) in enumerate(_ORBIT_HALVES):
        _path(ctx, back, _ORBIT_BACK[index], .75)
        _path(ctx, front, _ORBIT_COLOURS[index], .9)
    _circle(ctx, 0, -54, 12.5, _PANEL)
    _wire_planet(ctx, 0, -54, 11, now // 85 & 255, _CYAN)
    # The small worlds orbit on cached paths; the clock/date never drive them.
    for index, points in enumerate(_ORBITS):
        x, y = points[(now // (145 + index * 67) + index * 17) % 48]
        radius = (4.3, 3.2, 2.3)[index]
        _circle(ctx, x, y, radius + 1, _DARK)
        _circle(ctx, x, y, radius, _NODE_FILL[index])
        _ring(ctx, x, y, radius, _ORBIT_COLOURS[index], .8)
        if index == 0:
            _segments(ctx, ((x - radius, y, x + radius, y), (x, y - radius, x, y + radius)), _CYAN, .55)


def _moon_values(sky):
    moon = sky.get("moon") if isinstance(sky, dict) and sky.get("valid") is True else None
    if not isinstance(moon, dict):
        return None, None
    phase, illumination = moon.get("phase_fraction"), moon.get("illumination_percent")
    return (phase if _finite(phase) and 0 <= phase <= 1 else None,
            illumination if _finite(illumination) and 0 <= illumination <= 100 else None)


def _moon(ctx, phase):
    x, y, radius = 0, 59, 13
    _circle(ctx, x, y, radius, (.016, .055, .09))
    if phase is None:
        _text(ctx, "?", x, y, 20, 26, _WHITE)
        return
    if phase in (0, 1):
        _ring(ctx, x, y, radius, (.12, .28, .37), .8)
        return
    position = phase * 256
    at, fraction = int(position), position % 1
    # Cached cosine interpolation keeps the terminator smooth without a
    # per-frame trigonometric calculation. Phase comes from supplied science.
    terminator = _UNIT[at & 255][0] * (1 - fraction) + _UNIT[(at + 1) & 255][0] * fraction
    direction = 1 if phase <= .5 else -1
    ctx.rgb(.82, .94, 1).move_to(x, y - radius)
    for horizontal, vertical in _MOON_EDGE[1:]:
        ctx.line_to(x + direction * horizontal * radius, y + vertical * radius)
    for horizontal, vertical in reversed(_MOON_EDGE[:-1]):
        ctx.line_to(x + direction * horizontal * radius * terminator, y + vertical * radius)
    ctx.close_path().fill()


def draw(ctx, value, elapsed, now, palette, sky):
    """Draw Neon Orrery inside radius101; the caller owns outer status chrome.

    Palette deliberately does not invert this dark instrument. The large time
    is supplied local HH:MM, not uptime; only labelled decorative orbits use now.
    """
    value, clock, second = _clock(value)
    now = max(0, int(now)) if _finite(now) else 0
    elapsed = max(0, elapsed) if _finite(elapsed) else 0
    ctx.save()
    try:
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        _circle(ctx, 0, 0, 100, _DARK)
        _ring(ctx, 0, 0, 99.5, (.10, .37, .47), 1)
        _ring(ctx, 0, 0, 92, (.025, .10, .18), .65)
        _segments(ctx, _MINOR, (.05, .24, .32), .65)
        _segments(ctx, _MAJOR, (.21, .61, .68), .9)
        ctx.line_width = 1.4
        ctx.rgb(*_MAGENTA).arc(0, 0, 99.5, .20, .64, False).stroke()
        ctx.rgb(*_AMBER).arc(0, 0, 99.5, 3.34, 3.78, False).stroke()
        _segments(ctx, _GRID, (.025, .13, .20), .55)
        for index, (x, y) in enumerate(_STARS):
            _circle(ctx, x, y, 1.1 if index % 2 else .7, (.20, .41, .54))
        _orrery(ctx, now)
        _text(ctx, "NEON ORRERY", 0, -86, 11, 120, _CYAN)
        # One opaque readout protects legibility from every decorative path.
        ctx.rgb(*_PANEL).round_rectangle(-82, -32, 164, 51, 8).fill()
        _segments(ctx, ((-86, -23, -86, 10), (-86, -23, -81, -23), (-86, 10, -81, 10),
                        (86, -23, 86, 10), (86, -23, 81, -23), (86, 10, 81, 10)), (.10, .49, .61), .9)
        _text(ctx, clock, 0, -8, 48, 177, _WHITE, 45)
        date = value.get("date") if isinstance(value.get("date"), str) else "Clock unavailable"
        _text(ctx, date, 0, 27, 14, 166, _MUTED, 13)
        for x in (-55, 0, 55):
            _circle(ctx, x, 57, 19.5, _PANEL)
            _ring(ctx, x, 57, 19.5, (.07, .30, .39) if x != 55 else (.34, .23, .11), .8)
        weekday = value.get("weekday")
        weekday = weekday if weekday in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") else "--"
        day = value.get("day")
        day = day if isinstance(day, str) and len(day) == 2 else "--"
        _text(ctx, weekday, -55, 49, 10, 32, _CYAN)
        _text(ctx, day, -55, 64, 16, 30, _WHITE)
        phase, illumination = _moon_values(sky)
        _moon(ctx, phase)
        _text(ctx, "%02d" % second if second is not None else "--", 55, 55, 21, 32, _WHITE)
        _text(ctx, "SECONDS", 55, 70, 6.5, 31, _AMBER)
        if second is not None:
            angle = int((second + elapsed % 1000 / 1000) * 256 / 60) & 255
            c, s = _UNIT[angle]
            _circle(ctx, 55 + s * 18, 57 - c * 18, 1.4, _AMBER)
        detail = "MOON ~%d%%" % round(illumination) if phase is not None and illumination is not None else "MOON UNKNOWN"
        _text(ctx, detail, 0, 82, 8.5, 112, _MUTED)
        _text(ctx, "DECORATIVE ORBITS", 0, 93, 6.5, 78, (.28, .45, .57))
    finally:
        ctx.restore()
    return True
