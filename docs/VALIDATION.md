# Validation: badge 0.12.1 / bridge 0.6.0

## Version 0.12.1 automatic clock recovery

All 696 tests passed in 70.545 seconds. Clock-policy tests cover reconnects, retry cooldown, NTP failure, invalid results and loss of a previously valid clock. The native test reset the RTC to 2000 immediately before app launch, without a host time-setting command afterward. Version 0.12.1 restored the year to 2026 through NTP and resumed authenticated live state and fresh weather. Demo was off, the app focused, keyboard/EEH ready and brightness preserved. USB was detached cleanly afterward. This tests clock recovery on one physical badge; it does not guarantee access to NTP on every network.

## Version 0.12 railway clocks

All **691 automated tests passed in 68.584 seconds**. The new checks verify
Mondaine's 58-second sweep, two-second dwell and stepped minute; GBR's opposed
arrows and half-minute meetings; native path/primitive bounds; invalid and
fractional time; saved display preferences; and interruption by calls or an
unavailable source. Both faces appear in every theme's isolated demo without
saving synthetic preferences or submitting telephone commands.

The expanded showcase has **547 stages** across thirteen themes and eleven
clocks: 42 stages per theme plus Christmas Advent, including **143 theme/clock
pairs**. Its default uninterrupted loop is **45 minutes 35 seconds**. Automated
checks traverse every stage; this is not a claim of a new full-duration native
tour.

The official SDL/ctx [railway film](../CLOCKS.md) contains **421 actual captured
frames over 28.004306 seconds**. The MP4 fully decodes; the complete GIF contains
280 frames over 28 seconds. All 28 recorded runtime/asset hashes match the frozen
capture source. Native-LCD crops and full-window stills were visually reviewed.
Actual Mondaine dial pixels at 10:08:58 and 10:08:59 are identical, then change
at 10:09:00 when the minute hand advances. The GBR segment explicitly cuts its
synthetic clock to 10:09:22 and shows the arrows meeting at 10:09:30; frames on
either side were checked. These are synthetic simulator time
fixtures, not camera footage or a physical hardware frame-rate measurement.

The **28-file runtime update was read back and byte-verified** on the physical
Spaceagon, preserving its private configuration and TLS trust root. A native
display-only probe then rendered **66 tour stages and 18 injected time-boundary
cases**, covering both railway faces in all thirteen themes and the original
theme's full feature block. It completed **168 native frames over 40 seconds**,
with zero render errors or missing cases. The boundaries include 58/59/00,
29/30, midnight and unavailable time.

During that synthetic probe there were zero telephone write attempts and zero
new bridge reads. Exit restored the original configuration, controller and
appearance, and live monitoring resumed. Keyboard, Spaceagon inputs, EEH Logo
and matrix were ready throughout the final report. These are accelerated
coverage checks, not a 45-minute endurance run or proof of a real incoming call.
Heap snapshots were 1,329,888 bytes before and 1,145,072 afterward, with a sampled
uncollected minimum of 370,960; they do not establish long-term memory stability.

A separate clean startup left **Mondaine selected and saved**, with live
monitoring active and demo mode off. The clock preview was visible, the app was
focused, all attached inputs/displays were ready, and the saved ring/EEH levels
remained 15% and 3%. The USB session was released cleanly after this report.

## Previous automated and simulator checks: version 0.11

All **680 automated tests pass**. The full suite completed in 70.407 seconds.
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

The showcase checks traverse all **521 stages** through the actual app with a
test canvas: thirteen themes, all nine clocks per theme and every feature kind.
Every stage verifies its actual view contents as well as the DEMO footer and
synthetic data: detail names/numbers, presence colours, grid initials, settings,
notification bodies/progress and the expected weather/clock/sky/call readouts.
Phone-detail and presence cues cannot silently fall back to idle weather. The
progress readout is geometrically separate from the showcase footer; the timed
settings scene exposes all five rows without writes. Integration checks cover
four delayed live-read success/failure races across entry and exit, paused network
work, unsent/in-flight phone commands, held-button release, preference and private
date isolation, and returning to the previous view. An old physical C hold cannot
replay a DND confirmation after the tour. The old state transport is closed at
entry and a fresh client is retained for resuming monitoring. Ordinary caller
types remain distinct from the partner celebration. These are automated checks,
not camera evidence.

The 0.11 official-simulator preview contains **811 real captured frames over
56.014952 seconds**. Its 56.00-second MP4 fully decodes, and the complete GIF has
560 frames over 56 seconds. All 27 recorded runtime/asset hashes match the frozen
source. It uses production showcase navigation to select sixteen representative
stages, with explicit **CUT** labels; it does not depict the full 521-stage loop
or speed up its animation. Native-LCD stills were checked for the internal
245/Alex detail, External-only detail, magenta own status and the full 75% readout.
The partner still was captured separately through the same production showcase.

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

## Native badge 0.11.0

The final frozen source passed **all 521 native stages** on the physical
Spaceagon: thirteen themes, 40 stages each plus Christmas Advent, including all
117 theme/clock pairs. The accelerated seek probe rendered **1,042 native frames
over 242 seconds**, with no render errors or missing stages. This checks every
stage; it is not an uninterrupted 43-minute tour or a hardware FPS measurement.

During the demo there were **zero new bridge reads and zero phone-control
attempts**. The maximum observed ring channel was 38, within the configured demo
cap of 38. The Liteloop completed 39 display frames. The app stayed focused with
Spaceagon inputs, keyboard, EEH Logo and matrix ready.

Exit restored the original configuration/controller objects and appearance
settings, then live monitoring resumed with demo mode false. Free-heap snapshots
were 966,768 bytes before, 1,225,456 afterward and a sampled minimum of 399,424.
Those measurements do not establish long-term memory stability. No real incoming
call was placed and no PBX presence was changed for this display-only check.
Earlier physical appearance and notification checks below retain their original
version scope.

## Previous native validation: badge 0.10.0

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
