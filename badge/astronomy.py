"""Offline UTC astronomy for decorative badge complications.

USNO primary phase anchors cover2026/2027 with boundary months. Intermediate
phase and illumination are approximations. IMO annual shower dates are never
presented as observed meteors or promised visibility. See docs/ASTRONOMY.md.
"""
import math

PHASE_NAMES = ("New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
               "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent")
_MEAN_MONTH = 29.530589 * 86400
# USNO UTC minute-resolution epochs; code0=new,1=first,2=full,3=last quarter.
PHASE_ANCHORS = ((1764890040, 2), (1765486320, 3), (1766194980, 0), (1766862600, 1), (1767434580, 2), (1768060080, 3), (1768765920, 0), (1769402820, 1), (1769983740, 2), (1770640980, 3), (1771329660, 0), (1771936020, 1), (1772537880, 2), (1773221880, 3), (1773883380, 0), (1774466280, 1), (1775095920, 2), (1775796660, 3), (1776426720, 0), (1776997920, 1), (1777656180, 2), (1778361000, 3), (1778961660, 0), (1779534660, 1), (1780217100, 2), (1780912800, 3), (1781492040, 0), (1782078900, 1), (1782777360, 2), (1783452540, 3), (1784022180, 0), (1784631900, 1), (1785335760, 2), (1785982860, 3), (1786556220, 0), (1787193960, 1), (1787890680, 2), (1788508260, 3), (1789097220, 0), (1789764240, 1), (1790441340, 2), (1791033900, 3), (1791647400, 0), (1792339920, 1), (1792987920, 2), (1793564880, 3), (1794207720, 0), (1794916080, 1), (1795531980, 2), (1796105280, 3), (1796777520, 0), (1797486120, 1), (1798075680, 2), (1798657140, 3), (1799353440, 0), (1800045240, 1), (1800620220, 2), (1801220100, 3), (1801929360, 0), (1802591880, 1), (1803165780, 2), (1803791760, 3), (1804498140, 0), (1805127900, 1), (1805712240, 2), (1806368040, 3), (1807055460, 0), (1807656960, 1), (1808260020, 2), (1808943480, 3), (1809601080, 0), (1810183440, 1), (1810810740, 2), (1811512680, 3), (1812138000, 0), (1812711360, 1), (1813365840, 2), (1814072040, 3), (1814670120, 0), (1815244740, 1), (1815925500, 2), (1816620900, 3), (1817201100, 0), (1817787240, 1), (1818487740, 2), (1819160820, 3), (1819734060, 0), (1820341860, 1), (1821049380, 2), (1821694800, 3), (1822271760, 0), (1822909620, 1), (1823608020, 2), (1824226140, 3), (1824816960, 0), (1825488000, 1), (1826162760, 2), (1826758080, 3), (1827372240, 0), (1828070520, 1), (1828714140, 2), (1829293860, 3), (1829938320, 0), (1830649200, 1), (1831262580, 2), (1831836360, 3), (1832512320, 0))

# id,name,start(M,D),end(M,D),2026peak(M,D),2027peak(M,D).
# A compact UK/northern-interest selection from IMO Table5; no ZHR claims.
SHOWERS = (
    ("quadrantids", "Quadrantids", (12, 28), (1, 12), (1, 3), (1, 4)),
    ("lyrids", "Lyrids", (4, 14), (4, 30), (4, 22), (4, 23)),
    ("eta_aquariids", "Eta Aquariids", (4, 19), (5, 28), (5, 6), (5, 6)),
    ("southern_delta_aquariids", "S. Delta Aquariids", (7, 12), (8, 23), (7, 31), (7, 31)),
    ("perseids", "Perseids", (7, 17), (8, 24), (8, 13), (8, 13)),
    ("draconids", "Draconids", (10, 6), (10, 10), (10, 9), (10, 9)),
    ("orionids", "Orionids", (10, 2), (11, 7), (10, 21), (10, 22)),
    ("southern_taurids", "S. Taurids", (9, 20), (11, 20), (11, 5), (11, 6)),
    ("northern_taurids", "N. Taurids", (10, 20), (12, 10), (11, 12), (11, 13)),
    ("leonids", "Leonids", (11, 6), (11, 30), (11, 17), (11, 18)),
    ("geminids", "Geminids", (12, 4), (12, 20), (12, 14), (12, 14)),
    ("ursids", "Ursids", (12, 17), (12, 26), (12, 22), (12, 23)),
)
_cache_day = None
_cache_showers = None


