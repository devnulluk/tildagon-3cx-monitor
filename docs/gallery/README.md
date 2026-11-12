# Simulator gallery

These are actual frames from the official Tildagon SDL/ctx simulator running
the badge app. Every call and weather value is synthetic. **Westmoor is an
invented location**, **Partner is a placeholder name**, and the caller number
`+44 1632 960123` is a reserved example. The December dates demonstrate the
calendar and Advent pages; no personal birthdays, anniversary dates or ages
are supplied. The isolated simulator config contains no PBX address or token.

![Theme tour](themes.gif)

[Theme video](themes.mp4) · [Theme contact sheet](themes-contact-sheet.png) ·
[All theme stills](themes-gallery.png)

![Clock tour](clocks.gif)

[Clock video](clocks.mp4) · [Clock contact sheet](clocks-contact-sheet.png) ·
[Corpus-inspired loop](clock-corpus.mp4) · [Corpus animation](clock-corpus.gif)

![Moon and meteor pages](sky.gif)

[Sky video](sky.mp4) · [Sky stills](sky-gallery.png)

![Synthetic partner call](partner-call.gif)

[Call video](partner-call.mp4) · [Call still](partner-call.png)

The videos retain real monotonic capture timing. They contain no motion
interpolation; encoding may repeat captured frames to produce a compatible
H.264 stream. Capture speed varies with the computer and is **not a physical
badge frame-rate measurement**. GIFs are looped previews. The `-lcd.png` files
are the native 240 × 240 LCD pixels; paired PNGs show the whole simulator.

There is **no camera footage**. The upstream simulator uses its own board
artwork. The EEH panel is a schematic, and the Liteloop panel is a labelled
156-LED monochrome diagram driven by the real app adapter through an in-memory
I2C sink. Its dots illustrate the glyph and heartbeat; they do not establish
the physical LED colour, PCB arrangement, brightness or hardware timing.

## Reproduce the captures

From the project folder, prepare the pinned simulator runtime once:

```powershell
py -3.10 tools/prepare_simulator.py
```

Then run the public launcher. The `GalleryStills` switch exports matching
full-window and native LCD stills at each scene's midpoint.

```powershell
./Launch-Simulator.ps1 -Record ./docs/gallery/themes.mp4 -Showcase themes -Seconds 28 -DemoDate 2026-12-12 -GalleryStills
./Launch-Simulator.ps1 -Record ./docs/gallery/clocks.mp4 -Showcase clocks -Seconds 18 -DemoDate 2026-12-12 -GalleryStills
./Launch-Simulator.ps1 -Record ./docs/gallery/clock-corpus.mp4 -Showcase idle -Page clock -ClockStyle corpus -WeatherKind night -Seconds 8 -DemoDate 2026-12-12 -GalleryStills
./Launch-Simulator.ps1 -Record ./docs/gallery/sky.mp4 -Showcase sky -Seconds 12 -DemoDate 2026-12-12 -GalleryStills
./Launch-Simulator.ps1 -Record ./docs/gallery/partner-call.mp4 -Showcase calls -Page clock -Theme christmas -RecordView window -Seconds 12 -DemoDate 2026-12-12 -PartnerDemo -MatrixDemo -GalleryStills
```

A single screenshot or an interactive preview can use any theme and clock:

```powershell
./Launch-Simulator.ps1 -Screenshot -Page weather -Theme cyberpunk -DemoDate 2026-12-12 -OutputPath ./theme-example.png
./Launch-Simulator.ps1 -Page clock -Theme ocean -ClockStyle corpus -MatrixDemo
```

For direct Python use, see the [portable simulator instructions](../../simulator/README.md).
No live PBX action, contact lookup or weather request is made by these fixtures.
