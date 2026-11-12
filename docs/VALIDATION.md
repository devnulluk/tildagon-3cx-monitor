# Validation: badge 0.8.0

All **533 automated tests pass**. The automated suite covers bridge transport/authentication, allowlisted call controls, one-shot command outcomes, contact privacy, freshness, idle interruptions, calendar rules, assets, native drawing API arities, clock geometry, partner matching and matrix lifecycle. Tests use reserved numbers and local fake servers, with no live call placement or DND changes.

On the attached physical Spaceagon/Tildagon (MicroPython 1.28.0), all **13 theme faces, seven clock faces and two sky faces** rendered with live bridge state and no render exceptions. The bundled 240×240 photographic PNG loaded through native ctx.image. Source/config/assets were read back after transfer and byte-verified; private credentials and trust root were preserved.

Observed native mean draw times in the bounded sweep were approximately 64–172 ms for themed weather faces and 56–151 ms for the clocks. These are short per-draw samples, rather than a long-term FPS guarantee; display transfer, scheduling, animations and networking add time. The photographic face and Corpus clock are the most expensive scenes.

The physical Liteloop was identified from its exact header at slot 2. A display-only heart fixture completed multiple physical register frames, then returned to live status. Its asynchronous transfer keeps each one-byte I2C operation bounded, checks ownership before every transaction and yields after at most eight successful writes. Same-mode animation waits for a pending frame to finish, while status/brightness changes supersede it. EEH Logo and the keyboard remained initialized throughout, and the user's ring/EEH brightness levels were restored.

The heart test changed only the matrix's display input; it did not alter the bridge snapshot or request a telephone call. A real incoming partner call was not placed during this release's checks. The LCD caller effect and exact-match/stale-state behavior are covered by synthetic renderer/integration tests and the simulator demonstration.

All gallery stills and videos are official SDL/ctx simulator renders of the actual production app. Their fixture clocks, weather, occasions and calls are synthetic. Native device checks establish rendering and matrix register completion; the gallery is not camera footage of the hardware. Decorative meteor streaks are not observations.

A previous private version verified live DND and restored the original state. This release preserves that bridge/control code and adds no PBX credentials, public route or access scope. Long-term office Wi-Fi operation, actual call routing evidence for every DDI/queue and the timing of real partner calls remain deployment-specific checks.
