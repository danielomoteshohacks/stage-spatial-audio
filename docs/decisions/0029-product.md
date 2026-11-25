# 0029. The v3 product: light by default, one glossy object, a stream you can start at once

- Status: accepted
- Date: 2026-11-25

## Decision

**Light default, dark equal.** The page opens in light unless the system asks for dark; the listener
can force either. The theme is set on `<html data-theme>` before first paint (an inline script in
`index.html`), so there is no flash. Both themes are checked by Lighthouse and by the screenshot
script; neither is derived at runtime from the other.

**Information architecture.** Five destinations: Home (continue, shelves), Browse (search across
the whole catalogue, genres), Library (renders the listener saved on this device), Create (bring
your own song, with options), Credits (licences, appearance, backend address, calibration). A
bottom tab bar of five on phones (Credits is the fifth, because the licence credits and the
appearance setting must be reachable on a phone; they were not in the first build), a left rail
from 900 px. A mini player stays above the tab bar; the full
player is a sheet.

**One glossy object.** The play button is the only glossy, coloured-shadow element; cards are
matte, overlays translucent (web/BRAND.md). The aim is Spotify-like clarity of hierarchy without
copying its green or its density.

**Playback follows the stream.** Opening a catalogue track starts a v3 job and fetches the original
at once. The player plays the original while segments arrive and switches to Spatial when the first
rendered segment is contiguous with the playhead, then follows the stream with a buffering state
if the render falls behind (`StreamPlayer`, sample-locked A/B). The pill shows Spatial only when the
spatial side is actually playing.

**Local only.** The library, the calibrated head and the backend address live in IndexedDB or
localStorage in the listener's browser; nothing about a listener leaves it. Saved renders keep
their licence line.

**Installable.** Web manifest and Media Session (title, artist, artwork, play, pause, seek).
Accessibility: every control reachable by keyboard, labelled, 44 px targets, visible focus,
contrast of at least 4.5:1, reduced motion honoured.

## Evidence

- Lighthouse mobile, median of 3: performance 0.98 light and 0.99 dark; accessibility 1.00;
  best practices 0.96 (`web/scripts/lighthouse.mjs`).
- Mid-range Android profile (4x CPU, slow 4G): FCP 456 ms, LCP 732 ms, TBT 52 ms, 105 KB.
- Screenshots of every screen in both themes, phone and desktop, are in `docs/screens/` (52 images),
  produced by `web/e2e/screens.mjs` against a mock backend that replays real renderer output.
- 47 unit tests cover the stream scheduler (segment starts, gaps, trimming), scene geometry,
  calibration scoring and the theme helpers.

## Tags

- Theme, tokens, layout: ESTABLISHED (standard CSS, WCAG 2.1 contrast arithmetic).
- Switching A/B when the first contiguous segment lands, rather than waiting for a fixed buffer:
  SPECULATIVE. It is measured for scheduling correctness, not yet for what listeners prefer.

## Not done

The service worker caches the app shell only; offline replay of saved renders works from
IndexedDB but a first visit still needs the network. A real-device mobile test was not possible
here; the profile above is an emulated one and is labelled as such.
