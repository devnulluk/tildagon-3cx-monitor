"""Independent, bounded native-ctx watch faces for a240px round LCD.

The caller owns theme scenery, page/status chrome and DEMO labelling. Original
and unknown styles return False before touching ctx, preserving the original
renderer exactly. Moon phase is supplied astronomy, never a decorative guess.
"""
import math
from .clock_haute import draw as _haute_celestial
from .clock_cyber import draw as _neon_orrery

CLOCKS = ("original", "celestial", "tokyoflash", "radar", "flip", "analogue", "corpus", "haute_celestial", "neon_orrery")
_NAMES = ("Original", "Celestial", "Tokyo Code", "Orbital Radar", "Flip Station", "Clean Analogue", "Corpus / Time Eater", "Celestial Atelier", "Neon Orrery")
TAU = math.pi * 2
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_UNIT = tuple((math.sin(index * TAU / 360), -math.cos(index * TAU / 360)) for index in range(360))
_MOON_EDGE = tuple((math.cos(-math.pi / 2 + index * math.pi / 16),
                    math.sin(-math.pi / 2 + index * math.pi / 16)) for index in range(17))
_STARS = ((-72, -59), (-45, -74), (37, -69), (72, -51), (-83, 15), (83, 19), (-28, 86), (31, 87))
_DEFAULT = ((.025, .04, .10), (.015, .02, .06), (.025, .045, .10),
            (.94, .98, 1), (.54, .67, .78), (.36, .89, 1), False)


def get_clock_catalog():
    return [{"id": key, "name": name} for key, name in zip(CLOCKS, _NAMES)]


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and abs(value) < 1000000000000000)


def _palette(value):
    if not isinstance(value, (tuple, list)) or len(value) < 7:
        return _DEFAULT
    for colour in value[:6]:
        if (not isinstance(colour, (tuple, list)) or len(colour) != 3
                or any(not _finite(channel) or not 0 <= channel <= 1 for channel in colour)):
            return _DEFAULT
    return value


