# Brief offline flicker investigation

On 17 November 2026, a live badge observation reproduced four stale call-data samples in 80 observations, despite zero Wi-Fi losses and zero failed requests. A separate 80-request check of the bridge saw no disconnections or errors; source age remained under two seconds. The badge was spending enough time between requests that source age plus time since receipt occasionally crossed its five-second freshness limit.

The update combines state and optional peer-presence reads into one native worker round, bounds the local presence read to 600 ms, and schedules the next poll from the start of the round instead of adding a full sleep after it. Call data is accepted with the actual worker receive timestamp, so time waiting for the UI scheduler is not counted as fresh. A presence-read failure does not discard a valid call snapshot, and a bridge failure does not discard a valid presence result.

Phone/clock mode keeps the clock on screen during brief refresh delays. Calls, caller details, ringing LEDs and call controls retain their existing five-second freshness checks. A sustained outage shows CALL DATA OFFLINE on the clock; a bridge-reported disconnection shows it immediately. Other standalone app roles keep their existing offline presentation.

The installation preserved private configuration and the HTTPS trust root. All 775 regression tests pass, including tests for the independent failure paths and clock continuity without reviving stale call data. Post-install hardware observation is recorded separately in the validation report.

Post-install: 78 native observations, zero stale samples, zero Wi-Fi losses and zero request failures. The baseline contained four stale samples in 80 observations. The five-second call freshness limit is unchanged.
