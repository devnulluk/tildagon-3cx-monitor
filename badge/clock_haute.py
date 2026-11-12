"""Celestial Atelier: original enamel/gold artwork with live complications.

Bitmap artwork contains no time, hands, date or moon phase. Decorative sapphire
orbital motion is artistic; only supplied time and moon phase encode real data.
"""
import math

TAU = 2 * math.pi
_UNIT = tuple((math.sin(i * TAU / 360), -math.cos(i * TAU / 360)) for i in range(360))
_EDGE = tuple((math.cos(-math.pi / 2 + i * math.pi / 16),
               math.sin(-math.pi / 2 + i * math.pi / 16)) for i in range(17))
_GOLD = (.89, .65, .38)
_IVORY = (1, .94, .80)
_NAVY = (.006, .012, .045)
_SAPPHIRE = ((.012, .08, .15), (.018, .16, .28), (.026, .28, .43),
             (.05, .42, .61), (.10, .60, .75), (.27, .78, .86), (.69, .93, .95))
_ORBIT = tuple((math.cos(i * TAU / 48) * 47, -50 + math.sin(i * TAU / 48) * 10) for i in range(49))


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _ring(ctx, x, y, radius, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).stroke()


def _text(ctx, word, x, y, size, colour, width=180, minimum=9):
    ctx.font_size = size
    while size > minimum and ctx.text_width(word) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(x, y).text(word)


def _fallback(ctx):
    _circle(ctx, 0, 0, 101, _NAVY)
    for radius, colour, width in ((100, (.35, .20, .10), 2), (98, (.97, .77, .48), 1.2),
                                  (95, (.52, .31, .16), 1), (91, (.28, .21, .14), .6)):
        _ring(ctx, 0, 0, radius, colour, width)
    # Small sparse stars are cached geometry, not an inferred sky chart.
    ctx.line_width = 1
    ctx.rgb(.53, .45, .29)
    for x, y in ((-70, -40), (67, -38), (-24, -74), (33, -80), (68, 16), (-74, 18), (-26, 77), (26, 78)):
        ctx.move_to(x - 1, y).line_to(x + 1, y)
    ctx.stroke()
    for x in (-47, 0, 47):
        _ring(ctx, x, 43, 18, _GOLD)
    _circle(ctx, -55, -52, 7, _GOLD)
    _circle(ctx, -56.4, -53.5, 4.5, (1, .86, .55))


def _sphere(ctx, x, y):
    # Seven shaded layers suggest a polished gem with a fixed upper-left light.
    _circle(ctx, x + 1, y + 1, 6.5, (.002, .006, .025))
    for index, colour in enumerate(_SAPPHIRE):
        fraction = index / 6
        _circle(ctx, x - fraction * 1.8, y - fraction * 1.8, 5.5 * (1 - fraction * .83), colour)


def _moon(ctx, phase):
    x, y, radius = 0, 43, 12
    _circle(ctx, x, y, radius, (.045, .055, .09))
    if not isinstance(phase, (int, float)) or isinstance(phase, bool) or not 0 <= phase <= 1:
        _text(ctx, "?", x, y, 18, _GOLD, 20, 16)
        return
    direction = 1 if phase <= .5 else -1
    if phase in (0, 1):
        _ring(ctx, x, y, radius, (.28, .31, .36), .7)
        return
    terminator = math.cos(phase * TAU)
    ctx.rgb(.90, .89, .78).move_to(x, y - radius)
    for horizontal, vertical in _EDGE[1:]:
        ctx.line_to(x + direction * horizontal * radius, y + vertical * radius)
    for horizontal, vertical in reversed(_EDGE[:-1]):
        ctx.line_to(x + direction * horizontal * radius * terminator, y + vertical * radius)
    ctx.close_path().fill()


def draw(ctx, value, elapsed, now, palette, sky, artwork=None):
    painted = False
    if callable(artwork):
        try:
            painted = artwork(ctx) is True
        except (OSError, ValueError, TypeError, AttributeError, MemoryError):
            pass
    if not painted:
        _fallback(ctx)
    # Bounded orbit and moving gem sit above the clear live-time aperture.
    ctx.line_width = .7
    ctx.rgb(.30, .23, .17).move_to(*_ORBIT[0])
    for point in _ORBIT[1:]:
        ctx.line_to(*point)
    ctx.stroke()
    angle = int(now // 240) % 360
    x, y = _UNIT[angle]
    _sphere(ctx, x * 47, -50 + y * 10)
    _text(ctx, "CELESTIAL ATELIER", 0, -72, 10, _GOLD, 139, 10)
    _text(ctx, value["clock"], 0, -11, 53, _IVORY, 180, 45)
    second = value["second"]
    _text(ctx, "LOCAL / %02d" % second if second is not None else "LOCAL / --",
          0, 18, 10, (.69, .61, .45), 112, 10)
    _text(ctx, value["day"], -47, 42, 23, _IVORY, 30, 20)
    _text(ctx, "DATE", -47, 55, 7, _GOLD, 29, 7)
    weekday = value["weekday"] if len(value["weekday"]) == 3 else "--"
    _text(ctx, weekday, 47, 42, 15, _IVORY, 31, 13)
    _text(ctx, "DAY", 47, 55, 7, _GOLD, 29, 7)
    moon = sky.get("moon") if isinstance(sky, dict) and sky.get("valid") is True else None
    phase = moon.get("phase_fraction") if isinstance(moon, dict) else None
    _moon(ctx, phase)
    known = isinstance(phase, (int, float)) and not isinstance(phase, bool) and 0 <= phase <= 1
    _text(ctx, "LUNE" if known else "MOON UNKNOWN", 0, 63, 8, _GOLD, 98, 8)
    _text(ctx, value["date"], 0, 79, 11, (.79, .71, .55), 155, 10)
    if second is not None:
        angle = (second * 6 + int((elapsed % 1000) * .006)) % 360
        x, y = _UNIT[angle]
        _circle(ctx, x * 98, y * 98, 2.1, (.57, .34, .15))
        _circle(ctx, x * 98 - .5, y * 98 - .5, 1.2, (1, .91, .65))
