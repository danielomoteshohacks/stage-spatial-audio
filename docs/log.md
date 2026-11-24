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

## 2026-11-24: v2 Phase 0, housekeeping (guard, inputs, auto start)

### Done

- PR #9 rescued: `stage.guard.checks`, its tests, `scripts/measure_sector_sum.py` and its
  decision (renumbered 0010) are on main; `render_clip.py --guard` prints the table. The guard's
  exports merge `checks` with main's `levels`.
- `report.json` for every render (decision 0011): BS.1770-4 integrated loudness, 4x true peak,
  per-band downmix difference, mono-sum cancellation, low-end identity, artifact flags (clipping,
  dropouts, pre-echo, musical noise) with timestamps, and a verdict with plain reasons. A new
  pipeline stage `guard`; thresholds with reasons in `configs/thresholds/guard.json`, bundled into
  the Space by `space/bundle.sh`.
- Gradio form: Start and Length are single text boxes; empty means the default, and
  `stage.service` refuses a 0 or non-numeric length whatever the client sends.
- `start="auto"` by default in the service, pipeline, CLI, Gradio form and web app; run.json
  records the start, `start_mode` and the window's loudness.

### Measured

- Loudness against pyloudnorm 0.1.1: identical to its De Man filters; within 0.05 LU of its
  default filters at 44.1, 48 and 96 kHz (test requires 0.1 LU). 997 Hz full-scale sine in one
  channel: -3.01 LUFS.
- v1 `max` on the generated kick, hats and chord signal: verdict review, timbre 3.6 dB at
  3.15 kHz, 18 pre-echo flags (one per hat), musical noise throughout. Guard time 1.4 s per 10 s.
- Tests: 393 passed, 1 skipped, 9 xfailed.

### What went wrong

- The first K-weighting design used the RBJ cookbook shelf; it missed the standard's 48 kHz
  table by 0.05 in b0. De Man's shelf form (separate mid-band gain) matches it to 1e-12.
- The first pre-echo test smeared transients with a one-sided decay too weak to be audible; the
  detector correctly ignored it. The test now uses a centred 15 ms smear, the way a long frame does.

### Next

Phase 1: measured HRTFs (SADIE II KU100), interpolation, binaural rooms, neutrality.

## 2026-11-24: v2 Phase 1, real ears and real rooms

### Done

- **Measured HRTFs** (decision 0012): `tools/hrtf-pack` and the `hrtf-pack` workflow build a
  1.87 MB pack from SADIE II subject D1 (KU100) on a GitHub runner and publish it as release
  `hrtf-pack-v1`, with the measured studio BRIRs as a second asset. Licence Apache-2.0, checked
  in the Zenodo record and in the SOFA file. The Space downloads and verifies it at start-up;
  the analytic head remains the offline fallback.
- **Interpolation**: barycentric over the spherical Delaunay triangulation, minimum-phase
  magnitudes and ITD separately; ring-measured grid resampled onto 4000 uniform directions.
- **Rooms** (0013): six spaces with image sources (order 2 or 3) through the measured head, ISO
  9613-1 air absorption, Eyring-consistent wall absorption, a multiband FDN late field mixed to
  the KU100's measured diffuse coherence, fitted to the measured York studio BRIRs.
- **Neutrality** (0014): zero-phase Linkwitz-Riley bass bypass at 120 Hz, diffuse-field EQ,
  1/3-octave minimum-phase timbre matcher on both ears, upper-band BS.1770 loudness match.
- `space:<name>` profiles; `space:studio` is the default in the pipeline, service, Space and web.
- The deploy workflow now waits for the Space to run and checks its API lists `space:studio`.

### Measured

- Continuity: 0.47 dB per degree worst case along azimuth (target 0.5); 1.59 along elevation,
  left as is because it is the pinna's elevation cue.
- Studio against the measured SADIE II BRIRs: DRR within 1 dB except behind the head (4.5 dB too
  dry), IACC_E within 0.12. Every space's RT60 within 15 percent plus 30 ms of target where the
  octave filter can resolve it (table in 0013).
- Generated 30 s track, guard: v1 `max` review with 38 artifact flags; v2 studio, club, concert
  hall and cinema pass, living room and car review, no artifact flags in any v2 space; bass
  correlation 0.9997 to 1.0000; alignment 0.02 ms.
- Render time, 30 s at 44.1 kHz on the 4 vCPU build machine: v2 1.9 to 2.8 s per space (v1 `max`
  2.4 s). The first render in a process also builds the BRIRs (0.05 to 0.8 s per space).
- Tests: 427 passed, 1 skipped, 9 xfailed.

### What went wrong and how it was fixed

- The fetch tools of this session cannot reach York, Zenodo or Hugging Face; the pack is built
  on GitHub Actions and read back here from the release.
