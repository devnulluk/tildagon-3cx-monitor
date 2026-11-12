# Offline Moon and meteor data

The badge makes no astronomy API requests. `badge/astronomy.py` embeds primary-source dates and calculates UTC values independently of the firmware's time epoch. The clock's London local time does not shift the scientific dates.

## Moon

Primary-phase UTC anchors come from the US Naval Observatory annual services for [2026](https://aa.usno.navy.mil/api/moon/phases/year?year=2026) and [2027](https://aa.usno.navy.mil/api/moon/phases/year?year=2027), with December 2025 and January 2028 for boundary interpolation. Retrieved 12 November 2026.

Between adjacent quarter-phase anchors the code interpolates the phase angle. It estimates illuminated percentage with `(1-cos(2*pi*phase))/2`. Both are **approximations**, rather than an ephemeris or a calculation of the Moon's orientation above the local horizon. Phase 0 is new, 0.25 first quarter, 0.5 full and 0.75 last quarter; the northern-style icon lights the right side while waxing and the left while waning. The [USNO phase definitions](https://aa.usno.navy.mil/faq/moon_phases) explain the geometry.

Outside the embedded anchors, the fallback advances a mean 29.530589-day lunar cycle from a verified new Moon. That period comes from [NASA's eclipse periodicity reference](https://eclipse.gsfc.nasa.gov/SEsaros/SEperiodicity.html). The result explicitly says `Mean lunar cycle`; it may drift and should be treated as decorative information.

## Meteors

The twelve selected showers use Table 5, printed page 25, in the International Meteor Organization's [2026 calendar](https://www.imo.net/files/meteor-shower/cal2026.pdf) and [2027 calendar](https://www.imo.net/files/meteor-shower/cal2027.pdf), checked 12 November 2026. Their peak days are year-specific; for example, Quadrantids, Lyrids, Orionids, Taurids, Leonids and Ursids differ between these two calendars. Cross-year activity periods use the year of the peak.

An active shower means only that the UTC date falls inside its listed activity window. The selection includes northern-interest annual showers and some low-radiant showers; UK visibility can be poor. No count, hourly rate, clear sky, radiant altitude or actual observed meteor is promised. Animations are decorative. The calendars are working predictions and can be revised.

Outside 2026/2027, the code reuses the 2027 seasonal date pattern and explicitly labels each occurrence **Typical season**. This is not a prediction for that year. The overall year-support flag and each individual occurrence's support flag are separate, including a next-year Quadrantid peak shown in December.

Invalid or missing UTC time produces unknown Moon/activity data. Shower lookup results are cached for one UTC day; the returned dictionaries are copies, so renderers cannot alter the cached calendar.
