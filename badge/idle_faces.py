"""Three native ctx faces for the 240px round display; no bitmap assets.

Uses the firmware's arc, curve_to, round_rectangle and cached opaque colour bands,
and font_size/line_width properties. Forecast tracks show an hour and the
reported onset interval only: they never invent a precipitation time series.
"""
import math
from . import idle_art as art

TAU = 2 * math.pi
WHITE = (0.94, 0.97, 1.0)
MUTED = (0.58, 0.68, 0.79)
AMBER = (1.0, 0.72, 0.24)
CYAN = (0.20, 0.84, 1.0)
VIOLET = (0.67, 0.53, 1.0)
TEAL = (0.24, 0.94, 0.78)
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _text(ctx, value, x, y, size, width=210, colour=WHITE, minimum=18):
    value = str(value or "")
    ctx.font_size = size
    while size > minimum and ctx.text_width(value) > width:
        size -= 1
        ctx.font_size = size
    # Main values use a fitting font, never a clipped numeric prefix.
    ctx.rgb(*colour).move_to(x, y).text(value)


def _circle(ctx, x, y, radius, colour, alpha=1):
    ctx.rgba(colour[0], colour[1], colour[2], alpha).arc(x, y, radius, 0, TAU, False).fill()


def _stroke(ctx, points, colour, width=2, alpha=1):
    ctx.line_width = width
    ctx.rgba(colour[0], colour[1], colour[2], alpha).move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.stroke()


def _background(ctx, page, night=False, code=None):
    return art.base(ctx, page, night, code)


def _chrome(ctx, page, own_rgb, accent, demo):
    try:
        own = tuple(max(0, min(255, channel)) / 255 for channel in own_rgb)
        if len(own) != 3:
            raise ValueError()
        if not any(own):
            own = (0.30, 0.34, 0.42)
    except (TypeError, ValueError):
        own = (0.32, 0.35, 0.42)
    y = -89 if page == "clock" else -102
    _circle(ctx, -18, y, 3, own)
    _text(ctx, "MB", 4, y, 15, 32, own, 15)
    if demo:
        _text(ctx, "DEMO", 43, -100 if page != "clock" else -76, 9.5, 35, AMBER, 9.5)
    selected = ("weather", "rain", "clock").index(page)
    ctx.rgb(.018, .03, .085).round_rectangle(-24, 100, 48, 12, 6).fill()
    for index in range(3):
        _circle(ctx, (index - 1) * 12, 106, 2.7,
                accent if index == selected else (0.20, 0.26, 0.36))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) < 1000000


def _weather(ctx, weather, fresh, now_ms):
    current = weather.get("current") if fresh else None
    current = current if isinstance(current, dict) else {}
    art.weather(ctx, current, fresh, now_ms)
    code = current.get("weather_code")
    if not fresh or isinstance(code, bool) or code not in art.KNOWN_CODES:
        _text(ctx, "?", -18, -35, 32, 46, MUTED, 25)
    art.header(ctx)
    _text(ctx, weather.get("location") or "WEATHER", 0, -80, 16, 145, MUTED, 14)
    art.readout(ctx, "weather")
    temp = current.get("temperature_c")
    _text(ctx, "%.0f C" % temp if _number(temp) else "-- C", 0, 24, 67, 212, WHITE, 40)
    _text(ctx, current.get("condition") or "Unavailable", 0, 63, 23, 198, WHITE, 19)
    feels = current.get("apparent_temperature_c")
    _text(ctx, "Feels %.0f C" % feels if _number(feels) else "No fresh forecast", 0, 83, 17, 190, MUTED, 16)
    _text(ctx, "Open-Meteo", 0, 96, 9.5, 130, MUTED, 9.5)