- The KU100 grid's near-duplicate points made interpolation jump 37 dB per degree; resampling by
  kernel regression fixed it.
- The guard's alignment check locked onto bass half-periods on reverberant renders and its
  pre-echo detector counted reverb tails; both were rewritten (0014).
- RMS levelling dragged the untouched bass down by 7 to 17 dB; levelling now scales only the
  upper band, by loudness.
- FDN start-up gap, per-band power imbalance, frequency-domain wrap-around and a door-side
  loudspeaker in the car were each found by a failing RT60 or coherence test and fixed (0013).

### Next

Phase 2A: the SoundStage Separator (research note first).

## 2026-11-24: v2 Phase 2A, the SoundStage Separator

### Done

- Research note `docs/research/separation.md` before any code. The papers' own pages were
  blocked here; the Demucs and norbert READMEs were read, and paper tables were taken from
  search summaries and marked secondary.
- `stage.separation.ssep`: network (3.95 M parameters, 8.4 MB fp16 ONNX), spatial/HPSS/f0 front
  end, Wiener plus bleed plus consistency back end, ONNX Runtime inference.
- `training/`: data and augmentation, losses, training with AMP and resume, ONNX export with a
  model card, teacher pseudo-labels, the Kaggle notebook and its README.
- `scripts/eval_separation.py`: museval BSSEval v4 per stem for ssep, htdemucs, htdemucs_ft, with
  size and CPU time; writes the gate into model.json.
- `stage.separation.chain`: ssep (CPU, only when it beats htdemucs), teacher (GPU), Lite; the
  Space calls only the teacher inside @spaces.GPU. CI gains a `separator` job with CPU torch.

### Measured

- Overfit gate passes (mean SDR at least 8 dB in 100 steps); ONNX parity under 1e-4; stems sum to
  the mixture within 1e-6; 9.8 s of CPU per 30 s of audio for the full-size graph.
- Tests: 440 passed, 1 skipped locally with torch installed.

### What went wrong

- The bass converged inverted from random complex masks; fixed by initialising the mask heads at
  an equal in-phase split (decision 0015).
- The first network was 11.2 MB in fp16; the mask heads' hidden width was halved to fit 10 MB.

### Next

The owner runs the Kaggle notebook (four runs, about 25 GPU hours). Phase 2B: the spatial scene.

## 2026-11-24: v2 Phases 2B and 3, the spatial scene and the mix plan

### Done

- `stage.scene`: analysis (tempo, beats, downbeats, sections, energy, stem activity), the AST
  genre tagger with a licence check, ten genre templates as data, the deterministic plan
  (`schemas/plan.schema.json` v2), velvet-noise decorrelators with transient gating, and the
  scene renderer (decomposition, virtual-source objects, section breathing, tempo-locked motion,
  distance cues, the 7.1.4 bed export).
- Pipeline stage `analyse`; v2 writes plan.json and per-object spatial stems (which with the low
  end sum to spatial.flac); the Space returns the object stems to the web app's mixer.
- `stage.testsongs`: deterministic generated multitrack songs for tests and the benchmark.

### Measured

Table in decision 0016: three stems scenes pass the guard with bass correlation 0.9995 to 0.9999
and no artifact flags; render 23 to 29 s per 30 s on the build machine (too slow, Phase 4).

### What went wrong

- Reverb and decorrelated bed energy around the crossover changed the bass region by 6.4 dB;
  everything but the direct path is now high-passed at 200 Hz (0016).
- Object stems did not sum to the render when an original blend was set; the blend now lives
  inside each object stem.
- The guard's alignment estimator was tuned twice more; it reads 0.02 ms on every space and on
  the stems scene, but still about 1.5 ms on the Lite scene of the synthetic song (0016).

### Next

Phase 4: speed, the per-track cache, outputs and /rerender.

## 2026-11-24: v2 Phase 4, speed, the cache and /rerender

### Done

- Scene render 21 s to 8.4 s per 30 s (openness curve at control rate, cheaper HPSS).
- Per-track cache of the excerpt, stems, analysis and genre (decision 0019); `stage.service.rerender`.
- `/process` gains genre, motion, plan and the 7.1.4 flag; `/rerender` added; the final update
  carries the plan, the track id and file paths. The web client sends the new fields.
- `benchmarks/render_times.py`.

### Measured

v2 Lite 4.1 to 5.0 s, full stems scene 8.4 to 15.6 s per 30 s on the build machine (table in
0019). Process then re-render from the cache is covered by `tests/backend/test_app.py`.

### What went wrong

The guard's alignment estimate read an impossible -2.8 ms on a reverberant scene; fixed with a
causality-aware peak choice (0019).

### Next

Phase 5: the product.
