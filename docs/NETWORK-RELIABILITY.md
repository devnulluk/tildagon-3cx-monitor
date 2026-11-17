# Brief offline flicker investigation

On 17 November 2026, a live badge observation reproduced four stale call-data samples in 80 observations, despite zero Wi-Fi losses and zero failed requests. A separate 80-request bridge check saw no disconnections or errors. Source age plus time between badge refreshes occasionally exceeded the five-second safety cutoff.

The final update retains separate native workers for presence and state, and schedules polling from the start of each round instead of adding a full sleep after it. It disables Wi-Fi modem power saving where supported, using MicroPython WLAN.PM_NONE. The measured badge signal was -74 to -76 dBm. The local presence timeout remains 1.5 seconds: an observed successful local request took 664 ms.

An earlier combined-worker implementation passed an instrumented observation but failed a subsequent ordinary startup. It was reverted before the final installation. Its zero-stale result must not be interpreted as validation of the final implementation.

Phone/clock mode keeps the clock visible during brief refresh delays. Calls, caller details, ringing LEDs and call controls retain their five-second freshness checks. Sustained outages show CALL DATA OFFLINE on the clock; a bridge-reported disconnection shows it immediately. Brief stale samples can still occur on the observed weak Wi-Fi connection; the update prevents those from replacing the clock with the large offline screen.

Installation byte verification confirmed private configuration and HTTPS trust root were preserved. See the validation JSON for final native observations and regression results.

Final regression run: 773 tests passed. A clean launcher restart confirmed version 0.23.0 live, focused, with fresh weather and demo disabled. The final 32-sample native observation had zero Wi-Fi losses or reported errors, two brief stale samples, and fresh presence in all samples.

Wi-Fi configuration reference: https://docs.micropython.org/en/latest/library/network.WLAN.html
