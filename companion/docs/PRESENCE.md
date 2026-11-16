# iPhone presence and quiet ringing

Spaceport can recognise one enrolled iPhone over Bluetooth and gate its speaker locally. No Home Assistant, phone app or cloud location service is required. All automatic sounds, including priority calls, are quiet while the phone is absent. When away, Waveshare dims its display and shows a simple lock screen. A linked Spaceagon also hides call details behind an idle lock screen, uses a gentle two-minute rainbow cycle on ring LEDs (3% by default, respecting their saved brightness ceilings) and shows a static AWAY on its matrix. Priority calls and urgent notifications do not override the away display. The EEH logo is off while away. Returning nearby restores the saved normal brightness settings.

## Pair

Open the authenticated Spaceport control page on your LAN. Select **Only ring nearby**, then **Pair iPhone (2 minutes)**. On the iPhone, open **Settings â†’ Bluetooth â†’ Spaceport Presence** and accept pairing. Spaceport briefly presents an encrypted Heart Rate service solely to obtain the Bluetooth identity key; it does not read health data. After enrolment it disconnects and passively recognises the phone's changing private Bluetooth addresses. Pairing is advertised only during the explicit two-minute window.

The identity key and bond remain in device NVS, never in the public repository, bridge or status response. **Forget phone** removes both. Forget the accessory on the iPhone too before re-pairing. Flash backups can contain credentials and identity keys: keep them private.

## Behaviour and calibration

Detection starts quiet after every reboot. A matching signal at or above âˆ’72 dBm enables audio; an 8 dB hysteresis band helps avoid rapid switching. After 60 seconds without a qualifying signal, audio becomes quiet. These defaults are adjustable on the local page. A stronger threshold (for example âˆ’60 dBm) restricts the area; a weaker threshold expands it. Bluetooth signal strength is an approximation, not a room boundary. Existing mute/silence controls still apply. Test sound and diagnostic tones obey the same presence gate.

Check with your phone on the desk, locked for several minutes, then walk away and return. Trigger a new notification or incoming call at each stage. Some iPhones advertise irregularly while locked, so presence may time out even while you are nearby. This feature deliberately fails quiet; it is not guaranteed occupancy detection. Apple Watch/Handoff activity can improve advertising frequency, as described in [ESPresense's Apple guidance](https://espresense.com/apple/).

Initial firmware validation covers compilation, gate policy checks, BLE pairing-window startup and quiet output before enrolment. The user has paired their iPhone, matched advertisements have been detected, and a test chime generated nonzero audio only after detection. Locked-screen behaviour, address rotation over time and range still require physical verification.


## Spaceagon link and testing

Both devices must be able to reach each other on the same LAN. Spaceagon reads GET /v1/presence on Waveshare every three seconds using a separate read-only bearer token. This LAN-only HTTP endpoint returns presence booleans, timeout and signal strength; it cannot control calls, change settings or reveal the phone identity key. Its token is separate from the Waveshare administrator password and all PBX/notification keys. Store the URL and token only in private badge config as `presence_url` and `presence_token`; empty values disable linking. Authenticated Waveshare administrators can retrieve the link at /presence-link. Do not expose either LAN route publicly.

A linked badge starts locked until it has a valid response. A response older than 15 seconds shows PRESENCE OFFLINE and stays locked. Disabling presence in Waveshare's authenticated controls restores the ordinary badge display after its next successful poll. Inputs are ignored while locked; holding a key across the transition cannot initiate a call.

Test with Bluetooth enabled and the paired iPhone locked beside the devices. Confirm normal screens and a short test chime. Take the phone away for at least 90 seconds: Waveshare should be silent with a dim lock screen, and Spaceagon should lock, show a gentle rainbow on the ring LEDs and blank the matrix. Trigger a new notification to check that it does not wake the displays. Return and confirm the original screens and brightness resume. If the phone is still detected from the next room, increase the threshold (e.g. from -72 to -62 dBm) and repeat; signal strength is not a reliable room boundary. Do not use the iPhone Control Centre Bluetooth toggle for a range test.
