# Official Tildagon simulator

Run the actual badge app through the official SDL/ctx WebAssembly renderer. This is a synthetic DEMO: it does not connect to a PBX, read the badge's private configuration, or place calls. The public fixtures use example names, a fictitious location and reserved example telephone numbers.

## Requirements and setup

Install **Git** and **CPython 3.10**, then run these commands from the project checkout:

```powershell
py -3.10 tools/prepare_simulator.py
.\Launch-Simulator.ps1
```

On Linux/macOS, use the corresponding Python executable:

```sh
python3.10 tools/prepare_simulator.py
.simulator/venv/bin/python simulator/launch.py --keyboard --idle-page weather
```

The setup script creates `.simulator/firmware` and `.simulator/venv` inside this checkout. It installs only into that virtual environment. It downloads a shallow, sparse checkout of the [official firmware](https://github.com/emfcamp/badge-2024-software/tree/f10ecb8b18631b0cd328c765b4a3d9f39dbe1ede) at commit `f10ecb8b18631b0cd328c765b4a3d9f39dbe1ede`, plus the pinned packages in [requirements.txt](requirements.txt). The compiled `sim/wasm/ctx.wasm` is already in that commit; setup checks its SHA256, so Emscripten, a firmware toolchain and submodule downloads are unnecessary.

The [upstream simulator instructions](https://github.com/emfcamp/badge-2024-software/blob/f10ecb8b18631b0cd328c765b4a3d9f39dbe1ede/sim/README.md) describe additional SDL dependencies that some Linux/macOS installations need. Setup does not install operating-system packages. The optional missing-`mad` warning concerns MP3 playback and does not affect this app.

The portable wrapper, separate pinned firmware checkout, screenshot export and decoded video export were verified on Windows with CPython 3.10.18. The Linux/macOS commands follow upstream's setup; they were not exercised here.

If the Windows Python launcher cannot find 3.10, pass its executable explicitly:

```powershell
.\Launch-Simulator.ps1 -PythonPath 'C:\Path\To\Python310\python.exe'
```

An existing compatible simulator environment can be reused without installing anything into it:

```sh
python3.10 tools/prepare_simulator.py --reuse-runtime /path/to/existing/venv/bin/python
python3.10 tools/prepare_simulator.py --check
```

`TILDAGON_SIM_ROOT` selects a different cache directory for setup and launch. PowerShell also accepts `-SimRoot`. The cache contains machine-local paths and logs; keep `.simulator/` out of Git and release archives. A cache with a different firmware revision is rejected, never silently reset.

## Controls

The launcher enables the simulated keyboard:

- **Left/Right:** browse idle pages or select a teammate.
- **Enter:** show the next synthetic incoming-call scene.
- **Space:** return to the team/own view.
- **S:** settings; **T:** theme settings; **K:** clock settings.
- **N:** notification inbox; arrows browse, Enter dismisses, Space/Escape returns.
- In settings, **Up/Down** select a row, **Left/Right** change it, **Enter/Space** finish.
- **A–F:** badge buttons. Any simulated calling/DND action remains local to DEMO.
- **Escape:** exit.

The side panel is a labelled hexpansion diagram. `-MatrixDemo` adds a simulated I2C sink for the real Liteloop adapter and its documented LED mapping; it is not physical hardware footage.

## Screenshots and video

```powershell
.\Launch-Simulator.ps1 -Page clock -ClockStyle corpus -DemoDate 2026-12-12
.\Launch-Simulator.ps1 -Page weather -Theme christmas -WeatherKind snow -Screenshot -OutputPath .\preview.png
.\Launch-Simulator.ps1 -Page clock -ClockStyle celestial -Screenshot -OutputPath .\celestial.png
.\Launch-Simulator.ps1 -Page clock -ClockStyle mondaine -Screenshot -OutputPath .\mondaine.png
.\Launch-Simulator.ps1 -Page clock -Showcase rail -Record .\clocks-rail.mp4 -Seconds 28 -GalleryStills -MatrixDemo
.\Launch-Simulator.ps1 -Record .\clocks.mp4 -Showcase clocks -Seconds 28
.\Launch-Simulator.ps1 -Page clock -ClockStyle corpus -Record .\corpus.mp4 -Showcase idle -Seconds 8
.\Launch-Simulator.ps1 -Record .\calls.mp4 -Showcase calls -Seconds 16 -PartnerDemo -MatrixDemo -GalleryStills
.\Launch-Simulator.ps1 -Notification warning -Screenshot -OutputPath .\warning.png
.\Launch-Simulator.ps1 -Record .\notifications.mp4 -Showcase notifications -Seconds 32 -GalleryStills
```

The Python entry point supports the same options; replace the PowerShell spellings with `--idle-page`, `--clock-style`, `--demo-date`, `--theme`, `--weather-kind`, `--screenshot`, `--output`, `--record`, `--showcase`, `--seconds`, `--action`, `--partner-demo` and `--matrix-demo`. Headless captures require `SDL_VIDEODRIVER=dummy`, which the PowerShell wrapper sets automatically. An interactive window requires a normal desktop display.

Video output includes H.264 MP4, GIF, poster, contact sheet and JSON metadata. `-GalleryStills` with `-Record` also exports each scene's real midpoint frame. Frames come from the actual official renderer; capture timing is preserved, with no motion interpolation or generated UI frames. Recording performance does not establish physical badge FPS.

The `rail` showcase spends fourteen seconds on Mondaine and fourteen on Great
British Railways. Its synthetic local clock starts at 10:08:52 after boot so the
first face shows its two-second pause at twelve and the minute-hand advance.
The second face makes a labelled synthetic time cut to 10:09:22 so its arrows
meet at thirty seconds within the same short film.
The GIF retains the full pair. `-ClockStyle great_british_railways` selects the
British face for a standalone preview. This fixture never sets the badge's RTC.

The calls showcase reaches the synthetic priority partner scene and exports its heartbeat/matrix-heart still. A single `-Action ENTER` from an idle page reaches the first DDI scene; continue pressing Enter to cycle the remaining call types.

Private `config.json`, control/read tokens and CA files are never copied into the simulator app. Only Python source, public manifests and verified public theme assets are staged. The wrapper generates a fresh DEMO configuration with empty credentials.

`-Notification` / `--notification` accepts info, success, warning, failure and
progress. It opens the real badge inbox after the upstream boot overlay. The
notifications showcase includes a same-ID progress update, a synthetic priority
call preempting the card and the waiting alert returning afterward. No webhook,
ntfy subscription or real call is involved. See [notification controls and
examples](../docs/NOTIFICATIONS.md).

## Matrix caller preview

```powershell
./Launch-Simulator.ps1 -Showcase matrix -Record ./docs/gallery/matrix-caller.mp4 -Seconds 24 -RecordView window -GalleryStills
```

This uses synthetic caller names through the production matrix adapter and a
labelled in-memory I2C diagram. The first sixteen seconds demonstrate scrolling;
the final eight demonstrate the configured partner heart. The diagram is not
physical LED footage or a native brightness/FPS measurement. The Python launcher
also accepts `--settings-row 4 --matrix-demo --screenshot` for a direct preview of
the Matrix Call brightness row.
