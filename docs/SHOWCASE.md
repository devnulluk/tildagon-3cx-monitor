# On-device showcase

![Short production-mode preview, official simulator with explicit cuts](gallery/showcase.gif)

[Watch the short video](gallery/showcase.mp4) · [Screenshot contact sheet](gallery/showcase-contact-sheet.png)

This preview makes explicit manual jumps between representative scenes. The
badge's normal tour follows every stage in order and loops without those cuts.

The showcase runs the badge's real renderers with invented data. It walks through
the built-in themes, all eleven clocks, weather and rain conditions, lunar/meteor
pages, Advent, team status, caller-ID variants, notifications, presence and
settings. Every page is labelled **DEMO**. Partner names, example numbers,
locations and occasion dates come from isolated fixtures, not your configuration.

## Start and navigate

Use **A → Menu → Demo tour**, moving with F/B and selecting with C.
Keyboard **G** also starts the isolated tour; settings still offers a DEMO row.
No restart, bridge change or network connection is needed for synthetic scenes.

| Action | Badge buttons | Keyboard |
| --- | --- | --- |
| Start showcase | A → Menu → Demo tour → C | G, or Settings → DEMO → Enter |
| Next / previous scene | B / E | Right / Left |
| Next / previous theme | A / D | Up / Down |
| Pause / resume | C | Space or Enter |
| Leave showcase | F | Escape or G |

These are display-only demo controls, not the normal speed-dial mapping.
Leaving restores your previous view and resumes live monitoring while keeping
the app running. If you entered from settings, that settings view returns.
Buttons held across
that transition must be released before their normal phone-control mapping can
act again. On Spaceagon, joystick left/right steps scenes, up/down changes theme
and centre pauses/resumes. Touch-ring rotation steps scenes. These gestures never
confirm a telephone action.

The sequence groups the demonstrations by theme. Manual scene/theme changes do
not save a new appearance preference. The settings demonstration scrolls through
all six rows without changing or saving their values. The photographic theme and Atelier dial
use the same verified local assets and fallback behavior as normal operation.
Optional EEH and Liteloop displays use their existing drivers when present.

The thirteen built-in themes have **586 stages**: 45 per theme, plus Christmas
Advent. At five seconds per stage, an uninterrupted full loop takes **48 minutes
50 seconds**. It loops continuously; pause, skip a scene or jump to another theme
at any point.

The preview above was recorded with version 0.11's nine-clock, 521-stage tour.
Version 0.12 adds Mondaine and Great British Railways to each theme's clock block;
the [railway clock film](../CLOCKS.md) shows those additions separately.

## Separation from live monitoring

While showcasing, the badge displays synthetic data and **pauses live bridge
polling and phone commands**. Real incoming calls and external notifications are
not monitored during the tour; leave it to resume the desk monitor. The bridge
itself continues operating normally.

Opening the showcase clears an unsent phone intent. If a real call/DND request is
already being sent, entry is refused until that request finishes. Opening a
showcase cannot undo a request that has already been sent.

Theme, clock, brightness, private occasion dates and the original live state are
kept separate and restored on exit. The tour does not save synthetic preferences
or rewrite the private configuration. Restoring an old snapshot does not refresh
its age; the normal stale-data display applies until a new bridge read succeeds.
Late results from a read started before the mode change cannot replace the
showcase or become a fresh snapshot after it closes.

The showcase makes no calls, changes no PBX presence, submits no notification and
performs no contact or weather lookup. Its simulated calls and DND examples are
display-only. It needs no additional PBX permission or credential.

## Development checks

The portable official simulator can run this same production mode:

```powershell
./Launch-Simulator.ps1 -FeatureDemo
```

In that launcher, **G** sends the keyboard demo shortcut (the old Shift+D test
alias is also accepted). Plain PC **A–F** remain simulated physical badge buttons;
their meaning is captured by the active menu/settings/demo view.

`tests/test_showcase_integration.py` exercises the real app with fake hardware and
network work. It checks pending/in-flight command boundaries, delayed fetch
success and failure, preference isolation, button release gating and returning to
the original live controller. The pure scene-generator tests cover the sequence
and its synthetic fixtures. Native-device results retain their own version scope
in [validation](VALIDATION.md).
