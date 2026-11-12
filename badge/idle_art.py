"""Bounded native-ctx scenery: cached opaque sky bands and vector geometry.

Rain and water movement are decorative. Only idle_faces draws forecast data;
these particles and reflections are never represented as measured rain bins.
"""
import math

TAU = math.pi * 2
_WAVE = tuple(math.sin(i * TAU / 64) for i in range(64))
_UNIT = tuple((math.cos(i * TAU / 360), math.sin(i * TAU / 360)) for i in range(360))
_STARS = ((-86, -56, 1.3), (-63, -88, 1.0), (-35, -39, 1.6), (-12, -69, 1.0),
          (19, -98, 1.3), (64, -78, 1.1), (91, -43, 1.6), (77, -14, 1.0),
          (-99, -4, 1.2), (-59, -14, 1.0), (5, -33, 1.3), (38, -18, 1.0))
_DROPS = tuple(((i * 67 + 13) % 226 - 113, (i * 43) % 210, 9 + i % 4 * 3) for i in range(18))
_SNOW = tuple(((i * 61 + 11) % 220 - 110, (i * 37) % 195, 1.1 + i % 3 * .45) for i in range(14))
_RAYS = tuple(_UNIT[i * 30] for i in range(12))
_MAJOR = tuple((c * 98, s * 98, c * 109, s * 109) for i, (c, s) in enumerate(_UNIT) if i % 30 == 0)
_MINOR = tuple((c * 105, s * 105, c * 109, s * 109) for i, (c, s) in enumerate(_UNIT) if i % 6 == 0 and i % 30 != 0)
KNOWN_CODES = (0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
               71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99)
