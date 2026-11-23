# 0009. Bring the web app forward as a listening bench, backed by Python

- Status: accepted
- Date: 2026-11-23

## Context

- The project is now called **SoundStage**. The Python package keeps the name `stage`, so no
  import, script or test changes.
- Judging a profile, a width or a separator today means running scripts and switching WAV files
  in a desktop player. Switching files restarts playback and loses the passage, which is exactly
  the moment a difference is heard. That slows down every listening decision in slices 1 to 3.
- The listener tests on a phone (a Samsung Galaxy S21 FE), on mobile data as often as on Wi-Fi.
- The real-time engine (Rust compiled to WebAssembly, slice 4) is not built yet, so the browser
  cannot render by itself.
- Separation (Demucs) wants a GPU. Free CPU Spaces on Hugging Face now need a paid plan; a
  ZeroGPU Gradio Space gives each visitor a small daily GPU quota (about 5 GPU minutes).

## Decision

Build the web app now as a **listening bench**, with the processing in Python:

1. `stage.pipeline.run` turns one track into an A/B set: the original excerpt, the spatial render
   (RMS-matched, then peak-limited), the dry and spatial stems in stems mode, and `run.json`.
   Every stage is isolated and timed; a failed separation falls back to Lite and says so.
2. `stage.service` validates uploads and deletes everything after a time-to-live. It has no
   Gradio import, so it is tested on its own.
3. `space/app.py` is a thin Gradio app with one streaming endpoint. The same file runs on a laptop
   and on a ZeroGPU Space, where only the separation call holds the GPU.
4. `web/` (Svelte, Vite, TypeScript) uploads, streams progress and plays the files in a
   sample-locked A/B player with a 30 ms crossfade, a loop region, and live solo and mute on the
   spatial stems.
5. Audio crosses the network as 24-bit FLAC: lossless like WAV, much smaller, which matters on
   mobile data. The first page load must stay at or under 500 KB gzipped, checked in CI.
6. The Rust/WASM real-time path stays in slice 4.

## Consequences

- Listening comparisons become seamless: the switch never restarts playback.
- Every render carries a machine-readable report, so the bench can show honestly what played,
  including a fallback from stems to Lite.
- The browser needs a backend. When none is reachable, the page says so and shows the fix; it
  never shows a made-up result.
- ZeroGPU and real Demucs behaviour must be verified outside this repository's CI, which installs
  neither torch nor demucs. See `docs/log.md`.
- An https page cannot call an http backend on the local network, so the deployed site uses the
  Space, and testing against a laptop uses the Vite dev server on the network.

## Alternatives considered

- **Wait for the WebAssembly core.** Delays every listening decision until slice 4, and Lite-only.
- **A desktop app.** Does not reach the phone that is actually used for listening.
- **Gradio's own interface as the bench.** It cannot play two files in sync or crossfade between
  them, and it is not built for a phone.
- **The official Gradio JavaScript client.** Works, but adds weight to the first load; the HTTP
  protocol used here is small enough to speak directly.
- **WAV over the network.** About twice the size of FLAC for the same samples.
