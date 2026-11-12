"""Independent native-ctx idle themes; Original is an untouched caller fallback.

Artwork is decorative. Weather, rain and dates always come from supplied state.
No private calendar configuration, image download or call action lives here.
"""
import math

TAU = math.pi * 2
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_WAVE = tuple(math.sin(index * TAU / 64) for index in range(64))
_STARS = ((-91, -57), (-68, -92), (-41, -43), (-12, -71), (23, -96), (67, -74), (94, -34), (-104, 18), (88, 31))
_PALETTES = {
    # top, bottom, panel, text, muted, accent, light-background
    "christmas": ((.015, .12, .09), (.025, .035, .08), (.025, .065, .07), (.98, .97, .89), (.64, .77, .72), (1, .74, .27), False),
    "easter": ((.73, .90, .86), (.91, .86, .98), (.97, .98, .95), (.19, .24, .29), (.37, .43, .46), (.65, .34, .79), True),
    "anniversary": ((.24, .035, .13), (.065, .025, .10), (.12, .035, .10), (1, .93, .91), (.80, .60, .68), (1, .76, .40), False),
    "birthday_self": ((.035, .10, .29), (.025, .035, .10), (.04, .07, .17), (.94, .98, 1), (.60, .72, .87), (.34, .87, 1), False),
    "birthday_partner": ((.98, .79, .76), (.93, .85, .97), (.99, .95, .94), (.28, .15, .26), (.49, .32, .43), (.88, .22, .48), True),
    "cyberpunk": ((.045, .025, .12), (.012, .025, .06), (.02, .04, .09), (.65, 1, .96), (.44, .69, .75), (1, .15, .67), False),
    "lcars": ((.008, .012, .025), (.008, .012, .025), (.008, .012, .025), (1, .89, .78), (.73, .62, .80), (1, .65, .37), False),
    "kitty": ((1, .82, .91), (.91, .87, 1), (.99, .96, .99), (.25, .13, .27), (.48, .31, .47), (.89, .23, .53), True),
    "photo": ((.055, .08, .12), (.018, .035, .055), (.025, .045, .065), (.96, .98, 1), (.65, .74, .81), (.57, .85, .96), False),
    "ocean": ((.035, .40, .48), (.01, .055, .16), (.015, .08, .15), (.90, 1, 1), (.52, .81, .85), (.33, .96, .84), False),
    "noir": ((.025, .025, .035), (.005, .005, .012), (.015, .015, .025), (.97, .97, .94), (.63, .64, .65), (.95, .95, .90), False),
    "retro": ((.025, .07, .045), (.007, .025, .012), (.012, .04, .02), (.57, 1, .64), (.32, .65, .39), (.96, .73, .31), False),
}


