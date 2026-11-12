# Validation: badge 0.10.0 / bridge 0.6.0

## Automated and simulator checks

All **638 automated tests pass**. The full suite completed in 71.462 seconds.
It covers bridge transport/authentication, allowlisted phone controls, one-shot
command outcomes, contact privacy, freshness, idle interruptions, calendar rules,
assets, native drawing API arities, clock geometry, partner matching and matrix
lifecycle. This version adds notification expiry/deduplication, bearer-role
separation, bounded ntfy stream/reconnect handling, call preemption and canonical
Spaceagon input filtering. Clock checks cover all nine styles, native drawing
arities and primitive budgets, readable time, honest unknown states, lunar
orientation, bitmap validation/failure fallback, saved settings and immediate
interruption by incoming/connected calls or an offline source. A light-theme
regression checks bright status chrome over the full-frame Atelier artwork.
Tests use reserved numbers and local fake services; they do not place live calls
or change DND.

The 0.10 celestial-clock simulator tour contains **322 actual captured frames**
over 28.050923 seconds. The MP4 is 28.07 seconds and fully decodes; the complete
GIF has 281 frames over 28.1 seconds. All 26 runtime/asset hashes match the frozen
source. Canonical stills include the actual 240x240 LCD pixels and are identical
to their corresponding captured midpoint frames. The contact sheet, native
stills and full-window captures were inspected for clipping and text overlap.

The production 0.9 app rendered information, success, warning, failure and progress
notifications in the official SDL/ctx simulator. The 32-second tour contains 471
captured frames and a 320-frame GIF. It demonstrates a same-ID 25%→75% progress
update, 60 frames where a priority call hides the notification, and 59 frames where
the waiting notification appears after the call. The MP4 fully decodes, and the
recorded badge-source hashes matched the source used for these checks.

The portable launcher also rendered a progress notification from its separate
pinned firmware cache. Captures wait for the app after the firmware boot overlay.
Gallery text, clocks, weather, occasions and calls are synthetic. These recordings
are not camera footage or physical badge frame-rate measurements.

## Real Apprise compatibility

The real [Apprise 2.2.0 CLI](https://pypi.org/project/apprise/2.2.0/) passed nine
checks against the unmodified production HTTP receiver on loopback HTTPS, with
a generated CA explicitly trusted and certificate verification enabled. The
documented `jsons://` URL and `+Authorization=Bearer%20...` header option worked
without changes. All four message types and custom `style`/`icon` additions returned
202; an exact duplicate returned 200. Read/control-role tokens each returned 401,
and an untrusted certificate failed before any HTTP request reached the receiver.

Apprise emitted `version`, `title`, `message`, `type` and `attachments: []`. The
authenticated state response contained exactly five accepted alerts with the
expected types, styles and icons. All content and credentials were synthetic;
no external notification service or PBX was contacted. This validates the sender
format and local receiver, not deployed public-webhook activation or delivery.

## Bridge 0.6.0 live checks

Read-only checks after the bridge update confirmed a healthy service, verified
HTTPS state access, four configured team BLFs and confirmed own-user presence.
Existing call-control configuration and the persisted own-user grant were
preserved. No new PBX access scope was added for notifications.

**External notification delivery was not activated in this checked deployment.**
The dedicated `NOTIFY_TOKEN` and public `/v1/notify` ingress remain a separate
deployment step. There is no claim of a live Apprise or ntfy end-to-end delivery
test. See [notification setup](NOTIFICATIONS.md).

## Native badge 0.10.0

The 26-file runtime update was read back and byte-verified on the physical
Spaceagon. Private configuration and the TLS trust root were preserved. The
63,973-byte Atelier PNG was also read back and its SHA256 verified.

The focused app remained in live mode with the artwork, Spaceagon inputs,
keyboard, EEH Logo and Liteloop matrix available. Four display cases completed
without render errors:

| Display case | Frames in the bounded sample | Mean clock draw time |
| --- | ---: | ---: |
| Celestial Atelier | 14 | 179.87 ms |
| Neon Orrery | 17 | 144.49 ms |
| Atelier with a light Kitty theme | 14 | 178.72 ms |
| Forced Atelier vector fallback | 20 | 93.60 ms |

Each sample ran for four seconds. The first Atelier case made 15 native image
calls including its settling draw; Neon Orrery made none. Free heap measured
454,672 bytes at the probe snapshot. These are short clock-drawing measurements,
not a sustained FPS guarantee: display transfer, scheduling, animation and
networking add time.

There were **zero phone-control attempts**. The probe used only display changes
and existing live PBX reads, then restored the previous style and theme. It did
not place a real call or change DND. The earlier native notification and
appearance checks below retain their original version scope.

## Previous native validation: badge 0.9.0

The 23-file badge update was read back and byte-verified. Private configuration
and the TLS trust root were preserved. On the physical Spaceagon, the focused
app remained in live mode with the keyboard, EEH Logo and Liteloop matrix present.

The notification probe rendered these synthetic display cases:

| Case | Native frames |
| --- | ---: |
| Information card | 21 |
| Success badge | 22 |
| Warning toast | 21 |
| Failure card | 22 |
| Progress 25% | 22 |
| Same-ID progress 75% | 21 |

There were **no render errors and zero phone-control attempts**. Alerts were
inserted only into display memory; the phone-command sender was temporarily
blocked for the probe. Caller data was not changed, and the original empty
notification state was restored afterward.

These are rendering and device-presence checks, not a physical joystick/touch
gesture test or an end-to-end external notification test. Input-event filtering
and display-only behavior are covered by the automated suite. The older theme,
clock and matrix sweep below remains separately identified as 0.8.0 evidence.

## Previous native validation: badge 0.8.0

On the attached physical Spaceagon/Tildagon running MicroPython 1.28.0, all 13 theme
faces, seven clock faces and two sky faces rendered with live bridge state and no
render exceptions. The bundled 240×240 photographic PNG loaded through native
`ctx.image`. Source/config/assets were read back after transfer and byte-verified;
private credentials and the trust root were preserved.

The bounded sweep observed native mean draw times of approximately 64–172 ms for
themed weather faces and 56–151 ms for clocks. These short per-draw samples are not
a long-term FPS guarantee: display transfer, scheduling, animation and networking
add time. The photographic face and Corpus clock were the most expensive scenes.

The physical Liteloop was identified from its exact header. A display-only heart
fixture completed physical register frames and returned to live status. Transfers
used bounded one-byte I2C operations, checked ownership before writes and yielded
between batches. EEH Logo and the keyboard remained initialized, and ring/EEH
brightness levels were restored.

That heart fixture changed only matrix display input; it did not alter bridge
state or request a call. A real incoming partner call was not placed during those
checks. Caller decoration and exact-match/stale behavior were covered by synthetic
renderer/integration checks. Decorative meteor streaks are not observations.

A previous private version verified live DND and restored the original state.
Long-term office Wi-Fi operation, real routing evidence for every DDI/queue and
real partner-call timing remain deployment-specific checks.
