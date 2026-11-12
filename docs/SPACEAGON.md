# Spaceagon controls

Badge 0.9 adds navigation through the running 2026 Spaceagon frontboard's standard
joystick and capacitive touch-ring events. The round LCD is not a touchscreen.
The app uses the existing frontboard driver; it does not scan I2C, configure a
sensor, change port power or replace firmware.

## Navigation

| View | Joystick | Capacitive touch ring |
| --- | --- | --- |
| Monitoring | Left/up selects the previous teammate; right/down selects the next. Centre opens or closes a detail view. | A deliberate tap selects a teammate by its position around the ring. Rotation moves the selection. |
| Idle pages | Left/up and right/down browse pages. Centre returns to the monitoring view. | Rotation browses the idle pages. |
| Settings | Up/down selects a row; left/right changes its value; centre finishes settings. | Touch gestures do not change settings. |
| Open notifications | Directions browse; centre dismisses the current notification. | Rotation browses notifications. A touch-ring tap does not dismiss them. |

Touch rotation requires deliberate movement across neighbouring pads. Short taps
are distinguished from rotation, and simultaneous contacts, implausibly quick
jumps and buttons already held when the view changes are filtered. Incoming or
active phone attention takes precedence over this navigation.

These inputs are **display controls only**. They never request a call, toggle DND
or act as consent for a phone-control request. Phone actions retain the existing
dedicated physical-button/keyboard-expansion flow and separate bridge control
token. Notification dismissal is local to the badge and executes no remote action.

With an attached keyboard, **N** opens the inbox. Arrows browse, **Enter** dismisses
the current item, and **Space/Escape** returns. In the inbox, physical **B/E** browse,
**C** dismisses and **F** returns. See the
[notification guide](NOTIFICATIONS.md) for sender setup and animated examples.

## Optional inputs

The default configuration enables `space_joystick` and `space_touch`.
`space_tilt` and `space_proximity` are **false by default**. They are not required
for phone monitoring, notifications or the themes.

If explicitly enabled, a deliberate proximity wave moves the display focus; it
still cannot request a call or change DND. Optional tilt reads the firmware's
cached accelerometer sample as relative motion. It rejects absent/implausible
samples and loses validity safely. It does not initiate a sensor transaction or
calibrate hardware. Focus changes suppress held gestures before navigation resumes.

The mappings follow the official
[Spaceagon frontboard](https://github.com/emfcamp/badge-2024-software/blob/main/modules/frontboards/twentysix.py)
and [Spaceagon example](https://github.com/emfcamp/badge-2026-apps-spaceagon-test).
Older Tildagon frontboards retain their existing physical/keyboard controls.

## Simulator

The official simulator gallery uses synthetic data and the real application
renderer. Its keyboard **N** opens the same inbox. The upstream board artwork is
not a physical Spaceagon photograph, and a simulated picture is not evidence of
touch, joystick, proximity or tilt behavior on a particular device. Native checks
are recorded separately with their version scope in [validation](VALIDATION.md).
