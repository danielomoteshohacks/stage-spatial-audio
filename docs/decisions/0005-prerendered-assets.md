# 0005. Pre-rendered spatial assets first

- Status: accepted

## Context
Spatial renders can be produced offline and stored, or rendered on the device from stems.

## Decision
Start with pre-rendered stereo FLAC per mode (Option A). Keep the design open to stems plus
placement data rendered on the device later (Option B).

## Consequences
No new playback code on the phone and lossless quality stays simple. Storage grows with the number
of modes, controlled by opt-in, deduplication and tiering.

## Alternatives considered
Render every mode eagerly; render only on the device.
