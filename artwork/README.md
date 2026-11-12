# Photographic theme artwork

## Celestial Atelier clock dial

The [original dial artwork](celestial-atelier-source.png) was generated with the
built-in OpenAI image-generation tool using the [complete prompt](celestial-atelier-prompt.txt).
The runtime [dial plate](../badge/assets/clocks/atelier-dial.png) is a 240x240 RGB PNG,
63,973 bytes. Production processing only resized the source to 216x216 and placed
it centrally in a 240x240 navy canvas so the bezel fits the circular LCD and leaves
room for the badge's status chrome. No time, date or moon phase is baked into it.
Those complications are drawn live. The original and runtime asset are included
under this project's MIT licence. This is an original interpretation of celestial
watchmaking materials, without a watch manufacturer's logo or copied dial.

## Alpine landscape

Generated with the built-in OpenAI image-generation tool. The [original bitmap](alpine-dawn-source.png) is included for editing. The [runtime asset](../badge/assets/photo/alpine-dawn.png) is resized to 240×240 RGB without creative edits; it is 74,053 bytes and needs no SD card.

Generation prompt:

> Photorealistic natural landscape background for a240px circular weather display: still alpine lake, forested mountains atbluehour, softmist, restrained warmdawnlight; horizonupperthird and quietdarkwater center/lower for softwaretext; nopeople/buildings/UI/text/logos; fullbleed square.

The badge's native ctx.image function draws the verified runtime PNG. Source and thumbnail are included with the project's artwork; no remote image request happens while rendering.