_BAND_ROWS = tuple((-120 + i * 240 // 32, (i + 1) * 240 // 32 - i * 240 // 32) for i in range(32))


def _palette(top, middle, bottom):
    result = []
    for i in range(32):
        t = (i + .5) / 32
        a, b, mix = (top, middle, t / .55) if t <= .55 else (middle, bottom, (t - .55) / .45)
        result.append(tuple(a[j] + (b[j] - a[j]) * mix for j in range(3)))
    return tuple(result)


_NIGHT_SKY = _palette((.17, .045, .32), (.07, .09, .25), (.012, .023, .065))
_RAIN_SKY = _palette((.02, .24, .34), (.025, .105, .22), (.009, .028, .075))
_SNOW_SKY = _palette((.18, .25, .40), (.09, .14, .27), (.015, .032, .08))
_DAY_SKY = _palette((.36, .16, .045), (.10, .13, .23), (.016, .028, .075))
_CLOUD_SKY = _palette((.14, .20, .29), (.06, .10, .18), (.012, .028, .07))


def wave(now, period=6000, offset=0):
    return _WAVE[(int(now * 64 // period) + offset) & 63]


def circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def line(ctx, x0, y0, x1, y1, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).move_to(x0, y0).line_to(x1, y1).stroke()


def base(ctx, page, night=False, code=None):
    if page == "clock" or night:
        palette = _NIGHT_SKY
        accent = (.67, .52, 1)
    elif page == "rain" or code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        palette = _RAIN_SKY
        accent = (.20, .84, 1)
    elif code in (71, 73, 75, 77, 85, 86):
        palette = _SNOW_SKY
        accent = (.63, .82, 1)
    elif code in (3, 45, 48):
        palette, accent = _CLOUD_SKY, (.58, .76, .94)
    else:
        palette = _DAY_SKY
        accent = (1, .72, .24)
    for i in range(32):
        y, height = _BAND_ROWS[i]
        ctx.rgb(*palette[i]).rectangle(-120, y, 240, height).fill()
    return accent


def cloud(ctx, x, y, width, height, colour):
    """A single filled silhouette rather than overlapping large alpha circles."""
    ctx.rgb(*colour).move_to(x - width * .50, y + height * .30)
    ctx.curve_to(x - width * .73, y + height * .20, x - width * .66, y - height * .45, x - width * .34, y - height * .34)
    ctx.curve_to(x - width * .28, y - height * 1.02, x + width * .14, y - height * 1.02, x + width * .20, y - height * .36)
    ctx.curve_to(x + width * .65, y - height * .54, x + width * .77, y + height * .35, x + width * .43, y + height * .36)
    ctx.line_to(x - width * .50, y + height * .30).close_path().fill()


def _sun(ctx, x, y, now):
    # Rotation uses two cached trig lookups, not twelve per-ray trig calls.
    rotation = _UNIT[int(now // 170) % 360]
    rc, rs = rotation
    ctx.line_width = 2.1
    ctx.rgb(1, .63, .15)
    for c, s in _RAYS:
        dx, dy = c * rc - s * rs, s * rc + c * rs
        ctx.move_to(x + dx * 32, y + dy * 32).line_to(x + dx * 42, y + dy * 42)
    ctx.stroke()
    circle(ctx, x, y, 28, (1, .52, .12))
    circle(ctx, x - 1, y - 2, 23, (1, .78, .27))
    circle(ctx, x - 7, y - 9, 9, (1, .90, .51))


def _moon(ctx, x, y):
    ctx.rgb(.79, .83, 1).move_to(x + 9, y - 28)
    ctx.curve_to(x - 36, y - 22, x - 35, y + 25, x + 9, y + 29)
    ctx.curve_to(x - 12, y + 8, x - 13, y - 9, x + 9, y - 28).close_path().fill()
    circle(ctx, x - 17, y - 3, 3.2, (.62, .69, .92))
    circle(ctx, x - 12, y + 14, 2, (.66, .73, .96))


def _stars(ctx, now):
    shades = ((.43, .49, .75), (.59, .70, .94), (.83, .88, 1))
    for i, (x, y, radius) in enumerate(_STARS):
        brightness = int((wave(now, 4300 + i * 113, i * 9) + 1) * 1.49)
        circle(ctx, x, y, radius, shades[brightness])
    line(ctx, -83, -55, -83, -47, (.65, .81, 1), 1)
    line(ctx, -87, -51, -79, -51, (.65, .81, 1), 1)


def _rain(ctx, now, heavy=False):
    ctx.line_width = 1.4 if heavy else 1.1
    ctx.rgb(.27, .66, .83)
    for i, (x, seed, length) in enumerate(_DROPS):
        if not heavy and i % 2:
            continue
        y = (now // (10 + i % 3 * 2) + seed) % 210 - 112
        ctx.move_to(x, y).line_to(x - 5, y + length)
    ctx.stroke()


def _snow(ctx, now):
    for i, (x, seed, radius) in enumerate(_SNOW):
        y = (now // (47 + i % 4 * 9) + seed) % 195 - 111
        drift = wave(now, 6500 + i * 97, i * 7) * 5
        circle(ctx, x + drift, y, radius, (.78, .87, 1))


def _landscape(ctx, now, night):
    sway = wave(now, 15000) * 3
    ctx.rgb(.025, .055, .12).move_to(-125, 17)
    ctx.curve_to(-89, -5 + sway, -48, 25, -8, 8)
    ctx.curve_to(39, -7 - sway, 84, 29, 125, 8)
    ctx.line_to(125, 125).line_to(-125, 125).close_path().fill()
    # Sparse foreground silhouettes give parallax without another full-screen layer.
    line(ctx, -101, 59, -98, 30 + sway, (.10, .17, .24), 2)
    line(ctx, 103, 67, 99, 39 - sway, (.10, .17, .24), 2)


def weather(ctx, current, fresh, now):
    code = current.get("weather_code") if fresh else None
    known = not isinstance(code, bool) and code in KNOWN_CODES
    night = current.get("is_day") is False if fresh else False
    if night:
        _stars(ctx, now)
    if code in (0, 1, 2):
        if night:
            _moon(ctx, 42, -39 + wave(now, 13000) * 1.3)
        else:
            _sun(ctx, 40, -39 + wave(now, 11000) * 1.1, now)
    if code not in (0,):
        drift = wave(now, 13000) * 8
        cloud(ctx, -55 + drift, -55, 135, 32, (.12, .23, .37))
        cloud(ctx, 62 - drift * .55, -38, 121, 27, (.20, .33, .47))
        cloud(ctx, -18 + drift * .35, -24, 106, 28,
              (.65, .76, .87) if fresh and known else (.29, .37, .48))
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        _rain(ctx, now, code in (65, 67, 82, 95, 96, 99))
    elif code in (71, 73, 75, 77, 85, 86):
        _snow(ctx, now)
    elif code in (45, 48):
        for i in range(3):
            y, shift = -44 + i * 17, wave(now, 9000, i * 17) * 9
            line(ctx, -98 + shift, y, 93 + shift, y, (.39, .51, .61), 2)
    elif code in (95, 96, 99):
        pass
    _landscape(ctx, now, night)


def _umbrella(ctx, now, dry=False, unavailable=False):
    if dry or unavailable:
        circle(ctx, 0, -43, 25, (.10, .22, .31) if dry else (.16, .20, .28))
        if dry:
            ctx.line_width = 4
            ctx.rgb(.28, .94, .77).move_to(-13, -43).line_to(-3, -33).line_to(15, -53).stroke()
        return
    ctx.rgb(.18, .70, .98).move_to(-32, -41)
    ctx.curve_to(-31, -80, 31, -80, 32, -41)
    ctx.curve_to(21, -48, 14, -48, 10, -41)
    ctx.curve_to(4, -49, -4, -49, -10, -41)
    ctx.curve_to(-16, -49, -24, -49, -32, -41).close_path().fill()
    ctx.line_width = 2
    ctx.rgb(.57, .89, 1).move_to(0, -69).curve_to(-15, -65, -17, -54, -18, -46).stroke()
    ctx.line_width = 3
    ctx.rgb(.69, .85, .98).move_to(0, -42).line_to(0, -21)
    ctx.curve_to(0, -9, 14, -10, 14, -20).stroke()


def rain(ctx, state, now):
    fresh = state in ("rain_likely", "dry_likely")
    drift = wave(now, 12000) * 6
    cloud(ctx, -65 + drift, -83, 155, 31, (.055, .15, .25))
    cloud(ctx, 62 - drift, -68, 145, 32, (.07, .21, .31))
    if state == "rain_likely":
        _rain(ctx, now, True)
    # Water surface is a decorative scene, not a per-minute precipitation chart.
    ctx.rgb(.018, .075, .14).rectangle(-120, 53, 240, 67).fill()
    for i in range(4):
        width = 15 + ((now // 45 + i * 19) % 59)
        x, y = (-62, 5, 68, -23)[i], (72, 93, 66, 106)[i]
        ctx.line_width = 1
        ctx.rgb(*((.11, .37, .47) if fresh else (.12, .18, .25))).move_to(x - width, y)
        ctx.curve_to(x - width * .45, y - 3, x + width * .45, y - 3, x + width, y)
        ctx.curve_to(x + width * .45, y + 3, x - width * .45, y + 3, x - width, y).stroke()
    for i in range(4):
        offset = wave(now, 2100, i * 12) * 4
        line(ctx, -17 - i * 7 + offset, 62 + i * 8, 22 + i * 4 + offset, 62 + i * 8,
             (.07, .24, .34), 2)
    _umbrella(ctx, now, state == "dry_likely", not fresh)


def clock(ctx, sec, now, elapsed_ms=0):
    # Two batched tick paths replace sixty individually stroked paths.
    for geometry, colour, width in ((_MINOR, (.22, .28, .46), 1), (_MAJOR, (.65, .55, .98), 2)):
        ctx.line_width = width
        ctx.rgb(*colour)
        for x0, y0, x1, y1 in geometry:
            ctx.move_to(x0, y0).line_to(x1, y1)
        ctx.stroke()
    # Small-pixel-area aurora ribbons around the dial, without a blurred glow.
    phase = (now % 28000) * TAU / 28000
    for i, (colour, radius) in enumerate((((.26, .74, .87), 113), ((.57, .32, .92), 111), ((.92, .31, .67), 115))):
        start = phase + i * TAU / 3
        ctx.line_width = 2.6
        ctx.rgb(*colour).arc(0, 0, radius, start, start + .95, False).stroke()
    # A narrow moving curtain supplies depth behind the strong digital readout.
    shift = wave(now, 17000) * 5
    ctx.line_width = 3
    ctx.rgb(.13, .12, .31).move_to(-116, -38)
    ctx.curve_to(-64, -72 + shift, 22, -14 - shift, 119, -56).stroke()
    if sec is not None:
        index = int(sec * 6 + (elapsed_ms % 1000) * .006 - 90) % 360
        c, s = _UNIT[index]
        circle(ctx, c * 108, s * 108, 4.2, (.30, 1, .81))
        circle(ctx, c * 108, s * 108, 1.6, (.89, 1, .97))


def readout(ctx, page):
    if page == "weather":
        ctx.rgb(.024, .052, .115).round_rectangle(-98, -9, 196, 62, 18).fill()
        ctx.line_width = 1
        ctx.rgb(.11, .22, .34).round_rectangle(-98, -9, 196, 62, 18).stroke()
    elif page == "rain":
        ctx.rgb(.018, .065, .12).round_rectangle(-103, -8, 206, 61, 16).fill()
    elif page == "clock":
        ctx.rgb(.035, .035, .105).round_rectangle(-102, -29, 204, 57, 17).fill()


def header(ctx):
    ctx.rgb(.035, .055, .12).round_rectangle(-81, -91, 162, 21, 9).fill()