def _wave(now, period=6000, offset=0):
    return _WAVE[(int(now * 64 // period) + offset) & 63]


def _number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and value == value and abs(value) < 1000000


def _text(ctx, value, x, y, size, width=205, colour=(1, 1, 1), minimum=16):
    value = str(value or "")
    ctx.font_size = size
    while size > minimum and ctx.text_width(value) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(x, y).text(value)


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _line(ctx, points, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.stroke()


def _polygon(ctx, points, colour):
    ctx.rgb(*colour).move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.close_path().fill()


def _panel(ctx, x, y, width, height, colour, radius=14):
    ctx.rgb(*colour).round_rectangle(x, y, width, height, radius).fill()


def _heart(ctx, x, y, size, colour):
    ctx.rgb(*colour).move_to(x, y + size)
    ctx.curve_to(x - size * 1.5, y, x - size, y - size, x, y - size * .35)
    ctx.curve_to(x + size, y - size, x + size * 1.5, y, x, y + size).close_path().fill()


def _base(ctx, palette):
    top, bottom = palette[:2]
    for index in range(16):
        mix = index / 15
        colour = tuple(top[channel] + (bottom[channel] - top[channel]) * mix for channel in range(3))
        ctx.rgb(*colour).rectangle(-120, -120 + index * 15, 240, 15).fill()


def _christmas(ctx, page, now, palette):
    # Two fir silhouettes and sparse falling snow frame, rather than cover, data.
    for x, shift in ((-80, 0), (79, 8)):
        for y, half in ((-58 + shift, 18), (-42 + shift, 25), (-24 + shift, 31)):
            _polygon(ctx, [(x, y - 28), (x - half, y + 11), (x + half, y + 11)], (.06, .31, .19))
        ctx.rgb(.31, .17, .11).rectangle(x - 3, -10 + shift, 6, 20).fill()
        _circle(ctx, x, -81 + shift, 3, palette[5])
    for index, (x, seed) in enumerate(_STARS):
        _circle(ctx, x, (seed + now // (90 + index * 9)) % 145 - 103, 1.1, (.85, .94, .93))
    _line(ctx, [(-111, -54), (-70, -66), (0, -70), (70, -66), (111, -54)], (.24, .47, .25), 1.3)
    for index, x in enumerate((-77, -49, -21, 8, 36, 64, 91)):
        _circle(ctx, x, -64 + abs(x) * .08, 2.2,
                ((.95, .25, .27), (1, .76, .28), (.32, .87, .65))[(index + int(now // 1400)) % 3])


def _kitty(ctx, page, now, palette):
    # Original lavender kitten, mint bow and heart: no borrowed character assets.
    for index in range(8):
        x = -112 + (index % 4) * 63
        y = -103 + (index // 4) * 175
        _heart(ctx, x, y, 4.5, (.96, .64, .78))
    y = -43 + _wave(now, 8500) * .8
    _polygon(ctx, [(-31, y - 7), (-24, y - 39), (-7, y - 19)], (.72, .59, .83))
    _polygon(ctx, [(31, y - 7), (24, y - 39), (7, y - 19)], (.72, .59, .83))
    _panel(ctx, -35, y - 22, 70, 47, (.90, .83, .95), 22)
    _line(ctx, [(-21, y), (-15, y + 3), (-9, y)], (.34, .22, .38), 2)
    _line(ctx, [(9, y), (15, y + 3), (21, y)], (.34, .22, .38), 2)
    _heart(ctx, 0, y + 7, 3, (.82, .39, .54))
    _circle(ctx, 27, y - 18, 8, (.30, .73, .67))
    _circle(ctx, 40, y - 18, 8, (.30, .73, .67))
    _circle(ctx, 33.5, y - 18, 4, (.98, .85, .91))


def _lcars(ctx, page, now, palette):
    peach, violet, amber = (1, .65, .40), (.65, .55, .88), (1, .80, .48)
    _panel(ctx, -108, -91, 205, 24, peach, 12)
    _panel(ctx, -108, -78, 34, 148, peach, 12)
    for index, colour in enumerate((violet, amber, (.91, .55, .61), violet)):
        _panel(ctx, -108, -48 + index * 28, 34, 23, colour, 7)
    ctx.rgb(*palette[2]).rectangle(-74, -66, 176, 132).fill()
    _panel(ctx, 44, -58, 55, 7, amber, 3)
    for index in range(4):
        _panel(ctx, 64 + index * 8, -42, 5, 10 + ((int(now // 700) + index) % 3) * 3,
               violet if index % 2 else amber, 1)


def _egg(ctx, x, y, colour, stripe):
    ctx.rgb(*colour).move_to(x, y - 20)
    ctx.curve_to(x - 20, y - 7, x - 18, y + 20, x, y + 21)
    ctx.curve_to(x + 18, y + 20, x + 20, y - 7, x, y - 20).close_path().fill()
    _line(ctx, [(x - 10, y + 3), (x - 5, y - 1), (x, y + 3), (x + 5, y - 1), (x + 10, y + 3)], stripe, 2)


def _easter(ctx, page, now, palette):
    _polygon(ctx, [(-120, 76), (-91, 55), (-41, 67), (17, 55), (79, 69), (120, 56), (120, 120), (-120, 120)], (.59, .80, .66))
    _egg(ctx, -75, -38, (.96, .73, .43), (.76, .38, .63))
    _egg(ctx, -40, -22, (.77, .58, .88), (.99, .86, .55))
    _egg(ctx, -9, -49, (.47, .76, .78), (.96, .95, .82))
    _panel(ctx, 37, -83, 12, 43, (.98, .97, .92), 6)
    _panel(ctx, 56, -81, 12, 41, (.98, .97, .92), 6)
    _circle(ctx, 52, -31, 23, (.98, .97, .92))
    _circle(ctx, 44, -35, 2, (.32, .28, .39))
    _circle(ctx, 60, -35, 2, (.32, .28, .39))
    _heart(ctx, 52, -25, 3, (.87, .53, .66))


def _anniversary(ctx, page, now, palette):
    for index, (x, y) in enumerate(((-87, -53), (83, -47), (-103, 25), (96, 35))):
        _heart(ctx, x, y + _wave(now, 8000, index * 13) * 2, 5 + index % 2, (.55, .13, .31))
    for x in (-16, 16):
        ctx.line_width = 4
        ctx.rgb(1, .76, .40).arc(x, -43, 22, 0, TAU, False).stroke()
        ctx.line_width = 1.2
        ctx.rgb(1, .92, .68).arc(x, -43, 18, -2.7, -.7, False).stroke()
    _heart(ctx, 0, -49, 7, (.96, .37, .55))


def _confetti(ctx, now, light=False):
    colours = ((.96, .71, .31), (.38, .84, .88), (.89, .43, .70))
    for index in range(16):
        x = (index * 53 + 17) % 214 - 107
        y = (index * 37 + now // (90 + index * 3)) % 183 - 103
        _line(ctx, [(x - 2, y - 2), (x + 2, y + 2)], colours[index % 3], 2)


def _birthday_self(ctx, page, now, palette):
    _confetti(ctx, now)
    for index, (x, y, colour) in enumerate(((-72, -51, (.96, .70, .30)), (-45, -66, (.32, .76, .94)), (-17, -48, (.76, .40, .84)))):
        drift = _wave(now, 9000, index * 11) * 2
        _line(ctx, [(x + drift, y + 16), (x - 3, y + 48)], (.41, .53, .70), 1)
        _circle(ctx, x + drift, y, 15, colour)
    _panel(ctx, 28, -38, 56, 20, (.91, .64, .77), 5)
    _panel(ctx, 28, -44, 56, 9, (.97, .91, .77), 4)
    for x in (39, 55, 71):
        _line(ctx, [(x, -45), (x, -59)], (.39, .85, .86), 3)
        _circle(ctx, x, -63 + _wave(now, 1700, x) * .5, 2.4, (1, .78, .30))


def _birthday_partner(ctx, page, now, palette):
    _confetti(ctx, now, True)
    _panel(ctx, -31, -54, 62, 46, (.86, .31, .53), 5)
    _panel(ctx, -35, -60, 70, 13, (.99, .66, .70), 4)
    ctx.rgb(.98, .87, .61).rectangle(-4, -60, 8, 52).fill()
    _line(ctx, [(-27, -59), (-24, -78), (0, -61), (24, -78), (27, -59)], (.96, .69, .46), 4)
    for index, (x, y) in enumerate(((-79, -54), (80, -47), (-83, 46), (91, 39))):
        _heart(ctx, x, y + _wave(now, 7500, index * 9), 6, (.84, .35, .53))


def _cyberpunk(ctx, page, now, palette):
    ctx.line_width = 1
    ctx.rgb(.08, .27, .32)
    for x in (-120, -80, -40, 0, 40, 80, 120):
        ctx.move_to(x * .20, -39).line_to(x, 120)
    for y in (-29, -8, 22, 61, 110):
        ctx.move_to(-120, y).line_to(120, y)
    ctx.stroke()
    cyan, pink = (.22, .94, .90), (1, .16, .64)
    _line(ctx, [(-107, -61), (-107, -86), (-86, -86)], cyan, 3)
    _line(ctx, [(106, -60), (106, -86), (87, -86)], pink, 3)
    _line(ctx, [(-105, 58), (-105, 91), (-78, 91)], pink, 3)
    for index in range(5):
        height = 8 + ((int(now // 430) + index * 3) % 4) * 5
        ctx.rgb(*(pink if index % 2 else cyan)).rectangle(66 + index * 8, -39 - height, 4, height).fill()
    _text(ctx, "NEON / WX", -44, -48, 11, 100, cyan, 11)


def _ocean(ctx, page, now, palette):
    for index, (colour, base) in enumerate((((.025, .27, .37), -56), ((.025, .19, .31), -28), ((.02, .13, .25), 1))):
        shift = _wave(now, 10000 + index * 3100, index * 13) * 9
        ctx.rgb(*colour).move_to(-125, base)
        ctx.curve_to(-70, base - 24 + shift, -20, base + 22, 34, base - 1)
        ctx.curve_to(74, base - 22, 101, base + 10 - shift, 125, base - 4)
        ctx.line_to(125, 125).line_to(-125, 125).close_path().fill()
    _circle(ctx, 56, -67, 17, (.93, .83, .51))
    # A tiny decorative fish, never a claim about local marine conditions.
    _polygon(ctx, [(-54, -50), (-73, -61), (-73, -39)], (.19, .68, .68))
    _panel(ctx, -55, -59, 40, 19, (.21, .73, .71), 9)
    _circle(ctx, -24, -52, 1.6, (.025, .17, .24))
    ctx.line_width = 2
    ctx.rgb(.29, .66, .71).arc(0, 0, 114, 0, TAU, False).stroke()


def _noir(ctx, page, now, palette):
    _polygon(ctx, [(-120, -120), (-41, -120), (86, 120), (-120, 120)], (.07, .07, .085))
    for x in (-109, 101):
        for y in (-71, -43, -15, 13, 41, 69):
            _panel(ctx, x, y, 8, 15, (.22, .22, .25), 2)
    _line(ctx, [(-83, -76), (79, -76)], (.76, .76, .73), 1)
    _text(ctx, "MONO", 0, -49, 12, 100, palette[4], 12)


def _retro(ctx, page, now, palette):
    ctx.line_width = 1
    ctx.rgb(.025, .09, .045)
    for y in range(-110, 115, 8):
        ctx.move_to(-120, y).line_to(120, y)
    ctx.stroke()
    ctx.line_width = 2
    ctx.rgb(.38, .65, .37).round_rectangle(-108, -96, 216, 194, 25).stroke()
    _text(ctx, "LOCAL TERMINAL", 0, -57, 12, 150, palette[5], 12)
    _line(ctx, [(-84, -38), (-73, -38), (-68, -50), (-61, -24), (-52, -39), (-35, -39)], palette[5], 1.5)


def _photo(ctx, page, now, palette, context):
    draw = context.get("photo_draw")
    if callable(draw):
        try:
            if draw(ctx, now) is True:
                return
        except Exception:
            pass
        _base(ctx, palette)
    # Safe missing-asset state. No texture call, path probing or invented photo.
    ctx.line_width = 2
    ctx.rgb(*palette[4]).round_rectangle(-32, -65, 64, 39, 6).stroke()
    _panel(ctx, -20, -72, 23, 9, palette[4], 3)
    ctx.rgb(*palette[4]).arc(0, -46, 12, 0, TAU, False).stroke()
    _text(ctx, "Photo unavailable", 0, -13, 11, 150, palette[4], 11)


_DECORATORS = {"christmas": _christmas, "easter": _easter, "anniversary": _anniversary,
               "birthday_self": _birthday_self, "birthday_partner": _birthday_partner,
               "cyberpunk": _cyberpunk, "lcars": _lcars, "kitty": _kitty,
               "ocean": _ocean, "noir": _noir, "retro": _retro}


_SEGMENTS = {"0": "abcedf", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
             "6": "afgecd", "7": "abc", "8": "abcdefg", "9": "abfgcd", "-": "g"}
_BARS = {"a": (3, 0, 23, 4), "b": (26, 4, 4, 25), "c": (26, 34, 4, 25), "d": (3, 59, 23, 4),
         "e": (0, 34, 4, 25), "f": (0, 4, 4, 25), "g": (3, 29, 23, 4)}


def _retro_clock(ctx, clock, date, weekday, palette, now):
    digits = clock.replace(":", "")
    if len(digits) != 4 or any(char not in _SEGMENTS for char in digits):
        digits = "----"
    _text(ctx, weekday, 0, -83, 16, 150, palette[4], 15)
    for char, x in zip(digits, (-76, -39, 9, 46)):
        for segment in _SEGMENTS[char]:
            sx, sy, width, height = _BARS[segment]
            ctx.rgb(*palette[3]).rectangle(x + sx, -24 + sy, width, height).fill()
    if now % 1000 < 500:
        _circle(ctx, 0, -6, 2.4, palette[3])
        _circle(ctx, 0, 22, 2.4, palette[3])
    _text(ctx, date, 0, 76, 18, 183, palette[4], 15)


def _clock_values(weather, local):
    valid = isinstance(local, (tuple, list)) and len(local) >= 6
    if valid:
        month = max(1, min(12, int(local[1])))
        return ("%02d:%02d" % (local[3], local[4]),
                "%02d %s %04d" % (local[2], _MONTHS[month - 1], local[0]),
                _DAYS[int(local[6]) % 7] if len(local) > 6 else "LOCAL TIME")
    return weather.get("local_clock") or "--:--", weather.get("local_date") or "Clock unavailable", "LOCAL TIME"


def _chrome(ctx, page, palette, own_rgb, demo, context):
    try:
        if not isinstance(own_rgb, (list, tuple)) or len(own_rgb) != 3:
            raise ValueError()
        own = tuple(max(0, min(255, channel)) / 255 for channel in own_rgb)
    except (TypeError, ValueError):
        own = (.35, .40, .45)
    if not any(own):
        own = (.35, .40, .45)
    if palette[6]:
        own = tuple(channel * .48 for channel in own)
    if demo:
        _text(ctx, "DEMO", 48, -98, 9.5, 35, palette[5] if not palette[6] else (.56, .22, .36), 9.5)
    pages = ("weather", "rain", "clock", "advent") if context.get("advent") else ("weather", "rain", "clock")
    if page in pages:
        for index in range(len(pages)):
            _circle(ctx, (index - (len(pages) - 1) / 2) * 12, 106, 2.2,
                    palette[5] if pages[index] == page else palette[4])


def _normal_data(ctx, page, theme_id, palette, weather, fresh, local, now, context):
    text, muted, accent, panel = palette[3], palette[4], palette[5], palette[2]
    instrument = theme_id == "lcars"
    x, width = (24, 158) if instrument else (0, 206)
    title = {"weather": "WEATHER", "rain": "RAIN", "clock": "LOCAL TIME"}.get(page, page.upper())
    if instrument:
        _text(ctx, title, 19, -79, 15, 143, (.08, .045, .08), 13)
    elif page != "clock":
        _panel(ctx, -81, -94, 162, 22, panel, 10)
        _text(ctx, weather.get("location") or title, 0, -83, 15, 151, muted, 13)
    if page == "clock":
        clock_draw = context.get("clock_draw")
        if callable(clock_draw):
            try:
                if clock_draw(ctx, palette) is True:
                    return
            except Exception:
                # A malformed optional clock must not remove the readable time.
                pass
        clock, date, weekday = _clock_values(weather, local)
        if theme_id == "retro":
            _retro_clock(ctx, clock, date, weekday, palette, now)
            return
        if theme_id == "noir":
            hours, minutes = (clock.split(":", 1) + ["--"])[:2]
            _text(ctx, weekday, 0, -83, 16, 145, muted, 15)
            _text(ctx, hours, 0, -16, 67, 160, text, 50)
            _line(ctx, [(-48, 19), (48, 19)], muted, 1)
            _text(ctx, minutes, 0, 54, 67, 160, text, 50)
            _text(ctx, date, 0, 94, 14, 146, muted, 12)
            return
        if not instrument:
            caption = context.get("caption") if theme_id in ("anniversary", "birthday_self", "birthday_partner") else weekday
            _text(ctx, caption or weekday, 0, -83, 17, 164, muted, 14)
        _panel(ctx, -99 if not instrument else -65, -9, 198 if not instrument else 164, 61, panel, 16 if not instrument else 1)
        _text(ctx, clock, x, 22, 60 if not instrument else 55, width, text, 39)
        _text(ctx, date, x, 72, 20 if not instrument else 17, width, muted, 15)
    elif page == "rain":
        rain = weather.get("rain_next_hour")
        rain = rain if fresh and isinstance(rain, dict) else {}
        state = rain.get("status")
        label = {"rain_likely": "Rain likely", "dry_likely": "Dry likely"}.get(state, "Unavailable")
        amount = rain.get("precipitation_mm")
        _panel(ctx, -101 if not instrument else -65, -4, 202 if not instrument else 164, 62, panel, 16 if not instrument else 1)
        value = "%.1f" % amount if _number(amount) and state in ("rain_likely", "dry_likely") else "--"
        _text(ctx, value + " mm", x, 25, 52 if not instrument else 59, width, text, 37)
        _text(ctx, label, x, 67, 23 if not instrument else 20, width, accent if state == "rain_likely" else muted, 17)
        onset = rain.get("onset_minutes")
        valid = (isinstance(onset, (list, tuple)) and len(onset) == 2 and all(_number(value) for value in onset)
                 and 0 <= onset[0] <= onset[1] <= 60)
        detail = "In %d-%d min" % tuple(onset) if valid and state == "rain_likely" else "Model forecast" if state in ("rain_likely", "dry_likely") else "No fresh forecast"
        _text(ctx, detail, x, 88, 15, width, muted, 13)
    else:
        current = weather.get("current")
        current = current if fresh and isinstance(current, dict) else {}
        value = current.get("temperature_c")
        _panel(ctx, -99 if not instrument else -65, -4, 198 if not instrument else 164, 62, panel, 16 if not instrument else 1)
        _text(ctx, "%.0f C" % value if _number(value) else "-- C", x, 26, 63 if not instrument else 58, width, text, 40)
        _text(ctx, current.get("condition") or "Unavailable", x, 69, 22 if not instrument else 19, width, text, 16)
        feels = current.get("apparent_temperature_c")
        _text(ctx, "Feels %.0f C" % feels if _number(feels) else "No fresh forecast", x, 89, 15, width, muted, 13)
    count = context.get("age") if theme_id.startswith("birthday") else context.get("years") if theme_id == "anniversary" else None
    if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 200:
        if theme_id.startswith("birthday"):
            _circle(ctx, -61, -43, 16, accent)
            _text(ctx, str(count), -61, -43, 20, 31, panel, 17)
        elif theme_id == "anniversary":
            _text(ctx, "%d YEAR%s" % (count, "" if count == 1 else "S"), 0, -14, 10, 130, accent, 10)
    if page != "clock":
        _text(ctx, "Open-Meteo", x, 99, 8.5, width, muted, 8.5)


def _advent(ctx, palette, context):
    day = context.get("advent_day")
    day = day if isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 24 else None
    _text(ctx, "ADVENT", 0, -83, 20, 155, palette[5], 18)
    _text(ctx, str(day) if day else "DEC", 0, -50, 43, 150, palette[3], 32)
    for index in range(24):
        number, x, y = index + 1, -75 + index % 6 * 30, -12 + index // 6 * 23
        selected = number == day
        _panel(ctx, x - 12, y - 9, 24, 19, palette[5] if selected else (.055, .18, .12), 3)
        _text(ctx, str(number), x, y, 11, 23, (.10, .10, .08) if selected else palette[3], 11)
    remaining = context.get("days_until_christmas")
    caption = "%d day%s to Christmas" % (remaining, "" if remaining == 1 else "s") if isinstance(remaining, int) and not isinstance(remaining, bool) and 0 <= remaining <= 31 else "Starts in December"
    _text(ctx, caption, 0, 88, 14, 180, palette[4], 12)


def draw_theme_face(ctx, page, theme_id, weather, fresh, local, elapsed_ms, now_ms, own_rgb, demo=False, context=None):
    """Return False for Original/unknown; caller then runs its exact0.7 face."""
    if theme_id not in _PALETTES:
        return False
    context = context if isinstance(context, dict) else {}
    weather = weather if isinstance(weather, dict) else {}
    palette = _PALETTES[theme_id]
    ctx.save()
    try:
        ctx.text_align = ctx.CENTER
        ctx.text_baseline = ctx.MIDDLE
        _base(ctx, palette)
        if theme_id == "photo":
            _photo(ctx, page, now_ms, palette, context)
        else:
            _DECORATORS[theme_id](ctx, page, now_ms, palette)
        if page == "advent" and theme_id == "christmas":
            _advent(ctx, palette, context)
        else:
            _normal_data(ctx, page, theme_id, palette, weather, fresh, local, now_ms, context)
        _chrome(ctx, page, palette, own_rgb, demo, context)
    finally:
        ctx.restore()
    return True
