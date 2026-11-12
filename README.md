# Tildagon 3CX Monitor

A tiny, full-colour desk companion for a 3CX phone system. Four team BLFs surround a readable initials display; incoming calls take over the screen with caller ID and a distinct colour for direct, internal, queue and priority calls.

![Animated theme selection, official simulator with synthetic data](docs/gallery/themes.gif)

[Theme gallery and authoring guide](THEMES.md) Â· [Clock gallery](CLOCKS.md) Â· [Setup](docs/SETUP.md) Â· [Astronomy sources and accuracy](docs/ASTRONOMY.md)

![Theme examples](docs/gallery/themes-contact-sheet.png)

## What it does

- Live team status and internal peer extension/first name; teammates' external calls show **External**.
- Large own caller ID with wrapping; exact company/personal 3CX contact lookup when enabled.
- Allowlisted speed dials and DND with a keyboard expansion and a separate control token.
- Independent ring and East Essex logo brightness, saved locally; priority calls override those two levels temporarily.
- Thirteen themes, automatic seasonal/personal occasions, December Advent, and seven interchangeable clocks.
- Weather, next-hour rain, moon phase and animated meteor calendar pages during quiet periods. Call activity interrupts them immediately.
- A personal caller celebration, a heartbeat on the East Essex logo and an animated heart on the Liteloop matrix.
- Optional verified PNG asset packs on microSD. Every bundled theme, including the photographic background, fits internal storage.

Badge **0.8.0** / bridge **0.5.0**. The code targets the round 240Ã—240 Tildagon/Spaceagon screen and MicroPython firmware APIs. Gallery images and animations are recordings of the official SDL/ctx simulator running the app with synthetic data, rather than camera footage or hardware frame-rate measurements. Native validation is described in [validation](docs/VALIDATION.md).

## Controls

With a keyboard expansion: **S** opens settings, **T** opens the theme row, **K** opens the clock row. **Up/Down** selects Ring, EEH, Theme or Clock; **Left/Right** changes the selected value; **Enter** closes settings and previews an appearance change when there is no call activity. Physical **Aâ€“D** dial the four configured team targets, **E** the partner target, **F** toggles DND. Settings captures those buttons while open.

During idle, **Left/Right** browses pages and **Space** returns to monitoring. Outside settings, **Up/Down** adjusts EEH brightness. Without a keyboard, hold **C** for settings; A/D selects a row, B/E changes it, C/F closes it. A short C opens your own status or confirms the current view; F exits the app.

## Architecture

```text
3CX Call Control + own-user session
                â”‚
          Docker bridge
       state bearer / control bearer
                â”‚ verified HTTPS
          Tildagon / Spaceagon
       LCD + ring + EEH + Liteloop
```

The badge stores bridge access tokens; the PBX application key and optional own-user grant stay on the bridge. State reads may reuse one verified TLS connection. Control requests are single-use and never automatically replayed after an uncertain response. The bridge permits only the configured own extension and speed-dial targets. There is no arbitrary dial field or audio transport.

Start with [setup](docs/SETUP.md), copy the example configuration locally and keep populated credentials, personal dates and contacts out of Git. Weather uses Open-Meteo; astronomy runs offline from the cited USNO/IMO data. No caller-number guessing service is contacted.

## Development

```sh
python -m venv .venv
python -m pip install -r requirements-dev.txt
python tools/run_tests.py
python -m compileall -q badge bridge
```

The [media notes](docs/gallery/README.md) explain how screenshots and animations were captured. [Artwork provenance](artwork/README.md) includes the photographic background's generation prompt. MIT licence; independent visual homages and original art, with no affiliation to the referenced watch or character brands.
