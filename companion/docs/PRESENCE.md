# iPhone presence and quiet ringing

Spaceport can recognise one enrolled iPhone over Bluetooth and gate its speaker locally. No Home Assistant, phone app or cloud location service is required. All automatic sounds, including priority calls, are quiet while the phone is absent. Displays and Spaceagon LEDs continue normally.

## Pair

Open the authenticated Spaceport control page on your LAN. Select **Only ring nearby**, then **Pair iPhone (2 minutes)**. On the iPhone, open **Settings → Bluetooth → Spaceport Presence** and accept pairing. Spaceport briefly presents an encrypted Heart Rate service solely to obtain the Bluetooth identity key; it does not read health data. After enrolment it disconnects and passively recognises the phone's changing private Bluetooth addresses. Pairing is advertised only during the explicit two-minute window.

The identity key and bond remain in device NVS, never in the public repository, bridge or status response. **Forget phone** removes both. Forget the accessory on the iPhone too before re-pairing. Flash backups can contain credentials and identity keys: keep them private.

## Behaviour and calibration

Detection starts quiet after every reboot. A matching signal at or above −72 dBm enables audio; an 8 dB hysteresis band helps avoid rapid switching. After 60 seconds without a qualifying signal, audio becomes quiet. These defaults are adjustable on the local page. A stronger threshold (for example −60 dBm) restricts the area; a weaker threshold expands it. Bluetooth signal strength is an approximation, not a room boundary. Existing mute/silence controls still apply. Test sound and diagnostic tones obey the same presence gate.

Check with your phone on the desk, locked for several minutes, then walk away and return. Trigger a new notification or incoming call at each stage. Some iPhones advertise irregularly while locked, so presence may time out even while you are nearby. This feature deliberately fails quiet; it is not guaranteed occupancy detection. Apple Watch/Handoff activity can improve advertising frequency, as described in [ESPresense's Apple guidance](https://espresense.com/apple/).

Initial firmware validation covers compilation, gate policy checks, BLE pairing-window startup and quiet output before enrolment. Actual phone enrolment, rotating-address recognition, locked-screen behaviour and range still require physical verification with the user's phone.
