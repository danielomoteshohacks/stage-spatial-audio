# web

The browser side of Stage: TypeScript, Svelte 5 and Vite, tested with Vitest.

Status: **shell only.** The page plays a pair of files that were already rendered offline in Python;
it does not render anything itself. The planned in-browser engine (the Rust core compiled to
WebAssembly inside an audio worklet, slices 2, 4 and 5) is not built yet, and the page says so.
Budget: first load at most 500 KB compressed (currently about 25 KB).

## What works

- Load the two files that `scripts/render_clip.py` writes, `input_stereo.wav` (original) and
  `input_stage.wav` (Stage render), by dropping them on the page or with the file picker. Names
  containing `stage` are taken as the render; if the names do not decide, drop order is used and a
  Swap button appears.
- Both files are decoded with the Web Audio API and play from the same context time and offset.
  The A/B switch only moves two gains with a 20 ms linear crossfade, so it cannot change the
  playback position. Play, pause and seek use 5 ms fades so they do not click either.
- Waveform, time, play/pause, seek slider, and a session-only library of loaded pairs.
- Keyboard: Space or K play/pause, A original, B Stage, X switch, Left/Right seek 5 s.

Nothing is uploaded: files are read and decoded in the browser.

## Run it

```bash
cd web
npm ci
npm run dev       # http://localhost:5173
npm run lint      # eslint and svelte-check
npm test          # vitest
npm run build     # writes web/dist
```

Node 22.12 or newer. `npm ci` downloads about 100 MB into `web/node_modules`.

## Layout

- `src/lib/abPlayer.ts` : synchronised A/B playback and crossfade logic, written against a small
  interface so it can be tested without a browser.
- `src/lib/ramp.ts` : gain automation we model ourselves, so a fade can be reversed mid-way
  without a step.
- `src/lib/fakeAudio.ts` : fake AudioContext, gains, sources and buffers for the tests.
- `src/App.svelte`, `src/Waveform.svelte`, `src/app.css` : the UI.

## Deploy

`.github/workflows/pages.yml` builds with `BASE_PATH=/stage-spatial-audio/` and publishes to
GitHub Pages on every push to `main` that touches `web/`. Pages must be enabled once in the
repository settings with "GitHub Actions" as the source.
