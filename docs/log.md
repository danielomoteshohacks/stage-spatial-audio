# Build log

One entry per piece of work. Each entry has the date, then: done, measured, what went wrong and how
it was fixed, and next. Numbers are copied from the run that produced them; anything not run is
said to be not run.

## 2026-11-23: SoundStage listening bench (pipeline, backend, web app)

### Done

- **Name.** The project is called SoundStage in the README, the docs, `CITATION.cff` and
  `pyproject.toml`; the Python package stays `stage`. Decision
  [0009](decisions/0009-web-test-bench-first.md) records why the web app comes forward now.
- **Levels.** `match_rms`, `limit_peak` (and the `peak_gain` they share) moved from
  `scripts/render_clip.py` into `stage.guard.levels`. `render_clip.py` and `make_abx.py` import
  them; the existing tests for both scripts pass unchanged.
- **Separator.** `stage.separation.demucs_sep.separate(audio, sample_rate, model="htdemucs",
  device="auto")` returns vocals, drums, bass and other, each (2, n) float64 at the input rate and
  exact length, plus the residual SNR (input against the sum of the stems). torch and demucs are
  imported inside the function; without them it raises `SeparationUnavailable` with the install
  command. Six-source models are folded into four stems so the stems still sum to the mix.
- **Pipeline.** `stage.pipeline.run` with the stages load, separate, render, levels and write. Each
  records ok, failed or skipped, its duration and its error; no stage failure escapes the run. A
  failed or unavailable separation renders the whole mix in Lite and records the fallback. Stems
  are rendered one at a time with `render_profile` and summed. One shared gain (RMS match times
  peak safety) is applied to the full render and to every spatial stem, so the stems mixed at unity
  equal `spatial.flac`. Outputs: `original.flac`, `spatial.flac`, `stems/*.flac`,
  `stems_spatial/*.flac` (24-bit FLAC) and `run.json`, with `schemas/run.schema.json`.
- **CLI.** `scripts/process_track.py` prints a per-stage summary. `scripts/make_test_signal.py`
  writes the generated test track, and `benchmarks/pipeline_run.py` measures one run.
- **Service.** `stage.service.process_upload` validates type, size and length (12 minutes), picks
  the excerpt (30 s from 30 s in, moved earlier for short tracks; at most 120 s), decodes m4a
  with ffmpeg when libsndfile cannot, runs the pipeline in its own folder, and deletes runs after
  30 minutes. `stream_process_upload` yields the stage events for a streaming endpoint.
- **Backend.** `space/app.py`: one Gradio endpoint `/process` that streams progress and then
  returns the files; queue on, concurrency 1; `@spaces.GPU(duration=60)` wraps only the
  separation call, and only when `spaces` is installed. Space front matter, requirements, a
  bundle script and the deploy workflow are in place.
- **Web.** `web/`: Svelte 5, Vite 7, TypeScript. Drop zone, excerpt, mode, character and width
  controls, live progress, a sample-locked A/B player with a 30 ms crossfade, waveform with seek
  and drag-to-loop, live solo and mute of spatial stems, the run report, and a backend setting
  with a specific fix for each unreachable case.
- **CI.** The python job is unchanged in scope (no torch). New backend job (gradio, service and
  app tests, bundle import check) and web job (npm ci, type check, lint, unit tests, build, size
  budget). Actions are pinned to commit SHAs.

### Measured

All on the cloud build machine: 4 vCPU Intel Xeon at 2.10 GHz, 15 GB RAM, Python 3.13.18, numpy
2.5.3, scipy 1.18.1, soundfile 0.14.0 (libsndfile 1.2.2), gradio 6.32.0, Node 22. One run each,
so there is no interval. The test track is generated (sine tones at 220, 440 and 660 Hz and noise
bursts, panned left, centre and right), 10 s at 44.1 kHz, written to a temporary folder and never
committed.

| What | Result |
|---|---|
| Lite, profile `max`, 10 s (`benchmarks/pipeline_run.py`) | 1.53 s wall, 6.6x real time; render 1.455 s, write 0.056 s, load 0.006 s, levels 0.009 s |
| Peak memory, same run (process maximum RSS) | 784 MB, of which 132 MB before the run (interpreter and libraries) |
| Lite, profile `V0`, 10 s | 0.33 s wall, 30x real time; render 0.253 s; peak RSS 284 MB |
| FLAC sizes for 10 s (24-bit WAV would be 2.65 MB each) | `original.flac` 1.69 MB, `spatial.flac` 2.05 MB (noise-heavy test signal, so compression is weak) |
| Stems loop memory (tracemalloc, `V0`, 5 s, test separator) | 146 MB in stems mode against 118 MB for Lite, 1.24x; the test fails above 1.6x |
| Backend smoke test, `gradio_client` to `/process`, Lite, `max`, the 10 s track | 11 streamed updates; 1.79 s wall from submit to result; stages load 0.015 s, separate skipped, render 1.516 s, levels 0.010 s, write 0.065 s; both FLACs 441000 frames, PCM_24; spatial RMS -18.148 dBFS, equal to the original; peak gain 0 dB |
| Web app, first load | 43.1 KB gzipped (index.html 0.5, JS 38.1, CSS 4.4, favicon 0.2); budget 500 KB |
| Web app end to end (headless Chromium, 412 x 915 phone viewport, local backend) | upload, progress, download and decode of a 10 s Lite render in about 0.95 s; playback position kept advancing across Original/Spatial switches by button and space bar (0:01.2 to 0:02.0, no restart); a drag set a 3.0 s loop; Stems mode without Demucs showed the Lite fallback notice |
| Tests | Python with gradio installed: 336 passed, 1 skipped (real Demucs), 9 xfailed (the pre-existing strict proxy gates), of which the backend job's service and app tests are 28; web: 15 passed |

