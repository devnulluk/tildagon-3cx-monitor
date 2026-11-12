"""Lightweight vector chrome for live calls, team cards and settings."""
import math

TAU = 2 * math.pi
INK = (0.018, 0.035, 0.065)
PANEL = (0.035, 0.072, 0.11)
EDGE = (0.13, 0.22, 0.31)


def _ring(ctx, radius, start, end, colour, width=1):
    ctx.line_width = width
    ctx.rgb(*colour).arc(0, 0, radius, start, end, False).stroke()


def backdrop(ctx, now, own_rgb, call=None, offline=False):
    ctx.rgb(*INK).rectangle(-120, -120, 240, 240).fill()
    if call is None:
        colour = (0.15, 0.23, 0.33) if offline else (0.08, 0.30, 0.38)
        _ring(ctx, 115, 0, TAU, colour, 1.2)
        _ring(ctx, 111, -2.15, -0.99, (0.13, 0.50, 0.58), 1.6)
        return
    raw = call.get('_colour', (255, 255, 255))
    accent = tuple(channel / 255 for channel in raw)
    priority = bool(call.get('priority'))
    beat = now % 1000
    bright = (beat < 140 or 260 <= beat < 400) if priority else now % 1100 < 550
    _ring(ctx, 115, 0, TAU, tuple(channel * 0.38 for channel in accent), 2)
    for index in range(3):
        angle = now / 1500 + index * TAU / 3
        _ring(ctx, 109, angle, angle + 1.05, tuple(channel * (0.94 if bright else 0.40) for channel in accent), 3)
    ctx.rgb(*(channel * 0.09 + 0.015 for channel in accent)).arc(0, -16, 36, 0, TAU, False).fill()
    ctx.rgb(*(channel * 0.11 + 0.018 for channel in accent)).round_rectangle(-88, -79, 176, 31, 15).fill()


def team_card(ctx, x, y, colour, ringing=False, now=0):
    # Geometry follows the established large-initials layout exactly.
    top = y - 39
    ctx.rgb(*PANEL).round_rectangle(x - 49, top, 98, 74, 14).fill()
    intensity = 0.55 + 0.25 * (math.sin(now / 170) + 1) / 2 if ringing else 0.55
    ctx.line_width = 1.1
    ctx.rgb(*(channel * intensity for channel in colour)).round_rectangle(x - 49, top, 98, 74, 14).stroke()
    ctx.rgb(*colour).round_rectangle(x - 17, top + 1, 34, 2.5, 1).fill()


def settings_row(ctx, index, level, selected):
    top = -44 + index * 57
    accent = (0.20, 0.90, 0.83) if selected else (0.30, 0.43, 0.58)
    ctx.rgb(*PANEL).round_rectangle(-102, top, 204, 53, 12).fill()
    ctx.line_width = 1.5 if selected else 1
    ctx.rgb(*accent).round_rectangle(-102, top, 204, 53, 12).stroke()
    ctx.rgb(*EDGE).round_rectangle(-83, top + 45, 166, 3, 1.5).fill()
    if level > 0:
        ctx.rgb(*accent).round_rectangle(-83, top + 45, max(1, min(166, level * 166)), 3, 1.5).fill()


def speed_card(ctx,x,y,colour,crowned=False,ringing=False,now=0):
    """Equal-size dial tiles fitting five entries inside the round display."""
    ctx.rgb(*PANEL).round_rectangle(x-43,y-28,86,56,11).fill()
    gain=.55+.20*(math.sin(now/170)+1)/2 if ringing else .60
    ctx.line_width=1.2
    ctx.rgb(*(channel*gain for channel in colour)).round_rectangle(x-43,y-28,86,56,11).stroke()
    ctx.rgb(*colour).round_rectangle(x-13,y-27,26,2,1).fill()
    if crowned:
        ctx.rgb(1,.78,.27).move_to(x+19,y-22).line_to(x+22,y-14).line_to(x+32,y-14).line_to(x+35,y-22).line_to(x+29,y-19).line_to(x+27,y-25).line_to(x+25,y-19).close_path().fill()
        ctx.rgb(1,.78,.27).round_rectangle(x+22,y-12,10,2,1).fill()


def notice_panel(ctx):
    ctx.rgb(*PANEL).round_rectangle(-105, -53, 210, 104, 23).fill()
    ctx.line_width = 1
    ctx.rgb(0.12, 0.56, 0.67).round_rectangle(-105, -53, 210, 104, 23).stroke()
