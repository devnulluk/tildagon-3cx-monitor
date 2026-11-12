"""Native-vector railway faces, sized for the badge's 240px circular LCD.

Mondaine-inspired motion follows the Swiss station-clock 58-second sweep and
two-second wait. The British face interprets Network Rail's 2025 Rail Clock:
white 24-hour time, red circular rails and counter-running arrowheads meeting
every 30 seconds. Existing firmware fonts are used, not Rail Alphabet assets.

Time comes solely from the caller. No clock, transport or hardware is opened.
"""
import math

TAU = 2 * math.pi
_PAPER = (.985, .98, .965)
_INK = (.035, .04, .045)
_RED = (.88, .015, .035)
_SILVER = (.62, .64, .65)
_BLACK = (.008, .009, .012)
_WHITE = (.985, .985, .985)
_RAIL_RED = (.94, .005, .02)
_RAIL_MUTED = (.58, .59, .60)
_TICKS_MINOR = tuple((math.sin(i * TAU / 60) * 91, -math.cos(i * TAU / 60) * 91,
                      math.sin(i * TAU / 60) * 97, -math.cos(i * TAU / 60) * 97)
                     for i in range(60) if i % 5)
_TICKS_MAJOR = tuple((math.sin(i * TAU / 12) * 81, -math.cos(i * TAU / 12) * 81,
                      math.sin(i * TAU / 12) * 97, -math.cos(i * TAU / 12) * 97)
                     for i in range(12))


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and -1e15 < value < 1e15)


def _clock(value):
    if not isinstance(value, dict):
        return None
    hour, minute, second = (value.get(key) for key in ("hour", "minute", "second"))
    if (type(hour) is not int or not 0 <= hour < 24
            or type(minute) is not int or not 0 <= minute < 60
            or type(second) is not int or not 0 <= second < 60):
        return None
    return hour, minute, second


def _seconds(value, elapsed):
    clock = _clock(value)
    if clock is None:
        return None
    fraction = elapsed % 1000 / 1000 if _finite(elapsed) and elapsed >= 0 else 0
    return clock[2] + fraction


def _mondaine_phase(value, elapsed):
    """A normalized revolution; 58.000 through 59.999 seconds dwell at 12."""
    seconds = _seconds(value, elapsed)
    return None if seconds is None else seconds / 58 if seconds < 58 else 0


def _mondaine_hands(value):
    """Hour/minute positions only advance when the supplied minute advances."""
    clock = _clock(value)
    if clock is None:
        return None
    hour, minute, second = clock
    return (hour % 12 + minute / 60) / 12, minute / 60


def _rail_phases(value, elapsed):
    seconds = _seconds(value, elapsed)
    if seconds is None:
        return None
    phase = seconds / 60
    return phase, (-phase) % 1


def _circle(ctx, x, y, radius, colour):
    ctx.rgb(*colour).arc(x, y, radius, 0, TAU, False).fill()


def _ring(ctx, radius, colour, width):
    ctx.line_width = width
    ctx.rgb(*colour).arc(0, 0, radius, 0, TAU, False).stroke()


def _segments(ctx, geometry, colour, width):
    # 48 minor strokes make only 96 path edges, below ctx's native limit.
    ctx.line_width = width
    ctx.rgb(*colour)
    for x0, y0, x1, y1 in geometry:
        ctx.move_to(x0, y0).line_to(x1, y1)
    ctx.stroke()


def _text(ctx, text, y, size, width, colour, minimum=None):
    minimum = size if minimum is None else minimum
    ctx.font_size = size
    while size > minimum and ctx.text_width(text) > width:
        size -= 1
        ctx.font_size = size
    ctx.rgb(*colour).move_to(0, y).text(text)


def _hand(ctx, phase, length, width, tail, colour):
    angle = phase * TAU
    dx, dy = math.sin(angle), -math.cos(angle)
    px, py = -dy * width / 2, dx * width / 2
    ctx.rgb(*colour).move_to(-dx * tail + px, -dy * tail + py)
    ctx.line_to(dx * length + px, dy * length + py)
    ctx.line_to(dx * length - px, dy * length - py)
    ctx.line_to(-dx * tail - px, -dy * tail - py).close_path().fill()


def draw_mondaine(ctx, value, elapsed, now, palette, sky):
    """Independent paper-white dial; theme colours cannot reduce contrast."""
    _circle(ctx, 0, 0, 101, _PAPER)
    _ring(ctx, 100, _SILVER, 1)
    _segments(ctx, _TICKS_MINOR, _INK, 1.45)
    _segments(ctx, _TICKS_MAJOR, _INK, 5.7)
    _text(ctx, "MONDAINE", -34, 12, 95, _INK)
    _text(ctx, "SWISS RAILWAY", 40, 8, 100, (.27, .28, .29))
    hands = _mondaine_hands(value)
    if hands is None:
        # A clear central unknown replaces hands, rather than inventing noon.
        _text(ctx, "--:--", 1, 48, 155, _INK, 45)
        return
    _hand(ctx, hands[0], 53, 8, 8, _INK)
    _hand(ctx, hands[1], 76, 5.6, 9, _INK)
    phase = _mondaine_phase(value, elapsed)
    angle = phase * TAU
    dx, dy = math.sin(angle), -math.cos(angle)
    ctx.line_width = 1.7
    ctx.rgb(*_RED).move_to(-dx * 17, -dy * 17).line_to(dx * 74, dy * 74).stroke()
    _circle(ctx, dx * 74, dy * 74, 5.1, _RED)
    _circle(ctx, 0, 0, 3.6, _RED)


def _arrow(ctx, phase, radius, direction):
    angle = phase * TAU
    radial_x, radial_y = math.sin(angle), -math.cos(angle)
    tangent_x, tangent_y = math.cos(angle) * direction, math.sin(angle) * direction
    x, y = radial_x * radius, radial_y * radius
    # A filled concave chevron echoes the Double Arrow without font assets.
    ctx.rgb(*_RAIL_RED).move_to(x + tangent_x * 11, y + tangent_y * 11)
    ctx.line_to(x - tangent_x * 7 + radial_x * 6, y - tangent_y * 7 + radial_y * 6)
    ctx.line_to(x - tangent_x * 1.2, y - tangent_y * 1.2)
    ctx.line_to(x - tangent_x * 7 - radial_x * 6, y - tangent_y * 7 - radial_y * 6)
    ctx.close_path().fill()


def draw_gbr(ctx, value, elapsed, now, palette, sky):
    """The new British Rail Clock's opposing trains and accessible 24h time."""
    _circle(ctx, 0, 0, 101, _BLACK)
    _ring(ctx, 91, _RAIL_RED, 3.7)
    _ring(ctx, 82, _RAIL_RED, 3.7)
    clock = _clock(value)
    text = "%02d:%02d" % (clock[0], clock[1]) if clock is not None else "--:--"
    _text(ctx, text, 0, 62, 153, _WHITE, 53)
    _text(ctx, "GREAT BRITISH RAILWAYS", 39, 8, 131, _RAIL_MUTED)
    phases = _rail_phases(value, elapsed)
    if phases is not None:
        _arrow(ctx, phases[0], 91, 1)
        _arrow(ctx, phases[1], 82, -1)
