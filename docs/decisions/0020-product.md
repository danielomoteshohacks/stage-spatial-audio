# 0020. The product: brand, screens, the stage view, Feel, and head tracking left out

- Status: accepted
- Date: 2026-11-24

## Decision

- **Brand** (`web/BRAND.md`, `web/src/styles/tokens.css`): the orange-on-black bench look is gone.
  Night ink #08090D, frosted-glass surfaces with a top hairline, Lagoon #1FC8B4 and Coral
  #FF7A5C from a Lagos lagoon at sunset, Ivory #F4F1EA text; WCAG contrast computed for every
  text colour (lowest 5.7:1). Instrument Sans and Instrument Serif (OFL 1.1, Latin subset,
  self-hosted). A stage-arc logo of concentric sound fronts and one 24 px, 1.75 px-stroke icon set.
- **Screens**: Home (hero, drop zone, renders kept on this phone in IndexedDB so replaying uses
  no data); Now Playing as a full-screen sheet over a mini player, with the cover art read from
  the file's own tags (`lib/artwork.ts`: ID3v2 APIC/PIC including WAV "id3 " chunks, FLAC PICTURE,
  MP4 covr; no library), a blurred backdrop and accent colours taken from the art (`lib/palette.ts`,
  lazy, lifted to 4.5:1 on ink), the morphing Original/Spatial switch (still the sample-locked
  30 ms cross-fade), the waveform scrubber with loop, Space, Character, Motion and Genre (applied
  through /rerender, no upload), per-part solo and mute, the guard badge with its reasons, and
  downloads (spatial FLAC, plan.json, the 7.1.4 WAV when made).
- **Stage view** (lazy chunk): every plan object around the listener's head, moving with the
  playhead by the backend's own formulas and pulsing with its object stem's level; bed objects
  are drawn as rings because they surround the listener. Unlocked objects can be dragged (azimuth
  and distance) or raised; "Re-render with this stage" sends the edited plan to /rerender.
  Protected objects (lead vocal, bass, kit) are shown as locked.
- **Feel**: navigator.vibrate pulses on the kick and sub-bass onsets of the low-end object, synced
  to the playhead, with an intensity control; hidden where the Vibration API is missing (iOS).
- **Platform**: Media Session metadata and controls with the artwork, an installable PWA
  (manifest, maskable icons, a service worker that is network-first for pages and never touches
  the rendering server), keyboard control (Space, S, arrows, [ ], L), reduced-motion support,
  dialogs on native `<dialog>` for focus handling.
- **Blind test** (lazy chunk, Phase 6 item 28): original, v2 and optionally v1 under random
  letters, loudness-matched by turning down, ranking plus "most outside my head" and "most
  natural", kept in this browser and exported as CSV.

## Head tracking: designed, not shipped

The design (from decision 0008, adapted): on request only, lazy-load MediaPipe Face Landmarker
(Apache-2.0) and estimate yaw from the face's landmarks with the front camera; the server would
render the scene at a few head yaws (for example -60, -30, 0, 30, 60 degrees, each a rotation of
every object and the bed), and the browser would cross-fade between the two renders nearest the
measured yaw with an equal-power fade and a smoothing filter on the yaw. The UI would say that it
works best with the phone propped up facing you. It is left out of this pass: it multiplies the
server's render time by the number of yaws, the camera loop's cost and latency on a Galaxy S21 FE
cannot be measured from this session, and a tracker that lags or jitters is worse than none.

## Measured

| Check | Result |
|---|---|
| First load, gzipped, fonts included (`npm run size`) | 127 KB (budget 250 KB); stage view 3.4 KB, blind test 2.9 KB and palette 1.1 KB load lazily |
| Lighthouse 12.8.2, mobile emulation, production build | performance 0.97, accessibility 1.00, best practices 1.00 (CI fails under 0.90) |
| End to end in Chromium at 412 x 915 against a local backend | upload, live progress, render, decode, artwork from FLAC PICTURE, palette, play, switch, stage view: working (screenshots in the log) |
| Web unit tests | 26 passing, including the three tag parsers on hand-built tags |

Not tested on a real Galaxy S21 FE from this session; that is the next check.