def _rain(ctx, weather, fresh, now_ms):
    rain = weather.get("rain_next_hour")
    rain = rain if isinstance(rain, dict) else {}
    state = rain.get("status") if fresh else "unknown"
    if state not in ("rain_likely", "dry_likely"):
        state = "unknown"
    art.rain(ctx, state, now_ms)
    art.header(ctx)
    _text(ctx, "NEXT 60 MIN", 0, -80, 17, 150, MUTED, 17)
    if state == "unknown":
        _text(ctx, "?", 0, -43, 32, 50, MUTED, 25)
    art.readout(ctx, "rain")
    label = {"rain_likely": "Rain likely", "dry_likely": "Dry likely", "unknown": "Unavailable"}[state]
    _text(ctx, label, 0, 8, 31, 214, CYAN if state == "rain_likely" else TEAL if state == "dry_likely" else MUTED, 25)
    onset = rain.get("onset_minutes") if fresh else None
    valid_onset = (state == "rain_likely" and isinstance(onset, (list, tuple)) and len(onset) == 2
                   and all(_number(value) for value in onset) and 0 <= onset[0] <= onset[1] <= 60)
    detail = "In %d-%d min" % (onset[0], onset[1]) if valid_onset else "Model forecast" if state != "unknown" else "No fresh forecast"
    _text(ctx, detail, 0, 38, 23, 206, WHITE if state != "unknown" else MUTED, 20)
    ctx.rgb(0.11, 0.22, 0.30).round_rectangle(-70, 60, 140, 4, 2).fill()
    for minute in (0, 15, 30, 45, 60):
        x = -70 + minute * 140 / 60
        _stroke(ctx, [(x, 57), (x, 67)], MUTED, 1, 0.6)
    if valid_onset:
        left, right = -70 + onset[0] * 140 / 60, -70 + onset[1] * 140 / 60
        ctx.rgb(*CYAN).round_rectangle(left, 59, max(3, right - left), 6, 3).fill()
    _text(ctx, "0", -84, 62, 11, 15, MUTED, 11)
    _text(ctx, "60", 86, 62, 11, 21, MUTED, 11)
    amount = rain.get("precipitation_mm")
    credit = "Open-Meteo / ~%.1f mm" % amount if state != "unknown" and _number(amount) else "Open-Meteo"
    ctx.rgb(.018, .045, .10).round_rectangle(-78, 78, 156, 19, 8).fill()
    _text(ctx, credit, 0, 88, 10, 146, MUTED, 9.5)


def _clock(ctx, weather, local, now_ms, elapsed_ms=0):
    valid = isinstance(local, (tuple, list)) and len(local) >= 6
    sec = int(local[5]) % 60 if valid else (now_ms // 1000) % 60
    art.clock(ctx, sec if valid else None, now_ms, elapsed_ms)
    art.readout(ctx, "clock")
    if valid:
        weekday = _DAYS[int(local[6]) % 7] if len(local) > 6 else "LOCAL TIME"
        date = "%02d %s %04d" % (local[2], _MONTHS[max(1, min(12, int(local[1]))) - 1], local[0])
        clock = "%02d:%02d" % (local[3], local[4])
    else:
        weekday, date, clock = "LOCAL TIME", weather.get("local_date") or "Clock unavailable", weather.get("local_clock") or "--:--"
    _text(ctx, weekday, 0, -51, 18, 171, VIOLET, 18)
    _text(ctx, clock, 0, -4, 65, 213, WHITE, 45)
    _text(ctx, date, 0, 41, 23, 186, MUTED, 18)
    _circle(ctx, 0, 75, 13, (0.17, 0.15, 0.32))
    _text(ctx, "%02d" % sec if valid else "--", 0, 75, 18, 29, TEAL, 16)


def draw_idle_face(ctx, page, weather, fresh, local, elapsed_ms, now_ms, own_rgb, demo=False, clock_draw=None):
    """Draw one complete idle face; caller owns freshness and epoch conversion."""
    if page not in ("weather", "rain", "clock"):
        page = "weather"
    weather = weather if isinstance(weather, dict) else {}
    ctx.save()
    ctx.text_align = ctx.CENTER
    ctx.text_baseline = ctx.MIDDLE
    current = weather.get("current") if fresh else None
    current = current if isinstance(current, dict) else {}
    accent = _background(ctx, page, current.get("is_day") is False, current.get("weather_code"))
    if page == "rain":
        _rain(ctx, weather, bool(fresh), now_ms)
    elif page == "clock":
        if not callable(clock_draw) or clock_draw(ctx, None) is not True:
            _clock(ctx, weather, local, now_ms, elapsed_ms)
    else:
        _weather(ctx, weather, bool(fresh), now_ms)
    if page == "clock" and callable(clock_draw):
        _circle(ctx, -18, -106, 3, tuple(v / 255 for v in own_rgb))
        _text(ctx, "MB", 4, -106, 12, 30, WHITE, 12)
        if demo:
            _text(ctx, "DEMO", 0, 106, 9, 36, AMBER, 9)
    else:
        _chrome(ctx, page, own_rgb, accent, demo)
    ctx.restore()