def _values(local):
    try:
        if not isinstance(local, (tuple, list)) or len(local) < 6:
            raise ValueError()
        if any(not isinstance(value, int) or isinstance(value, bool) for value in local[:6]):
            raise ValueError()
        year, month, day, hour, minute, second = local[:6]
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        if not (1 <= year <= 9999 and 1 <= month <= 12 and 1 <= day <= days[month - 1]
                and 0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
            raise ValueError()
        weekday = (_DAYS[local[6]] if len(local) > 6 and isinstance(local[6], int)
                   and not isinstance(local[6], bool) and 0 <= local[6] < 7 else "LOCAL TIME")
        return {"clock": "%02d:%02d" % (hour, minute), "date": "%02d %s %04d" % (day, _MONTHS[month - 1], year),
                "weekday": weekday, "day": "%02d" % day, "hour": hour, "minute": minute, "second": second}
    except (TypeError, ValueError, IndexError, OverflowError):
        return {"clock": "--:--", "date": "Clock unavailable", "weekday": "LOCAL TIME", "day": "--",
                "hour": None, "minute": None, "second": None}


def _text(ctx, value, x, y, size, width=190, colour=(1, 1, 1), minimum=14):
    ctx.font_size = size
    while size > minimum and ctx.text_width(value) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(x, y).text(value)


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _ring(ctx, x, y, radius, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).stroke()


def _panel(ctx, x, y, width, height, colour, radius=10):
    ctx.rgb(*colour).round_rectangle(x, y, width, height, radius).fill()


def _line(ctx, x0, y0, x1, y1, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).move_to(x0, y0).line_to(x1, y1).stroke()


def _mix(first, second, fraction):
    return tuple(first[index] + (second[index] - first[index]) * fraction for index in range(3))


def _ticks(radius, inner, count, centre_y=0):
    return tuple((x * inner, y * inner + centre_y, x * radius, y * radius + centre_y)
                 for index in range(count) for x, y in (_UNIT[(index * 360 // count) % 360],))


_CELESTIAL_TICKS = _ticks(99, 96, 24)
_ANALOGUE_MINOR = tuple(value for index, value in enumerate(_ticks(86, 83, 60, -9)) if index % 5)
_ANALOGUE_MAJOR = _ticks(86, 79, 12, -9)
_RADAR_TICKS = _ticks(92, 88, 24)
_CORPUS_SLITS = (_ticks(68, 65, 12, 7), _ticks(81, 78, 60, 7), _ticks(94, 91, 60, 7))
_GEAR_TEETH = _ticks(14, 10, 12)


def _segments(ctx, geometry, colour, width=1):
    # Each cached batch remains below the native255-edge path limit.
    ctx.line_width = width
    ctx.rgb(*colour)
    for x0, y0, x1, y1 in geometry:
        ctx.move_to(x0, y0).line_to(x1, y1)
    ctx.stroke()


def draw_moon(ctx, x, y, radius, phase, light, shadow):
    """Draw supplied phase:0new,.25right-lit,.5full,.75left-lit.

    Returns False and draws an explicit '?' when phase is unavailable.
    Polygon geometry is cached; one small disc and one path bound pixel work.
    """
    _circle(ctx, x, y, radius, shadow)
    if not _finite(phase) or not 0 <= phase <= 1:
        _text(ctx, "?", x, y, radius * 1.1, radius * 1.7, light, radius * .8)
        return False
    if phase == 0 or phase == 1:
        _ring(ctx, x, y, radius, _mix(shadow, light, .35), 1)
        return True
    direction = 1 if phase <= .5 else -1
    terminator = math.cos(phase * TAU)
    ctx.rgb(*light).move_to(x, y - radius)
    for horizontal, vertical in _MOON_EDGE[1:]:
        ctx.line_to(x + direction * horizontal * radius, y + vertical * radius)
    for horizontal, vertical in reversed(_MOON_EDGE[:-1]):
        ctx.line_to(x + direction * horizontal * radius * terminator, y + vertical * radius)
    ctx.close_path().fill()
    return True


def _moon_values(sky):
    if not isinstance(sky, dict) or sky.get("valid") is not True:
        return None, None
    moon = sky.get("moon")
    moon = moon if isinstance(moon, dict) else {}
    phase, illumination = moon.get("phase_fraction"), moon.get("illumination_percent")
    return (phase if _finite(phase) and 0 <= phase <= 1 else None,
            illumination if _finite(illumination) and 0 <= illumination <= 100 else None)


def _celestial(ctx, value, elapsed, now, palette, sky):
    panel, text, muted, accent = palette[2:6]
    _circle(ctx, 0, 0, 101, panel)
    _ring(ctx, 0, 0, 101, _mix(panel, accent, .42), 1.3)
    _segments(ctx, _CELESTIAL_TICKS, _mix(panel, accent, .55))
    for index, (x, y) in enumerate(_STARS):
        _circle(ctx, x, y, 1 if (index + int(now // 1300)) % 3 else 1.7, _mix(muted, text, .35))
    _text(ctx, "CELESTIAL", 0, -80, 13, 130, accent, 13)
    _text(ctx, value["clock"], 0, -27, 54, 183, text, 45)
    _text(ctx, value["date"], 0, 13, 17, 176, muted, 15)
    for x in (-57, 0, 57):
        _circle(ctx, x, 57, 21, _mix(panel, accent, .09))
        _ring(ctx, x, 57, 21, _mix(panel, accent, .45))
    _text(ctx, value["day"], -57, 54, 23, 35, text, 20)
    _text(ctx, "DATE", -57, 70, 8, 32, muted, 8)
    phase, illumination = _moon_values(sky)
    draw_moon(ctx, 0, 57, 15, phase, _mix(text, accent, .20), panel)
    _text(ctx, value["weekday"] if len(value["weekday"]) <= 3 else "--", 57, 54, 16, 37, text, 14)
    _text(ctx, "DAY", 57, 70, 8, 32, muted, 8)
    detail = "MOON ~%d%%" % round(illumination) if phase is not None and illumination is not None else "MOON UNKNOWN"
    _text(ctx, detail, 0, 88, 10, 130, muted, 10)
    # Decorative orbit has no claim to represent a real planet's position.
    x, y = _UNIT[int(now // 150) % 360]
    _circle(ctx, x * 99, y * 99, 2.8, accent)


def _tokyo(ctx, value, elapsed, now, palette, sky):
    panel, text, muted, accent = palette[2:6]
    _circle(ctx, 0, 0, 101, panel)
    hour, minute = value["hour"], value["minute"]
    hours = (hour % 12 or 12) if hour is not None else 0
    off = _mix(panel, accent, .17)
    ctx.line_width = 5
    for index in range(12):
        start = index * TAU / 12 - math.pi / 2 + .045
        ctx.rgb(*(accent if index < hours else off)).arc(0, 0, 95, start, start + .43, False).stroke()
    _text(ctx, "TOKYO CODE", 0, -76, 13, 132, muted, 13)
    _text(ctx, value["clock"], 0, -21, 53, 182, text, 45)
    _text(ctx, value["weekday"] + " / " + value["day"], 0, 17, 17, 176, muted, 14)
    tens, units = (minute // 10, minute % 10) if minute is not None else (0, 0)
    for index in range(5):
        _panel(ctx, -50 + index * 22, 42, 12, 8, accent if index < tens else off, 2)
    for index in range(9):
        _circle(ctx, -56 + index * 14, 63, 2.7, text if index < units else off)
    _text(ctx, "HOURS / 10m / 1m", 0, 77, 9, 120, muted, 9)


def _radar(ctx, value, elapsed, now, palette, sky):
    panel, text, muted, accent = palette[2:6]
    _circle(ctx, 0, 0, 95, panel)
    grid = _mix(panel, accent, .32)
    for radius in (31, 60, 90):
        _ring(ctx, 0, 0, radius, grid, 1)
    _segments(ctx, _RADAR_TICKS, muted)
    _segments(ctx, ((-90, 0, 90, 0), (0, -90, 0, 90)), grid)
    second = value["second"]
    if second is not None:
        angle = (second * 6 + int(elapsed % 1000 * .006)) % 360
        for offset in (0, 12, 24):
            x, y = _UNIT[(angle - offset) % 360]
            _line(ctx, 0, 0, x * 87, y * 87, _mix(panel, accent, .9 - offset / 40), 1.8)
        for index, (x, y) in enumerate(((-49, -48), (58, 26), (-30, 62))):
            _circle(ctx, x, y, 2 + index % 2, _mix(panel, accent, .6))
    _panel(ctx, -61, -83, 122, 19, panel, 7)
    _text(ctx, "ORBITAL RADAR", 0, -74, 12, 117, muted, 12)
    _panel(ctx, -91, -35, 182, 54, panel, 10)
    _text(ctx, value["clock"], 0, -8, 55, 180, text, 45)
    _panel(ctx, -81, 34, 162, 42, panel, 9)
    _text(ctx, value["weekday"], 0, 44, 15, 144, accent, 14)
    _text(ctx, value["date"], 0, 65, 16, 158, muted, 14)
    _panel(ctx, -34, 78, 68, 16, panel, 5)
    _text(ctx, "SEC %02d" % second if second is not None else "SEC --", 0, 86, 11, 102, muted, 11)


def _flip(ctx, value, elapsed, now, palette, sky):
    panel, text, muted, accent = palette[2:6]
    _text(ctx, "FLIP STATION", 0, -78, 14, 144, accent, 14)
    hours, minutes = value["clock"].split(":")
    for x, digits in ((-91, hours), (5, minutes)):
        _panel(ctx, x, -49, 86, 91, _mix(panel, muted, .13), 9)
        _panel(ctx, x + 2, -47, 82, 43, _mix(panel, muted, .20), 7)
        _text(ctx, digits, x + 43, -4, 67, 81, text, 52)
        _line(ctx, x + 3, -3, x + 83, -3, panel, 1.5)
        for hinge in (x + 1, x + 83):
            _panel(ctx, hinge, -8, 2, 11, accent, 1)
    _circle(ctx, 0, -14, 1.9, accent)
    _circle(ctx, 0, 10, 1.9, accent)
    _text(ctx, value["weekday"], 0, 64, 18, 165, accent, 16)
    _text(ctx, value["date"], 0, 88, 16, 166, muted, 14)
    # A small mechanical highlight, without manufacturing a prior time value.
    if value["second"] == 0 and elapsed % 1000 < 350:
        y = -45 + int(elapsed % 1000) * 84 / 350
        _line(ctx, -85, y, -11, y, _mix(panel, text, .4), 1)
        _line(ctx, 11, y, 85, y, _mix(panel, text, .4), 1)


def _analogue(ctx, value, elapsed, now, palette, sky):
    panel, text, muted, accent = palette[2:6]
    _circle(ctx, 0, -9, 89, panel)
    _segments(ctx, _ANALOGUE_MINOR, _mix(panel, muted, .8), 1)
    _segments(ctx, _ANALOGUE_MAJOR, accent, 2)
    for label, x, y in (("12", 0, -78), ("3", 68, -9), ("9", -68, -9)):
        _text(ctx, label, x, y, 17, 30, muted, 16)
    hour, minute, second = value["hour"], value["minute"], value["second"]
    if hour is not None:
        for angle, length, width, colour in (((hour % 12) * 30 + minute / 2, 39, 5, text),
                                            (minute * 6 + second / 10, 60, 3, text),
                                            (second * 6 + elapsed % 1000 * .006, 71, 1.1, accent)):
            x, y = _UNIT[int(angle) % 360]
            _line(ctx, -x * 8, -9 - y * 8, x * length, -9 + y * length, colour, width)
        _circle(ctx, 0, -9, 4.5, accent)
        _circle(ctx, 0, -9, 1.8, panel)
    else:
        _text(ctx, "?", 0, -9, 23, 34, muted, 20)
    _panel(ctx, -84, 35, 168, 42, panel, 11)
    _text(ctx, value["clock"], 0, 56, 48, 163, text, 40)
    _text(ctx, value["weekday"] + " / " + value["day"], 0, 88, 15, 154, muted, 14)


def _dart(now):
    """Decorative escapement hesitates/darts; never alters the time value."""
    phase = int(now) % 2400
    if phase < 400:
        return 0
    if phase < 600:
        return (phase - 400) * 18 / 200
    if phase < 1000:
        return 18
    if phase < 1500:
        return 18 - (phase - 1000) * 30 / 500
    if phase < 1800:
        return -12
    return -12 + (phase - 1800) * 12 / 600


def _time_eater(ctx, second, now):
    """Original small grasshopper silhouette and exposed escape wheel."""
    gold, dark, edge = (.80, .57, .22), (.12, .105, .06), (.99, .81, .40)
    step = _dart(now)
    ctx.save()
    ctx.translate(0, -60)
    ctx.rotate(step * math.pi / 180)
    _segments(ctx, _GEAR_TEETH, gold, 3)
    _ring(ctx, 0, 0, 9, dark, 3)
    _circle(ctx, 0, 0, 3, edge)
    ctx.restore()
    # Bent hind legs, feelers and hooked tail stay inside the round bezel.
    ctx.line_width = 2
    ctx.rgb(*gold).move_to(-24, -71).line_to(-34, -53).line_to(-11, -49)
    ctx.move_to(-8, -70).line_to(-13, -51).line_to(10, -47)
    ctx.move_to(13, -72).line_to(22, -53).line_to(30, -56)
    ctx.move_to(-24, -78).line_to(-43, -84).line_to(-46, -76)
    ctx.move_to(22, -80).line_to(31, -92).line_to(42, -93).stroke()
    ctx.rgb(*dark).move_to(-30, -79).line_to(-14, -88).line_to(9, -85)
    ctx.line_to(24, -78).line_to(20, -68).line_to(-9, -70).close_path().fill()
    _line(ctx, -23, -79, 8, -79, gold, 3)
    _line(ctx, -17, -84, 3, -82, edge, 1)
    _circle(ctx, 20, -78, 8, gold)
    # The jaw is decorative; a real supplied second controls its slow opening.
    jaw = (second / 59 * 7 if second is not None else (step + 12) / 6)
    if second == 59:
        jaw = 0 if int(now // 90) % 2 else 5
    _line(ctx, 24, -74, 34, -72 + jaw, dark, 3)
    _line(ctx, 24, -71, 33, -66 - jaw * .3, gold, 2)
    _circle(ctx, 23, -80, 1.8, (.08, .55, 1))


def _corpus(ctx, value, elapsed, now, palette, sky):
    # Inspired by the Corpus Clock's rippled gold, blue vernier lights and
    # exposed grasshopper escapement, not a replica of its proprietary design.
    # Primary sources: cam.ac.uk/news/time-to-unveil-corpus-clock and
    # johnctaylor.com/the-chronophage/. Digital time remains strictly truthful.
    brass, shadow, highlight = (.50, .33, .12), (.24, .16, .065), (.86, .65, .27)
    blue, glow = (.055, .48, .95), (.30, .80, 1)
    _circle(ctx, 0, 7, 97, brass)
    for index, radius in enumerate((95, 89, 84, 76, 72, 63, 56, 47, 37)):
        _ring(ctx, 0, 7, radius, highlight if index % 2 else shadow, 1.2 if index % 2 else 2)
    for geometry in _CORPUS_SLITS:
        # Sixty independent slits fit under the255-edge native path budget;
        # each concentric ring is deliberately a separate path.
        _segments(ctx, geometry, (.095, .16, .20), 2.5)
    second = value["second"]
    if second is not None:
        positions = (((value["hour"] % 12) * 30 + value["minute"] / 2, 68),
                     (value["minute"] * 6 + second / 10, 81),
                     (second * 6 + elapsed % 1000 * .006, 94))
        for angle, radius in positions:
            start = angle * math.pi / 180 - math.pi / 2
            ctx.line_width = 4
            ctx.rgb(*blue).arc(0, 7, radius, start - .045, start + .045, False).stroke()
            x, y = _UNIT[int(angle) % 360]
            _circle(ctx, x * radius, 7 + y * radius, 1.9, glow)
        # A faint darting reflection is explicitly decorative, independent of
        # the three accurate light positions and the large supplied HH:MM.
        reflection = positions[-1][0] + _dart(now)
        angle = reflection * math.pi / 180 - math.pi / 2
        ctx.line_width = 1.3
        ctx.rgb(.08, .26, .43).arc(0, 7, 90, angle - .08, angle + .08, False).stroke()
    _time_eater(ctx, second, now)
    _panel(ctx, -55, -42, 110, 18, shadow, 6)
    _text(ctx, "CORPUS / TIME EATER", 0, -33, 10, 106, (.99, .86, .57), 9)
    _panel(ctx, -87, -15, 174, 55, (.065, .075, .085), 13)
    _text(ctx, value["clock"], 0, 12, 54, 169, (.95, .98, 1), 45)
    _panel(ctx, -73, 48, 146, 21, shadow, 7)
    _text(ctx, value["date"], 0, 59, 15, 140, (.99, .86, .57), 13)
    _panel(ctx, -35, 78, 70, 16, shadow, 5)
    _text(ctx, "H / M / S", 0, 86, 10, 113, (.99, .86, .57), 10)


_DRAWERS = {"celestial": _celestial, "tokyoflash": _tokyo, "radar": _radar,
            "flip": _flip, "analogue": _analogue, "corpus": _corpus,
            "haute_celestial": _haute_celestial, "neon_orrery": _neon_orrery}


def draw_clock_content(ctx, style, weather, local, elapsed_ms, now_ms, palette=None, sky=None, artwork=None):
    """Draw clock content only, returning True when the style is handled."""
    drawer = _DRAWERS.get(style) if isinstance(style, str) else None
    if drawer is None:
        return False
    value = _values(local)
    elapsed = elapsed_ms if _finite(elapsed_ms) and elapsed_ms >= 0 else 0
    now = now_ms if _finite(now_ms) and now_ms >= 0 else 0
    ctx.save()
    try:
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        if style == "haute_celestial":
            drawer(ctx, value, elapsed, now, _palette(palette), sky, artwork=artwork)
        else:
            drawer(ctx, value, elapsed, now, _palette(palette), sky)
    finally:
        ctx.restore()
    return True
