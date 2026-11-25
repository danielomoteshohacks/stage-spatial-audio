# SoundStage

**A spatial audio engine that lives inside the music app: any song, any phone, no Dolby hardware, artist in control.**

[![CI](https://github.com/danielomoteshohacks/stage-spatial-audio/actions/workflows/ci.yml/badge.svg)](https://github.com/danielomoteshohacks/stage-spatial-audio/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-blue.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-v3%20in%20listening%20tests-1FC8B4.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)

> SoundStage is an independent research and engineering project. It is not affiliated with, or endorsed by, Spotify, Apple or Dolby.

---

## Why this exists

Streaming services now compete on sound. Lossless audio has become common, and spatial audio is the
next gap. Today, spatial music mostly means a dedicated Dolby Atmos mix of each song, and on
Android the experience also depends on the phone maker supplying Dolby support: without it, the
same track plays in plain stereo. Spotify offers lossless, and as of early 2026 no native spatial format.

SoundStage asks a different question: **what if the app itself owned the renderer?** Then it would work on any
phone, on any song, and the artist could decide whether their track receives it.

## The idea in one minute

Most upmixers invent positions. SoundStage does the opposite: **it keeps every sound where the
mix put it**, splits the song into its parts, and builds a scene around the listener from them,
through measured human-ear filters in a real-sounding room. The vocal, the bass and the kick never
move; below 120 Hz the record passes through untouched. A fidelity guard compares every render
with the original and says what it found.

```mermaid
flowchart LR
    A[Stereo song] --> B[Separation<br/>our engine, else the teacher]
    B --> C[Analysis<br/>beats, sections, genre]
    C --> D[Plan<br/>template, motion, plan.json]
    D --> E[Scene<br/>objects, 7.1.4 bed, motion]
    E --> F[Binaural rooms<br/>SADIE II KU100 ears]
    F --> G[Neutrality<br/>bass bypass, timbre, loudness]
    G --> H[Guard report<br/>verdict and reasons]
```

## Three complete tiers

| Tier | Neural network | Runs where | What it adds |
|---|---|---|---|
| **Lite** | None | On the device, real time | Pan-anchored rendering of the whole mix; works on any song instantly |
| **Standard** | Small separation model | Offline, once per track | Per-stem roles and distances |
| **Studio** | Separation plus refiner | Offline, once per track | Cleaner stems on hard passages, for flagship tracks |

Each tier is a complete product, not a stripped-down demo. Every tier must beat the one below it in
blind listening tests to earn its cost.

## How we know it works

No claim is made without a measurement. Each claim is a hypothesis with a pass condition written
before the test is run (see [`experiments/`](experiments/)).

| Claim | Gate |
|---|---|
| Lite is preferred over a generic stereo virtualiser | Lower end of the 95 percent interval above 50 percent |
| The timbre bound keeps the tone without losing direction | Average deviation at most 1.5 dB |
| Role-based distance beats one room for everything | Preferred in blind A/B |
| The real-time core is light | WebAssembly at most 300 KB; CPU at most 5 percent of one mid-range phone core |
| Triage-and-refine keeps the ensemble's gain cheaply | At least 90 percent of the gain at no more than 40 percent of the cost |

Results, including failures, will be published here with sample sizes and confidence intervals.

## Try it

On a phone with headphones: <https://soundstage-phi.vercel.app>. Drop a song you own, wait for
the stage to be built, and switch between Original and Spatial. The processing server is
<https://danieltesh-soundstage.hf.space> (a sleeping Space takes a minute to wake).

On your own machine, in two terminals (Python 3.10+, Node 20+):

```bash
python -m pip install -e ".[backend]"   # add ",separation" for stems (installs torch, demucs)
python space/app.py                      # http://127.0.0.1:7860
cd web && npm ci && npm run dev          # http://localhost:5173
```

From the command line, without the web app:

```bash
python scripts/process_track.py track.flac --mode lite --profile space:living_room --out-dir runs/a
```

Tracks are processed and deleted after 30 minutes; use audio you own or may use.

## Status

v3 is live: <https://soundstage-phi.vercel.app> (web app) and
<https://danieltesh-soundstage.hf.space> (processing). v2 sounded like the stereo mix pushed
backwards (decision 0022); v3 treats the song as objects. What exists, honestly:

- **Objects, not a widened stereo image** (0024 to 0026): each separated part is a dry point source
  through a measured head at its own direction, with a sparse set of early reflections and no
  late tail; the room that was in the recording returns from the sides, rear and above; placement
  comes from data (`configs/placement/`); parts move on musical events within speed and range caps;
  several measured heads and a short calibration game that picks the one that fits your ears.
- **Separation cascade** (0023): six levels behind a licence-checked manifest, with our own
  post-processing and a per-part quality score. **The neural levels have never run**: this
  environment has no GPU and could not reach the weight hosts. What runs today is the model-free
  levels on top of a four-stem separator (htdemucs on the Space).
- **Whole songs, streamed** (0027): rendered in chunks, played while they render, Opus segments;
  time to first sound 1.9 s on the model-free path; first sound with the neural cascade is not measured.
- **A catalogue to stream** (0028): 115 openly licensed tracks (CC BY, CC BY-SA; never NoDerivatives),
  verified, with creator and licence shown, search and 11 shelves.
- **The product** (0029, `web/BRAND.md`): light by default and dark, tab bar, mini player, full
  now-playing with an Original and Spatial switch, library on the device, calibration game,
  blind test with a slot for a reference rendering you load yourself. Lighthouse (mobile, median of
  3): performance 0.98 light and 0.99 dark, accessibility 1.00. Screens: [`docs/screens/`](docs/screens/).
- **Fidelity guard** (0011), **real ears** (0012 to 0014), **our separator** (0015, **weights not
  trained yet**): as in v2.
- **Not claimed:** no perceptual result yet, and nothing here says SoundStage matches or beats any
  commercial format. The numbers below are objective measurements of where sound is placed; the
  blind test decides what people prefer.

## Benchmark: v1, v2 and v3

Two benchmarks, because the first one cannot judge v3. Both are objective, on generated songs
(no recordings), reproducible with the scripts named, raw rows in
[`docs/benchmarks/`](docs/benchmarks/) (decision 0030).

**1. Where the sound is placed.** `scripts/benchmark_groundtruth.py`: two generated songs of 15
parts with known 3D positions, folded to stereo; each engine sees only the stereo fold and the
stems it is given, 30 s, means. "True parts" hands v3 the 15 true parts (what a perfect separator
would give); "four stems" hands v3 the four true stems and our model-free split of them (what
today's separators plus our DSP levels give). v2 always gets the four stems.

| Measure | Truth | v2 | v3, true parts | v3, four stems |
|---|---|---|---|---|
| Direct energy outside the front (azimuth) | 31.5% | 14.1% | **45.2%** | 30.1% |
| Distance of the direction-energy map from the truth (degrees, lower better) | 0 | 24.5 | 12.3 | **6.6** |
| Per-part angular error, RMS (degrees, lower better) | 0 | 51.2 | **16.4** | 67.2 |
| Median direct-to-reverberant ratio (dB) | n/a | -6.1 | 26.2 | 29.2 |
| IACC (lower: further from the head centre) | n/a | 0.72 | 0.54 | 0.89 |
| Timbre deviation (dB, lower better) | n/a | 1.73 | 0.78 | 0.64 |
| Guard verdict | | pass, pass | pass, pass | review, pass |

Read it plainly. With a perfect separator v3 puts sources where they belong (16 degrees against
51) and carries 3.2 times v2's share outside the front, but that share (45%) is more than the
truth's 31.5%: v3's templates place guitars and pads wider than these generated songs do. With only
four stems and model-free splitting, v3's overall direction map is the closest to the truth
(6.6 degrees), yet individual parts are in the wrong place more often than in v2 (67 degrees, for
example two guitars split by a pan cluster are not matched to the right original). **v3 needs the
neural cascade to deliver its promise, and the neural cascade has not been run.**

**2. The v2-era proxies.** `scripts/benchmark_spatial.py`, five generated songs, 30 s, means:

| Metric | Better | v1 Lite | v2 Lite | v2 stems, studio | v2 stems, living room | v3 Lite | v3 four stems |
|---|---|---|---|---|---|---|---|
| IACC | lower | 0.956 | 0.887 | 0.973 | **0.830** | 1.000 | 0.995 |
| ITD spread (us) | higher | 96.5 | 184 | 103 | **273** | 11.5 | 28.1 |
| ILD spread (dB) | higher | 7.19 | 5.96 | 6.46 | **7.60** | 4.82 | 6.30 |
| Lateral energy | higher | 0.0068 | **0.118** | 0.0094 | 0.0804 | 0.000 | 0.001 |
| Timbre deviation (dB) | lower | 4.45 | 1.20 | **0.95** | 2.39 | 1.36 | 1.96 |
| Artifact flags per 30 s | lower | 18.2 | **0** | **0** | **0** | 0.2 | **0** |
| Bass correlation (< 120 Hz) | higher | 0.999 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Render time, 30 s, 4 vCPU (s), without separation | lower | 2.1 | 4.4 | 10.9 | 11.0 | **1.4** | 1.5 |
| Guard verdict | | 5 review | 5 pass | 5 pass | 5 pass | 1 review, 4 pass | 5 pass |

**On these proxies v3 scores worse than v2**, and that is what they measure, not a hidden win.
They reward interaural decorrelation (low IACC, wide ITD and lateral energy), which v2 produced
by sending every sound through a room. A dry source straight ahead is, correctly, nearly identical
in both ears, and the generated songs keep the vocal, chords and drums centred, so v3 on a
centre-heavy mix reads as nearly mono on these numbers. Whether it sounds more outside the head,
because direction and distance cues do that work instead of room reverberation, is exactly what
the proxies cannot say and the blind test must. Where v3 does not win, decision 0030 says why.

## Benchmark: v1 and v2 (the earlier table)

Five generated multitrack songs (synthesised drums, bass, chords, a formant voice, ambience; no
recordings), 30 s each, `scripts/benchmark_spatial.py`, means (decision 0021):

| Metric | Better | v1 Lite | v2 Lite | v2 stems, studio | v2 stems, living room (default) |
|---|---|---|---|---|---|
| IACC | lower | 0.956 | 0.887 | 0.973 | **0.830** |
| ITD spread (us) | higher | 96.5 | 184 | 103 | **273** |
| ILD spread (dB) | higher | 7.19 | 5.96 | 6.46 | **7.60** |
| DRR estimate (dB) | lower: more room | 7.19 | 15.4 | 7.53 | **3.09** |
| Lateral energy | higher | 0.0068 | **0.118** | 0.0094 | 0.0804 |
| Interaural coherence | lower | 0.949 | **0.419** | 0.965 | 0.759 |
| Timbre deviation (dB) | lower | 4.45 | 1.20 | **0.95** | 2.39 |
| Artifact flags per 30 s | lower | 18.2 | **0** | **0** | **0** |
| Bass correlation (< 120 Hz) | higher | 0.999 | **1.000** | **1.000** | **1.000** |
| Loudness difference (LU) | lower | 0.046 | **0** | **0** | **0** |
| Render time, 30 s, 4 vCPU (s) | lower | **1.8** | 4.0 | 8.8 | 8.8 |
| Guard verdict | | 5 review | 5 pass | 5 pass | 5 pass |

Where v2 does not win, decision 0021 says why (render time; the deliberately dry studio).

## Separation

| Engine | Avg SDR, MUSDB18-HQ test | Size | CPU per 30 s | Status |
|---|---|---|---|---|
| htdemucs (teacher fallback) | 9.0 dB (Demucs README) | measured on Kaggle | GPU on the Space | in use |
| SoundStage Separator | not trained yet | 8.4 MB (fp16 ONNX) | 9.8 s on 4 vCPU | default only once it reaches htdemucs |

MUSDB18-HQ is for research use only; weights trained on it are research weights. The training
steps for Kaggle's free GPUs are in [`training/README.md`](training/README.md).

## Repository layout

| Path | Purpose | Status |
|---|---|---|
| [`src/stage/`](src/stage/) | Python reference implementation (the oracle) | active |
| [`schemas/`](schemas/) | JSON Schemas for the plan, report, run and consent files | active |
| [`tests/`](tests/) | Unit, property, golden-file and integration tests | active |
| [`docs/`](docs/) | Specifications, architecture, roadmap, decision records | active |
| [`experiments/`](experiments/) | Hypotheses, gates and results | active |
| [`stage-core/`](stage-core/) | Rust real-time core, compiled to WebAssembly | planned |
| [`tools/hrtf-pack/`](tools/hrtf-pack/) | Builds the measured HRTF pack from SADIE II (on GitHub Actions) | active |
| [`training/`](training/) | SoundStage Separator training (Kaggle) and export | active |
| [`web/`](web/) | The web app: library, player, stage view, blind test | active |
| [`space/`](space/) | Gradio backend for a laptop or a Hugging Face Space | active |
| [`android/`](android/) | Optional Android client | planned |
| [`configs/`](configs/) | Genre templates, spaces, guard thresholds | active |
| [`models/`](models/) | Model and dataset manifest (files are never committed) | active |
| [`data/`](data/) | Dataset licences (audio is never committed) | active |
| [`benchmarks/`](benchmarks/) | Reproducible performance measurements | active (Python) |
| [`examples/`](examples/) | Small runnable examples | planned |
| [`scripts/`](scripts/) | Processing, rendering, blind-test and test-signal helpers | active |

## Quick start

```bash
git clone https://github.com/danielomoteshohacks/stage-spatial-audio.git
cd stage-spatial-audio
python -m venv .venv
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate
python -m pip install -e ".[dev]"
ruff check . && pytest -q
```

## Documentation

- [`docs/specs/`](docs/specs/): the project plan and the technical build specification (version 2)
- [`docs/architecture.md`](docs/architecture.md): the system and its data contracts
- [`docs/decisions/`](docs/decisions/): why each major choice was made, and what else was considered
- [`docs/roadmap.md`](docs/roadmap.md): the five slices
- [`docs/log.md`](docs/log.md): the build log, with every measurement and limitation

## Principles

- **True to the record.** Change position, not the performance.
- **Measured.** Report sample sizes and intervals, including failures.
- **Light.** Heavy work runs offline; what runs on the device stays small.
- **Open and clean.** Only audio that is owned or licensed; every model and dataset licence is recorded.
- **Artist in control.** Spatial processing is opt-in with preview and approval.

## Music, data and licensing policy

- No audio, models or datasets are committed. Manifests record source and licence.
- Only music that is owned, used with written permission, or openly licensed appears in demos.
- Spotify audio, previews and API data are **never** used for training, testing or demos.
- Pretrained model weights are treated as research-only until their licence is confirmed.

## Prior art and acknowledgements

SoundStage builds on established research and says so: panning-index and ambience extraction
(Avendano and Jot), azimuth discrimination and resynthesis (Barry and colleagues), primary-ambient
extraction (He, Tan and Gan, and others), stereo position estimation (Kraft and Zolzer), source
separation models (Demucs, SCNet, RoFormer families), and open head-related transfer function
datasets (used with attribution).

**Credits.** The default head-related filters are built from the SADIE II Database, subject D1
(Neumann KU100), The Audio Lab, University of York: C. Armstrong, L. Thresh, D. Murphy and
G. Kearney, "A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study of the
SADIE II Database", Applied Sciences 8(11), 2029, 2018. Copyright 2018 University of York,
licensed under the Apache License 2.0. Every model and dataset is listed with its licence in
[`models/MANIFEST.md`](models/MANIFEST.md). Some structures used in commercial binaural virtualisers are
patented; SoundStage avoids copying them and a freedom-to-operate check is planned before any product claim.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Experiments use the Experiment issue template.

## Licence

Code is licensed under [Apache-2.0](LICENSE). Models and datasets keep their own licences.
