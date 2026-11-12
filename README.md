# Spaceagon 3CX Monitor

A full-colour desk companion for a 3CX phone system, built for Spaceagon and compatible Tildagon badges. Four team BLFs surround a readable display; incoming calls take over the screen with caller ID and distinct colours for direct, internal, queue and priority calls.

![Animated theme selection, official simulator with synthetic data](docs/gallery/themes.gif)

[Theme gallery and authoring guide](THEMES.md) · [Clock gallery](CLOCKS.md) · [Setup](docs/SETUP.md) · [Notifications](docs/NOTIFICATIONS.md) · [Spaceagon controls](docs/SPACEAGON.md) · [Astronomy sources and accuracy](docs/ASTRONOMY.md)

![Theme examples](docs/gallery/themes-contact-sheet.png)

## What it does

- Live team status and internal peer extension/first name; teammates' external calls show **External**.
- Large own caller ID with wrapping; exact company/personal 3CX contact lookup when enabled.
- Allowlisted speed dials and DND with a keyboard expansion and a separate control token.
- Independent ring and East Essex logo brightness, saved locally; priority calls override those two levels temporarily.
- Thirteen themes, automatic seasonal/personal occasions, December Advent, and seven interchangeable clocks.
- Weather, next-hour rain, moon phase and animated meteor calendar pages during quiet periods. Call activity interrupts them immediately.
- Rich Apprise/ntfy notification cards with local icons, severity colours and progress updates. Calls take precedence over notification cards.
- Spaceagon joystick and capacitive touch-ring navigation, including notification browsing. These gestures never place calls or change DND.
- A personal caller celebration, a heartbeat on the East Essex logo and an animated heart on the Liteloop matrix.
- Optional verified PNG asset packs on microSD. Every bundled theme, including the photographic background, fits internal storage.

Badge **0.9.0** / bridge **0.6.0**. The code targets the round 240×240 Spaceagon/Tildagon screen and MicroPython firmware APIs. Gallery images and animations are recordings of the official SDL/ctx simulator running the app with synthetic data. They are not camera footage or hardware frame-rate measurements. Native checks and their version scope are recorded in [validation](docs/VALIDATION.md).

## Notifications

![Animated notification types, progress updates and call preemption](docs/gallery/notifications.gif)

[Watch the 32-second MP4](docs/gallery/notifications.mp4) · [Notification screenshots](docs/gallery/notifications-contact-sheet.png) · [Configuration and controls](docs/NOTIFICATIONS.md)

The previews use invented messages and reserved example numbers. External senders require a separate `NOTIFY_TOKEN` and an explicitly enabled HTTPS webhook path, or an optional ntfy subscription configured on the bridge. The default example configuration leaves both disabled. Notification payloads cannot execute actions, open links or fetch remote images.

## Controls

With a keyboard expansion: **S** opens settings, **T** opens the theme row, **K** opens the clock row. **Up/Down** selects Ring, EEH, Theme or Clock; **Left/Right** changes the selected value; **Enter** closes settings and previews an appearance change when there is no call activity. Physical **A–D** request the four configured team speed dials, **E** requests the partner speed dial, and **F** requests a DND toggle. Settings and notification views capture those buttons while open.

**N** opens the notification inbox. Arrow keys browse, **Enter/C** dismisses the current item, and **Space/Escape/F** returns. Spaceagon joystick directions and touch-ring rotation also browse; the joystick centre press dismisses an open notification. The [Spaceagon guide](docs/SPACEAGON.md) describes the gestures and their display-only scope.

During idle, keyboard **Left/Right** browses pages and **Space** returns to monitoring. Outside settings, keyboard **Up/Down** adjusts EEH brightness. Without a keyboard, hold **C** for settings; A/D selects a row, B/E changes it, C/F closes it. A short C opens your own status or confirms the current view; F exits the app.

## Architecture

```text
3CX Call Control + own-user session
                  |
             Docker bridge <--- optional Apprise webhook / ntfy stream
                  |
        state bearer / control bearer
                  | verified HTTPS
           Spaceagon / Tildagon
         LCD + ring + EEH + Liteloop
```

The badge stores bridge access tokens; the PBX application key and optional own-user grant stay on the bridge. State reads may reuse one verified TLS connection. Control requests are single-use and never automatically replayed after an uncertain response. The bridge permits only the configured own extension and speed-dial targets. There is no arbitrary dial field or audio transport. A separate notification bearer can submit display messages without reading call data or invoking phone controls.

Start with [setup](docs/SETUP.md), copy the example configuration locally and keep populated credentials, personal dates and contacts out of Git. Weather uses Open-Meteo; astronomy runs offline from the cited USNO/IMO data. No caller-number guessing service is contacted.

## Development

```sh
python -m venv .venv
python -m pip install -r requirements-dev.txt
python tools/run_tests.py
python -m compileall -q badge bridge
```

The [media notes](docs/gallery/README.md) explain how screenshots and animations were captured. [Artwork provenance](artwork/README.md) includes the photographic background's generation prompt. MIT licence; independent visual homages and original art, with no affiliation to the referenced watch or character brands.