def _day(year, month, day):
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    shifted = month - 3 if month > 2 else month + 9
    doy = (153 * shifted + 2) // 5 + day - 1
    return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719468


def _date(day):
    value = day + 719468
    era = value // 146097
    doe = value - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    shifted = (5 * doy + 2) // 153
    day = doy - (153 * shifted + 2) // 5 + 1
    month = shifted + 3 if shifted < 10 else shifted - 9
    return year + (month <= 2), month, day


def _iso(value):
    return "%04d-%02d-%02d" % value


def _moon(unix):
    lower, upper = 0, len(PHASE_ANCHORS)
    while lower < upper:
        middle = (lower + upper) // 2
        if PHASE_ANCHORS[middle][0] <= unix:
            lower = middle + 1
        else:
            upper = middle
    index = lower - 1
    supported = 0 <= index < len(PHASE_ANCHORS) - 1
    if index == len(PHASE_ANCHORS) - 1 and unix == PHASE_ANCHORS[index][0]:
        supported = True
        fraction = PHASE_ANCHORS[index][1] / 4
    elif supported:
        stamp, code = PHASE_ANCHORS[index]
        following = PHASE_ANCHORS[index + 1][0]
        fraction = ((code + (unix - stamp) / (following - stamp)) / 4) % 1
    else:
        # Mean-cycle fallback anchored at a verified USNO New Moon.
        fraction = ((unix - 1768765920) / _MEAN_MONTH) % 1
    illumination = 50 * (1 - math.cos(fraction * math.pi * 2))
    return {"phase_fraction": fraction, "illumination_percent": round(illumination, 1),
            "name": PHASE_NAMES[int((fraction + 0.0625) * 8) % 8], "waxing": fraction < 0.5,
            "approximate": True, "reference_supported": supported,
            "basis": "USNO phase interpolation" if supported else "Mean lunar cycle"}


def _showers(day, year):
    global _cache_day, _cache_showers
    if day == _cache_day:
        return _cache_showers
    active, upcoming = [], None
    for peak_year in (year - 1, year, year + 1):
        supported = peak_year in (2026, 2027)
        basis = "IMO " + str(peak_year) if supported else "Typical season"
        for row in SHOWERS:
            ident, name, start, end, peak26, peak27 = row
            peak = peak26 if peak_year == 2026 else peak27
            start_year = peak_year - 1 if start > end else peak_year
            first, last, maximum = _day(start_year, *start), _day(peak_year, *end), _day(peak_year, *peak)
            is_active = first <= day <= last
            if not is_active and maximum < day:
                continue
            item = {"id": ident, "name": name, "start": _iso((start_year,) + start),
                    "end": _iso((peak_year,) + end), "peak": _iso((peak_year,) + peak),
                    "date": _iso((peak_year,) + peak), "peak_in_days": maximum - day,
                    "basis": basis, "calendar_year_supported": supported, "active": is_active}
            if is_active:
                active.append(item)
            if maximum >= day and (upcoming is None or maximum - day < upcoming["peak_in_days"]):
                upcoming = item
    active.sort(key=lambda item: (abs(item["peak_in_days"]), item["id"]))
    _cache_day, _cache_showers = day, (active, upcoming)
    return _cache_showers


def sky_snapshot(unix, local=None):
    """Pure UTC result, independent of MicroPython's1970/2000 time epoch.

    local is accepted for UI compatibility but never shifts scientific UTC dates.
    No runtime API, file, date-of-birth data, observation rates or forecasts.
    """
    if (isinstance(unix, bool) or not isinstance(unix, (int, float))
            or not 946684800 <= unix < 4133980800):
        return {"valid": False, "asof": None, "calendar_year_supported": False, "calendar_basis": "Unavailable",
                "moon": {"phase_fraction": None, "illumination_percent": None, "name": "Unknown", "waxing": None,
                         "approximate": True, "reference_supported": False, "basis": "Unavailable"},
                "active_showers": [], "next_shower": None}
    day = int(unix // 86400)
    year, month, date = _date(day)
    active, upcoming = _showers(day, year)
    return {"valid": True, "asof": int(unix), "calendar_year_supported": year in (2026, 2027),
            "calendar_basis": "IMO " + str(year) if year in (2026, 2027) else "Typical season",
            "moon": _moon(unix), "active_showers": [dict(item) for item in active],
            "next_shower": dict(upcoming) if upcoming else None}
