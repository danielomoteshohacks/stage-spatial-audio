# Roadmap

Five vertical slices. Each ends with something that works end to end. Nothing waits for a later
slice to be useful.

| Slice | Goal | Done when |
|---|---|---|
| 1 Hear it | One clip spatialised by Lite in Python and heard on headphones | You can switch between stereo and spatial and describe the difference honestly |
| 2 Prove it | Measurements and a first blind test beat a generic virtualiser | Ten listeners, a result with an interval, and the guard passes |
| 3 Make it smart | Stems, roles, style templates and masking-aware placement | Standard beats Lite in a blind test with thirty listeners |
| 4 Make it light | Rust core in real time in the browser, within budgets | Drop any file and hear it live; size and CPU budgets met |
| 5 Show it | Demo, efficiency chart, write-up and video | A stranger understands it in two minutes |

## Current order of work (decision 0009)

The web app comes forward as a **listening bench**, before the real-time path: drop a track, hear
the original against the spatial render in sync, and tune the spatializer and the separator by
ear. It is the instrument that slices 1 to 3 are judged with.

- The processing runs in Python (`stage.pipeline`, `stage.service`, `space/app.py`), on a laptop or
  on a Hugging Face ZeroGPU Space. The web app only uploads, shows progress and plays.
- Stems mode (Demucs) is available through the bench for listening, ahead of the slice 3 blind
  test that has to justify it.
- The Rust core and WebAssembly real-time path stay in slice 4. When they land, the bench gains
  an in-browser Lite mode; the Python backend stays the reference.

| Bench item | Status |
|---|---|
| Pipeline, run report, CLI | done; Lite measured, real Demucs not yet run |
| Service and Gradio backend | done; tested locally, ZeroGPU not yet run |
| Web listening bench | done; tested in desktop Chromium with a phone viewport, not yet on a phone |
| Deploy to a Space and to Cloudflare Pages | configured, waiting for the account setup |

Progress is recorded in [`log.md`](log.md).

Rules: always keep a working version; add one idea at a time; decide the test before the work;
time-box experiments; end each session with three lines (done, measured, next).

## v2 rebuild (November 2026)

The owner's listening of v1 (static, dry, inside the head, audible artifacts) started a rebuild
in phases, each pushed to main green and recorded in [`log.md`](log.md):

| Phase | What | Status |
|---|---|---|
| 0 | Guard report, auto start, input fixes | done |
| 1 | Measured HRTFs (SADIE II), interpolation, binaural rooms, neutrality | done |
| 2A | SoundStage Separator: engine, training, evaluation | code done; Kaggle training pending (owner) |
| 2B | Stereo mix to a spatial scene: objects, bed, distance | done |
| 3 | Analysis, genre templates, motion, plan.json | done |
| 4 | Speed, cache, outputs, /rerender | done |
| 5 | The product (web app) | done; head tracking designed, not shipped |
| 6 | Objective benchmark, blind-test page | done; listening tests pending |

Next: train the separator on Kaggle, run the blind test with listeners, check on a Galaxy S21 FE,
then decide on head tracking.

## v3 rebuild (November 2026)

The owner's listening of v2 (the stereo pushed backwards, little outside the head) started a second
rebuild, again in phases pushed green and recorded in [`log.md`](log.md):

| Phase | What | Status |
|---|---|---|
| 0 | Diagnose v2 with numbers; ground-truth object songs | done |
| 1 | Separation cascade, post-processing, quality score, evaluation | model-free levels done and measured; neural levels coded, never run (no GPU or weight host reachable) |
| 2 | Object renderer: dry sources, placement templates, events, HRTF heads | done; head choice by calibration game shipped |
| 3 | Whole songs in chunks, streamed, Opus delivery | done; real time to first sound with the neural cascade not measured |
| 4 | Streaming catalogue, 60+ verified tracks, legal page | 115 tracks verified; Jamendo API and pre-rendered dataset need the owner's keys |
| 5 | Product: light and dark, shelves, player, calibration | done; emulated phone profile, not a real phone |
| 6 | Benchmark v1/v2/v3, blind test with a reference slot, documents | done; listening tests pending |

Next, in order: (1) run the cascade on the Space's GPU and record seconds per minute and time to
first sound; (2) set `JAMENDO_CLIENT_ID` and the Hugging Face write token, run the catalogue
workflow, and check Jamendo in a browser; (3) run the blind test with listeners, including the
reference slot, and publish the CSV with an interval; (4) train the SoundStage Separator on Kaggle;
(5) check on a real phone; (6) only then consider head tracking.
