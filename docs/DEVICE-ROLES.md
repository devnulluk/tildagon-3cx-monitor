# Two-device layout

Spaceagon 0.18.0 keeps 3CX call screens, BLF/speed dials, DND, caller animations, matrix call details and clock faces. Its idle rotation is clock-only when `"device_role": "phone_clock"` is set in its private `badge/config.json`. The public example includes that setting. The historical manual showcase remains available; its synthetic scenes do not change live role settings.

Waveshare Spaceport 0.2.0 shows weather, rain, approximate Moon phase, seasonal meteor activity, December Advent and rich notifications. It still plays 3CX ringtones, but caller/crew/clock screens are removed from the live dashboard. Urgent notifications remain visible during calls; ringing takes audio precedence.

Both independently read the existing protected `/v1/state`. Spaceagon uses those same notification entries for ring LEDs and urgent EEH red breathing without opening an inbox or interrupting clock/call screens. Priority phone calls override notification lighting. The matrix retains its phone/clock duties.

Normal notification lights animate briefly. Urgent lighting lasts for the shared item lifetime. Acknowledgement on Waveshare is local and does not clear Spaceagon LEDs; they follow bridge expiry or sender updates. No new server endpoint or public permission is required.

Source and firmware builds are verified, including 748 badge/bridge tests and the companion native engine/protocol checks. Neither split-role image has been physically installed: the Spaceagon is disconnected from USB, and the ordered Waveshare has not arrived. Before installing the badge update, back up its existing private config and add only `device_role`; preserve tokens, CA, brightness, contacts and dates. Use a normal badge file update, not the Waveshare factory flasher.

See [Spaceport setup, previews and sound](../companion/README.md).