### What went wrong, and how it was fixed

- `limit_peak` and `match_rms` lived inside a script, so the pipeline could not share them. Moved
  to `stage.guard.levels`; `PEAK_CEILING` is still importable from both scripts because their
  tests read it there.
- Rendering stems with one peak limit per file would make solo and mute not sum back to the full
  render. Fixed with one shared gain for the full render and every stem, computed from the
  loudest of them; the run report shows it as `peak_gain_db`.
- The integration test first imported a helper through `tests.conftest`, which is not a package;
  it now loads the test-signal script by path.
- `/usr/bin/time` is not installed on the build machine, so peak memory is read with
  `resource.getrusage` inside `benchmarks/pipeline_run.py`.
- Gradio only accepts cross-origin requests from localhost pages when it listens on localhost.
  A page on the network calling `127.0.0.1` therefore fails, and on a phone `127.0.0.1` is the
  phone. The web app detects both cases and shows the exact fix (start the backend with
  `GRADIO_SERVER_NAME=0.0.0.0` and use the laptop's address). An https page cannot call an http
  backend at all, which is why the deployed site must use the Space.
- Gradio 6 renamed the attribute that marks an endpoint as public; the app test reads it in a way
  that works with both names.
- The first web dependency set (Vitest 3) carried two critical advisories in a transitive
  dependency. Moved to Vitest 5; `npm audit` reports 0 vulnerabilities. Vite 8 had a peer
  conflict with the Svelte plugin, so the app stays on Vite 7.
- In the browser test, the backend status text was hidden at phone width and a tap outside an
  active loop appeared to do nothing (playback jumped back into the loop). The status now always
  shows a short word, and a seek outside the loop clears it. A profile-ordering bug put unknown
  profile names before the known ones; fixed and tested.

### Limitations (not done here, and why)

- **Real Demucs has not been run.** torch and demucs were deliberately not installed and no
  weights were downloaded in this environment. `separate` is written against the demucs 4.0.1
  Python API (`demucs.pretrained.get_model`, `demucs.apply.apply_model`,
  `demucs.audio.convert_audio`, and the input normalisation of `demucs.separate`), which was
  checked against the published 4.0.1 source, not executed. `tests/integration/test_demucs_real.py`
  runs it and skips itself where demucs is absent.
- **ZeroGPU has not been run.** The `@spaces.GPU` path, the GPU duration of 60 s, the quota
  charge per visitor, and calling the decorated function from the pipeline's worker thread are
  untested. No Space was created, and the deploy workflow has not run (it needs `HF_TOKEN` and
  `HF_SPACE`).
- **Not tested on a real phone.** The web app was checked in headless Chromium with a phone-sized
  viewport and touch emulation, not on the Galaxy S21 FE, and not in Safari. FLAC decoding by
  `decodeAudioData` is assumed from browser support tables for those.
- **Memory.** The renderer keeps whole-signal arrays (decision 0006 measured about 3.1 GB for a
  4 minute song), so the service caps an excerpt at 120 s.
- **No listening result.** Nothing here says how any profile sounds. The bench is the tool for
  that; the blind test (`scripts/make_abx.py`) decides.

### Next

1. On the laptop, run the stems commands below on one owned track and record the separation time,
   residual SNR and peak memory here.
2. Create the Space, set `HF_TOKEN` and `HF_SPACE`, deploy, and measure one stems run on ZeroGPU
   (time, and GPU seconds charged).
3. Open the bench on the S21 FE against the laptop (`npm run dev -- --host`) and against the Space,
   and note anything that does not work.
4. Use the bench to pick the clips and widths for the slice 2 blind test.

### Run on the laptop

From a fresh clone, in a virtual environment (Python 3.10 to 3.12; check that PyTorch publishes a
wheel for your Python version first):

```bash
python -m venv .venv
source .venv/bin/activate                      # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev,separation]"   # installs torch and demucs

# Real Demucs test (downloads the htdemucs weights once, into the torch hub cache)
pytest -q tests/integration/test_demucs_real.py

# A real stems job on 30 s of a track you own, from 30 s in
python scripts/process_track.py path/to/track.flac --mode stems --profile max --beta 2.0 \
    --start 30 --seconds 30 --out-dir runs/stems-1

# The same job through the backend and the web app
python -m pip install -e ".[backend]"
python space/app.py                            # terminal 1
cd web && npm ci && npm run dev                # terminal 2, then open http://localhost:5173
```

`runs/stems-1/run.json` holds the stage timings, the device used, and the residual SNR. If the
separate stage shows `failed`, the error text there says why, and the run will have fallen back to
Lite.
