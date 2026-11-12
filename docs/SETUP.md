# Installation and configuration

The badge runs a MicroPython app. A separate Python bridge reads the PBX and sends a small, authenticated state snapshot to the badge. PBX credentials and the optional own-user authentication grant stay on the bridge.

Start with demo mode, then enable monitoring. Enable call and DND controls only after checking the configured own extension and speed-dial destinations.

## Requirements

- A Tildagon or compatible Spaceagon running the official app framework, with Wi-Fi configured and a correct clock.
- A 3CX v20 system with the Call Control API available for its licence. Follow the [official API setup guide](https://www.3cx.com/docs/call-control-api/) for the current prerequisites and application permissions.
- A bridge host that can reach the PBX over HTTPS. The badge must be able to reach the bridge; the PBX itself does not need to be exposed to the badge.
- Docker Compose, or Python 3.14 with the packages in `requirements.txt`.

The monitor was developed against v20 Update 9. DND and optional phonebook lookup additionally use that version's own-user MyPhone interface, which can change between PBX releases. Monitoring and allowlisted speed dials can operate without this extra login.

## Configure the bridge

From the repository root, copy `config.example.json` to `config.json` and `.env.example` to `.env`. These are separate from the badge's configuration file.

In the bridge's `config.json`, replace the synthetic example data:

- `own_extension` is the extension making calls and changing its own DND state.
- `team` lists monitored extensions in display order. Four team members fit the main overview.
- `queues`, `ddis` and `trunk_dns` identify routing information used to classify incoming calls. Unknown external routing stays unknown rather than being assumed to be a DDI.
- `priority_callers`, `priority_extensions` and `priority_ddis` define priority matches. `country_code` supports national/international number normalization.
- `contacts`, `internal_extensions` and `initials` provide explicit names and short labels. Optional live lookup is described below.
- `speed_dials` is the server-side destination allowlist. The badge maps F→`tb`, B→`pd`, E→`jh`, C→`sm` and D→`kz`; A opens the menu; keep those IDs and change their labels/numbers for your own destinations. Array order does not change this mapping. The badge sends target IDs; it cannot submit an arbitrary destination number.

Create a Call Control API application in 3CX and grant access to the DNs needed for the own extension, team and relevant routing. Set these values in `.env`:

| Variable | Purpose |
| --- | --- |
| `PBX_URL` | HTTPS origin of the PBX, without a path or query. |
| `PBX_CLIENT_ID` | API application's DN/client identifier. |
| `PBX_CLIENT_SECRET` | API application's secret. |
| `PBX_TOKEN_FORMAT` | `multipart` by default; use `urlencoded` only if your PBX requires it. |
| `BRIDGE_TOKEN` | Random token authorizing state reads. |
| `BRIDGE_CONTROL_TOKEN` | A different random token authorizing the configured own extension's controls; leave empty to disable controls. |

Generate each bridge token separately with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep `.env`, private configuration, user grants and tokens out of source control. The bridge rejects reuse of the read token as the control token.

## Start with Docker Compose

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail 50
```

The supplied Compose service reads `config.json`, runs as an unprivileged user and stores the optional user grant in the `own-status-grant` named volume. Keep this volume when recreating the service.

The default host binding is `127.0.0.1:8787`. Put an HTTPS reverse proxy in front of it, or set `BRIDGE_BIND_ADDRESS` to an appropriate interface for a proxy on another host. `BRIDGE_BIND_ADDRESS` controls listening access; it does not enable TLS. Use an HTTPS bridge URL for authenticated use across an untrusted network.

`GET /healthz` reports bridge/PBX health without caller details. `GET /v1/state` requires the read Bearer token. Both control endpoints require the separate control token. A healthy HTTP listener alone does not prove that the PBX connection or own-user login is working.

For Portainer, use `portainer-stack.example.yaml` and replace its environment placeholders and inline `BRIDGE_CONFIG_JSON`. That stack uses an image rather than the local build context; choose an image you have built or a published version you trust.

For a Python installation, install `requirements.txt`, export the same environment variables through your service manager, then run this from the repository's `bridge` directory:

```sh
python -m bridge --config ../config.json --host 127.0.0.1 --port 8787
```

Python does not automatically read `.env`. Docker Compose reads it for the supplied stack. A native service must supply its environment explicitly and should set `PBX_USER_TOKEN_FILE` to a private, writable persistent path if using DND.

## Optional confirmed presence and DND

Call Control credentials alone do not provide confirmed own-user presence. To enable DND, supply a separate login for exactly the configured own extension. This is an own-user grant, not an administrator login.

1. Set `PBX_USER_USERNAME` to the configured `own_extension`, and temporarily provide `PBX_USER_PASSWORD`. If that account requires two-factor authentication, also provide a fresh `PBX_USER_SECURITY_CODE`.
2. Start or recreate the bridge promptly. The login must complete while the code is valid. In Docker, `PBX_USER_TOKEN_FILE` already points to `/data/own-user-grant.json` in the persistent volume.
3. Check that `/v1/state` reports a confirmed `own.presence` and that `controls.dnd` becomes available while the own extension is idle. Check locally with an authenticated client; avoid copying caller-bearing responses into public logs.
4. After the grant is saved, remove the temporary password and security code from `.env` or the service environment and recreate the container. Keep the persistent grant volume. The bridge refreshes the saved grant without needing those bootstrap values on every start.

The grant file contains private refresh credentials/cookies bound to the PBX origin and own extension. It is written atomically with owner-only file permissions. Treat a backup of it as a credential. If authentication is revoked or expires, repeat the bootstrap with a fresh code. Do not edit the grant JSON or change its identity binding to another extension.

DND changes are read back from the PBX before being reported as confirmed. `Out of office` is treated as DND and `Available` as available. Unknown or stale presence is shown as unknown; an HTTP acknowledgement alone is not considered confirmation. A user-login failure leaves call monitoring available.

Optional `phonebook_lookup: true` uses the same own-user grant. This provider is initialized when the bridge has a control token; a read-only badge can still omit its own `control_token`. Lookup resolves current own callers and internal peers of active monitored calls; it does not download the whole directory. Explicit configured names take precedence. Leave it disabled if it is not needed.

## Install the badge app

1. Copy `badge/config.example.json` to `badge/config.json`. Leave `demo: true` for the initial check. Demo mode uses synthetic calls and does not contact the PBX or bridge.
2. Copy the **complete contents** of `badge/` into `/apps/threecx_monitor/` on the device using your normal MicroPython file-transfer tool. Preserve subdirectories, including `assets/`. Copy every runtime `.py` file, `metadata.json` and `tildagon.toml`; copying only `app.py` is insufficient.
3. Start **3CX Monitor** from the Apps menu. Check the team overview, caller-ID scenes, settings and idle pages in demo mode.
4. Edit the device's `config.json`: set `demo` to `false`, `bridge_url` to the bridge's HTTPS base URL, and `token` to `BRIDGE_TOKEN`. The base URL has no `/v1/state` suffix. For controls, set `control_token` to `BRIDGE_CONTROL_TOKEN`; leave it empty for a read-only badge.
5. Set `ca_file` to the local DER trust-root certificate used to verify your bridge's HTTPS certificate. A relative path is resolved inside the app directory. Obtain the appropriate root from the issuer or your private CA; a bundled certificate is not automatically correct for another deployment. The server must send its necessary intermediate chain.
6. Ensure Wi-Fi is connected and the device clock is correct, then restart the app. Verify live extension status before using any call or DND button.

The app verifies certificates and the server hostname, rejects redirects, and requires a usable clock for HTTPS. A `TLS CA / FIRMWARE ERROR` calls for checking the certificate file, server chain and firmware TLS support; `SET BADGE CLOCK` calls for correcting the clock. Do not solve either by disabling verification.

When updating, preserve the device's private `config.json`, the appropriate `ca_file`, and any private asset packs. Replace the runtime files together so imports and manifests stay consistent. Stop the running app before replacing its files, then launch it again.

## Controls and appearance

Physical F/B/E/C/D request the five allowlisted targets with or without a keyboard; A opens the menu. DND is selected explicitly in that menu. The app suppresses held/repeated/chord presses. In live mode these buttons perform real PBX actions; opening settings is a useful way to inspect brightness and appearance without issuing a call.

Keyboard shortcuts are `S` for settings, `T` for the theme row and `K` for the clock row. In settings, up/down select a row, left/right adjust it, and Enter, Space or Escape close the page. On the physical buttons, A/D select, B/E adjust and C/F close. Without a keyboard, use A → Menu → Settings, then C to select.

Ring and EEH brightness are independent. Defaults are 15% for the outer ring and 3% for the EEH logo. A live own priority call temporarily uses full brightness. Changes and appearance choices are saved in firmware settings; demo changes are not persisted.

Themes and clock styles are independent. `original` keeps the original appearance. Auto themes use the bridge's London local date: own birthday, partner birthday, anniversary, Christmas, then Easter, in that priority order. Add optional ISO dates only to the private badge configuration's `personal_dates` object using keys `birthday_self`, `birthday_partner` and `anniversary`. Missing dates do not invent an occasion. Christmas can add an Advent page from December 1–24. Private personal dates never belong in a public asset manifest.

Built-in vector themes and the bundled photo work from internal storage. Additional photo packs can be installed on a computer with:

```sh
python tools/install_theme_pack.py --target /path/to/mounted-sd/threecx-themes --ref main
```

The installer accepts assets only from the project's fixed GitHub source, verifies bounded PNG files against the catalog, and stages a managed pack before replacing it. It refuses unrelated nonempty target directories. Point `--target` at the dedicated pack directory, not an SD-card root. The badge checks known mount paths, including `/sdcard_1/threecx-themes`, or explicit `theme_asset_roots`; it does not recursively scan personal files. Missing assets fall back safely. Reopen the app after installing a new pack.

Optional EEH and Liteloop expansion support is deliberately restricted to recognized hardware. Stop another app that owns the same expansion before starting this one. The matrix is an indicator; its decorative animation does not represent a measured heart rate or observed meteor activity.

## Weather and astronomy

Weather is disabled in the bridge example. Enable it in the bridge's `weather` object with your chosen latitude, longitude, a short location label and `timezone: "Europe/London"`. The same service supplies the UTC/local-time metadata used by clocks, automatic themes and astronomy; when it is disabled these pages cannot infer the date. Once enabled, clock metadata remain available even when a forecast fetch fails. Weather uses the authenticated state route and fails independently of call monitoring. The public API receives the configured coordinates and normal request metadata, not caller information. Check the service's current usage terms for your deployment; `WEATHER_API_KEY` selects its paid endpoint when required.

Idle pages rotate immediately when live phone state is quiet. The BLF/speed-dial panel appears when requested with Space or a badge button, or automatically while any teammate has an active call, including connected/held calls. The first button press from an idle page only wakes the panel; it never also dials. Manual wake lasts `idle_seconds` (default60s), then quiet pages resume. When the last teammate call ends, quiet pages return immediately unless a manual wake is still active. Own calls and notifications retain their existing display priority. Left/right browse idle pages. Forecasts become unavailable when stale; a missing rain forecast is not displayed as dry weather.

The panel includes a full-size crowned partner tile, using your configured `partner_name`. Badge D or keyboard D requests the existing `kz` speed dial once the panel is awake. Space explicitly closes the panel even during a stable teammate call; new teammate call activity may wake it again. Destinations remain controlled by the bridge allowlist. `overview_on_demand: false` restores the legacy quiet-delay scheduling if required.

Moon phases are calculated locally and marked approximate. Meteor pages use the bundled calendar, with a typical-season label outside the supported calendar years. Animated streaks are decoration, not observations or a visibility forecast. See [ASTRONOMY.md](ASTRONOMY.md) for sources and limitations.

## Checks and troubleshooting

- **Demo appears instead of live data:** check the device's `config.json`, not the bridge's similarly named file.
- **No live BLFs:** check PBX API permissions, bridge health and API credentials. A stale or disconnected PBX intentionally grays the indicators and hides caller details.
- **Controls disabled:** check that the control token is present and different from the read token, the bridge is live, and the own extension is idle. DND additionally requires fresh confirmed own-user presence.
- **Call outcome unknown:** inspect the phone/PBX before pressing again. The app does not automatically replay a potentially accepted call request.
- **Unexpected classification/name:** check configured DDIs, queues, priority matches and manual contact names. A route can only be identified when the PBX supplies evidence for it.
- **Blank screen or import error after an update:** confirm every runtime module and asset directory was transferred together, and restart the app. Preserve private configuration when reinstalling.

For development checks, install `requirements-dev.txt` and run:

```sh
python tools/run_tests.py
python -m compileall -q badge bridge
```

The tests use synthetic data and local fake servers. They do not place PBX calls or change a live user's DND state.


### Spatial BLF lights (0.16.1)

With four team members, the twelve outer LEDs match the screen quadrants: TB upper-left (10-12), PD upper-right (1-3), JH lower-left (7-9), SM lower-right (4-6). Indices are the one-based hardware LEDs, clockwise from the upper-right. Incoming-call and urgent-notification effects still use the full ring.


### Queue and ring-group names (0.17.0)

Configure `queues` and `ring_groups` as maps from routing extensions to display names in the bridge JSON. The bridge checks referred-by, on-behalf-of and originated-by DNs, and legs sharing the same nonzero call ID. Queue membership alone never classifies a direct call as a queue call. Queue routes take precedence when both are present; both fields are retained. Unknown routes stay unknown rather than being guessed.

Incoming calls show the route name beneath the caller. Connected/held calls retain it in the lower caption. Queue effects are cyan; ring-group effects violet; priority colours override either while preserving the route caption. The PBX must expose routing metadata or a matching call leg to the scoped client.
